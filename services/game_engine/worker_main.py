import asyncio
import signal

from core.config import settings
from core.logging_config import configure_logging
from services.eventing.event_job_runner import FishingEventJobRunner
from services.eventing.se_job_runner import SEJobRunner
from services.retention.retention_job_runner import RetentionJobRunner


async def run_workers() -> None:
    configure_logging(settings.LOG_LEVEL)
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signal_name, stop_event.set)

    event_runner = FishingEventJobRunner()
    se_runner = SEJobRunner()
    retention_runner = RetentionJobRunner()
    await event_runner.start()
    await se_runner.start()
    await retention_runner.start()
    try:
        await stop_event.wait()
    finally:
        await event_runner.stop()
        await se_runner.stop()
        await retention_runner.stop()


if __name__ == "__main__":
    asyncio.run(run_workers())
