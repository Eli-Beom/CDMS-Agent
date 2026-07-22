from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING

from .base import InputTuple, field_def, item_id, pick_existing_field, visit_seg

if TYPE_CHECKING:
    from ..models import FieldDef


BASE_VISIT_DATE = date(2024, 1, 1)


def add_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(year=value.year + years, day=28)


def sub_years(value: date, years: int) -> date:
    return add_years(value, -years)


def is_derived_age_field(fd: "FieldDef | None") -> bool:
    if fd is None:
        return False
    return fd.field_type == "AUTO_TEXT" or bool(fd.calculate) or bool(fd.disability)


def is_age_leaf(node: dict) -> bool:
    left = node.get("left", {})
    return isinstance(left, dict) and item_id(left) == "AGE" and isinstance(node.get("right"), (int, float))


def age_input(
    left: dict,
    op: str,
    threshold: float,
    trigger_page: str,
    field_map: dict[str, "FieldDef"],
    *,
    use_violation: bool,
) -> list[InputTuple]:
    """Convert an AGE rule into visit-date and birth-date inputs."""
    visit_date = BASE_VISIT_DATE
    visit_id = visit_seg(left) or "V0"
    age = int(float(threshold))
    visit_field = pick_existing_field(field_map, [("SV", "VISDAT"), ("SV", "SVDTC")]) or ("SV", "SVDTC")
    birth_field = pick_existing_field(field_map, [(trigger_page, "BRTHDAT"), (trigger_page, "BRTHDTC")]) or (
        trigger_page,
        "BRTHDTC",
    )

    if use_violation:
        if op in ("<", "<="):
            birth_date = sub_years(visit_date, age) + timedelta(days=1)
        elif op in (">", ">="):
            birth_date = sub_years(visit_date, age + 1)
        else:
            birth_date = sub_years(visit_date, age)
    else:
        if op in ("<", "<="):
            birth_date = sub_years(visit_date, age)
        elif op in (">", ">="):
            birth_date = sub_years(visit_date, age) + timedelta(days=1)
        else:
            birth_date = sub_years(visit_date, age + 10)

    return [
        ("PRECOND", visit_field[1], visit_id, visit_field[0], visit_date.isoformat()),
        ("MAIN", birth_field[1], visit_id, birth_field[0], birth_date.isoformat()),
    ]


def age_range_or_variants(
    node: dict,
    trigger_page: str,
    field_map: dict[str, "FieldDef"],
    *,
    use_violation: bool,
) -> list[list[InputTuple]] | None:
    if node.get("operator") != "OR" or not all(is_age_leaf(c) for c in node.get("expr", [])):
        return None

    leaves = node["expr"]
    lower = next((c for c in leaves if c.get("operator") in ("<", "<=")), None)
    upper = next((c for c in leaves if c.get("operator") in (">", ">=")), None)
    if lower is None or upper is None:
        return None

    if use_violation:
        return [
            age_input(lower["left"], lower["operator"], lower["right"], trigger_page, field_map, use_violation=True),
            age_input(upper["left"], upper["operator"], upper["right"], trigger_page, field_map, use_violation=True),
        ]

    return [
        age_input(lower["left"], lower["operator"], lower["right"], trigger_page, field_map, use_violation=False),
        age_input(upper["left"], upper["operator"], upper["right"], trigger_page, field_map, use_violation=False),
    ]
