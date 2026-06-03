from fastapi import APIRouter

from src.api.v1 import jobs, parse

# Create v1 router and include sub-routers
v1_router = APIRouter(prefix="/v1")
v1_router.include_router(parse.router, tags=["parsing"])
v1_router.include_router(jobs.router, tags=["jobs"])

__all__ = ["v1_router"]
