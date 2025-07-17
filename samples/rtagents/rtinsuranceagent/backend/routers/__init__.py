from fastapi import APIRouter

from . import acs, health, realtime

router = APIRouter()
for r in (realtime.router, acs.router, health.router):
    router.include_router(r)
