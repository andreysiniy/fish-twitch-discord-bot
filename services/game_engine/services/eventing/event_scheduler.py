import json
import time
import uuid
from typing import Any, Dict, List

from redis import Redis


class FishingEventScheduler:
    ZSET_KEY = "fish:event:disable:jobs"
    CHANNEL_JOB_KEY_TEMPLATE = "fish:event:disable:channel:{channel_twitch_id}"
    JOB_KEY_TEMPLATE = "fish:event:disable:job:{job_id}"

    def __init__(self, redis_client: Redis):
        self.redis_client = redis_client

    def schedule_disable(
        self,
        channel_twitch_id: str,
        channel_id: int,
        event_id: int,
        event_title: str,
        delay_seconds: int,
        requested_by: str,
    ) -> Dict[str, Any]:
        self.cancel_scheduled_disable(channel_twitch_id)

        now = int(time.time())
        execute_at = now + max(int(delay_seconds), 1)
        job_id = str(uuid.uuid4())
        payload = {
            "job_id": job_id,
            "kind": "disable_fishing_event",
            "channel_twitch_id": channel_twitch_id,
            "channel_id": channel_id,
            "event_id": event_id,
            "event_title": event_title,
            "requested_by": requested_by,
            "scheduled_at": now,
            "execute_at": execute_at,
            "chat": {
                "on_disable_message": f"Event '{event_title}' has ended.",
            },
        }

        job_key = self.JOB_KEY_TEMPLATE.format(job_id=job_id)
        channel_key = self.CHANNEL_JOB_KEY_TEMPLATE.format(channel_twitch_id=channel_twitch_id)
        self.redis_client.set(job_key, json.dumps(payload), ex=max(delay_seconds + 86400, 86400))
        self.redis_client.zadd(self.ZSET_KEY, {job_id: execute_at})
        self.redis_client.set(channel_key, job_id, ex=max(delay_seconds + 86400, 86400))
        return payload

    def cancel_scheduled_disable(self, channel_twitch_id: str) -> None:
        channel_key = self.CHANNEL_JOB_KEY_TEMPLATE.format(channel_twitch_id=channel_twitch_id)
        job_id = self.redis_client.get(channel_key)
        if not job_id:
            return
        if isinstance(job_id, bytes):
            job_id = job_id.decode("utf-8", errors="ignore")
        if not job_id:
            self.redis_client.delete(channel_key)
            return

        self.redis_client.zrem(self.ZSET_KEY, job_id)
        self.redis_client.delete(self.JOB_KEY_TEMPLATE.format(job_id=job_id))
        self.redis_client.delete(channel_key)

    def get_due_jobs(self, limit: int = 50) -> List[Dict[str, Any]]:
        now = int(time.time())
        job_ids = self.redis_client.zrangebyscore(self.ZSET_KEY, "-inf", now, start=0, num=max(int(limit), 1))
        jobs: List[Dict[str, Any]] = []
        for raw_job_id in job_ids:
            job_id = raw_job_id.decode("utf-8", errors="ignore") if isinstance(raw_job_id, bytes) else str(raw_job_id)
            payload_raw = self.redis_client.get(self.JOB_KEY_TEMPLATE.format(job_id=job_id))
            if not payload_raw:
                self.redis_client.zrem(self.ZSET_KEY, job_id)
                continue
            if isinstance(payload_raw, bytes):
                payload_raw = payload_raw.decode("utf-8", errors="ignore")
            try:
                jobs.append(json.loads(payload_raw))
            except Exception:
                self.redis_client.zrem(self.ZSET_KEY, job_id)
                self.redis_client.delete(self.JOB_KEY_TEMPLATE.format(job_id=job_id))
        return jobs

    def complete_job(self, channel_twitch_id: str, job_id: str) -> None:
        self.redis_client.zrem(self.ZSET_KEY, job_id)
        self.redis_client.delete(self.JOB_KEY_TEMPLATE.format(job_id=job_id))
        self.redis_client.delete(self.CHANNEL_JOB_KEY_TEMPLATE.format(channel_twitch_id=channel_twitch_id))
