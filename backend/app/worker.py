"""Background worker (arq + Redis): scheduled tasks for all users.

Job search at 07:00 and 15:00 Israel time, Gmail every 5 minutes, AI grades every 5 minutes.
JSearch results are cached for 20 hours, so the paid-quota source is effectively queried once
a day; company boards are fetched both times.
"""

import logging
from zoneinfo import ZoneInfo

from arq import cron
from arq.connections import RedisSettings

from app.config import get_settings
from app.db import SessionLocal
from app.services import ai_match, ingest
from app.services.gmail import sync as gmail_sync

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


async def collect_all(ctx) -> dict:
    return await ingest.collect(SessionLocal)


async def ai_grade_pending(ctx) -> dict:
    return await ai_match.grade_pending(SessionLocal)


async def gmail_sync_all(ctx) -> dict:
    return await gmail_sync.sync_all(SessionLocal)


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    timezone = ZoneInfo("Asia/Jerusalem")
    cron_jobs = [
        cron(collect_all, hour={7, 15}, minute=0, timeout=1800, unique=True),
        # Job emails every 5 minutes (each check re-reads the last 24 hours of the Inbox, read or unread)
        cron(gmail_sync_all, minute=set(range(0, 60, 5)), timeout=240, unique=True),
        # AI grades for new or changed jobs (does nothing without ANTHROPIC_API_KEY)
        cron(ai_grade_pending, minute=set(range(2, 60, 5)), timeout=600, unique=True),
    ]
    functions = [collect_all, gmail_sync_all, ai_grade_pending]
