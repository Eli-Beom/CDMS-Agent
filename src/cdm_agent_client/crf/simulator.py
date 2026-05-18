from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING

from .parser import is_null_guard

if TYPE_CHECKING:
    from .models import FieldDef


# ── 값 생성 헬퍼 ──────────────────────────────────────────────────────────────

def _today(delta: int = 0) -> str:
    return (date.today() + timedelta(days=delta)).isoformat()


def _violation_value(op: str, threshold: float) -> float:
    """조건을 위반(쿼리 발생)하는 경계값"""
    t = float(threshold)
    if op == "<":  return t - 1
    if op == ">":  return t + 1
    if op == "<=": return t - 1
    if op == ">=": return t + 1
    if op == "!=": return t
    return t


def _valid_value(op: str, threshold: float) -> float:
    """조건을 만족(쿼리 미발생)하는 값"""
    t = float(threshold)
    if op in ("<", "<="): return t + 10
    if op in (">", ">="): return t - 10
    return t


def _visit_seg(ref: dict) -> str:
    v = ref.get("visitId", "")
    return "" if isinstance(v, dict) else str(v)


# ── conditional → 입력 목록 추출 ─────────────────────────────────────────────

_InputTuple = tuple[str, str, str, str, str]   # (role, itemId, visitId, pageId, value)


def extract_inputs(
    cond: dict | None,
    trigger_page: str,
    field_map: dict[str, "FieldDef"],
    *,
    use_violation: bool = True,
) -> list[_InputTuple]:
    """Parse a trigger conditional and produce a list of field input tuples.

    Each tuple: (role, item_id, visit_id, page_id, value)
      role = "PRECOND" | "MAIN"
    use_violation=True  → values that trigger the query (발생)
    use_violation=False → values that satisfy the condition (미발생)
    """
    if not cond:
        return []

    def walk(node: dict) -> list[_InputTuple]:
        # ── compound node ──────────────────────────────────────────────────────
        if "expr" in node:
            compound_op = node.get("operator", "AND")
            if compound_op == "OR":
                # OR: 첫 번째 파싱 가능한 branch 하나만 사용
                for c in node["expr"]:
                    branch = walk(c)
                    if branch:
                        return branch
                return []
            else:  # AND: 모든 branch 조건을 병합
                result: list[_InputTuple] = []
                for c in node["expr"]:
                    result.extend(walk(c))
                return result

        # ── leaf node ──────────────────────────────────────────────────────────
        left = node.get("left", {})
        op = node.get("operator", "")
        right = node.get("right")

        if is_null_guard(node):
            return []

        if isinstance(right, dict) and right.get("reserved") and not right.get("itemId"):
            return []

        if isinstance(left, dict) and isinstance(left.get("visitId"), dict):
            return []
        if isinstance(right, dict) and isinstance(right.get("visitId"), dict):
            return []

        # date arithmetic: (A - B).DAYS op N
        if (isinstance(left, dict) and left.get("valAs") == "DAYS"
                and isinstance(right, (int, float))):
            a_ref = left.get("left", {})
            b_ref = left.get("right", {})
            if use_violation:
                offset = int(float(right)) - 1 if op == "<" else int(float(right)) + 1
            else:
                offset = int(float(right))
            return [
                ("PRECOND", b_ref.get("itemId", ""), _visit_seg(b_ref),
                 b_ref.get("crfPageId", trigger_page), _today(0)),
                ("MAIN", a_ref.get("itemId", ""), _visit_seg(a_ref),
                 a_ref.get("crfPageId", trigger_page), _today(offset)),
            ]

        # numeric threshold: field op N
        if isinstance(right, (int, float)):
            fn = _violation_value if use_violation else _valid_value
            return [("MAIN", left.get("itemId", ""), _visit_seg(left),
                     left.get("crfPageId", trigger_page), str(fn(op, right)))]

        # cross-field comparison: field op field
        if isinstance(right, dict) and right.get("itemId"):
            l_item = left.get("itemId", "")
            r_item = right.get("itemId", "")
            fd = field_map.get(l_item)
            if fd and fd.field_type == "DATE":
                ref_date = _today(0)
                test_date = _today(-10 if op in ("<", "<=") else 10) if use_violation else ref_date
                return [
                    ("PRECOND", r_item, _visit_seg(right), right.get("crfPageId", ""), ref_date),
                    ("MAIN", l_item, _visit_seg(left), left.get("crfPageId", trigger_page), test_date),
                ]
            else:
                base = 100
                l_val = (base - 1 if op in ("<", "<=") else base + 1) if use_violation else base
                return [
                    ("PRECOND", r_item, _visit_seg(right), right.get("crfPageId", ""), str(base)),
                    ("MAIN", l_item, _visit_seg(left), left.get("crfPageId", trigger_page), str(l_val)),
                ]

        return []

    inputs = walk(cond)

    # deduplicate by (itemId, visitId)
    seen: set[tuple[str, str]] = set()
    deduped: list[_InputTuple] = []
    for inp in inputs:
        key = (inp[1], inp[2])
        if key not in seen:
            seen.add(key)
            deduped.append(inp)
    return deduped
