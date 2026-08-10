"""Validation for item-to-item and item-to-loot-table dependencies."""

from collections.abc import Iterable
from typing import Any

from infrastructure.models import ItemDefinition, LootTable, LootTableEntry
from sqlalchemy.orm import Session


def _effect_dict(effect: Any) -> dict[str, Any]:
    if isinstance(effect, dict):
        return effect
    model_dump = getattr(effect, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    return {}


def _dependencies(
    db: Session,
    channel_id: int,
    effects: Iterable[Any],
) -> set[str]:
    dependencies: set[str] = set()
    for raw_effect in effects or []:
        effect = _effect_dict(raw_effect)
        effect_type = effect.get("type")
        if effect_type == "grant_item":
            target = str(effect.get("item_id") or "").strip()
            if target:
                dependencies.add(target)
        elif effect_type == "loot_table_roll":
            table_id = str(effect.get("loot_table_id") or "").strip()
            if not table_id:
                continue
            table = (
                db.query(LootTable)
                .filter(
                    LootTable.channel_id == channel_id,
                    LootTable.table_id == table_id,
                    LootTable.is_active.is_(True),
                )
                .first()
            )
            if not table:
                # Missing table is reported by the normal runtime path. It is
                # not a graph edge and must not make item creation impossible.
                continue
            rows = (
                db.query(LootTableEntry)
                .filter(LootTableEntry.loot_table_id == table.id)
                .all()
            )
            definitions = {row.definition for row in rows if row.definition is not None}
            dependencies.update(str(definition.item_id) for definition in definitions)
    return dependencies


def validate_item_dependency_graph(
    db: Session,
    channel_id: int,
    item_id: str,
    effects: Iterable[Any],
) -> None:
    """Reject any positive item/lootbox dependency cycle in one channel.

    The validator is intentionally conservative: even a cycle whose current
    quantities would eventually terminate is rejected because its behavior is
    configuration-dependent and can become an unbounded reproduction loop
    after a later table edit.
    """
    rows = (
        db.query(ItemDefinition)
        .filter(ItemDefinition.channel_id == channel_id)
        .all()
    )
    graph: dict[str, set[str]] = {
        str(row.item_id): _dependencies(db, channel_id, row.effects or []) for row in rows
    }
    graph[str(item_id)] = _dependencies(db, channel_id, effects)

    visiting: set[str] = set()
    visited: set[str] = set()
    path: list[str] = []

    def visit(node: str) -> None:
        if node in visiting:
            start = path.index(node) if node in path else 0
            cycle = path[start:] + [node]
            raise ValueError(f"Item dependency cycle detected: {' -> '.join(cycle)}")
        if node in visited:
            return
        visiting.add(node)
        path.append(node)
        for dependency in graph.get(node, set()):
            if dependency in graph:
                visit(dependency)
        path.pop()
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        visit(node)
