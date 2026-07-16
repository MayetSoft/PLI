"""In-process scheduler (the alternative is a plain cron container
calling `python -m pli.jobs ...` — see docker-compose.yml).

Run alongside the web app:  python -m pli.scheduler
"""

from __future__ import annotations

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from . import jobs
from .config import Settings
from .rounds import PARIS


def build_scheduler(settings: Settings) -> BlockingScheduler:
    scheduler = BlockingScheduler(timezone=PARIS)
    scheduler.add_job(
        lambda: jobs.run_open(settings),
        CronTrigger(day_of_week="mon", hour=0, minute=0, timezone=PARIS),
        name="open-round",
    )
    scheduler.add_job(
        lambda: jobs.run_close(settings),
        CronTrigger(day_of_week="fri", hour=23, minute=59, timezone=PARIS),
        name="close-round",
    )
    scheduler.add_job(
        lambda: jobs.run_reveal(settings),
        CronTrigger(day_of_week="sat", hour=8, minute=0, timezone=PARIS),
        name="reveal-round",
    )
    return scheduler


if __name__ == "__main__":
    build_scheduler(Settings.from_env()).start()
