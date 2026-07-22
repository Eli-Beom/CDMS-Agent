from __future__ import annotations

from typing import Any

from ..models import Step
from ..discovery.row_matcher import normalize_label, skip_browser_row


def numeric_discovery_value_for(label: str, *, expect_query: bool) -> str | None:
    normalized = normalize_label(label)
    if "수축기혈압" in normalized:
        return "79" if expect_query else "120"
    if "이완기혈압" in normalized:
        return "39" if expect_query else "80"
    if "맥박" in normalized:
        return "49" if expect_query else "70"
    if "체온" in normalized:
        return "34.9" if expect_query else "36.5"
    return None


def default_date_for(label: str) -> str:
    if "생년월일" in label:
        return "2005-01-01"
    return "2026-05-27"


def default_text_for(label: str) -> str:
    if "사유" in label:
        return "테스트 입력"
    return "1"


def preferred_option(label: str, row: dict[str, Any]) -> str | None:
    hardcoded = {
        "성별": "여성",
        "가임 여부": "예",
        "비가임 사유": "기타",
        "수유 여부": "예",
        "[좌측 유방] 수술 목적": "해당사항 없음",
        "[우측 유방] 수술 목적": "해당사항 없음",
        "유방암 병력이 있습니까?": "아니요",
        "흡연력": "흡연력 없음",
        "음주력": "음주력 없음",
    }
    if label in hardcoded:
        return hardcoded[label]
    options = [str(option).strip() for option in row.get("options") or [] if str(option).strip()]
    for preferred in ("해당사항 없음", "아니요", "예", "흡연력 없음", "음주력 없음"):
        if preferred in options:
            return preferred
    return options[0] if options else None


def input_step_from_row(label: str, row: dict[str, Any], *, page_id: str, visit_id: str | None) -> Step | None:
    kwargs = {"page_id": page_id or None, "visit_id": visit_id}
    numeric_value = numeric_discovery_value_for(label, expect_query=False)
    if numeric_value is not None:
        return Step("set_text", [label, numeric_value], kwargs)
    control_type = str(row.get("controlType") or "")
    option = preferred_option(label, row)
    if "일" in label or "date" in label.lower() or control_type == "date":
        if any(token in label for token in ("일", "생년월일", "날짜")):
            return Step("set_date", [label, default_date_for(label)], kwargs)
    if control_type == "select" and option:
        return Step("select_option", [label, option], kwargs)
    if control_type in {"textarea", "input", "text"}:
        return Step("set_text", [label, default_text_for(label)], kwargs)
    if option:
        return Step("select_radio", [label, option], kwargs)
    return None


def query_mode_step(step: Any, *, expect_query: bool) -> Step:
    label = str(step.args[0])
    args = list(step.args)
    if step.method == "set_date" and "생년월일" in label:
        args[1] = "2005-01-01" if expect_query else "2002-01-01"
    return Step(step.method, args, dict(step.kwargs), note="query 발생 예상" if expect_query else "query 미발생 예상")


def fallback_query_steps(context: dict[str, Any], *, expect_query: bool) -> list[Step]:
    page_id = context.get("page_id") or ""
    visit_id = visit_id_from_path(context.get("pathname"))
    steps: list[Step] = []
    for row in context.get("structured_rows") or []:
        label = str(row.get("rowLabel") or "").strip()
        if not label or skip_browser_row(label):
            continue
        numeric_value = numeric_discovery_value_for(label, expect_query=expect_query)
        if numeric_value is not None:
            steps.append(Step("set_text", [label, numeric_value], {"page_id": page_id or None, "visit_id": visit_id}))
            continue
        step = input_step_from_row(label, row, page_id=page_id, visit_id=visit_id)
        if not step:
            continue
        if step.method == "set_date" and label == "생년월일":
            step.args[1] = "2005-01-01" if expect_query else "2002-01-01"
        steps.append(step)
    return steps


def visit_id_from_path(pathname: str | None) -> str | None:
    if not pathname:
        return None
    parts = [part for part in str(pathname).split("/") if part]
    if len(parts) >= 4:
        return parts[-4]
    return None
