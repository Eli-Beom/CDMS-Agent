from __future__ import annotations


# ── conditional 파싱 가능 여부 ────────────────────────────────────────────────

def is_null_guard(expr: dict) -> bool:
    return expr.get("right") is None and expr.get("operator") == "!="


def can_parse(cond: dict | None) -> bool:
    """Return True if a trigger conditional can produce test inputs automatically."""
    if not cond:
        return False

    def walk(node: dict) -> bool:
        if "expr" in node:
            op = node.get("operator", "AND")
            if op == "OR":
                return any(walk(c) for c in node["expr"])
            else:  # AND — 모든 branch가 파싱 가능해야 전체 조건 커버 가능
                return all(walk(c) for c in node["expr"])
        if is_null_guard(node):
            return False
        right = node.get("right")
        if isinstance(right, (int, float)):
            return True
        if isinstance(right, dict):
            if right.get("reserved") and not right.get("itemId"):
                return False
            if isinstance(right.get("visitId"), dict):
                return False
            return True
        left = node.get("left", {})
        if isinstance(left, dict) and left.get("valAs") == "DAYS":
            return True
        return False

    return walk(cond)


def classify_triggers(triggers: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split into (auto-parseable, manual-only)."""
    auto, skip = [], []
    for t in triggers:
        (auto if can_parse(t.get("conditional")) else skip).append(t)
    return auto, skip


# ── 페이지 항목 수집 ──────────────────────────────────────────────────────────

def collect_visibility_items(spec: dict) -> list[dict]:
    return [
        f for fields in spec["pages"].values()
        for f in fields
        if f.get("itemId") and f.get("visibility")
    ]


def collect_availability_items(spec: dict) -> list[dict]:
    return [
        f for fields in spec["pages"].values()
        for f in fields
        if f.get("itemId") and f.get("availability")
    ]


# ── visibility / availability 스펙 파싱 ──────────────────────────────────────

def parse_visibility(vis_spec) -> list[dict]:
    """visibility spec → [{visit_num, condition}]"""
    if not vis_spec:
        return []
    if isinstance(vis_spec, dict):
        vis_spec = [vis_spec]
    rules: list[dict] = []
    for v in vis_spec:
        if not isinstance(v, dict):
            continue
        if v.get("type") == "NORMAL_VISIT":
            rules.append({"visit_num": v["operand"], "condition": v["condition"]})
        elif "expr" in v:
            for e in v["expr"]:
                if isinstance(e, dict) and e.get("type") == "NORMAL_VISIT":
                    rules.append({"visit_num": e["operand"], "condition": e["condition"]})
    return rules


def parse_availability(avail_spec: dict | None) -> dict | None:
    """availability spec → {ctrl_item_id, enable_val, disable_val, condition}.

    Only handles ref:ITEM pattern (most common). Returns None for complex specs.
    """
    if not avail_spec or avail_spec.get("ref") != "ITEM":
        return None
    operand = avail_spec.get("operand")
    return {
        "ctrl_item_id": avail_spec.get("id", ""),
        "enable_val": operand,
        "disable_val": 0 if operand != 0 else 1,
        "condition": avail_spec.get("condition", "="),
    }
