from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .models import Check, CRFCase

if TYPE_CHECKING:
    from ..client import CDMSAgent


class CRFRun:
    """Run generated CRF cases with a CDMSAgent."""

    def __init__(self, agent: "CDMSAgent") -> None:
        self.agent = agent

    def case(self, case: CRFCase) -> dict[str, Any]:
        """Run one generated case and return a compact result dict."""
        failures: list[str] = []
        print(f"[{case.kind}] {case.id} {case.label or ''}")

        if case.errors:
            return {
                "id": case.id,
                "kind": case.kind,
                "result": "SKIP",
                "errors": "; ".join(case.errors),
            }

        for step_index, step in enumerate(case.steps, start=1):
            call = getattr(self.agent, step.method)
            print(">", step.to_code("agent"))
            call(*step.args, **step.kwargs)

            for check in case.checks:
                if check.after_step == step_index:
                    self._check(check, failures)

        for check in case.checks:
            if check.after_step is None:
                self._check(check, failures)

        return {
            "id": case.id,
            "kind": case.kind,
            "result": "FAIL" if failures else "PASS",
            "errors": "; ".join(failures),
        }

    def cases(self, cases: list[CRFCase]) -> list[dict[str, Any]]:
        """Run multiple generated cases."""
        return [self.case(case) for case in cases]

    def _check(self, check: Check, failures: list[str]) -> None:
        if check.check_type == "query":
            actual = self.agent.check_result(check.expected)
            print("check_result:", check.expected, "=>", actual)
            if actual != "PASS":
                failures.append(f"query expected {check.expected}")
            return

        if check.check_type in ("visible", "not_visible"):
            snap = self.agent.inspect()
            visible = check.label in snap.visible_rows
            passed = visible if check.check_type == "visible" else not visible
            print(check.label, check.check_type, "=>", "PASS" if passed else "FAIL")
            if not passed:
                failures.append(f"{check.label} {check.check_type}")
