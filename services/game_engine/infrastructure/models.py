import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
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
            "type IN ('equipment','consumable','lootbox','material','quest','currency','collectible')",
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
    )

    id = Column(Integer, primary_key=True)
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=False, index=True)
    item_id = Column(String, nullable=False, index=True)
    title = Column(String, nullable=False)
    description = Column(String)
    type = Column(String, default="equipment", nullable=False)
    slot = Column(String, nullable=True)
    rarity = Column(String, default="common", nullable=False)
    durability = Column(Integer, nullable=True)
    max_durability = Column(Integer, nullable=True)
    break_policy = Column(String, default="indestructible", nullable=False)
    stack_size = Column(Integer, default=1, nullable=False)
    image_url = Column(String)
    base_stats = Column(JSONB, default=dict, nullable=False)
    effects = Column(JSONB, default=list, nullable=False)
    value = Column(Numeric(18, 2), nullable=True)
    sell_value = Column(Numeric(18, 2), nullable=True)
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
    is_sellable = Column(Boolean, default=True, nullable=False)
    is_tradeable = Column(Boolean, default=True, nullable=False)

    channel = relationship("Channel", back_populates="item_definitions")


class InventoryItem(Base):
    __tablename__ = "inventory_items"
    __table_args__ = (
        UniqueConstraint("user_id", "slot_id", name="uq_inventory_item_user_slot"),
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
    )


class EquippedItem(Base):
    __tablename__ = "equipped_items"
    __table_args__ = (
        UniqueConstraint("user_id", "slot", name="uq_equipped_items_user_slot"),
        UniqueConstraint("inventory_item_id", name="uq_equipped_items_inventory_item"),
        CheckConstraint(
            "slot IN ('rod','bait','defense','storage','charm_1','charm_2')",
            name="ck_equipped_items_slot",
        ),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users_progress.id", ondelete="CASCADE"), nullable=False)
    slot = Column(String, nullable=False)
    inventory_item_id = Column(
        Integer, ForeignKey("inventory_items.id", ondelete="CASCADE"), nullable=False
    )
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    owner = relationship("UserProgress", back_populates="equipped_items")
    inventory_item = relationship("InventoryItem", back_populates="equipped_record", lazy="joined")


class RewardPool(Base):
    __tablename__ = "reward_pools"
    __table_args__ = (
        UniqueConstraint("channel_id", "location_id", name="uq_reward_pool_channel_location"),
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
    loot_table_id = Column(Integer, ForeignKey("loot_tables.id", ondelete="CASCADE"), nullable=False)
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
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
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
