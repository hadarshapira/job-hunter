"""Background worker (arq + Redis): scheduled job collection and Gmail checks for all users.

Runs at 07:00 and 15:00 Israel time. JSearch results are cached for 20 hours, so the
paid-quota source is effectively queried once a day; company boards are fetched both times.
"""

import logging
from zoneinfo import ZoneInfo

from arq import cron
from arq.connections import RedisSettings

from app.config import get_settings
from app.db import SessionLocal
from app.services import ingest
from app.services.gmail import sync as gmail_sync

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


async def collect_all(ctx) -> dict:
    return await ingest.collect(SessionLocal)


async def gmail_sync_all(ctx) -> dict:
    return await gmail_sync.sync_all(SessionLocal)


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    timezone = ZoneInfo("Asia/Jerusalem")
    cron_jobs = [
        cron(collect_all, hour={7, 15}, minute=0, timeout=1800, unique=True),
        # New job emails every 10 minutes
        cron(gmail_sync_all, minute=set(range(0, 60, 10)), timeout=300, unique=True),
    ]
    functions = [collect_all, gmail_sync_all]
