from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class FieldDef:
    item_id: str
    label: str
    field_type: str
    layout: Optional[str]
    page_id: str
    section_id: str
    options: list[dict] = field(default_factory=list)
    visibility: Optional[list] = None
    availability: Optional[dict] = None

    @property
    def agent_action(self) -> str:
        if self.field_type == "DATE":
            return "set_date"
        if self.field_type == "AUTO_TEXT":
            return "SKIP"
        if self.field_type == "SINGLE_SELECT" and self.layout == "RADIO":
            return "select_radio"
        if self.field_type in ("SINGLE_SELECT", "CHECK"):
            return "select_option"
        return "set_text"


@dataclass
class SimResult:
    sim_type: str   # "Query 발생" | "Query 미발생" | "visibility" | "availability"
    id: str
    result: str     # "PASS" | "FAIL" | "SKIP"
    note: str = ""
    expect: str = ""
    actual: str = ""
    errors: list[str] = field(default_factory=list)
    page: str = ""
    item: str = ""
    label: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": self.sim_type,
            "id": self.id,
            "page": self.page,
            "item": self.item,
            "label": self.label,
            "note": self.note,
            "expect": self.expect,
            "actual": self.actual,
            "result": self.result,
            "errors": "; ".join(self.errors),
            **self.details,
        }


@dataclass
class AgentStep:
    """One CDMSAgent method call generated for a validation scenario."""

    method: str
    args: list[Any] = field(default_factory=list)
    kwargs: dict[str, Any] = field(default_factory=dict)
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "args": self.args,
            "kwargs": self.kwargs,
            "note": self.note,
        }

    def to_code(self, agent_name: str = "agent") -> str:
        args = ", ".join(repr(v) for v in self.args)
        kwargs = ", ".join(f"{k}={v!r}" for k, v in self.kwargs.items() if v is not None)
        params = ", ".join(p for p in (args, kwargs) if p)
        return f"{agent_name}.{self.method}({params})"


@dataclass
class ScenarioCheck:
    """A manual/interactive assertion to run after generated agent steps."""

    check_type: str
    expected: Any
    label: str = ""
    note: str = ""
    after_step: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "check_type": self.check_type,
            "expected": self.expected,
            "label": self.label,
            "note": self.note,
            "after_step": self.after_step,
        }


@dataclass
class CRFScenario:
    """Generated CRF validation scenario.

    The scenario is intentionally browser-client agnostic. It stores the
    CDMSAgent calls and checks that a notebook can execute step by step.
    """

    kind: str
    id: str
    page: str
    label: str = ""
    note: str = ""
    expect: str = ""
    steps: list[AgentStep] = field(default_factory=list)
    checks: list[ScenarioCheck] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def runnable(self) -> bool:
        return not self.errors and bool(self.steps)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "id": self.id,
            "page": self.page,
            "label": self.label,
            "note": self.note,
            "expect": self.expect,
            "runnable": self.runnable,
            "steps": len(self.steps),
            "checks": len(self.checks),
            "errors": "; ".join(self.errors),
        }

    def to_code(self, agent_name: str = "agent") -> str:
        lines = [step.to_code(agent_name) for step in self.steps]
        for check in self.checks:
            if check.check_type == "query":
                lines.append(f"print({agent_name}.check_result({check.expected!r}))")
            elif check.check_type == "visible":
                lines.append(f"snap = {agent_name}.inspect()")
                lines.append(f"print({check.label!r}, 'visible =', {check.label!r} in snap.visible_rows)")
            elif check.check_type == "not_visible":
                lines.append(f"snap = {agent_name}.inspect()")
                lines.append(f"print({check.label!r}, 'hidden =', {check.label!r} not in snap.visible_rows)")
        return "\n".join(lines)
