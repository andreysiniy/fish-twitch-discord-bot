"""PostgreSQL-backed tests for durable inventory overflow (mailbox) storage.

Covers plan section 10: a finite-stock drop that does not fit the player's
inventory is parked in ``inventory_overflow_items`` instead of being lost, and
an administrator reclaims it through ``DiscordAdminService``. Rows are
tenant-safe (composite FKs), status transitions are versioned, and a claim that
cannot fit leaves the parked row untouched.
"""

import os
import uuid
from datetime import datetime, timezone

import pytest
from api.discord_dependencies import DiscordServiceContext
from core.api_errors import ApiProblem
from domain.schemas.discord_admin import PlayerOverflowClaimRequest, PlayerOverflowItemDTO
from infrastructure.database import SessionLocal
from infrastructure.models import (
    Channel,
    DiscordAccountLink,
    DiscordGuildBinding,
    InventoryItem,
    InventoryOverflowItem,
    ItemDefinition,
    UserProgress,
)
from infrastructure.repositories.inventory_overflow_repo import InventoryOverflowRepository
from infrastructure.repositories.inventory_repo import InventoryRepository
from services.discord_admin_service import DiscordAdminService
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="requires PostgreSQL and Redis",
)


def _context(key: str, suffix: str) -> DiscordServiceContext:
    discord_user_id = f"1001-{suffix}"
    discord_guild_id = f"2001-{suffix}"
    return DiscordServiceContext(
        discord_user_id=discord_user_id,
        discord_guild_id=discord_guild_id,
        request_id=f"request-{key}",
        idempotency_key=f"integration:overflow:{suffix}:{key}",
        can_manage_guild=True,
        management_channel_id="3001",
    )


def _seed(db, suffix: str, *, slots: int = 1) -> tuple[Channel, UserProgress, ItemDefinition]:
    discord_user_id = f"1001-{suffix}"
    discord_guild_id = f"2001-{suffix}"
    channel = Channel(twitch_id=f"overflow-{suffix}", name="Overflow Channel", config={})
    db.add(channel)
    db.flush()
    now = datetime.now(timezone.utc)
    player = UserProgress(
        user_twitch_id=f"player-{suffix}",
        username=f"player_{suffix}",
        channel_id=channel.id,
        base_inventory_slots=slots,
    )
    definition = ItemDefinition(
        channel_id=channel.id,
        item_id=f"drop-{suffix}",
        title="Overflow Drop",
        type="material",
        stack_size=1,
        effects=[],
    )
    db.add_all(
        [
            player,
            definition,
            DiscordAccountLink(
                discord_user_id=discord_user_id,
                twitch_user_id=channel.twitch_id,
                twitch_login=channel.name,
                verified_at=now,
                last_verified_at=now,
            ),
            DiscordGuildBinding(
                discord_guild_id=discord_guild_id,
                channel_id=channel.id,
                configured_by_discord_id=discord_user_id,
            ),
        ]
    )
    db.flush()
    return channel, player, definition


def _park(db, player: UserProgress, definition: ItemDefinition) -> InventoryOverflowItem:
    return InventoryOverflowRepository(db).park(
        user=player,
        item_definition_id=definition.id,
        quantity=1,
        source_type="fishing_cast",
        source_id=f"cast-{uuid.uuid4().hex[:8]}",
    )


@pytest.mark.integration
def test_overflow_rows_are_parked_and_listed_for_the_owner() -> None:
    db = SessionLocal()
    try:
        suffix = uuid.uuid4().hex[:8]
        channel, player, definition = _seed(db, suffix)
        parked = _park(db, player, definition)
        db.flush()
        service = DiscordAdminService(db)

        listed = service.list_player_overflow(
            _context("list", suffix), channel.twitch_id, player.user_twitch_id
        )
        assert listed["user_twitch_id"] == player.user_twitch_id
        assert len(listed["items"]) == 1
        row = listed["items"][0]
        assert row["id"] == parked.id
        assert row["item_id"] == definition.item_id
        assert row["status"] == "parked"
        assert row["version"] == 1
        assert row["source_type"] == "fishing_cast"
        assert row["quantity"] == 1
        assert row["claimed_at"] is None

        other = UserProgress(
            user_twitch_id=f"other-{suffix}",
            username=f"other_{suffix}",
            channel_id=channel.id,
            base_inventory_slots=1,
        )
        db.add(other)
        db.flush()
        assert (
                service.list_player_overflow(
                _context("list-other", suffix), channel.twitch_id, other.user_twitch_id
            )["items"]
            == []
        )
    finally:
        db.rollback()
        db.close()


