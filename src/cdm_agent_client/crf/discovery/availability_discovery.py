from __future__ import annotations

from typing import Any

from ..models import Step
from ..extraction.parser import collect_availability_items
from .row_matcher import current_input_row_labels, resolve_field_for_label


def build_browser_availability_discovery_candidates(runner: Any, context: dict[str, Any]) -> list[dict[str, Any]]:
    page_id = str(context.get("page_id") or "")
    visit_id = _visit_id_from_path(context.get("pathname"))
    visible_labels = current_input_row_labels(context)
    spec = getattr(runner, "_spec", None) or {}
    field_map = getattr(runner, "_field_map", {})

    candidates: list[dict[str, Any]] = []
    for field in collect_availability_items(spec):
        if str(field.get("pageId") or "") != page_id:
            continue
        target_label = str(field.get("label") or "").strip() or str(field.get("itemId") or "")
        if visible_labels and target_label not in visible_labels:
            matched = resolve_field_for_label(field_map, page_id, target_label)
            if not matched and target_label not in visible_labels:
                continue

        rules = _parse_simple_availability_rules(field.get("availability"))
        if not rules:
            candidates.append(_manual_candidate(field, page_id=page_id, visit_id=visit_id, target_label=target_label))
            continue

        available_steps: list[Step] = []
        unavailable_steps: list[Step] = []
        control_labels: list[str] = []
        control_ids: list[str] = []
        for index, rule in enumerate(rules):
            ctrl_id = rule["control_item_id"]
            ctrl_field = _resolve_field(field_map, page_id, ctrl_id)
            if ctrl_field is None:
                continue
            control_ids.append(ctrl_id)
            control_labels.append(ctrl_field.label or ctrl_id)
            available_value = _value_for_rule(rule, make_available=True)
            unavailable_value = _value_for_rule(rule, make_available=False)
            available_step = _step_for_field(ctrl_field, available_value, visit_id=visit_id, note="make_available")
            unavailable_step = _step_for_field(
                ctrl_field,
                unavailable_value,
                visit_id=visit_id,
                note="make_unavailable" if index == 0 else "keep_condition",
            )
            if available_step:
                available_steps.append(available_step)
            if index == 0 and unavailable_step:
                unavailable_steps.append(unavailable_step)
            elif index > 0 and available_step:
                unavailable_steps.append(available_step)

        if not available_steps or not unavailable_steps:
            candidates.append(_manual_candidate(field, page_id=page_id, visit_id=visit_id, target_label=target_label))
            continue

        candidates.append(
            {
                "name": f"AVAIL_{page_id}_{field.get('itemId')}",
                "availability_id": f"AVAIL_{page_id}_{field.get('itemId')}",
                "page_id": page_id,
                "visit_id": visit_id,
                "target_item_id": field.get("itemId") or "",
                "target_label": target_label,
                "control_item_id": ",".join(control_ids),
                "control_label": ",".join(control_labels),
                "Specification": _specification_text(rules),
                "expected_before": "observe_current_state",
                "expected_after": "unavailable_then_available",
                "steps_to_make_available": _steps_to_dicts(available_steps),
                "steps_to_make_unavailable": _steps_to_dicts(unavailable_steps),
            }
        )
    return candidates


def _manual_candidate(field: dict[str, Any], *, page_id: str, visit_id: str | None, target_label: str) -> dict[str, Any]:
    return {
        "name": f"AVAIL_{page_id}_{field.get('itemId')}",
        "availability_id": f"AVAIL_{page_id}_{field.get('itemId')}",
        "page_id": page_id,
        "visit_id": visit_id,
        "target_item_id": field.get("itemId") or "",
        "target_label": target_label,
        "control_item_id": "",
        "control_label": "",
        "Specification": "manual_review: unsupported availability spec",
        "expected_before": "observe_current_state",
        "expected_after": "manual_review",
        "steps_to_make_available": [],
        "steps_to_make_unavailable": [],
    }


def _parse_simple_availability_rules(spec: Any) -> list[dict[str, Any]]:
    if isinstance(spec, dict):
        specs = [spec]
    elif isinstance(spec, list):
        specs = spec
    else:
        return []
    rules: list[dict[str, Any]] = []
    for rule in specs:
        if not isinstance(rule, dict):
            return []
        parsed = _parse_ref_rule(rule) or _parse_operand_rule(rule)
        if parsed is None:
            return []
        rules.append(parsed)
    return [rule for rule in rules if rule["control_item_id"]]


def _parse_ref_rule(rule: dict[str, Any]) -> dict[str, Any] | None:
    if rule.get("ref") != "ITEM":
        return None
    if rule.get("condition") not in {"=", "!="}:
        return None
    return {
        "control_item_id": str(rule.get("id") or ""),
        "condition": rule.get("condition"),
        "operand": rule.get("operand"),
    }


def _parse_operand_rule(rule: dict[str, Any]) -> dict[str, Any] | None:
    left = rule.get("left")
    if not isinstance(left, dict):
        return None
    operator = rule.get("operator")
    if operator not in {"=", "!="}:
        return None
    right = rule.get("right")
    if isinstance(right, list):
        operand = right[0] if right else None
    else:
        operand = right
    return {
        "control_item_id": str(left.get("itemId") or ""),
        "condition": operator,
        "operand": operand,
    }


def _value_for_rule(rule: dict[str, Any], *, make_available: bool) -> Any:
    operand = rule["operand"]
    condition = rule["condition"]
    if condition == "=":
        return operand if make_available else _alternate_value(operand)
    return _alternate_value(operand) if make_available else operand


def _alternate_value(value: Any) -> Any:
    if value is None:
        return 1
    if value == 1:
        return 2
    if value == 2:
        return 1
    if value == 0:
        return 1
    return None


def _resolve_field(field_map: dict[str, Any], page_id: str, item_id: str) -> Any | None:
    return field_map.get(f"{page_id}.{item_id}") or field_map.get(item_id)


def _step_for_field(field: Any, value: Any, *, visit_id: str | None, note: str) -> Step | None:
    method = getattr(field, "agent_action", "set_text")
    if method == "SKIP":
        return None
    label = getattr(field, "label", "") or getattr(field, "item_id", "")
    page_id = getattr(field, "page_id", None)
    kwargs = {"page_id": page_id, "visit_id": visit_id}
    if method in {"select_radio", "select_option"}:
        option = _option_for_value(getattr(field, "options", []) or [], value)
        if option is None:
            return None
        return Step(method, [label, option], kwargs, note=note)
    return Step(method, [label, str(value)], kwargs, note=note)


def _option_for_value(options: list[dict[str, Any]], value: Any) -> str | None:
    for option in options:
        if str(option.get("dbVal")) == str(value) or str(option.get("calcVal")) == str(value):
            return str(option.get("uiVal"))
    return None


def _steps_to_dicts(steps: list[Step]) -> list[dict[str, Any]]:
    return [
        {
            "method": step.method,
            "args": list(step.args),
            "kwargs": dict(step.kwargs),
            "note": step.note,
        }
        for step in steps
    ]


def _specification_text(rules: list[dict[str, Any]]) -> str:
    return " AND ".join(
        f"{rule['control_item_id']} {rule['condition']} {rule['operand']!r}"
        for rule in rules
    )


def _visit_id_from_path(pathname: str | None) -> str | None:
    if not pathname:
        return None
    parts = [part for part in str(pathname).split("/") if part]
    if len(parts) >= 4:
        return parts[-4]
    return None
