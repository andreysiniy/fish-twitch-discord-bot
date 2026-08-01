import asyncio

from infrastructure.database import SessionLocal
from infrastructure.repositories.channel_repo import ChannelRepository
from services.eventing.event_lifecycle_service import FishingEventLifecycleService


class FishingEventJobRunner:
    def __init__(self, poll_interval_seconds: float = 1.0, batch_size: int = 50):
        self.poll_interval_seconds = max(float(poll_interval_seconds), 0.2)
        self.batch_size = max(int(batch_size), 1)
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop(), name="fishing-event-job-runner")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            await self._task
            self._task = None

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._run_once()
            except Exception as error:
                print(f"[FishingEventJobRunner] loop error: {error}")

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.poll_interval_seconds)
            except asyncio.TimeoutError:
                continue

    def _run_once(self) -> None:
        db = SessionLocal()
        try:
            channel_repo = ChannelRepository(db)
            lifecycle = FishingEventLifecycleService(channel_repo=channel_repo)
            lifecycle.apply_due_jobs(limit=self.batch_size)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
