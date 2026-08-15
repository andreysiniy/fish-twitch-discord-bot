import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Uuid,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
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
    twitch_id = Column(String, nullable=False)
    name = Column(String)
    is_active = Column(Boolean, default=True, nullable=False)
    # Durable desired membership for the Twitch bot.  This is intentionally
    # separate from ``is_active`` which controls the game's configuration.
    twitch_bot_enabled = Column(Boolean, default=False, nullable=False)
    bot_membership_updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    bot_membership_updated_by_discord_id = Column(String, nullable=True)
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
        "ChannelAccessRole", back_populates="channel", cascade="all, delete-orphan"
    )
    integrations = relationship(
        "ChannelIntegration", back_populates="channel", cascade="all, delete-orphan"
    )
    economy_settings = relationship(
        "ChannelEconomySettings",
        back_populates="channel",
        uselist=False,
        cascade="all, delete-orphan",
    )


class ChannelIntegration(Base):
    """Encrypted credentials and provider identity for one channel."""

    __tablename__ = "channel_integrations"
    __table_args__ = (
        UniqueConstraint("channel_id", "provider", name="uq_channel_integrations_channel_provider"),
        CheckConstraint("provider = 'streamelements'", name="ck_channel_integrations_provider"),
        CheckConstraint(
            "status IN ('connected','degraded','invalid','disconnected')",
            name="ck_channel_integrations_status",
        ),
        CheckConstraint("credential_key_version >= 1", name="ck_channel_integrations_key_version"),
        CheckConstraint(
            "consecutive_failures >= 0",
            name="ck_channel_integrations_failures_nonnegative",
        ),
        CheckConstraint(
            "validation_latency_ms IS NULL OR validation_latency_ms >= 0",
            name="ck_channel_integrations_latency_nonnegative",
        ),
    )

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    channel_id = Column(
        Integer, ForeignKey("channels.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider = Column(String, nullable=False, default="streamelements")
    provider_channel_id = Column(String, nullable=False)
    credential_ciphertext = Column(Text, nullable=False)
    credential_key_version = Column(Integer, nullable=False, default=1)
    credential_fingerprint = Column(String(16), nullable=False)
    status = Column(String, nullable=False, default="connected")
    version = Column(Integer, nullable=False, default=1)
    last_validated_at = Column(DateTime(timezone=True), nullable=True)
    last_check_at = Column(DateTime(timezone=True), nullable=True)
    last_success_at = Column(DateTime(timezone=True), nullable=True)
    last_error_at = Column(DateTime(timezone=True), nullable=True)
    next_validation_at = Column(DateTime(timezone=True), nullable=True)
    consecutive_failures = Column(Integer, nullable=False, default=0)
    validation_latency_ms = Column(Integer, nullable=True)
    last_error_code = Column(String, nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    channel = relationship("Channel", back_populates="integrations")


class ChannelEconomySettings(Base):
    """Channel-owned points/mass pricing configuration."""

    __tablename__ = "channel_economy_settings"
    __table_args__ = (
        UniqueConstraint("channel_id", name="uq_channel_economy_settings_channel"),
        CheckConstraint("buy_points_per_kg > 0", name="ck_economy_settings_buy_rate_positive"),
        CheckConstraint("sell_points_per_kg > 0", name="ck_economy_settings_sell_rate_positive"),
        CheckConstraint("min_transaction_mass > 0", name="ck_economy_settings_min_mass_positive"),
        CheckConstraint(
            "max_transaction_mass >= min_transaction_mass", name="ck_economy_settings_mass_range"
        ),
    )

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    channel_id = Column(Integer, ForeignKey("channels.id", ondelete="CASCADE"), nullable=False)
    buy_points_per_kg = Column(Numeric(18, 4), nullable=False, default=Decimal("120"))
    sell_points_per_kg = Column(Numeric(18, 4), nullable=False, default=Decimal("100"))
    buy_enabled = Column(Boolean, nullable=False, default=True)
    sell_enabled = Column(Boolean, nullable=False, default=True)
    min_transaction_mass = Column(Numeric(18, 2), nullable=False, default=Decimal("0.01"))
    max_transaction_mass = Column(
        Numeric(18, 2), nullable=False, default=Decimal("2147483647")
    )
    enabled = Column(Boolean, nullable=False, default=True)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    channel = relationship("Channel", back_populates="economy_settings")


class ChannelAccessRole(Base):
    __tablename__ = "channel_access_roles"
    __table_args__ = (
        UniqueConstraint("channel_id", "user_twitch_id", name="uq_channel_user_access"),
        CheckConstraint(
            "role IN ('owner','editor','moderator')",
            name="ck_channel_access_roles_role",
        ),
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
        # Tenant-aware composite key used by composite FKs from children.
        UniqueConstraint("id", "channel_id", name="uq_users_progress_id_channel"),
        CheckConstraint("level >= 1", name="ck_users_progress_level_positive"),
        CheckConstraint("xp >= 0", name="ck_users_progress_xp_nonnegative"),
        CheckConstraint("total_fish_stat >= 0", name="ck_users_progress_total_fish_nonnegative"),
        CheckConstraint("current_mass >= 0", name="ck_users_progress_current_mass_nonnegative"),
        CheckConstraint(
            "base_inventory_slots >= 1",
            name="ck_users_progress_base_inventory_slots_positive",
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

    base_inventory_slots = Column(Integer, default=20, nullable=False)

    channel = relationship("Channel", back_populates="users_progress")
    items = relationship("InventoryItem", back_populates="owner", cascade="all, delete-orphan")
    equipped_items = relationship(
        "EquippedItem", back_populates="owner", cascade="all, delete-orphan"
    )
    modifiers = relationship("PlayerModifier", back_populates="owner", cascade="all, delete-orphan")


class ItemDefinition(Base):
    __tablename__ = "item_definitions"
    __table_args__ = (
        UniqueConstraint("channel_id", "item_id", name="uq_item_definitions_channel_item"),
        UniqueConstraint("id", "channel_id", name="uq_item_definitions_id_channel"),
        CheckConstraint("stack_size > 0", name="ck_item_definitions_stack_size_positive"),
        CheckConstraint(
            "type <> 'equipment' OR stack_size = 1",
            name="ck_item_definitions_equipment_single_stack",
        ),
        CheckConstraint(
            "(type = 'equipment' AND slot IS NOT NULL AND stack_size = 1) "
            "OR (type <> 'equipment' AND slot IS NULL)",
            name="ck_item_definitions_type_slot",
        ),
        CheckConstraint(
            "(break_policy = 'indestructible' AND max_durability IS NULL) "
            "OR (break_policy <> 'indestructible' AND max_durability IS NOT NULL)",
            name="ck_item_definitions_durability_policy",
        ),
        CheckConstraint(
            "max_durability IS NULL OR max_durability > 0",
            name="ck_item_definitions_max_durability_positive",
        ),
        # Charges belong to consumables only (spec 11.4): a non-consumable must
        # never carry max_charges, and a charge-based consumable is a single
        # instance (stack_size 1) because each instance tracks its own charges.
        CheckConstraint(
            "type = 'consumable' OR max_charges IS NULL",
            name="ck_item_definitions_charges_consumable_only",
        ),
        CheckConstraint(
            "max_charges IS NULL OR max_charges > 0",
            name="ck_item_definitions_max_charges_positive",
        ),
        CheckConstraint(
            "max_charges IS NULL OR stack_size = 1",
            name="ck_item_definitions_charges_single_stack",
        ),
        # Durability belongs to equipment only (spec 11.4). Non-equipment items
        # never carry durability, so the durability policy is meaningless there.
        CheckConstraint(
            "type = 'equipment' OR max_durability IS NULL",
            name="ck_item_definitions_durability_equipment_only",
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
        CheckConstraint("schema_version >= 1", name="ck_item_definitions_schema_version_positive"),
        CheckConstraint(
            "nominal_value IS NULL OR nominal_value >= 0",
            name="ck_item_definitions_nominal_value_nonnegative",
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
    max_charges = Column(Integer, nullable=True)
    break_policy = Column(String, default="indestructible", nullable=False)
    stack_size = Column(Integer, default=1, nullable=False)
    image_url = Column(String)
    effects = Column(JSONB, default=list, nullable=False)
    nominal_value = Column(Numeric(18, 2), nullable=True)
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
        # Charges are only meaningful for a charge-based consumable definition;
        # the row may not exceed the definition's max_charges (spec 11.4).
        CheckConstraint(
            "current_charges IS NULL OR current_charges >= 0",
            name="ck_inventory_items_charges_nonnegative",
        ),
        CheckConstraint("version >= 1", name="ck_inventory_items_version_positive"),
        CheckConstraint(
            "obtained_definition_version >= 1",
            name="ck_inventory_items_obtained_definition_version_positive",
        ),
        # Tenant-aware composite FKs: an inventory row belongs to the same
        # Twitch channel as its owner and its item definition.
        ForeignKeyConstraint(
            ["user_id", "channel_id"],
            ["users_progress.id", "users_progress.channel_id"],
            name="fk_inventory_items_user_channel",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["item_id", "channel_id"],
            ["item_definitions.id", "item_definitions.channel_id"],
            name="fk_inventory_items_item_channel",
        ),
    )

    id = Column(Integer, primary_key=True)
    channel_id = Column(Integer, nullable=False, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    item_id = Column(Integer, nullable=False, index=True)
    slot_id = Column(Integer, nullable=False)
    quantity = Column(Integer, default=1, nullable=False)
    current_durability = Column(Integer, nullable=True)
    current_charges = Column(Integer, nullable=True)
    meta = Column(JSONB, default=dict, nullable=False)
    # This is the immutable definition version captured when the instance was
    # granted. The current live version is read from ItemDefinition.version.
    obtained_definition_version = Column(Integer, default=1, nullable=False)
    version = Column(Integer, default=1, nullable=False)

    definition = relationship(
        "ItemDefinition",
        lazy="joined",
        primaryjoin="and_(InventoryItem.item_id == ItemDefinition.id, "
        "InventoryItem.channel_id == ItemDefinition.channel_id)",
        foreign_keys="[InventoryItem.item_id, InventoryItem.channel_id]",
        overlaps="owner,items",
    )
    owner = relationship("UserProgress", back_populates="items", overlaps="definition")
    equipped_record = relationship(
        "EquippedItem",
        back_populates="inventory_item",
        uselist=False,
        cascade="all, delete-orphan",
        foreign_keys="EquippedItem.inventory_item_id",
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
    inventory_item_id = Column(
        Integer,
        ForeignKey("inventory_items.id", ondelete="CASCADE"),
        nullable=False,
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

    owner = relationship(
        "UserProgress", back_populates="equipped_items", overlaps="equipped_record"
    )
    inventory_item = relationship(
        "InventoryItem",
        back_populates="equipped_record",
        lazy="joined",
        overlaps="owner,equipped_items",
        foreign_keys=[inventory_item_id],
    )


class RewardPool(Base):
    __tablename__ = "reward_pools"
    __table_args__ = (
        UniqueConstraint("channel_id", "location_id", name="uq_reward_pool_channel_location"),
        UniqueConstraint("id", "channel_id", name="uq_reward_pools_id_channel"),
        CheckConstraint(
            "items_drop_rate BETWEEN 0 AND 1",
            name="ck_reward_pools_items_drop_rate_range",
        ),
        CheckConstraint("version >= 1", name="ck_reward_pools_version_positive"),
        # Tenant-aware link: a pool may only reference a loot table of the SAME
        # channel. RESTRICT (not SET NULL) because the composite FK cannot
        # null out channel_id; deleting a table still in use is blocked.
        ForeignKeyConstraint(
            ["item_loot_table_id", "channel_id"],
            ["loot_tables.id", "loot_tables.channel_id"],
            name="fk_reward_pools_item_loot_table_channel",
            ondelete="RESTRICT",
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

    items_drop_rate = Column(Numeric(18, 6), default=Decimal("0.1"), nullable=False)
    item_loot_table_id = Column(Integer, nullable=True)
    channel = relationship("Channel", back_populates="reward_pools")


class FishingEvent(Base):
    __tablename__ = "fishing_events"
    __table_args__ = (
        Index(
            "uq_fishing_events_active_per_channel",
            "channel_id",
            unique=True,
            postgresql_where=text("is_active = true"),
        ),
        Index(
            "ix_fishing_events_active_ends_at",
            "ends_at",
            postgresql_where=text("is_active = true"),
        ),
        CheckConstraint(
            "status IN ('draft', 'active', 'ended')",
            name="ck_fishing_events_status_values",
        ),
        CheckConstraint("version >= 1", name="ck_fishing_events_version_positive"),
        CheckConstraint(
            "modifier_schema_version >= 1",
            name="ck_fishing_events_modifier_schema_version_positive",
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
    modifiers_history = Column(JSONB, default=list, nullable=False)
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
    __table_args__ = (
        CheckConstraint(
            "operation_type IN ('sell','buy','reward_points')",
            name="ck_economy_operations_operation_type",
        ),
        CheckConstraint(
            "state IN ('pending','queued','processing','external_pending','external_applied',"
            "'completed','compensated','failed','reconciliation_required','dead_letter')",
            name="ck_economy_operations_state",
        ),
        ForeignKeyConstraint(
            ["user_id", "channel_id"],
            ["users_progress.id", "users_progress.channel_id"],
            name="fk_economy_operations_user_channel",
        ),
    )

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    idempotency_key = Column(String, unique=True, nullable=False)
    operation_type = Column(String, nullable=False)
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=False, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    twitch_username = Column(String, nullable=False)
    provider = Column(String, nullable=False, default="streamelements")
    integration_id = Column(
        Uuid(as_uuid=True), ForeignKey("channel_integrations.id"), nullable=True, index=True
    )
    source = Column(String, nullable=False, default="twitch")
    source_request_id = Column(String, nullable=True)
    provider_channel_id_snapshot = Column(String, nullable=True)
    raw_command_argument = Column(String, nullable=True)
    argument_mode = Column(String, nullable=True)
    argument_unit = Column(String, nullable=True)
    argument_multiplier_kg = Column(Numeric(24, 8), nullable=True)
    mass_effective = Column(Numeric(18, 2), nullable=True)
    pricing_mode_snapshot = Column(String, nullable=True)
    buy_rate_snapshot = Column(Numeric(18, 4), nullable=True)
    sell_rate_snapshot = Column(Numeric(18, 4), nullable=True)
    rate_used_snapshot = Column(Numeric(18, 4), nullable=True)
    settings_version_snapshot = Column(Integer, nullable=True)
    player_mass_before = Column(Numeric(18, 2), nullable=True)
    player_mass_after = Column(Numeric(18, 2), nullable=True)
    provider_balance_before = Column(Integer, nullable=True)
    provider_balance_after = Column(Integer, nullable=True)
    provider_points_cap = Column(Integer, nullable=True)
    provider_points_headroom_before = Column(Integer, nullable=True)
    provider_points_headroom_after = Column(Integer, nullable=True)
    provider_status_code = Column(Integer, nullable=True)
    provider_request_meta = Column(JSONB, default=dict, nullable=False)
    mass_delta = Column(Numeric(18, 2), nullable=False, default=0)
    points_delta = Column(Numeric(30, 0), nullable=False, default=0)
    points_calculated = Column(Numeric(30, 0), nullable=False, default=0)
    state = Column(String, nullable=False, default="pending", index=True)
    external_applied = Column(Boolean, nullable=False, default=False)
    attempts = Column(Integer, nullable=False, default=0)
    version = Column(Integer, nullable=False, default=1)
    last_error = Column(Text, nullable=True)
    error_code = Column(String, nullable=True)
    compensation_state = Column(String, nullable=True)
    reconciliation_reason = Column(Text, nullable=True)
    response_payload = Column(JSONB, default=dict, nullable=False)
    requested_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    started_at = Column(DateTime(timezone=True), nullable=True)
    external_applied_at = Column(DateTime(timezone=True), nullable=True)
    internal_applied_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
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


class EconomyOperationEvent(Base):
    __tablename__ = "economy_operation_events"
    __table_args__ = (
        UniqueConstraint(
            "operation_id", "sequence_no", name="uq_economy_operation_events_sequence"
        ),
        Index("ix_economy_operation_events_operation_sequence", "operation_id", "sequence_no"),
        Index("ix_economy_operation_events_created_at", "created_at"),
    )

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    operation_id = Column(
        Uuid(as_uuid=True), ForeignKey("economy_operations.id", ondelete="CASCADE"), nullable=False
    )
    sequence_no = Column(Integer, nullable=False)
    event_type = Column(String, nullable=False)
    from_state = Column(String, nullable=True)
    to_state = Column(String, nullable=True)
    actor_type = Column(String, nullable=False, default="system")
    actor_id = Column(String, nullable=True)
    event_metadata = Column("metadata", JSONB, default=dict, nullable=False)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class EconomyProviderAttempt(Base):
    __tablename__ = "economy_provider_attempts"
    __table_args__ = (
        UniqueConstraint("operation_id", "attempt_no", name="uq_economy_provider_attempts_number"),
        Index("ix_economy_provider_attempts_operation", "operation_id"),
    )

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    operation_id = Column(
        Uuid(as_uuid=True), ForeignKey("economy_operations.id", ondelete="CASCADE"), nullable=False
    )
    attempt_no = Column(Integer, nullable=False)
    request_kind = Column(String, nullable=False)
    points_delta = Column(Integer, nullable=True)
    provider_balance_before = Column(Integer, nullable=True)
    provider_balance_after = Column(Integer, nullable=True)
    provider_points_cap = Column(Integer, nullable=True)
    request_started_at = Column(DateTime(timezone=True), nullable=False)
    request_finished_at = Column(DateTime(timezone=True), nullable=True)
    http_status = Column(Integer, nullable=True)
    outcome = Column(String, nullable=False)
    latency_ms = Column(Integer, nullable=True)
    provider_request_id = Column(String, nullable=True)
    safe_request_meta = Column(JSONB, default=dict, nullable=False)
    safe_response_meta = Column(JSONB, default=dict, nullable=False)
    error_code = Column(String, nullable=True)
    error_message = Column(Text, nullable=True)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        CheckConstraint(
            "state IN ('pending','processing','processed','failed',"
            "'dead_letter','compensated','reconciliation_required')",
            name="ck_outbox_events_state",
        ),
        Index(
            "ix_outbox_pending_due",
            "next_attempt_at",
            "created_at",
            postgresql_where=text("state = 'pending'"),
        ),
        Index(
            "ix_outbox_processing_lease",
            "lease_expires_at",
            "created_at",
            postgresql_where=text("state = 'processing'"),
        ),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    idempotency_key = Column(String, unique=True, nullable=False)
    topic = Column(String, nullable=False, index=True)
    payload = Column(JSONB, default=dict, nullable=False)
    state = Column(String, nullable=False, default="pending", index=True)
    attempts = Column(Integer, nullable=False, default=0)
    version = Column(Integer, nullable=False, default=1)
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
            "scope IN ('fishing','robbery','inventory','all')",
            name="ck_player_modifiers_scope",
        ),
        Index("ix_player_modifiers_user", "user_progress_id"),
        ForeignKeyConstraint(
            ["user_progress_id", "channel_id"],
            ["users_progress.id", "users_progress.channel_id"],
            name="fk_player_modifiers_user_channel",
            ondelete="CASCADE",
        ),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    channel_id = Column(Integer, ForeignKey("channels.id", ondelete="CASCADE"), nullable=False)
    user_progress_id = Column(Integer, nullable=False)
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
        UniqueConstraint("id", "channel_id", name="uq_loot_tables_id_channel"),
        CheckConstraint("version >= 1", name="ck_loot_tables_version_positive"),
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
        CheckConstraint("xp_gain >= 0", name="ck_loot_table_entries_xp_nonnegative"),
        CheckConstraint("version >= 1", name="ck_loot_table_entries_version_positive"),
        CheckConstraint(
            "config_version >= 1", name="ck_loot_table_entries_config_version_positive"
        ),
        UniqueConstraint(
            "loot_table_id", "item_definition_id", name="uq_loot_table_entries_table_item"
        ),
        ForeignKeyConstraint(
            ["loot_table_id", "channel_id"],
            ["loot_tables.id", "loot_tables.channel_id"],
            name="fk_loot_table_entries_table_channel",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["item_definition_id", "channel_id"],
            ["item_definitions.id", "item_definitions.channel_id"],
            name="fk_loot_table_entries_item_channel",
        ),
    )

    id = Column(Integer, primary_key=True)
    channel_id = Column(Integer, nullable=False)
    loot_table_id = Column(Integer, nullable=False)
    item_definition_id = Column(Integer, nullable=False)
    weight = Column(Integer, nullable=False)
    min_quantity = Column(Integer, default=1, nullable=False)
    max_quantity = Column(Integer, default=1, nullable=False)
    xp_gain = Column(Integer, default=0, nullable=False)
    message = Column(String, nullable=True)
    config_version = Column(Integer, default=1, nullable=False)
    version = Column(Integer, default=1, nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    table = relationship("LootTable", back_populates="entries", overlaps="definition")
    definition = relationship(
        "ItemDefinition",
        lazy="joined",
        primaryjoin="and_(LootTableEntry.item_definition_id == ItemDefinition.id, "
        "LootTableEntry.channel_id == ItemDefinition.channel_id)",
        foreign_keys="[LootTableEntry.item_definition_id, LootTableEntry.channel_id]",
        overlaps="entries,table",
    )
    stock = relationship(
        "LootTableEntryStock",
        back_populates="entry",
        uselist=False,
        cascade="all, delete-orphan",
    )


class LootTableEntryStock(Base):
    """Global remaining stock for a single loot-table entry."""

    __tablename__ = "loot_table_entry_stock"
    __table_args__ = (
        CheckConstraint(
            "remaining_quantity >= 0",
            name="ck_loot_table_entry_stock_remaining_nonnegative",
        ),
        CheckConstraint("version >= 1", name="ck_loot_table_entry_stock_version_positive"),
    )
    id = Column(Integer, primary_key=True)
    loot_table_entry_id = Column(
        Integer,
        ForeignKey("loot_table_entries.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    remaining_quantity = Column(Integer, nullable=False)
    version = Column(Integer, default=1, nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    entry = relationship("LootTableEntry", back_populates="stock")


class InventoryItemUseRecord(Base):
    __tablename__ = "inventory_item_use_records"
    __table_args__ = (UniqueConstraint("user_id", "idempotency_key", name="uq_item_use_user_key"),)

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users_progress.id", ondelete="CASCADE"), nullable=False)
    inventory_item_id = Column(
        Integer,
        ForeignKey("inventory_items.id", ondelete="SET NULL"),
        nullable=True,
    )
    idempotency_key = Column(String, nullable=False)
    response_json = Column(JSONB, default=dict, nullable=False)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class DiscordAccountLink(Base):
    __tablename__ = "discord_account_links"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    discord_user_id = Column(String, unique=True, nullable=False)
    twitch_user_id = Column(String, unique=True, nullable=False)
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
    discord_guild_id = Column(String, unique=True, nullable=False)
    channel_id = Column(Integer, ForeignKey("channels.id"), unique=True, nullable=False)
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
    __table_args__ = (
        CheckConstraint(
            "result IN ('success','error')",
            name="ck_admin_audit_log_result",
        ),
    )

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

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
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
        UniqueConstraint("id", "channel_id", name="uq_fishing_casts_id_channel"),
        ForeignKeyConstraint(
            ["user_progress_id", "channel_id"],
            ["users_progress.id", "users_progress.channel_id"],
            name="fk_fishing_casts_user_channel",
        ),
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

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=False, index=True)
    user_progress_id = Column(Integer, nullable=False, index=True)
    ruleset_snapshot_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("fishing_ruleset_snapshots.id"),
        nullable=True,
        index=True,
    )
    source = Column(String(32), nullable=False, default="twitch")
    source_request_id = Column(String(128), nullable=True)

    status = Column(String(32), nullable=False, default="resolved", index=True)
    error_code = Column(String(64), nullable=True)
    error_message = Column(String(500), nullable=True)

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
    # Fine-grained drop outcome: gate roll, selection, stock reservation and
    # the inventory grant are tracked separately so a failed grant (e.g. full
    # inventory) is not confused with a failed gate roll.
    item_drop_gate_success = Column(Boolean, nullable=True)
    item_drop_selection_success = Column(Boolean, nullable=True)
    item_drop_stock_reserved = Column(Boolean, nullable=True)
    item_drop_grant_success = Column(Boolean, nullable=True)

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
        ForeignKeyConstraint(
            ["cast_id", "channel_id"],
            ["fishing_casts.id", "fishing_casts.channel_id"],
            name="fk_fishing_cast_item_drops_cast_channel",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["item_definition_id", "channel_id"],
            ["item_definitions.id", "item_definitions.channel_id"],
            name="fk_fishing_cast_item_drops_item_channel",
        ),
    )

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cast_id = Column(Uuid(as_uuid=True), nullable=False, index=True)
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


class FishingStatsDaily(Base):
    """Idempotent daily aggregate over the fishing cast ledger."""

    __tablename__ = "fishing_stats_daily"
    __table_args__ = (
        # NULLS NOT DISTINCT so a bucket with any NULL dimension stays unique
        # under parallel rebuilds (PostgreSQL 15+).
        Index(
            "uq_fishing_stats_daily_bucket",
            "day",
            "channel_id",
            "location_id",
            "event_id",
            "reward_type",
            "item_definition_id",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        Index(
            "ix_fishing_stats_daily_channel_day",
            "channel_id",
            "day",
        ),
    )

    id = Column(Integer, primary_key=True)
    day = Column(DateTime(timezone=True), nullable=False)
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=False)
    location_id = Column(String, nullable=True)
    event_id = Column(Integer, nullable=True)
    reward_type = Column(String, nullable=True)
    item_definition_id = Column(Integer, nullable=True)
    casts = Column(Integer, nullable=False, default=0)
    unique_players = Column(Integer, nullable=False, default=0)
    mass_positive = Column(Numeric(18, 2), nullable=False, default=0)
    mass_negative = Column(Numeric(18, 2), nullable=False, default=0)
    xp_gained = Column(Integer, nullable=False, default=0)
    item_drop_expected = Column(Numeric(18, 2), nullable=False, default=0)
    item_drop_actual = Column(Integer, nullable=False, default=0)
    failures = Column(Integer, nullable=False, default=0)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class InventoryOverflowItem(Base):
    """Durable parking for drops that did not fit the player's inventory.

    A full inventory must never lose a finite-stock drop (plan section 10):
    when the normal grant raises ``InventoryCapacityError``, the drop is parked
    here and counted as delivered until a moderator claims it back into the
    player's inventory. Tenancy is enforced by composite FKs identical to
    ``InventoryItem``.
    """

    __tablename__ = "inventory_overflow_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_inventory_overflow_items_quantity_positive"),
        CheckConstraint(
            "status IN ('parked','claimed','revoked')",
            name="ck_inventory_overflow_items_status",
        ),
        CheckConstraint(
            "source_type IN ('fishing_cast','lootbox')",
            name="ck_inventory_overflow_items_source_type",
        ),
        CheckConstraint("version >= 1", name="ck_inventory_overflow_items_version_positive"),
        ForeignKeyConstraint(
            ["user_id", "channel_id"],
            ["users_progress.id", "users_progress.channel_id"],
            name="fk_inventory_overflow_items_user_channel",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["item_definition_id", "channel_id"],
            ["item_definitions.id", "item_definitions.channel_id"],
            name="fk_inventory_overflow_items_item_channel",
        ),
        Index("ix_inventory_overflow_items_user", "user_id"),
        Index("ix_inventory_overflow_items_status", "status"),
        Index(
            "ix_inventory_overflow_items_status_created_at",
            "status",
            "created_at",
        ),
    )

    id = Column(Integer, primary_key=True)
    channel_id = Column(Integer, nullable=False, index=True)
    user_id = Column(Integer, nullable=False)
    item_definition_id = Column(Integer, nullable=False, index=True)
    quantity = Column(Integer, default=1, nullable=False)
    source_type = Column(String, nullable=False, default="fishing_cast")
    source_id = Column(String, nullable=True)
    status = Column(String, nullable=False, default="parked")
    version = Column(Integer, default=1, nullable=False)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    claimed_at = Column(DateTime(timezone=True), nullable=True)

    definition = relationship(
        "ItemDefinition",
        lazy="joined",
        primaryjoin="and_(InventoryOverflowItem.item_definition_id == ItemDefinition.id, "
        "InventoryOverflowItem.channel_id == ItemDefinition.channel_id)",
        foreign_keys="[InventoryOverflowItem.item_definition_id, InventoryOverflowItem.channel_id]",
    )
    owner = relationship("UserProgress", overlaps="definition")
