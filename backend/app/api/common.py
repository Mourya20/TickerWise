from datetime import date
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

# Re-export pure read query from app.queries for backward compatibility
from app.queries.freshness_queries import compute_snapshot_freshness


def database_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Database service is unavailable.",
    )


__all__ = ["database_error", "compute_snapshot_freshness"]