@pytest.mark.integration
def test_claim_overflow_grants_item_and_marks_row_claimed() -> None:
    db = SessionLocal()
    try:
        suffix = uuid.uuid4().hex[:8]
        channel, player, definition = _seed(db, suffix, slots=1)
        parked = _park(db, player, definition)
        db.flush()
        service = DiscordAdminService(db)

        result = service.claim_player_overflow(
            _context("claim-ok", suffix),
            channel.twitch_id,
            player.user_twitch_id,
            PlayerOverflowClaimRequest(
                items=[PlayerOverflowItemDTO(id=parked.id, version=parked.version)]
            ),
        )
        assert result["failed"] == []
        assert len(result["claimed"]) == 1
        assert result["claimed"][0]["status"] == "claimed"

        items = (
            db.query(InventoryItem)
            .filter(InventoryItem.user_id == player.id, InventoryItem.item_id == definition.id)
            .all()
        )
        assert [(item.slot_id, item.quantity) for item in items] == [(1, 1)]

        refreshed = (
            db.query(InventoryOverflowItem).filter(InventoryOverflowItem.id == parked.id).one()
        )
        assert refreshed.status == "claimed"
        assert refreshed.version == 2
        assert refreshed.claimed_at is not None
    finally:
        db.rollback()
        db.close()


@pytest.mark.integration
def test_claim_overflow_is_idempotent_and_does_not_double_grant() -> None:
    db = SessionLocal()
    try:
        suffix = uuid.uuid4().hex[:8]
        channel, player, definition = _seed(db, suffix, slots=1)
        parked = _park(db, player, definition)
        db.flush()
        service = DiscordAdminService(db)
        request = PlayerOverflowClaimRequest(
            items=[PlayerOverflowItemDTO(id=parked.id, version=parked.version)]
        )

        first = service.claim_player_overflow(
            _context("claim-replay", suffix), channel.twitch_id, player.user_twitch_id, request
        )
        replay = service.claim_player_overflow(
            _context("claim-replay", suffix), channel.twitch_id, player.user_twitch_id, request
        )

        assert replay == first
        items = (
            db.query(InventoryItem)
            .filter(InventoryItem.user_id == player.id, InventoryItem.item_id == definition.id)
            .all()
        )
        assert sum(item.quantity for item in items) == 1
    finally:
        db.rollback()
        db.close()


@pytest.mark.integration
def test_claim_overflow_when_inventory_full_returns_capacity_conflict() -> None:
    db = SessionLocal()
    try:
        suffix = uuid.uuid4().hex[:8]
        channel, player, definition = _seed(db, suffix, slots=1)
        filler = ItemDefinition(
            channel_id=channel.id,
            item_id=f"filler-{suffix}",
            title="Filler",
            type="material",
            stack_size=1,
            effects=[],
        )
        db.add(filler)
        db.flush()
        InventoryRepository(db).grant_many(player, [{"item_id": filler.item_id}])
        parked = _park(db, player, definition)
        db.flush()
        service = DiscordAdminService(db)

        result = service.claim_player_overflow(
            _context("claim-full", suffix),
            channel.twitch_id,
            player.user_twitch_id,
            PlayerOverflowClaimRequest(
                items=[PlayerOverflowItemDTO(id=parked.id, version=parked.version)]
            ),
        )
        assert result["claimed"] == []
        assert len(result["failed"]) == 1
        assert result["failed"][0]["code"] == "INVENTORY_CAPACITY_CONFLICT"

        refreshed = (
            db.query(InventoryOverflowItem).filter(InventoryOverflowItem.id == parked.id).one()
        )
        assert refreshed.status == "parked"
        assert refreshed.version == 1
    finally:
        db.rollback()
        db.close()


@pytest.mark.integration
def test_claim_overflow_stale_version_returns_version_conflict() -> None:
    db = SessionLocal()
    try:
        suffix = uuid.uuid4().hex[:8]
        channel, player, definition = _seed(db, suffix, slots=1)
        parked = _park(db, player, definition)
        db.flush()
        service = DiscordAdminService(db)

        result = service.claim_player_overflow(
            _context("claim-stale", suffix),
            channel.twitch_id,
            player.user_twitch_id,
            PlayerOverflowClaimRequest(items=[PlayerOverflowItemDTO(id=parked.id, version=99)]),
        )
        assert result["claimed"] == []
        assert result["failed"][0]["code"] == "OVERFLOW_VERSION_CONFLICT"
        assert result["failed"][0]["current_version"] == 1

        refreshed = (
            db.query(InventoryOverflowItem).filter(InventoryOverflowItem.id == parked.id).one()
        )
        assert refreshed.status == "parked"
    finally:
        db.rollback()
        db.close()


