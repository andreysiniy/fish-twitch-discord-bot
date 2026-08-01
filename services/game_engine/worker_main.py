import asyncio
import logging
import signal

from core.config import settings
from services.eventing.event_job_runner import FishingEventJobRunner
from services.eventing.se_job_runner import SEJobRunner


async def run_workers() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signal_name, stop_event.set)

    event_runner = FishingEventJobRunner()
    se_runner = SEJobRunner()
    await event_runner.start()
    await se_runner.start()
    try:
        await stop_event.wait()
    finally:
        await event_runner.stop()
        await se_runner.stop()


if __name__ == "__main__":
    asyncio.run(run_workers())
