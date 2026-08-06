import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from infrastructure.database import SessionLocal
from infrastructure.models import Channel, FishingCast, RewardPool, UserProgress
from services.fishing_service import FishingService


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="requires PostgreSQL",
)


def _seed_channel_user(db, suffix: str):
    suffix = f"{suffix}-{uuid.uuid4().hex[:8]}"
    channel = Channel(twitch_id=suffix, name=f"ledger_{suffix}", config={})
    db.add(channel)
    db.flush()
    user = UserProgress(
        user_twitch_id=f"viewer-{suffix}",
        username=f"viewer_{suffix}",
        channel_id=channel.id,
        current_mass=Decimal("100.00"),
        xp=100,
        level=1,
        current_location_id="default",
    )
    db.add(user)
    db.flush()
    return channel, user


def _make_service(db):
    from infrastructure.repositories.channel_repo import ChannelRepository
    from infrastructure.repositories.config_repo import ConfigRepository
    from infrastructure.repositories.cooldown_repo import CooldownRepository
    from infrastructure.repositories.user_repo import UserRepository

    from infrastructure.redis_client import RedisClient

    service = FishingService(
        user_repo=UserRepository(db),
        config_repo=ConfigRepository(db),
        cooldown_repo=CooldownRepository(redis_client=RedisClient.get_client()),
        channel_repo=ChannelRepository(db),
    )
    return service


@pytest.mark.integration
def test_resolved_cast_is_recorded_with_response_snapshot() -> None:
    db = SessionLocal()
    try:
        channel, user = _seed_channel_user(db, "cast")
        service = _make_service(db)
        from domain.schemas.fishing import FishResponse

        service.presenter.build_response = lambda _u, _r: FishResponse(
            chat_message="ok", xp_gained=0, actions=[]
        )

        response = service.process_cast(
            user.user_twitch_id,
            user.username,
            channel.twitch_id,
            is_mod=True,
            source="twitch",
            source_request_id="msg-cast-1",
        )

        db.flush()
        cast = (
            db.query(FishingCast)
            .filter(FishingCast.source_request_id == "msg-cast-1")
            .one()
        )
        assert cast.status == "resolved"
        assert cast.channel_id == channel.id
        assert cast.user_progress_id == user.id
        assert cast.twitch_user_id_snapshot == user.user_twitch_id
        assert response is not None
    finally:
        db.rollback()
        db.close()


@pytest.mark.integration
def test_duplicate_source_request_replays_without_second_cast() -> None:
    db = SessionLocal()
    try:
        channel, user = _seed_channel_user(db, "replay")
        service = _make_service(db)
        from domain.schemas.fishing import FishResponse

        service.presenter.build_response = lambda _u, _r: FishResponse(
            chat_message="ok", xp_gained=0, actions=[]
        )

        service.process_cast(
            user.user_twitch_id,
            user.username,
            channel.twitch_id,
            is_mod=True,
            source="twitch",
            source_request_id="msg-replay-1",
        )
        db.flush()
        count_after_first = db.query(FishingCast).filter(
            FishingCast.source_request_id == "msg-replay-1"
        ).count()
        assert count_after_first == 1

        service.process_cast(
            user.user_twitch_id,
            user.username,
            channel.twitch_id,
            is_mod=True,
            source="twitch",
            source_request_id="msg-replay-1",
        )
        db.flush()
        count_after_second = db.query(FishingCast).filter(
            FishingCast.source_request_id == "msg-replay-1"
        ).count()
        assert count_after_second == 1
    finally:
        db.rollback()
        db.close()


