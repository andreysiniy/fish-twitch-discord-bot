import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from infrastructure.database import Base

class Channel(Base):
    __tablename__ = "channels"
    __table_args__ = (UniqueConstraint("twitch_id", name="uq_channels_twitch_id"),)

    id = Column(Integer, primary_key=True)
    twitch_id = Column(String, nullable=False, index=True)
    name = Column(String)
    is_active = Column(Boolean, default=True, nullable=False)
    se_token = Column(String, nullable=True)
    se_channel_id = Column(String, nullable=True)
    
    config = Column(JSONB, default=dict, nullable=False)
    config_version = Column(Integer, default=1, nullable=False)
    config_updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    users_progress = relationship("UserProgress", back_populates="channel")
    reward_pools = relationship("RewardPool", back_populates="channel")
    item_definitions = relationship("ItemDefinition", back_populates="channel")
    fishing_events = relationship("FishingEvent", back_populates="channel")
    access_list = relationship(
        "ChannelAccessRole",
        back_populates="channel",
        cascade="all, delete-orphan"
    )


class ChannelAccessRole(Base):
    __tablename__ = "channel_access_roles"
    __table_args__ = (
        UniqueConstraint("channel_id", "user_twitch_id", name="uq_channel_user_access"),
    )

    id = Column(Integer, primary_key=True)
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=False, index=True)
    user_twitch_id = Column(String, nullable=False, index=True)
    user_twitch_name = Column(String, nullable=False, default="")
    role = Column(String, nullable=False, default="editor")

    channel = relationship("Channel", back_populates="access_list")


class UserProgress(Base):
    __tablename__ = "users_progress"
    __table_args__ = (
        UniqueConstraint("channel_id", "user_twitch_id", name="uq_user_progress_channel_user"),
        CheckConstraint("level >= 1", name="ck_users_progress_level_positive"),
        CheckConstraint("xp >= 0", name="ck_users_progress_xp_nonnegative"),
        CheckConstraint(
            "total_fish_stat >= 0", name="ck_users_progress_total_fish_nonnegative"
        ),
        CheckConstraint(
            "current_mass >= 0", name="ck_users_progress_current_mass_nonnegative"
        ),
    )

    id = Column(Integer, primary_key=True)
    user_twitch_id = Column(String, nullable=False, index=True)
    username = Column(String)                    
    
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=False, index=True)
    
    level = Column(Integer, default=1, nullable=False)
    xp = Column(Integer, default=0, nullable=False)

    total_fish_stat = Column(Integer, default=0, nullable=False)
    total_mass_stat = Column(Numeric(18, 2), default=0, nullable=False)

    current_mass = Column(Numeric(18, 2), default=0, nullable=False)

    current_location_id = Column(String, default="default", nullable=False)
    
    inventory = Column(
        JSONB,
        default=lambda: {"equipped_rod_slot": None, "max_slots": 20},
        nullable=False,
    )

    channel = relationship("Channel", back_populates="users_progress")
    items = relationship("InventoryItem", back_populates="owner", cascade="all, delete-orphan")
    equipped_items = relationship(
        "EquippedItem", back_populates="owner", cascade="all, delete-orphan"
    )
    modifiers = relationship(
        "PlayerModifier", back_populates="owner", cascade="all, delete-orphan"
    )


