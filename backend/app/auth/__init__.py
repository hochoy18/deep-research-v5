"""Auth package — exposes the FastAPI router and shared dependencies."""

from .deps import get_auth_service, get_current_bearer, get_current_user
from .router import router

__all__ = ["router", "get_auth_service", "get_current_bearer", "get_current_user"]