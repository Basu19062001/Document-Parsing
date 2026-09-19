from fastapi import APIRouter
from app.routes.v1.document import router as document_router

v1_router = APIRouter()

# Centralized V1 Route Registration with explicit prefixes and tags
v1_router.include_router(
    document_router,
    prefix="/documents",
    tags=["Documents"],
)

__all__ = ["v1_router"]