class ItemDefinition(Base):
    __tablename__ = "item_definitions"
    __table_args__ = (
        UniqueConstraint("channel_id", "item_id", name="uq_item_definitions_channel_item"),
        CheckConstraint("stack_size > 0", name="ck_item_definitions_stack_size_positive"),
        CheckConstraint(
            "type <> 'equipment' OR stack_size = 1",
            name="ck_item_definitions_equipment_single_stack",
        ),
        CheckConstraint(
            "max_durability IS NULL OR max_durability > 0",
            name="ck_item_definitions_max_durability_positive",
        ),
        CheckConstraint(
            "type IN ('equipment','consumable','lootbox','material','quest',"
            "'currency','collectible')",
            name="ck_item_definitions_type",
        ),
        CheckConstraint(
            "slot IS NULL OR slot IN ('rod','bait','defense','storage','charm_1','charm_2')",
            name="ck_item_definitions_slot",
        ),
        CheckConstraint(
            "rarity IN ('common','rare','epic','legendary')",
            name="ck_item_definitions_rarity",
        ),
        CheckConstraint(
            "break_policy IN ('indestructible','retain_broken','unequip_broken','destroy_at_zero')",
            name="ck_item_definitions_break_policy",
        ),
        CheckConstraint("version >= 1", name="ck_item_definitions_version_positive"),
        CheckConstraint(
            "schema_version >= 1", name="ck_item_definitions_schema_version_positive"
        ),
    )

    id = Column(Integer, primary_key=True)
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=False, index=True)
    item_id = Column(String, nullable=False, index=True)
    title = Column(String, nullable=False)
    description = Column(String)
    type = Column(String, default="equipment", nullable=False)
    slot = Column(String, nullable=True)
    rarity = Column(String, default="common", nullable=False)
    max_durability = Column(Integer, nullable=True)
    break_policy = Column(String, default="indestructible", nullable=False)
    stack_size = Column(Integer, default=1, nullable=False)
    image_url = Column(String)
    effects = Column(JSONB, default=list, nullable=False)
    value = Column(Numeric(18, 2), nullable=True)
    schema_version = Column(Integer, default=1, nullable=False)
    version = Column(Integer, default=1, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    archived_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_by = Column(String, nullable=True)

    channel = relationship("Channel", back_populates="item_definitions")


class InventoryItem(Base):
    __tablename__ = "inventory_items"
    __table_args__ = (
        UniqueConstraint("user_id", "slot_id", name="uq_inventory_item_user_slot"),
        # Composite key used by equipped_items to enforce same-owner equip.
        UniqueConstraint("id", "user_id", name="uq_inventory_item_id_user"),
        CheckConstraint("quantity > 0", name="ck_inventory_items_quantity_positive"),
        CheckConstraint("slot_id >= 1", name="ck_inventory_items_slot_positive"),
        CheckConstraint(
            "current_durability IS NULL OR current_durability >= 0",
            name="ck_inventory_items_durability_nonnegative",
        ),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer, ForeignKey("users_progress.id", ondelete="CASCADE"), nullable=False, index=True
    )
    item_id = Column(Integer, ForeignKey("item_definitions.id"), nullable=False, index=True)
    slot_id = Column(Integer, nullable=False)
    quantity = Column(Integer, default=1, nullable=False)
    current_durability = Column(Integer, nullable=True)
    meta = Column(JSONB, default=dict, nullable=False)
    definition_version = Column(Integer, default=1, nullable=False)
    version = Column(Integer, default=1, nullable=False)

    definition = relationship("ItemDefinition", lazy="joined")
    owner = relationship("UserProgress", back_populates="items")
    equipped_record = relationship(
        "EquippedItem",
        back_populates="inventory_item",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
        single_parent=True,
        overlaps="owner,equipped_items",
    )


class EquippedItem(Base):
    __tablename__ = "equipped_items"
    __table_args__ = (
        UniqueConstraint("user_id", "slot", name="uq_equipped_items_user_slot"),
        UniqueConstraint("inventory_item_id", name="uq_equipped_items_inventory_item"),
        ForeignKeyConstraint(
            ["inventory_item_id", "user_id"],
            ["inventory_items.id", "inventory_items.user_id"],
            name="fk_equipped_items_inventory_owner",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "slot IN ('rod','bait','defense','storage','charm_1','charm_2')",
            name="ck_equipped_items_slot",
        ),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users_progress.id", ondelete="CASCADE"), nullable=False)
    slot = Column(String, nullable=False)
    inventory_item_id = Column(Integer, nullable=False)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    owner = relationship(
        "UserProgress", back_populates="equipped_items", overlaps="equipped_record"
    )
    inventory_item = relationship(
        "InventoryItem",
        back_populates="equipped_record",
        lazy="joined",
        overlaps="owner,equipped_items",
    )


class RewardPool(Base):
    __tablename__ = "reward_pools"
    __table_args__ = (
        UniqueConstraint("channel_id", "location_id", name="uq_reward_pool_channel_location"),
        CheckConstraint(
            "items_drop_rate BETWEEN 0 AND 1",
            name="ck_reward_pools_items_drop_rate_range",
        ),
    )

    id = Column(Integer, primary_key=True)
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=False)
    location_id = Column(String, nullable=False, index=True)
    location_name = Column(String, nullable=True)
    
    rewards_data = Column(JSONB, default=list, nullable=False)
    requirements = Column(JSONB, default=dict, nullable=False)
    version = Column(Integer, default=1, nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    items_drop_rate = Column(Float, default=0.1, nullable=False)
    items = relationship("LocationItem", back_populates="pool")

    channel = relationship("Channel", back_populates="reward_pools")

class LocationItem(Base):
    __tablename__ = "location_items"
    __table_args__ = (
        UniqueConstraint(
            "reward_pool_id", "item_id", name="uq_location_items_pool_item"
        ),
        CheckConstraint(
            "weight > 0", name="ck_location_items_weight_positive"
        ),
        CheckConstraint(
            "quantity IS NULL OR quantity >= 0", name="ck_location_items_stock_nonnegative"
        ),
        CheckConstraint(
            "xp_gain >= 0", name="ck_location_items_xp_nonnegative"
        ),
    )

    id = Column(Integer, primary_key=True)
    reward_pool_id = Column(Integer, ForeignKey("reward_pools.id"), nullable=False)
    item_id = Column(Integer, ForeignKey("item_definitions.id"), nullable=False, index=True)
    weight = Column(Integer, default=100, nullable=False)
    xp_gain = Column(Integer, default=0, nullable=False)
    quantity = Column(Integer, nullable=True)
    message = Column(String, default="You caught {name}!", nullable=False)
    version = Column(Integer, default=1, nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    pool = relationship("RewardPool", back_populates="items")
    definition = relationship("ItemDefinition", lazy="joined")


class FishingEvent(Base):
    __tablename__ = "fishing_events"
    __table_args__ = (
        Index(
            "uq_fishing_events_active_per_channel",
            "channel_id",
            unique=True,
            postgresql_where=text("is_active = true"),
        ),
    )

    id = Column(Integer, primary_key=True)
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=False, index=True)
    event_title = Column(String, nullable=False, default="Untitled Event")
    is_active = Column(Boolean, default=False, nullable=False)
    status = Column(String, nullable=False, default="draft")
    starts_at = Column(DateTime(timezone=True), nullable=True)
    ends_at = Column(DateTime(timezone=True), nullable=True, index=True)
    activated_at = Column(DateTime(timezone=True), nullable=True)
    deactivated_at = Column(DateTime(timezone=True), nullable=True)
    modifier_schema_version = Column(Integer, nullable=False, default=2)
    requires_review = Column(Boolean, nullable=False, default=False)
    modifiers = Column(JSONB, default=dict, nullable=False)
    override_loot_pool = Column(String, nullable=True)
    version = Column(Integer, default=1, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    channel = relationship("Channel", back_populates="fishing_events")


class EconomyOperation(Base):
    __tablename__ = "economy_operations"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    idempotency_key = Column(String, unique=True, nullable=False)
    operation_type = Column(String, nullable=False)
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users_progress.id"), nullable=False, index=True)
    twitch_username = Column(String, nullable=False)
    mass_delta = Column(Numeric(18, 2), nullable=False, default=0)
    points_delta = Column(Integer, nullable=False, default=0)
    state = Column(String, nullable=False, default="pending", index=True)
    external_applied = Column(Boolean, nullable=False, default=False)
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    response_payload = Column(JSONB, default=dict, nullable=False)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    compensated_at = Column(DateTime(timezone=True), nullable=True)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    idempotency_key = Column(String, unique=True, nullable=False)
    topic = Column(String, nullable=False, index=True)
    payload = Column(JSONB, default=dict, nullable=False)
    state = Column(String, nullable=False, default="pending", index=True)
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    next_attempt_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    processed_at = Column(DateTime(timezone=True), nullable=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True, index=True)


class PlayerModifier(Base):
    __tablename__ = "player_modifiers"
    __table_args__ = (
        UniqueConstraint(
            "channel_id",
            "user_progress_id",
            "stat_key",
            "scope",
            "source_key",
            name="uq_player_modifiers_source",
        ),
        CheckConstraint("version >= 1", name="ck_player_modifiers_version_positive"),
        CheckConstraint(
            "operation IN ('add','multiply','override','min','max')",
            name="ck_player_modifiers_operation",
        ),
        CheckConstraint(
            "scope IN ('fishing','robbery','economy','inventory','all')",
            name="ck_player_modifiers_scope",
        ),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    channel_id = Column(Integer, ForeignKey("channels.id", ondelete="CASCADE"), nullable=False)
    user_progress_id = Column(
        Integer, ForeignKey("users_progress.id", ondelete="CASCADE"), nullable=False
    )
    stat_key = Column(String, nullable=False)
    operation = Column(String, nullable=False)
    value = Column(Numeric(24, 8), nullable=False)
    scope = Column(String, nullable=False, default="all")
    source_key = Column(String, nullable=False)
    reason = Column(String, nullable=False)
    starts_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
    is_enabled = Column(Boolean, default=True, nullable=False)
    created_by_twitch_id = Column(String, nullable=False)
    created_by_discord_id = Column(String, nullable=True)
    version = Column(Integer, default=1, nullable=False)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    owner = relationship("UserProgress", back_populates="modifiers")


class LootTable(Base):
    __tablename__ = "loot_tables"
    __table_args__ = (
        UniqueConstraint("channel_id", "table_id", name="uq_loot_tables_channel_table"),
    )

    id = Column(Integer, primary_key=True)
    channel_id = Column(Integer, ForeignKey("channels.id", ondelete="CASCADE"), nullable=False)
    table_id = Column(String, nullable=False)
    title = Column(String, nullable=False)
    version = Column(Integer, default=1, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    entries = relationship("LootTableEntry", cascade="all, delete-orphan", back_populates="table")


class LootTableEntry(Base):
    __tablename__ = "loot_table_entries"
    __table_args__ = (
        CheckConstraint("weight > 0", name="ck_loot_table_entries_weight_positive"),
        CheckConstraint("min_quantity > 0", name="ck_loot_table_entries_min_quantity_positive"),
        CheckConstraint(
            "max_quantity >= min_quantity", name="ck_loot_table_entries_quantity_range"
        ),
    )

    id = Column(Integer, primary_key=True)
    loot_table_id = Column(
        Integer,
        ForeignKey("loot_tables.id", ondelete="CASCADE"),
        nullable=False,
    )
    item_definition_id = Column(
        Integer, ForeignKey("item_definitions.id", ondelete="RESTRICT"), nullable=False
    )
    weight = Column(Integer, nullable=False)
    min_quantity = Column(Integer, default=1, nullable=False)
    max_quantity = Column(Integer, default=1, nullable=False)
    rarity_filter = Column(String, nullable=True)
    table = relationship("LootTable", back_populates="entries")
    definition = relationship("ItemDefinition", lazy="joined")


class InventoryItemUseRecord(Base):
    __tablename__ = "inventory_item_use_records"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_item_use_user_key"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users_progress.id", ondelete="CASCADE"), nullable=False)
    inventory_item_id = Column(Integer, nullable=False)
    idempotency_key = Column(String, nullable=False)
    response_json = Column(JSONB, default=dict, nullable=False)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class DiscordAccountLink(Base):
    __tablename__ = "discord_account_links"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    discord_user_id = Column(String, unique=True, nullable=False, index=True)
    twitch_user_id = Column(String, unique=True, nullable=False, index=True)
    twitch_login = Column(String, nullable=False)
    verified_at = Column(DateTime(timezone=True), nullable=False)
    last_verified_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    revoked_at = Column(DateTime(timezone=True), nullable=True)


class DiscordGuildBinding(Base):
    __tablename__ = "discord_guild_bindings"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    discord_guild_id = Column(String, unique=True, nullable=False, index=True)
    channel_id = Column(Integer, ForeignKey("channels.id"), unique=True, nullable=False, index=True)
    configured_by_discord_id = Column(String, nullable=False)
    management_channel_id = Column(String, nullable=True)
    locale = Column(String, nullable=False, default="en")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    channel = relationship("Channel")


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_log"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    request_id = Column(String, nullable=False, index=True)
    idempotency_key = Column(String, nullable=True, index=True)
    channel_twitch_id = Column(String, nullable=False, index=True)
    actor_twitch_id = Column(String, nullable=False, index=True)
    actor_discord_id = Column(String, nullable=True, index=True)
    actor_service = Column(String, nullable=False)
    guild_id = Column(String, nullable=True, index=True)
    action = Column(String, nullable=False, index=True)
    entity_type = Column(String, nullable=False)
    entity_id = Column(String, nullable=False)
    before_json = Column(JSONB, default=dict, nullable=False)
    after_json = Column(JSONB, default=dict, nullable=False)
    result = Column(String, nullable=False)
    error_code = Column(String, nullable=True)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("actor_scope", "idempotency_key", name="uq_idempotency_actor_key"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    actor_scope = Column(String, nullable=False)
    idempotency_key = Column(String, nullable=False)
    request_hash = Column(String, nullable=False)
    response_status = Column(Integer, nullable=False)
    response_json = Column(JSONB, default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)


class FishingRulesetSnapshot(Base):
    """Deduplicated snapshot of the static configuration applied to a cast."""

    __tablename__ = "fishing_ruleset_snapshots"
    __table_args__ = (
        UniqueConstraint("channel_id", "ruleset_hash", name="uq_ruleset_snapshot_channel_hash"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=False, index=True)
    ruleset_hash = Column(String(64), nullable=False)
    channel_config_version = Column(Integer, nullable=False)
    reward_pool_id = Column(Integer, nullable=True)
    reward_pool_version = Column(Integer, nullable=True)
    item_loot_table_id = Column(Integer, nullable=True)
    item_loot_table_version = Column(Integer, nullable=True)
    event_id = Column(Integer, nullable=True)
    event_version = Column(Integer, nullable=True)
    modifier_schema_version = Column(Integer, nullable=False)
    engine_version = Column(String(64), nullable=False)
    location_snapshot = Column(JSONB, default=dict, nullable=False)
    reward_entries_snapshot = Column(JSONB, default=list, nullable=False)
    item_entries_snapshot = Column(JSONB, default=list, nullable=False)
    effective_params_snapshot = Column(JSONB, default=dict, nullable=False)
    event_snapshot = Column(JSONB, default=dict, nullable=False)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    channel = relationship("Channel")


class FishingCast(Base):
    """One ledger row for every processed fishing attempt."""

    __tablename__ = "fishing_casts"
    __table_args__ = (
        # One idempotent source request may only produce one cast.
        Index(
            "uq_fishing_casts_source_request",
            "channel_id",
            "source",
            "source_request_id",
            unique=True,
            postgresql_where=text("source_request_id IS NOT NULL"),
        ),
        Index(
            "ix_fishing_casts_channel_requested",
            "channel_id",
            "requested_at",
            "id",
        ),
        Index(
            "ix_fishing_casts_channel_user",
            "channel_id",
            "user_progress_id",
            "requested_at",
        ),
        Index(
            "ix_fishing_casts_channel_location",
            "channel_id",
            "location_id",
            "requested_at",
        ),
        Index(
            "ix_fishing_casts_channel_reward",
            "channel_id",
            "reward_type",
            "requested_at",
        ),
        Index(
            "ix_fishing_casts_channel_event",
            "channel_id",
            "event_id",
            "requested_at",
        ),
        Index(
            "ix_fishing_casts_channel_status",
            "channel_id",
            "status",
            "requested_at",
        ),
        Index(
            "ix_fishing_casts_channel_item_drop",
            "channel_id",
            "requested_at",
            postgresql_where=text("item_drop_count > 0"),
        ),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=False, index=True)
    user_progress_id = Column(
        Integer, ForeignKey("users_progress.id"), nullable=False, index=True
    )
    ruleset_snapshot_id = Column(
        String,
        ForeignKey("fishing_ruleset_snapshots.id"),
        nullable=True,
        index=True,
    )
    source = Column(String(32), nullable=False, default="twitch")
    source_request_id = Column(String(128), nullable=True)

    status = Column(String(32), nullable=False, default="resolved", index=True)
    error_code = Column(String(64), nullable=True)

    # User and context snapshots.
    twitch_user_id_snapshot = Column(String, nullable=False)
    username_snapshot = Column(String, nullable=False)
    location_id = Column(String, nullable=False, default="default")
    location_name_snapshot = Column(String, nullable=True)
    is_mod = Column(Boolean, nullable=False, default=False)
    is_sub = Column(Boolean, nullable=False, default=False)
    bypass_cooldown = Column(Boolean, nullable=False, default=False)
    event_id = Column(Integer, nullable=True)
    event_title_snapshot = Column(String, nullable=True)

    # Time.
    requested_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    started_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    persisted_at = Column(
        DateTime(timezone=True),
        server_default=text("now()"),
        nullable=False,
    )
    duration_ms = Column(Integer, nullable=True)
    cooldown_seconds_applied = Column(Integer, nullable=False, default=0)
    next_available_at = Column(DateTime(timezone=True), nullable=True)

    # Mass/XP/level before and after.
    mass_before = Column(Numeric(18, 2), nullable=True)
    mass_after = Column(Numeric(18, 2), nullable=True)
    mass_delta_requested = Column(Numeric(18, 2), nullable=True)
    mass_delta_applied = Column(Numeric(18, 2), nullable=True)
    xp_before = Column(Integer, nullable=True)
    xp_after = Column(Integer, nullable=True)
    xp_gained = Column(Integer, nullable=True)
    level_before = Column(Integer, nullable=True)
    level_after = Column(Integer, nullable=True)
    points_delta = Column(Integer, nullable=False, default=0)
    was_level_up = Column(Boolean, nullable=False, default=False)

    # Ordinary reward.
    reward_id = Column(String, nullable=True)
    reward_type = Column(String, nullable=True)
    reward_weight = Column(Numeric(24, 8), nullable=True)
    reward_total_weight = Column(Numeric(24, 8), nullable=True)
    reward_probability = Column(Numeric(14, 12), nullable=True)
    reward_roll = Column(Numeric(24, 12), nullable=True)
    reward_snapshot = Column(JSONB, default=dict, nullable=False)

    # Item roll.
    item_drop_probability = Column(Numeric(14, 12), nullable=True)
    item_drop_roll = Column(Numeric(14, 12), nullable=True)
    item_drop_succeeded = Column(Boolean, nullable=False, default=False)
    item_drop_count = Column(Integer, nullable=False, default=0)

    # Explanation.
    resolved_modifiers = Column(JSONB, default=dict, nullable=False)
    modifier_sources = Column(JSONB, default=dict, nullable=False)
    equipped_items_snapshot = Column(JSONB, default=list, nullable=False)
    triggered_effects = Column(JSONB, default=list, nullable=False)
    rng_trace = Column(JSONB, default=list, nullable=False)
    special_result = Column(JSONB, default=dict, nullable=False)
    result_snapshot = Column(JSONB, default=dict, nullable=False)
    response_snapshot = Column(JSONB, default=dict, nullable=False)

    channel = relationship("Channel")
    item_drops = relationship(
        "FishingCastItemDrop",
        back_populates="cast",
        cascade="all, delete-orphan",
        order_by="FishingCastItemDrop.created_at",
    )


class FishingCastItemDrop(Base):
    """One item granted (or attempted) during a single cast."""

    __tablename__ = "fishing_cast_item_drops"
    __table_args__ = (
        Index(
            "ix_cast_item_drops_channel_item",
            "channel_id",
            "item_definition_id",
            "created_at",
        ),
        Index(
            "ix_cast_item_drops_channel_snapshot",
            "channel_id",
            "item_id_snapshot",
            "created_at",
        ),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    cast_id = Column(
        String, ForeignKey("fishing_casts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=False, index=True)
    item_definition_id = Column(Integer, nullable=True)
    item_id_snapshot = Column(String, nullable=False)
    title_snapshot = Column(String, nullable=False)
    rarity_snapshot = Column(String, nullable=True)
    item_type_snapshot = Column(String, nullable=True)
    definition_version = Column(Integer, nullable=True)
    loot_table_id = Column(Integer, nullable=True)
    loot_table_entry_id = Column(Integer, nullable=True)
    selection_weight = Column(Numeric(24, 8), nullable=True)
    selection_total_weight = Column(Numeric(24, 8), nullable=True)
    selection_probability = Column(Numeric(14, 12), nullable=True)
    selection_roll = Column(Numeric(24, 12), nullable=True)
    quantity_requested = Column(Integer, nullable=False)
    quantity_granted = Column(Integer, nullable=False)
    grant_status = Column(String(32), nullable=False, default="granted")
    stock_before = Column(Integer, nullable=True)
    stock_after = Column(Integer, nullable=True)
    inventory_grants = Column(JSONB, default=list, nullable=False)
    metadata_snapshot = Column(JSONB, default=dict, nullable=False)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    cast = relationship("FishingCast", back_populates="item_drops")
