from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import FieldDef


InputTuple = tuple[str, str, str, str, str]  # (role, itemId, visitId, pageId, value)


def visit_seg(ref: dict) -> str:
    if isinstance(ref.get("id"), list) and len(ref["id"]) > 1:
        return str(ref["id"][1])
    v = ref.get("visitId", "")
    return "" if isinstance(v, dict) else str(v)


def item_id(ref: dict) -> str:
    if isinstance(ref.get("id"), list) and len(ref["id"]) > 5:
        return str(ref["id"][5])
    return str(ref.get("itemId", ""))


def page_id(ref: dict, fallback: str = "") -> str:
    if isinstance(ref.get("id"), list) and len(ref["id"]) > 3:
        return str(ref["id"][3])
    return str(ref.get("crfPageId", fallback))


def field_def(field_map: dict[str, "FieldDef"], page: str, item: str) -> "FieldDef | None":
    return field_map.get(f"{page}.{item}") or field_map.get(item)


def pick_existing_field(
    field_map: dict[str, "FieldDef"],
    candidates: list[tuple[str, str]],
) -> tuple[str, str] | None:
    for page, item in candidates:
        if field_def(field_map, page, item):
            return page, item
    return None
