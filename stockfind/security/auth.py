"""JWT authentication + role-based authorization (buyer vs admin).

- Missing / invalid / expired credential on a protected route -> ``401``.
- Valid credential lacking the required role -> ``403``.

The signing secret is read from settings (env only); tokens are short-lived.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from stockfind.config import Settings

ROLES = ("buyer", "admin")

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    username: str
    role: str


def issue_token(username: str, role: str, settings: Settings) -> tuple[str, int]:
    if role not in ROLES:
        raise ValueError(f"Unknown role: {role}")
    now = int(time.time())
    payload = {
        "sub": username,
        "role": role,
        "iat": now,
        "exp": now + settings.jwt_ttl_seconds,
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, settings.jwt_ttl_seconds


def decode_token(token: str, settings: Settings) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


def get_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Principal:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    settings: Settings = request.app.state.settings
    try:
        payload = decode_token(credentials.credentials, settings)
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    role = payload.get("role")
    if role not in ROLES:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing a valid role",
        )
    return Principal(username=payload.get("sub", ""), role=role)


def require_admin(principal: Principal = Depends(get_principal)) -> Principal:
    if principal.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return principal
