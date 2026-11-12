"""Background worker (arq + Redis): scheduled job collection for all users.

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

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


async def collect_all(ctx) -> dict:
    return await ingest.collect(SessionLocal)


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    timezone = ZoneInfo("Asia/Jerusalem")
    cron_jobs = [cron(collect_all, hour={7, 15}, minute=0, timeout=1800, unique=True)]
    functions = [collect_all]
