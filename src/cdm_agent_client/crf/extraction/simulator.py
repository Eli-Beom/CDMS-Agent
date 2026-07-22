from __future__ import annotations

from datetime import date, timedelta
from itertools import product
from typing import TYPE_CHECKING

from .parser import is_null_guard
from ..value_generators import (
    InputTuple,
    age_input,
    age_range_or_variants,
    field_def,
    format_numeric_value,
    is_derived_age_field,
    item_id,
    page_id,
    valid_value,
    violation_value,
    visit_seg,
)

if TYPE_CHECKING:
    from ..models import FieldDef


_BASE_DATE = date(2024, 1, 1)


def _today(delta: int = 0) -> str:
    return (_BASE_DATE + timedelta(days=delta)).isoformat()


def extract_inputs(
    cond: dict | None,
    trigger_page: str,
    field_map: dict[str, "FieldDef"],
    *,
    use_violation: bool = True,
) -> list[InputTuple]:
    """Return the first generated input variant for backward compatibility."""
    variants = extract_input_variants(cond, trigger_page, field_map, use_violation=use_violation)
    return variants[0] if variants else []


def extract_input_variants(
    cond: dict | None,
    trigger_page: str,
    field_map: dict[str, "FieldDef"],
    *,
    use_violation: bool = True,
) -> list[list[InputTuple]]:
    """Parse a trigger conditional and return executable input variants."""
    if not cond:
        return []

    def walk(node: dict) -> list[list[InputTuple]]:
        if "expr" in node:
            compound_op = node.get("operator", "AND")
            if compound_op == "OR":
                age_variants = age_range_or_variants(
                    node,
                    trigger_page,
                    field_map,
                    use_violation=use_violation,
                )
                if age_variants is not None:
                    return age_variants

                for child in node["expr"]:
                    branch_variants = walk(child)
                    if branch_variants:
                        return [branch_variants[0]]
                return []

            parts: list[list[list[InputTuple]]] = []
            for child in node["expr"]:
                variants = walk(child)
                if variants:
                    parts.append(variants)
            if not parts:
                return [[]]
            return [[inp for group in combo for inp in group] for combo in product(*parts)]

        left = node.get("left", {})
        op = node.get("operator", "")
        right = node.get("right")

        if is_null_guard(node):
            return [[]]

        if isinstance(right, dict) and right.get("reserved") and not right.get("itemId"):
            return [[]]

        if isinstance(left, dict) and isinstance(left.get("visitId"), dict):
            return [[]]
        if isinstance(right, dict) and isinstance(right.get("visitId"), dict):
            return [[]]

        if isinstance(left, dict) and left.get("valAs") == "DAYS" and isinstance(right, (int, float)):
            a_ref = left.get("left", {})
            b_ref = left.get("right", {})
            if use_violation:
                offset = int(float(right)) - 1 if op == "<" else int(float(right)) + 1
            else:
                offset = int(float(right))
            return [[
                ("PRECOND", item_id(b_ref), visit_seg(b_ref), page_id(b_ref, trigger_page), _today(0)),
                ("MAIN", item_id(a_ref), visit_seg(a_ref), page_id(a_ref, trigger_page), _today(offset)),
            ]]

        if isinstance(right, (int, float)):
            left_item = item_id(left)
            fd = field_def(field_map, page_id(left, trigger_page), left_item)
            if left_item == "AGE" and is_derived_age_field(fd):
                return [age_input(left, op, right, trigger_page, field_map, use_violation=use_violation)]
            value_fn = violation_value if use_violation else valid_value
            value = value_fn(op, right, fd)
            return [[
                (
                    "MAIN",
                    left_item,
                    visit_seg(left),
                    page_id(left, trigger_page),
                    format_numeric_value(value, fd),
                ),
            ]]

        if isinstance(right, dict) and item_id(right):
            l_item = item_id(left)
            r_item = item_id(right)
            fd = field_map.get(l_item)
            if fd and fd.field_type == "DATE":
                ref_date = _today(0)
                test_date = _today(-10 if op in ("<", "<=") else 10) if use_violation else ref_date
                return [[
                    ("PRECOND", r_item, visit_seg(right), page_id(right), ref_date),
                    ("MAIN", l_item, visit_seg(left), page_id(left, trigger_page), test_date),
                ]]

            base = 100
            l_val = (base - 1 if op in ("<", "<=") else base + 1) if use_violation else base
            return [[
                ("PRECOND", r_item, visit_seg(right), page_id(right), str(base)),
                ("MAIN", l_item, visit_seg(left), page_id(left, trigger_page), str(l_val)),
            ]]

        return []

    deduped_variants: list[list[InputTuple]] = []
    for inputs in walk(cond):
        seen: set[tuple[str, str, str]] = set()
        deduped: list[InputTuple] = []
        for inp in inputs:
            key = (inp[1], inp[2], inp[3])
            if key not in seen:
                seen.add(key)
                deduped.append(inp)
        if deduped:
            deduped_variants.append(deduped)
    return deduped_variants
