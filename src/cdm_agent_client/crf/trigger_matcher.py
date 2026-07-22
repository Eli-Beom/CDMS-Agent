from __future__ import annotations

from typing import Any
from collections import Counter


def trigger_references_page(trigger: dict[str, Any], page_id: str) -> bool:
    if not page_id:
        return False
    if str(trigger.get("pageId") or trigger.get("crfPageId") or "") == page_id:
        return True
    trigger_id = str(trigger.get("id") or "")
    if trigger_id.startswith(f"D_{page_id}_"):
        return True
    return any(
        _ref_tree_has_page(trigger.get(key), page_id)
        for key in ("issue", "conditional", "bindTo", "value", "target", "disable", "enable")
    )


def classify_dvs_type(trigger: dict[str, Any]) -> str:
    trigger_type = str(trigger.get("type") or "").upper()
    note = str(trigger.get("note") or "").lower()
    if trigger_type == "QUERY":
        return "QUERY"
    if trigger_type == "ASSIGN":
        return "ASSIGN"
    if trigger_type in {"VISIBILITY", "VISIBLE", "SHOW", "HIDE"} or "visibility" in note:
        return "VISIBILITY"
    if trigger_type in {"AVAILABILITY", "AVAILABLE"} or "availability" in note:
        return "AVAILABILITY"
    if trigger_type in {"DISABILITY", "DISABLE", "READONLY", "LOCK"}:
        return "DISABILITY"
    if "disabled" in note or "readonly" in note or "lock" in note:
        return "DISABILITY"
    if trigger_type in {"STATUS", "PAGE_STATUS"}:
        return "STATUS"
    if "deactivate page" in note or "status" in note:
        return "STATUS"
    return "UNKNOWN"


def summarize_triggers(triggers: list[dict[str, Any]], current_page_id: str | None) -> list[dict[str, Any]]:
    current_page_id = current_page_id or ""
    current_page_triggers = [trigger for trigger in triggers if trigger_references_page(trigger, current_page_id)]
    records: list[dict[str, Any]] = []
    for scope, scoped_triggers in (
        ("all_crf", triggers),
        ("current_page", current_page_triggers),
    ):
        counts = Counter(classify_dvs_type(trigger) for trigger in scoped_triggers)
        for dvs_type in ("QUERY", "ASSIGN", "VISIBILITY", "AVAILABILITY", "DISABILITY", "STATUS", "UNKNOWN"):
            records.append({"scope": scope, "dvs_type": dvs_type, "count": counts.get(dvs_type, 0)})
    return records


def condition_comparisons(trigger: dict[str, Any]) -> list[dict[str, Any]]:
    """Return simple item/operator/value comparisons from a trigger conditional.

    This intentionally keeps only directly executable comparison leaves. Compound
    AND/OR shape is still represented on the source trigger; candidate builders
    can use these leaves as condition metadata and query-label hints without
    adding page-specific overrides.
    """

    comparisons: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for child in node:
                walk(child)
            return
        if not isinstance(node, dict):
            return
        if "expr" in node:
            for child in node.get("expr") or []:
                walk(child)
            return
        left = node.get("left")
        if not isinstance(left, dict):
            return
        item_id = str(left.get("itemId") or "").strip()
        if not item_id:
            return
        right = node.get("right")
        if isinstance(right, dict):
            return
        comparisons.append(
            {
                "item_id": item_id,
                "operator": node.get("operator") or "",
                "value": right,
                "page_id": left.get("crfPageId") or left.get("pageId") or "",
                "visit_id": left.get("visitId") or "",
                "section_id": left.get("sectionId") or "",
            }
        )

    walk(trigger.get("conditional"))
    return comparisons


def condition_branches(trigger: dict[str, Any]) -> list[list[dict[str, Any]]]:
    """Return executable comparison branches from a trigger conditional.

    The output is a small DNF expansion for simple AND/OR comparison trees:
    ``(A OR B) AND C`` becomes ``[[A, C], [B, C]]``. Unsupported leaves are
    ignored by returning no branches rather than guessing.
    """

    def leaf(node: dict[str, Any]) -> dict[str, Any] | None:
        left = node.get("left")
        if not isinstance(left, dict):
            return None
        item_id = str(left.get("itemId") or "").strip()
        if not item_id:
            return None
        right = node.get("right")
        if isinstance(right, dict):
            return None
        return {
            "item_id": item_id,
            "operator": node.get("operator") or "",
            "value": right,
            "page_id": left.get("crfPageId") or left.get("pageId") or "",
            "visit_id": left.get("visitId") or "",
            "section_id": left.get("sectionId") or "",
        }

    def expand(node: Any) -> list[list[dict[str, Any]]]:
        if not isinstance(node, dict):
            return []
        if "expr" not in node:
            item = leaf(node)
            return [[item]] if item else []
        operator = str(node.get("operator") or "").upper()
        children = [expand(child) for child in (node.get("expr") or [])]
        if not children or any(not child for child in children):
            return []
        if operator == "OR":
            return [branch for child in children for branch in child]
        if operator == "AND":
            branches: list[list[dict[str, Any]]] = [[]]
            for child in children:
                branches = [left + right for left in branches for right in child]
            return branches
        return []

    branches = expand(trigger.get("conditional"))
    unique: list[list[dict[str, Any]]] = []
    seen: set[tuple[tuple[str, str, str, str], ...]] = set()
    for branch in branches:
        key = tuple(
            sorted(
                (
                    str(item.get("page_id") or ""),
                    str(item.get("item_id") or ""),
                    str(item.get("operator") or ""),
                    str(item.get("value") or ""),
                )
                for item in branch
            )
        )
        if key not in seen:
            seen.add(key)
            unique.append(branch)
    return unique


def _ref_tree_has_page(value: Any, page_id: str) -> bool:
    if isinstance(value, dict):
        ref_page = value.get("crfPageId") or value.get("pageId")
        if str(ref_page or "") == page_id:
            return True
        return any(_ref_tree_has_page(child, page_id) for child in value.values())
    if isinstance(value, list):
        return any(_ref_tree_has_page(child, page_id) for child in value)
    return False
