from __future__ import annotations

import re
from typing import Any


VALIDATION_CATEGORIES = {
    "query",
    "availability",
    "calculation",
    "auto_link",
    "auto_generation",
    "save_block",
    "manual_review",
}

QUERY_SUBTYPES = {
    "range_numeric",
    "range_age",
    "date_window",
    "date_order",
    "option_consistency",
    "cross_page_consistency",
    "missing_or_required",
    "derived_query",
    "unknown",
}

AUTOMATION_SCOPES = {
    "current_page_only",
    "browser_assisted_cross_page",
    "static_only",
    "manual_review",
}

LIMITATION_REASONS = {
    "cross_page_reference",
    "cross_visit_reference",
    "calculation_prerequisite",
    "auto_link_prerequisite",
    "availability_prerequisite",
    "appendable_table_required",
    "target_row_not_found",
    "source_row_not_found",
    "option_not_found",
    "unsupported_expression",
    "browser_navigation_required",
    "manual_review_required",
}


def enrich_candidate_taxonomy(
    candidate: dict[str, Any],
    *,
    current_page_id: str | None = None,
    trigger: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a candidate copy with Phase 1 taxonomy metadata added."""

    out = dict(candidate)
    category = validation_category(out)
    out.setdefault("validation_category", category)
    out.setdefault("query_subtype", query_subtype(out, trigger=trigger) if category == "query" else "")
    if category == "query":
        out.setdefault("query_category", query_category(out, trigger=trigger, current_page_id=current_page_id))
        out.setdefault("condition_type", condition_type(out, trigger=trigger, current_page_id=current_page_id))
        out.setdefault("prerequisite_shape", out["condition_type"])
        if "condition_steps" not in out and out.get("condition_items"):
            out["condition_steps"] = list(out.get("steps") or [])
    else:
        out.setdefault("query_category", "")
        out.setdefault("condition_type", "none")
        out.setdefault("prerequisite_shape", "none")
    out.setdefault("calculation_subtype", calculation_subtype(out))
    out.setdefault("automation_scope", automation_scope(out, current_page_id=current_page_id, trigger=trigger))
    out.setdefault("expected_query_message_label", expected_query_message_label(out))
    out.setdefault("depends_on_item_id", ",".join(depends_on_item_ids(out, trigger=trigger)))
    out.setdefault("limitation_reason", "")
    return out


def enrich_limitation_taxonomy(
    limitation: dict[str, Any],
    *,
    current_page_id: str | None = None,
) -> dict[str, Any]:
    out = dict(limitation)
    rule_type = str(out.get("rule_type") or "").lower()
    reason = str(out.get("reason") or out.get("limitation_reason") or "")
    out.setdefault("validation_category", "availability" if "availability" in rule_type else "manual_review")
    out.setdefault("query_subtype", "")
    out.setdefault("calculation_subtype", "")
    out.setdefault("automation_scope", "manual_review")
    out.setdefault("expected_query_message_label", "")
    out["limitation_reason"] = limitation_reason_code(reason)
    if current_page_id:
        out.setdefault("page_id", current_page_id)
    return out


def validation_category(candidate: dict[str, Any]) -> str:
    rule_type = str(candidate.get("rule_type") or candidate.get("discovery_kind") or "").lower()
    if "availability" in rule_type:
        return "availability"
    if "calculation" in rule_type:
        return "calculation"
    if "auto_link" in rule_type:
        return "auto_link"
    if "save" in rule_type and "block" in rule_type:
        return "save_block"
    if "query" in rule_type or str(candidate.get("Expected Result") or "").endswith("query_expected"):
        return "query"
    return "manual_review"


def query_subtype(candidate: dict[str, Any], *, trigger: dict[str, Any] | None = None) -> str:
    text = _combined_text(candidate, trigger)
    item_id = str(candidate.get("item_id") or "").upper()
    if item_id == "AGE" or "AGE<" in text or "AGE >" in text or "AGE =" in text:
        return "range_age"
    if _has_date_window(candidate, trigger, text):
        return "date_window"
    if any(token in text for token in ("OPTION", "RADIO", "SELECT")):
        return "option_consistency"
    if any(token in text for token in ("MISSING", "REQUIRED", "NULL", "NOT FOUND")):
        return "missing_or_required"
    if _has_numeric_range(text):
        return "range_numeric"
    if _references_other_page(candidate, current_page_id=str(candidate.get("page_id") or "")):
        return "cross_page_consistency"
    return "unknown"


def query_category(
    candidate: dict[str, Any],
    *,
    trigger: dict[str, Any] | None = None,
    current_page_id: str | None = None,
) -> str:
    explicit = str(candidate.get("query_category") or "").strip()
    if explicit:
        return explicit
    rule_type = str(candidate.get("rule_type") or "").lower()
    text = _combined_text(candidate, trigger)
    if "unsupported" in text or str(candidate.get("limitation_reason") or ""):
        return "unsupported_query"
    if "range" in rule_type:
        return "range_query"
    if candidate.get("calculation_rule_id") or candidate.get("calculation_target_item_id"):
        return "calculation_query"
    if condition_items(candidate, trigger=trigger):
        return "condition_query"
    if query_subtype(candidate, trigger=trigger) in {"range_age", "range_numeric", "date_window"}:
        return "range_query"
    if any(token in text for token in ("MISSING", "REQUIRED", "INPUT MISSING", "INPUT REQUIRED", "NULL")):
        return "missing_query"
    if "GENERATE A QUERY WHEN THE CONDITION IS MET" in text and not condition_items(candidate, trigger=trigger):
        return "missing_query"
    return "consistency_query"


def condition_type(
    candidate: dict[str, Any],
    *,
    trigger: dict[str, Any] | None = None,
    current_page_id: str | None = None,
) -> str:
    explicit = str(candidate.get("condition_type") or candidate.get("prerequisite_shape") or "").strip()
    if explicit:
        return explicit
    items = condition_items(candidate, trigger=trigger)
    if not items:
        if candidate.get("calculation_target_item_id") or candidate.get("calculation_rule_id"):
            return "derived"
        return "none"
    current = str(current_page_id or candidate.get("page_id") or "").strip()
    pages = {str(item.get("page_id") or current or "").strip() for item in items if str(item.get("page_id") or current or "").strip()}
    if current and any(page != current for page in pages):
        return "cross"
    unique_ids = {str(item.get("item_id") or "").strip() for item in items if str(item.get("item_id") or "").strip()}
    if len(unique_ids) <= 1:
        return "single"
    return "multi"


def prerequisite_shape(
    candidate: dict[str, Any],
    *,
    trigger: dict[str, Any] | None = None,
    current_page_id: str | None = None,
) -> str:
    return condition_type(candidate, trigger=trigger, current_page_id=current_page_id)


def condition_items(candidate: dict[str, Any], *, trigger: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    items = candidate.get("condition_items") or []
    if isinstance(items, list) and items:
        return [item for item in items if isinstance(item, dict)]
    if trigger:
        # Keep this as metadata-only fallback. Candidate builders should populate
        # resolved labels/ui values before runtime execution.
        from .trigger_matcher import condition_comparisons

        return condition_comparisons(trigger)
    return []


def calculation_subtype(candidate: dict[str, Any]) -> str:
    explicit = str(candidate.get("calculation_subtype") or "")
    if explicit:
        return explicit
    item_id = str(candidate.get("calculation_target_item_id") or candidate.get("item_id") or "").upper()
    text = _combined_text(candidate, None)
    if item_id == "AGE" or "AGE" in text:
        return "age"
    if "RASCH" in text or "CHOICE" in text:
        return "rasch_score"
    if "SUM" in text or "TOTAL" in text:
        return "sum_score"
    return ""


def automation_scope(
    candidate: dict[str, Any],
    *,
    current_page_id: str | None,
    trigger: dict[str, Any] | None = None,
) -> str:
    if validation_category(candidate) not in {"query", "availability"}:
        return "static_only"
    pages = step_page_ids(candidate)
    if trigger:
        pages.update(trigger_page_ids(trigger))
    current = str(current_page_id or candidate.get("page_id") or "")
    if current and pages and not pages <= {current}:
        return "browser_assisted_cross_page"
    if not pages and current:
        return "static_only"
    return "current_page_only"


def expected_query_message_label(candidate: dict[str, Any]) -> str:
    return str(candidate.get("item_label") or candidate.get("calculation_target_label") or candidate.get("item_id") or "")


def depends_on_item_ids(candidate: dict[str, Any], *, trigger: dict[str, Any] | None = None) -> list[str]:
    ids: list[str] = []
    for key in ("depends_on_item_id", "calculation_target_item_id", "control_item_id"):
        for value in str(candidate.get(key) or "").split(","):
            value = value.strip()
            if value and value not in ids:
                ids.append(value)
    if trigger:
        for value in _ref_item_ids(trigger.get("conditional")):
            if value and value != candidate.get("item_id") and value not in ids:
                ids.append(value)
    return ids


def limitation_reason_code(reason: str) -> str:
    text = str(reason or "").lower()
    if "appendable" in text:
        return "appendable_table_required"
    if "option" in text:
        return "option_not_found"
    if "target row" in text or "field not found" in text:
        return "target_row_not_found"
    if "source row" in text:
        return "source_row_not_found"
    if "calculate" in text or "assign" in text:
        return "calculation_prerequisite"
    if "cross" in text or "other page" in text or "page/visit" in text:
        return "cross_page_reference"
    if "unsupported" in text or "could not generate" in text:
        return "unsupported_expression"
    if "navigation" in text:
        return "browser_navigation_required"
    return "manual_review_required"


def step_page_ids(candidate: dict[str, Any]) -> set[str]:
    pages: set[str] = set()
    for step in _candidate_steps(candidate):
        kwargs = step.get("kwargs") or {}
        page_id = kwargs.get("page_id")
        if page_id:
            pages.add(str(page_id))
        if step.get("method") == "go_to_page":
            for arg in step.get("args") or []:
                segment = str(arg or "")
                if segment:
                    pages.add(segment.split("/")[-1])
    return pages


def trigger_page_ids(trigger: dict[str, Any]) -> set[str]:
    pages: set[str] = set()
    for key in ("pageId", "crfPageId"):
        value = trigger.get(key)
        if value:
            pages.add(str(value))
    for key in ("issue", "conditional", "bindTo", "value", "target", "disable", "enable"):
        pages.update(_ref_page_ids(trigger.get(key)))
    return pages


def _candidate_steps(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for key in ("steps", "steps_to_make_unavailable", "steps_to_make_available"):
        for step in candidate.get(key) or []:
            if isinstance(step, dict):
                steps.append(step)
    return steps


def _combined_text(candidate: dict[str, Any], trigger: dict[str, Any] | None) -> str:
    parts = [
        candidate.get("DVS ID"),
        candidate.get("name"),
        candidate.get("item_id"),
        candidate.get("item_label"),
        candidate.get("rule_type"),
        candidate.get("Specification"),
        candidate.get("evidence"),
    ]
    if trigger:
        parts.extend([trigger.get("id"), trigger.get("note"), trigger.get("conditional")])
    return " ".join(str(part or "") for part in parts).upper()


def _has_numeric_range(text: str) -> bool:
    return bool(re.search(r"(<|>|<=|>=)\s*-?\d", text)) or any(token in text for token in ("RANGE", "MIN", "MAX"))


def _has_date_window(candidate: dict[str, Any], trigger: dict[str, Any] | None, text: str) -> bool:
    if "DATE_WINDOW" in text or "DAYS" in text or "SVDAT" in text:
        return True
    return bool(trigger and "valAs" in str(trigger.get("conditional") or "") and "DAYS" in str(trigger.get("conditional") or ""))


def _references_other_page(candidate: dict[str, Any], *, current_page_id: str) -> bool:
    pages = step_page_ids(candidate)
    return bool(current_page_id and pages and not pages <= {current_page_id})


def _ref_item_ids(value: Any) -> list[str]:
    ids: list[str] = []
    if isinstance(value, dict):
        item_id = str(value.get("itemId") or "")
        if item_id:
            ids.append(item_id)
        for child in value.values():
            ids.extend(_ref_item_ids(child))
    elif isinstance(value, list):
        for child in value:
            ids.extend(_ref_item_ids(child))
    return ids


def _ref_page_ids(value: Any) -> set[str]:
    pages: set[str] = set()
    if isinstance(value, dict):
        for key in ("crfPageId", "pageId"):
            page_id = value.get(key)
            if page_id:
                pages.add(str(page_id))
        for child in value.values():
            pages.update(_ref_page_ids(child))
    elif isinstance(value, list):
        for child in value:
            pages.update(_ref_page_ids(child))
    return pages
