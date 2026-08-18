"""Domain errors, mapped to HTTP status codes at the API boundary."""

from __future__ import annotations


class StockFindError(Exception):
    """Base class for expected, user-facing domain errors."""


class NotFoundError(StockFindError):
    """A referenced product / warehouse / reservation does not exist."""


class InsufficientStockError(StockFindError):
    """A reservation asked for more units than the warehouse can promise."""
