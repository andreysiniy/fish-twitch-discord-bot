import os
import uuid
from decimal import Decimal

import pytest
from infrastructure.database import SessionLocal
from infrastructure.models import Channel, FishingCast, UserProgress
from services.fishing.ledger_service import FishingLedgerService
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

    service = FishingService(
        user_repo=UserRepository(db),
        config_repo=ConfigRepository(db),
        cooldown_repo=CooldownRepository(db),
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
