import asyncio
import json

from redis import Redis

from core.security import decrypt_token
from infrastructure.database import SessionLocal
from infrastructure.models import Channel
from infrastructure.redis_client import RedisClient
from infrastructure.se_client import SEApiClient


class SEJobRunner:
    QUEUE_NAME = "se_points_queue"

    def __init__(self, redis_client: Redis | None = None):
        self.redis_client = redis_client or RedisClient.get_client()
        self.se_client = SEApiClient()
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop(), name="se-job-runner")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            await self._task
            self._task = None

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                queue_entry = await asyncio.to_thread(self.redis_client.brpop, self.QUEUE_NAME, 1)
                if not queue_entry:
                    continue
                _, payload = queue_entry
                await self._process_job_payload(payload)
            except Exception as error:
                print(f"[SEJobRunner] loop error: {error}")

    async def _process_job_payload(self, payload: str) -> None:
        try:
            job = json.loads(payload)
        except json.JSONDecodeError:
            print(f"[SEJobRunner] invalid payload: {payload}")
            return

        channel_id = job.get("channel_id")
        twitch_username = str(job.get("twitch_username") or "").strip()
        amount = int(job.get("amount") or 0)
        if not channel_id or not twitch_username or amount == 0:
            return

        db = SessionLocal()
        try:
            channel = db.query(Channel).filter(Channel.id == int(channel_id)).first()
            if not channel or not channel.se_token or not channel.se_channel_id:
                return

            try:
                plain_token = decrypt_token(channel.se_token)
            except ValueError as error:
                print(f"[SEJobRunner] decrypt failed for channel {channel_id}: {error}")
                channel.se_token = None
                db.commit()
                return

            try:
                await self.se_client.add_points(
                    se_channel_id=str(channel.se_channel_id),
                    plain_token=plain_token,
                    username=twitch_username,
                    amount=amount,
                )
            except PermissionError:
                channel.se_token = None
                db.commit()
            except ValueError as error:
                print(f"[SEJobRunner] SE API error for channel {channel_id}: {error}")
            finally:
                await asyncio.sleep(0.5)
        finally:
            db.close()