@pytest.mark.integration
def test_claim_overflow_unknown_or_already_claimed_row_is_not_found() -> None:
    db = SessionLocal()
    try:
        suffix = uuid.uuid4().hex[:8]
        channel, player, definition = _seed(db, suffix, slots=1)
        parked = _park(db, player, definition)
        db.flush()
        service = DiscordAdminService(db)

        missing = service.claim_player_overflow(
            _context("claim-missing", suffix),
            channel.twitch_id,
            player.user_twitch_id,
            PlayerOverflowClaimRequest(items=[PlayerOverflowItemDTO(id=999_999, version=1)]),
        )
        assert missing["claimed"] == []
        assert missing["failed"][0]["code"] == "OVERFLOW_ITEM_NOT_FOUND"

        service.claim_player_overflow(
            _context("claim-first", suffix),
            channel.twitch_id,
            player.user_twitch_id,
            PlayerOverflowClaimRequest(
                items=[PlayerOverflowItemDTO(id=parked.id, version=parked.version)]
            ),
        )
        repeat = service.claim_player_overflow(
            _context("claim-repeat", suffix),
            channel.twitch_id,
            player.user_twitch_id,
            PlayerOverflowClaimRequest(
                items=[PlayerOverflowItemDTO(id=parked.id, version=parked.version)]
            ),
        )
        assert repeat["claimed"] == []
        assert repeat["failed"][0]["code"] == "OVERFLOW_ITEM_NOT_FOUND"
    finally:
        db.rollback()
        db.close()


@pytest.mark.integration
def test_overflow_claim_requires_permission() -> None:
    db = SessionLocal()
    try:
        suffix = uuid.uuid4().hex[:8]
        channel, player, definition = _seed(db, suffix, slots=1)
        parked = _park(db, player, definition)
        db.add(
            DiscordAccountLink(
                discord_user_id=f"1002-{suffix}",
                twitch_user_id=f"outsider-{suffix}",
                twitch_login=f"outsider_{suffix}",
                verified_at=datetime.now(timezone.utc),
                last_verified_at=datetime.now(timezone.utc),
            )
        )
        db.flush()
        service = DiscordAdminService(db)
        outsider = DiscordServiceContext(
            discord_user_id=f"1002-{suffix}",
            discord_guild_id=f"2001-{suffix}",
            request_id=f"request-claim-forbidden-{suffix}",
            idempotency_key=f"integration:overflow:{suffix}:claim-forbidden",
            can_manage_guild=True,
            management_channel_id="3001",
        )

        with pytest.raises(ApiProblem) as denied:
            service.claim_player_overflow(
                outsider,
                channel.twitch_id,
                player.user_twitch_id,
                PlayerOverflowClaimRequest(
                    items=[PlayerOverflowItemDTO(id=parked.id, version=parked.version)]
                ),
            )
        assert denied.value.code == "PERMISSION_DENIED"
    finally:
        db.rollback()
        db.close()


@pytest.mark.integration
def test_overflow_table_rejects_invalid_status_and_quantity_at_db_level() -> None:
    db = SessionLocal()
    try:
        suffix = uuid.uuid4().hex[:8]
        channel, player, definition = _seed(db, suffix, slots=1)

        with pytest.raises(IntegrityError):
            db.add(
                InventoryOverflowItem(
                    channel_id=channel.id,
                    user_id=player.id,
                    item_definition_id=definition.id,
                    quantity=1,
                    source_type="fishing_cast",
                    status="invalid-status",
                    version=1,
                )
            )
            db.flush()
        db.rollback()

        with pytest.raises(IntegrityError):
            db.add(
                InventoryOverflowItem(
                    channel_id=channel.id,
                    user_id=player.id,
                    item_definition_id=definition.id,
                    quantity=0,
                    source_type="fishing_cast",
                    status="parked",
                    version=1,
                )
            )
            db.flush()
        db.rollback()
    finally:
        db.rollback()
        db.close()
