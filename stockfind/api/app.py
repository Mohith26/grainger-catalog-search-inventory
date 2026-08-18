"""FastAPI application factory.

``create_app`` builds a fully wired app: settings + DB pool, per-app metrics and
rate limiters on ``app.state``, structured-logging + metrics middleware, a single
consistent error envelope for every failure mode, and the catalog / inventory /
meta routers.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from stockfind import db
from stockfind.api import routes_catalog, routes_inventory, routes_meta
from stockfind.config import Settings, get_settings
from stockfind.envelope import fail
from stockfind.errors import InsufficientStockError, NotFoundError, StockFindError
from stockfind.observability.logging import RequestContextMiddleware, configure_logging, get_logger
from stockfind.observability.metrics import Metrics, PrometheusMiddleware
from stockfind.security.ratelimit import TokenBucketLimiter

log = get_logger("stockfind.app")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.require_real_secret()
    configure_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db.init_pool(settings.pg_dsn)
        if settings.seed_on_start:
            from stockfind.catalog.seed import seed_database

            counts = seed_database(settings.seed)
            log.info("seeded_catalog", **counts)
        yield

    app = FastAPI(
        title="StockFind — Industrial Catalog Search + Inventory Availability",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.state.settings = settings
    app.state.metrics = Metrics()
    app.state.search_limiter = TokenBucketLimiter(settings.search_rate_limit)
    app.state.reserve_limiter = TokenBucketLimiter(settings.reserve_rate_limit)

    # Order: add Prometheus first so RequestContext (added last) is the outer layer.
    app.add_middleware(PrometheusMiddleware, metrics=app.state.metrics)
    app.add_middleware(RequestContextMiddleware)

    _register_error_handlers(app)

    app.include_router(routes_meta.router, tags=["meta"])
    app.include_router(routes_catalog.router, tags=["catalog"])
    app.include_router(routes_inventory.router, tags=["inventory"])
    return app


def _register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content=fail("Invalid request parameters"))

    @app.exception_handler(NotFoundError)
    async def _not_found(request: Request, exc: NotFoundError):
        return JSONResponse(status_code=404, content=fail(str(exc)))

    @app.exception_handler(InsufficientStockError)
    async def _insufficient(request: Request, exc: InsufficientStockError):
        return JSONResponse(status_code=409, content=fail(str(exc)))

    @app.exception_handler(StockFindError)
    async def _domain(request: Request, exc: StockFindError):
        return JSONResponse(status_code=400, content=fail(str(exc)))

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content=fail(str(exc.detail)),
            headers=getattr(exc, "headers", None),
        )


# Run with uvicorn factory mode so app construction (which validates the JWT
# secret) happens at startup, not merely on import:
#   uvicorn --factory stockfind.api.app:create_app
