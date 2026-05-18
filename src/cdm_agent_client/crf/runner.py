from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from .extractor import build_field_map, extract_spec
from .models import AgentStep, CRFScenario, FieldDef, ScenarioCheck
from .parser import (
    classify_triggers,
    collect_availability_items,
    collect_visibility_items,
    parse_availability,
    parse_visibility,
)
from .simulator import extract_inputs

if TYPE_CHECKING:
    from ..client import CDMSAgent


class CRFRunner:
    """Generate CRF validation scenarios from TypeScript CRF source code.

    ``CRFRunner`` reads a CRF spec, classifies Query/Visibility/Availability
    checks, and turns parseable rules into ``CDMSAgent`` call sequences. It no
    longer drives the browser directly; generated notebooks execute the calls
    so an operator can inspect each step in Jupyter.
    """

    def __init__(
        self,
        agent: "CDMSAgent | None" = None,
        maven_root: str | Path | None = None,
        study: str | None = None,
        *,
        visit_map: dict[int, str] | None = None,
    ) -> None:
        if maven_root is None:
            raise TypeError("maven_root is required")
        if study is None:
            raise TypeError("study is required")

        # Kept for compatibility with older notebooks that passed an agent.
        self.agent = agent
        self.maven_root = Path(maven_root)
        self.study = study
        self.visit_map: dict[int, str] = visit_map or {}

        self._spec: dict | None = None
        self._field_map: dict[str, FieldDef] = {}
        self._query_auto: list[dict] = []
        self._query_skip: list[dict] = []
        self._vis_items: list[dict] = []
        self._avail_items: list[dict] = []

    def load_spec(self) -> None:
        """Extract CRF spec from TypeScript source and build internal indexes."""
        self._spec = extract_spec(self.study, self.maven_root)
        self._field_map = build_field_map(self._spec)
        self._query_auto, self._query_skip = classify_triggers(self._spec["triggers"])
        self._vis_items = collect_visibility_items(self._spec)
        self._avail_items = collect_availability_items(self._spec)

    def _require_spec(self) -> None:
        if self._spec is None:
            raise RuntimeError("Call load_spec() first.")

    def summary(self):
        """Return a pandas DataFrame summarising generated scenario counts."""
        import pandas as pd

        self._require_spec()
        total_triggers = len(self._spec["triggers"])  # type: ignore[index]
        return pd.DataFrame(
            [
                {
                    "validation_type": "query_expected",
                    "generated": len(self._query_auto),
                    "manual_review": len(self._query_skip),
                    "total": total_triggers,
                },
                {
                    "validation_type": "no_query_expected",
                    "generated": len(self._query_auto),
                    "manual_review": len(self._query_skip),
                    "total": total_triggers,
                },
                {
                    "validation_type": "visibility",
                    "generated": len(self._vis_items),
                    "manual_review": 0,
                    "total": len(self._vis_items),
                },
                {
                    "validation_type": "availability",
                    "generated": len(self._avail_items),
                    "manual_review": 0,
                    "total": len(self._avail_items),
                },
            ]
        )

    def query_scenarios(self, *, expect_query: bool | None = None) -> list[CRFScenario]:
        """Generate Query and/or No Query scenarios from parseable triggers."""
        self._require_spec()
        scenarios: list[CRFScenario] = []
        modes = [True, False] if expect_query is None else [expect_query]
        for mode in modes:
            scenarios.extend(self.build_query_scenario(t, expect_query=mode) for t in self._query_auto)
        return scenarios

    def visibility_scenarios(self) -> list[CRFScenario]:
        """Generate visibility scenarios from CRF visibility rules."""
        self._require_spec()
        return [self.build_visibility_scenario(f) for f in self._vis_items]

    def availability_scenarios(self) -> list[CRFScenario]:
        """Generate availability scenarios from CRF availability rules."""
        self._require_spec()
        return [self.build_availability_scenario(f) for f in self._avail_items]

    def all_scenarios(self) -> list[CRFScenario]:
        """Return Query, No Query, Visibility, and Availability scenarios."""
        return [
            *self.query_scenarios(expect_query=True),
            *self.query_scenarios(expect_query=False),
            *self.visibility_scenarios(),
            *self.availability_scenarios(),
        ]

    def to_dataframe(self, scenarios: list[CRFScenario]):
        """Convert generated scenarios to a pandas DataFrame."""
        import pandas as pd

        return pd.DataFrame([s.as_dict() for s in scenarios])

    def build_query_scenario(self, trigger: dict, *, expect_query: bool) -> CRFScenario:
        """Build one Query/No Query validation scenario without executing it."""
        self._require_spec()
        inputs = extract_inputs(
            trigger.get("conditional"),
            trigger["pageId"],
            self._field_map,
            use_violation=expect_query,
        )
        kind = "query_expected" if expect_query else "no_query_expected"
        expected = "Query" if expect_query else "No Query"
        scenario = CRFScenario(
            kind=kind,
            id=trigger["id"],
            page=trigger["pageId"],
            note=trigger.get("note", ""),
            expect=expected,
        )
        if not inputs:
            scenario.errors.append("Could not generate input values from trigger conditional.")
            return scenario

        for role, item_id, visit_id, page_id, value in inputs:
            fd = self._resolve_field(page_id, item_id)
            if fd is None:
                scenario.errors.append(f"Field not found: {page_id}.{item_id}")
                continue
            scenario.steps.append(AgentStep("go_to_page", [self._nav_segment(visit_id, page_id)], note=role))
            self._append_set_field_steps(scenario, fd, value, visit_id=visit_id)
            scenario.steps.append(AgentStep("click_save", [], {"page_id": page_id, "visit_id": visit_id or None}))

        last_page = inputs[-1][3]
        scenario.steps.append(AgentStep("go_to_page", [last_page], note="Return to trigger page"))
        scenario.steps.append(AgentStep("click_save", [], {"page_id": last_page}))
        scenario.checks.append(ScenarioCheck("query", expected, after_step=len(scenario.steps)))
        return scenario

    def build_visibility_scenario(self, field: dict) -> CRFScenario:
        """Build one visibility validation scenario without executing it."""
        self._require_spec()
        rules = parse_visibility(field.get("visibility"))
        label = field["label"]
        page = field["pageId"]
        scenario = CRFScenario(kind="visibility", id=field["itemId"], page=page, label=label)
        if not rules:
            scenario.errors.append("Could not parse visibility rule.")
            return scenario

        rule = rules[0]
        on_seg = self._visit_seg(rule["visit_num"])
        expected_check = "visible" if rule["condition"] == "=" else "not_visible"
        scenario.steps.append(AgentStep("go_to_page", [f"{on_seg}/{page}"]))
        scenario.checks.append(
            ScenarioCheck(expected_check, True, label=label, note=f"visit={on_seg}", after_step=len(scenario.steps))
        )

        off_visit = next((n for n in self.visit_map if n != rule["visit_num"]), None)
        if off_visit is not None:
            off_seg = self._visit_seg(off_visit)
            scenario.steps.append(AgentStep("go_to_page", [f"{off_seg}/{page}"]))
            scenario.checks.append(
                ScenarioCheck("not_visible", True, label=label, note=f"visit={off_seg}", after_step=len(scenario.steps))
            )
        return scenario

    def build_availability_scenario(self, field: dict) -> CRFScenario:
        """Build one availability validation scenario without executing it."""
        self._require_spec()
        parsed = parse_availability(field.get("availability"))
        label = field["label"]
        page = field["pageId"]
        scenario = CRFScenario(kind="availability", id=field["itemId"], page=page, label=label)
        if not parsed:
            scenario.errors.append("Could not parse availability rule.")
            return scenario

        ctrl_fd = self._resolve_field(page, parsed["ctrl_item_id"])
        if ctrl_fd is None:
            scenario.errors.append(f"Control field not found: {parsed['ctrl_item_id']}")
            return scenario

        scenario.steps.append(AgentStep("go_to_page", [page]))
        self._append_set_field_steps(scenario, ctrl_fd, parsed["enable_val"])
        scenario.checks.append(
            ScenarioCheck("visible", True, label=label, note="after enable value", after_step=len(scenario.steps))
        )
        self._append_set_field_steps(scenario, ctrl_fd, parsed["disable_val"])
        scenario.checks.append(
            ScenarioCheck("not_visible", True, label=label, note="after disable value", after_step=len(scenario.steps))
        )
        return scenario

    # Backward-compatible names. They now generate scenarios instead of running
    # browser automation.
    def sim_query(self, trigger: dict, *, expect_query: bool) -> CRFScenario:
        return self.build_query_scenario(trigger, expect_query=expect_query)

    def sim_visibility(self, field: dict) -> CRFScenario:
        return self.build_visibility_scenario(field)

    def sim_availability(self, field: dict) -> CRFScenario:
        return self.build_availability_scenario(field)

    def run_all(self) -> list[CRFScenario]:
        """Generate all scenarios.

        This method is kept for older notebooks. It no longer executes browser
        steps; use a generated notebook to run the returned scenario steps with
        ``CDMSAgent``.
        """
        return self.all_scenarios()

    def _visit_seg(self, visit_num: int) -> str:
        return self.visit_map.get(visit_num, str(visit_num))

    def _nav_segment(self, visit_id: str, page_id: str) -> str:
        return f"{visit_id}/{page_id}" if visit_id else page_id

    def _resolve_field(self, page_id: str, item_id: str) -> FieldDef | None:
        return self._field_map.get(f"{page_id}.{item_id}") or self._field_map.get(item_id)

    def _append_set_field_steps(
        self,
        scenario: CRFScenario,
        fd: FieldDef,
        value: Any,
        *,
        visit_id: str | None = None,
    ) -> None:
        method = fd.agent_action
        if method == "SKIP":
            scenario.errors.append(f"Field is not directly editable: {fd.item_id}")
            return
        str_val = str(value)
        kwargs = {"page_id": fd.page_id, "visit_id": visit_id}
        if method == "set_date":
            scenario.steps.append(AgentStep("set_date", [fd.label, str_val], kwargs))
        elif method == "set_text":
            scenario.steps.append(AgentStep("set_text", [fd.label, str_val], kwargs))
        elif method in ("select_radio", "select_option"):
            ui_val = next((o.get("uiVal", str_val) for o in fd.options if str(o.get("dbVal")) == str_val), str_val)
            scenario.steps.append(AgentStep(method, [fd.label, ui_val], kwargs))