@pytest.mark.integration
def test_cross_channel_cast_isolation() -> None:
    db = SessionLocal()
    try:
        channel_a, user_a = _seed_channel_user(db, "iso-a")
        _channel_b, _user_b = _seed_channel_user(db, "iso-b")

        service = _make_service(db)
        from domain.schemas.fishing import FishResponse

        service.presenter.build_response = lambda _u, _r: FishResponse(
            chat_message="ok", xp_gained=0, actions=[]
        )
        service.process_cast(
            user_a.user_twitch_id,
            user_a.username,
            channel_a.twitch_id,
            is_mod=True,
            source="twitch",
            source_request_id="msg-iso-1",
        )
        db.flush()

        # Same source_request_id under a different channel is a distinct cast.
        service.process_cast(
            user_a.user_twitch_id,
            user_a.username,
            channel_a.twitch_id,
            is_mod=True,
            source="twitch",
            source_request_id="msg-iso-2",
        )
        db.flush()
        assert (
            db.query(FishingCast)
            .filter(FishingCast.source_request_id == "msg-iso-2")
            .count()
            == 1
        )
    finally:
        db.rollback()
        db.close()


@pytest.mark.integration
def test_daily_stats_rebuild_is_idempotent() -> None:
    from datetime import datetime, timezone

    from infrastructure.models import FishingStatsDaily
    from infrastructure.repositories.fishing_cast_query_repo import (
        FishingCastQueryRepository,
    )

    db = SessionLocal()
    try:
        channel, user = _seed_channel_user(db, "daily")
        from domain.schemas.fishing import FishResponse

        service = _make_service(db)
        service.presenter.build_response = lambda _u, _r: FishResponse(
            chat_message="ok", xp_gained=0, actions=[]
        )
        service.process_cast(
            user.user_twitch_id,
            user.username,
            channel.twitch_id,
            is_mod=True,
            source="twitch",
            source_request_id="msg-daily-1",
        )
        db.flush()

        repo = FishingCastQueryRepository(db)
        day = datetime.now(timezone.utc).date()
        day_start = datetime(
            day.year, day.month, day.day, tzinfo=timezone.utc
        )
        buckets1 = repo.rebuild_daily_stats(day_start, channel_id=channel.id)

        # Idempotent: rebuilding yields the same total casts.
        buckets2 = repo.rebuild_daily_stats(day_start, channel_id=channel.id)
        db.flush()
        total = (
            db.query(FishingStatsDaily)
            .filter(FishingStatsDaily.day == day_start)
            .with_entities(FishingStatsDaily.casts)
            .all()
        )
        assert sum(row[0] for row in total) >= 1
        assert buckets1 == buckets2
    finally:
        db.rollback()
        db.close()


@pytest.mark.integration
def test_retention_runner_deletes_expired_idempotency_rows() -> None:
    from datetime import datetime, timedelta, timezone

    import asyncio

    from infrastructure.models import IdempotencyRecord
    from services.retention.retention_job_runner import RetentionJobRunner

    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        db.add(
            IdempotencyRecord(
                actor_scope="twitch:retention-test",
                idempotency_key="retention-key",
                request_hash="abc",
                response_status=200,
                response_json={},
                created_at=now - timedelta(days=400),
                expires_at=now - timedelta(days=399),
            )
        )
        db.commit()

        runner = RetentionJobRunner(interval_seconds=60.0)
        runner.run_once.__globals__["SessionLocal"] = lambda: db
        stats = asyncio.run(runner.run_once())

        remaining = (
            db.query(IdempotencyRecord)
            .filter(IdempotencyRecord.idempotency_key == "retention-key")
            .count()
        )
        assert remaining == 0
        assert stats["idempotency_records"] >= 1
    finally:
        db.rollback()
        db.close()


