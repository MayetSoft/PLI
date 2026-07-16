"""In-process scheduler (the alternative is plain cron running
`python -m pli.jobs tick` every minute — see docker-compose.yml).

A single minute tick drives everything: weekly cohorts keep their
Monday 00:00 / Friday 23:59 / Saturday 08:00 cadence, and custom-timeline
events open, close, and reveal at their own instants. The schedule lives
in the data, not the crontab.

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
        lambda: jobs.run_tick(settings),
        CronTrigger(minute="*", timezone=PARIS),
        name="tick",
    )
    return scheduler


if __name__ == "__main__":
    build_scheduler(Settings.from_env()).start()
