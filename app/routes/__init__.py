from fastapi import APIRouter
from app.routes.v1 import v1_router

# Central API Router aggregating all API versions
api_router = APIRouter()

# Mount API Version 1
api_router.include_router(v1_router, prefix="/v1")

# Future:
# api_router.include_router(v2_router, prefix="/v2")

__all__ = ["api_router"]
