"""HTTP API routers."""

from fastapi import APIRouter

from . import (
    account,
    applications,
    interview,
    jobs,
    profile,
    settings,
    strategy,
    system,
    traces,
)

api_router = APIRouter()
for module in (
    system,
    account,
    interview,
    strategy,
    profile,
    jobs,
    applications,
    traces,
    settings,
):
    api_router.include_router(module.router)

__all__ = ["api_router"]