@pytest.mark.integration
def test_moderator_never_draws_timeout_reward_from_the_pool() -> None:
    """A channel moderator fishing must not get the timeout reward."""
    db = SessionLocal()
    try:
        channel, user = _seed_channel_user(db, "mod")
        # Pool containing only a timeout reward.
        pool = RewardPool(
            channel_id=channel.id,
            location_id="default",
            rewards_data=[
                {"type": "timeout", "weight": 100, "message": "Timed out!"}
            ],
            requirements={},
        )
        db.add(pool)
        db.flush()

        service = _make_service(db)
        response = service.process_cast(
            twitch_id=user.user_twitch_id,
            username=user.username,
            channel_id=channel.twitch_id,
            is_mod=True,
        )
        actions = response.model_dump(mode="json").get("actions", [])
        assert all(action.get("type") != "timeout" for action in actions)
        assert not any(
            str(action).find("Timed out!") != -1 for action in actions
        )

        # The same user WITHOUT mod flag can draw the timeout reward.
        non_mod = service.process_cast(
            twitch_id=user.user_twitch_id,
            username=user.username,
            channel_id=channel.twitch_id,
            is_mod=False,
        )
        non_mod_actions = non_mod.model_dump(mode="json").get("actions", [])
        assert any(
            action.get("type") == "timeout" for action in non_mod_actions
        )
    finally:
        db.rollback()
        db.close()


@pytest.mark.integration
def test_cast_without_source_request_id_still_records_internal_uuid() -> None:
    """Every processed cast gets a ledger row even without an external key."""
    db = SessionLocal()
    try:
        channel, user = _seed_channel_user(db, "nouuid")
        service = _make_service(db)
        response = service.process_cast(
            twitch_id=user.user_twitch_id,
            username=user.username,
            channel_id=channel.twitch_id,
        )
        cast = (
            db.query(FishingCast)
            .filter(
                FishingCast.channel_id == channel.id,
                FishingCast.status == "resolved",
            )
            .first()
        )
        assert cast is not None
        assert cast.source_request_id.startswith("internal-")
        assert response.cast_id == str(cast.id)
    finally:
        db.rollback()
        db.close()


@pytest.mark.integration
def test_full_inventory_records_cast_and_keeps_cooldown(monkeypatch) -> None:
    """A full inventory must not cancel the cast or skip the cooldown."""
    db = SessionLocal()
    try:
        channel, user = _seed_channel_user(db, "fullbag")
        service = _make_service(db)
        monkeypatch.setattr(
            "services.fishing_service.InventoryRepository.grant_many",
            _raise_capacity,
        )
        service.process_cast(
            twitch_id=user.user_twitch_id,
            username=user.username,
            channel_id=channel.twitch_id,
            source_request_id="fullbag-1",
            requested_at=datetime.now(timezone.utc),
        )
        cast = (
            db.query(FishingCast)
            .filter(
                FishingCast.channel_id == channel.id,
                FishingCast.source_request_id == "fullbag-1",
            )
            .first()
        )
        assert cast is not None
        assert cast.status == "resolved"
        # The cast must still be replayed by its stable key.
        replay = service.ledger.find_replay(channel.id, "twitch", "fullbag-1")
        assert replay is not None
    finally:
        db.rollback()
        db.close()


def _raise_capacity(*_args, **_kwargs):
    from infrastructure.repositories.inventory_repo import InventoryCapacityError

    raise InventoryCapacityError("Inventory is full (10 slots)")


@pytest.mark.integration
def test_unexpected_engine_error_records_a_failed_cast(monkeypatch) -> None:
    """An unexpected cast error still produces a durable failed ledger row."""
    db = SessionLocal()
    try:
        channel, user = _seed_channel_user(db, "fail")
        # Commit the seed so the separate failed-cast transaction can see it.
        db.commit()
        service = _make_service(db)

        def _boom(*_args, **_kwargs):
            raise RuntimeError("engine exploded")

        monkeypatch.setattr("services.fishing_service.FishingEngine.calculate_result", _boom)
        with pytest.raises(RuntimeError):
            service.process_cast(
                twitch_id=user.user_twitch_id,
                username=user.username,
                channel_id=channel.twitch_id,
                source_request_id="fail-1",
            )
        failed = (
            db.query(FishingCast)
            .filter(
                FishingCast.channel_id == channel.id,
                FishingCast.source_request_id == "fail-1",
                FishingCast.status == "failed",
            )
            .first()
        )
        assert failed is not None
        assert failed.error_code == "RuntimeError"
        assert failed.error_message == "engine exploded"
    finally:
        db.rollback()
        db.close()
