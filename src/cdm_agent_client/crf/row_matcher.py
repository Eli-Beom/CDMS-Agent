from __future__ import annotations

import re
from typing import Any


def normalize_label(label: str) -> str:
    return re.sub(r"[\s\[\]\(\){}_/·:：-]+", "", str(label or ""))


def skip_browser_row(label: str) -> bool:
    skip_tokens = (
        "Query [",
        "자동계산",
        "인구학적 조사",
        "사회력 조사",
        "유방암 관련 병력 정보",
        "활력징후",
        "비고",
    )
    return any(token in label for token in skip_tokens)


def force_include_browser_row(label: str) -> bool:
    labels = {
        "생년월일",
        "비가임 사유",
        "[좌측 유방] 수술 목적",
        "[우측 유방] 수술 목적",
        "유방암 병력이 있습니까?",
    }
    return label in labels or any(token in label for token in ("진단일", "병기 확인일"))


def current_input_row_labels(context: dict[str, Any]) -> set[str]:
    labels: set[str] = set()
    for row in context.get("structured_rows") or []:
        label = str(row.get("rowLabel") or "").strip()
        if not label or skip_browser_row(label):
            continue
        if not bool(row.get("visible", True)):
            continue
        if bool(row.get("editable", False)) or force_include_browser_row(label) or row.get("options"):
            labels.add(label)
    return labels


def first_step_label(steps: list[Any]) -> str:
    for step in steps:
        if step.args:
            label = str(step.args[0]).strip()
            if label:
                return label
    return ""


def resolve_field_for_label(field_map: dict[str, Any], page_id: str, label: str) -> Any | None:
    """Return the CRF field whose label best matches a browser row label."""
    label = str(label or "").strip()
    if not label:
        return None
    candidates = _unique_page_fields(field_map, page_id)
    exact = [field for field in candidates if str(getattr(field, "label", "") or "").strip() == label]
    if exact:
        return exact[0]
    normalized_label = normalize_label(label)
    normalized = [
        field
        for field in candidates
        if normalize_label(str(getattr(field, "label", "") or "")) == normalized_label
    ]
    if normalized:
        return normalized[0]
    suffix = [
        field
        for field in candidates
        if _labels_overlap(normalized_label, normalize_label(str(getattr(field, "label", "") or "")))
    ]
    return suffix[0] if suffix else None


def _unique_page_fields(field_map: dict[str, Any], page_id: str) -> list[Any]:
    seen: set[tuple[str, str]] = set()
    fields: list[Any] = []
    for field in field_map.values():
        if page_id and str(getattr(field, "page_id", "") or "") != str(page_id):
            continue
        key = (str(getattr(field, "page_id", "") or ""), str(getattr(field, "item_id", "") or ""))
        if key in seen:
            continue
        seen.add(key)
        fields.append(field)
    return fields


def _labels_overlap(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if left == right:
        return True
    return left.endswith(right) or right.endswith(left)
