from __future__ import annotations

from typing import Any

from .availability_discovery import (
    _parse_simple_availability_rules,
    _resolve_field,
    _step_for_field,
    _steps_to_dicts,
    _value_for_rule,
)


def enrich_same_page_prerequisites(
    candidate: dict[str, Any],
    runner: Any,
    *,
    current_page_id: str,
    visit_id: str | None = None,
) -> dict[str, Any]:
    """Add prerequisite steps for target/input rows gated by same-page availability.

    This is candidate-generation metadata, not a DM-specific override. It reads
    page field availability specs and records control-row prerequisite steps so the
    target row can be edited before the main query steps run.
    """

    out = dict(candidate)
    out.setdefault("requires_prerequisite", False)
    if str(out.get("rule_type") or "") == "availability":
        return out

    page_id = str(current_page_id or "")
    if not page_id:
        return out

    spec = getattr(runner, "_spec", {}) or {}
    page_fields = (spec.get("pages") or {}).get(page_id, []) or []
    availability_by_item = {
        str(field.get("itemId") or ""): field.get("availability")
        for field in page_fields
        if field.get("availability")
    }
    if not availability_by_item:
        return out

    referenced_ids = _candidate_referenced_item_ids(out)
    prerequisite_steps = list(out.get("prerequisite_steps") or out.get("setup_steps") or [])
    prerequisite_ids = list(out.get("prerequisite_item_ids") or [])
    prerequisite_reasons = list(out.get("prerequisite_reasons") or [])

    existing_keys = {_step_key(step) for step in prerequisite_steps}
    for item_id in referenced_ids:
        rules = _parse_simple_availability_rules(availability_by_item.get(item_id))
        for rule in rules:
            control_id = str(rule.get("control_item_id") or "")
            if not control_id or control_id in referenced_ids:
                continue
            control_field = _resolve_field(getattr(runner, "_field_map", {}) or {}, page_id, control_id)
            if control_field is None:
                continue
            value = _value_for_rule(rule, make_available=True)
            step = _step_for_field(
                control_field,
                value,
                visit_id=visit_id or _visit_id_from_candidate(out),
                note=f"same-page prerequisite for {item_id}",
            )
            if step is None:
                continue
            for step_dict in _steps_to_dicts([step]):
                key = _step_key(step_dict)
                if key in existing_keys:
                    continue
                existing_keys.add(key)
                prerequisite_steps.append(step_dict)
            if control_id not in prerequisite_ids:
                prerequisite_ids.append(control_id)
            reason = f"{item_id} availability depends on {control_id}"
            if reason not in prerequisite_reasons:
                prerequisite_reasons.append(reason)

    if prerequisite_steps:
        out["requires_prerequisite"] = True
        out["prerequisite_steps"] = prerequisite_steps
        out["prerequisite_steps_count"] = len(prerequisite_steps)
        out["prerequisite_item_ids"] = prerequisite_ids
        out["prerequisite_reasons"] = prerequisite_reasons
        out["prerequisite_reason"] = "same_page_availability"
    return out


def _candidate_referenced_item_ids(candidate: dict[str, Any]) -> list[str]:
    out: list[str] = []
    values = [candidate.get("item_id"), *(candidate.get("input_item_ids") or [])]
    for value in values:
        text = str(value or "").strip()
        if text and text != "unknown" and text not in out:
            out.append(text)
    return out


def _visit_id_from_candidate(candidate: dict[str, Any]) -> str | None:
    for key in ("setup_steps", "steps", "steps_to_make_available", "steps_to_make_unavailable"):
        for step in candidate.get(key) or []:
            visit_id = (step.get("kwargs") or {}).get("visit_id")
            if visit_id:
                return str(visit_id)
    return None


def _step_key(step: dict[str, Any]) -> tuple[Any, ...]:
    return (
        step.get("method"),
        tuple(step.get("args") or []),
        tuple(sorted((step.get("kwargs") or {}).items())),
    )
