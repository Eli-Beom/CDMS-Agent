from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .extractor import _coerce_visit_map, build_field_map, extract_spec
from .models import Check, CRFCase, CRFPlan, FieldDef, Step
from .overrides import StudyOverrides
from .parser import (
    classify_triggers,
    collect_availability_items,
    collect_visibility_items,
    parse_availability,
    parse_visibility,
)
from .simulator import extract_inputs, extract_input_variants

if TYPE_CHECKING:
    from ..client import CDMSAgent


def _is_query_trigger(trigger: dict) -> bool:
    trigger_id = str(trigger.get("id", ""))
    return trigger.get("type") == "QUERY" and not trigger_id.startswith("SYSTEM_")


def resolve_crf_location(
    *,
    crf_path: str | Path | None = None,
    maven_root: str | Path | None = None,
    study: str | None = None,
) -> tuple[Path, str]:
    """Resolve CRF source location from ``crf_path`` or the legacy two-part form."""
    if crf_path is not None:
        path = Path(crf_path)
        inferred_study = path.name
        if study is not None and study != inferred_study:
            raise ValueError(f"study={study!r} does not match crf_path folder name {inferred_study!r}")
        if maven_root is None:
            if path.parent.name != "crfs" or path.parent.parent.name != "src":
                raise ValueError("crf_path must point to .../maven-crfs/src/crfs/<crf-folder>")
            maven_root = path.parent.parent.parent
        return Path(maven_root), inferred_study

    if maven_root is None:
        raise TypeError("maven_root is required unless crf_path is provided")
    if study is None:
        raise TypeError("study is required unless crf_path is provided")
    return Path(maven_root), study


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
        crf_path: str | Path | None = None,
        visit_map: dict[int, str] | None = None,
        page_ids: set[str] | list[str] | tuple[str, ...] | None = None,
        overrides: "StudyOverrides | None" = None,
        overrides_dir: str | Path | None = None,
    ) -> None:
        resolved_maven_root, resolved_study = resolve_crf_location(
            crf_path=crf_path,
            maven_root=maven_root,
            study=study,
        )

        # Kept for compatibility with older notebooks that passed an agent.
        self.agent = agent
        self.maven_root = resolved_maven_root
        self.study = resolved_study
        self._provided_visit_map = visit_map
        self.visit_map: dict[int, str] = _coerce_visit_map(visit_map or {})
        self.page_ids = set(page_ids) if page_ids else None

        # Override JSON: caller may inject a pre-loaded object or a directory path.
        if overrides is not None:
            self._overrides: StudyOverrides = overrides
        else:
            self._overrides = StudyOverrides(resolved_study, overrides_dir)
            self._overrides.load()

        self._spec: dict | None = None
        self._field_map: dict[str, FieldDef] = {}
        self._query_auto: list[dict] = []
        self._query_skip: list[dict] = []
        self._query_total = 0
        self._vis_items: list[dict] = []
        self._avail_items: list[dict] = []

    def load_spec(self) -> None:
        """Extract CRF spec from TypeScript source and build internal indexes."""
        full_spec = extract_spec(self.study, self.maven_root)
        if self._provided_visit_map is None:
            self.visit_map = _coerce_visit_map(full_spec.get("visitMap") or full_spec.get("visit_map") or {})
        self._field_map = build_field_map(full_spec)
        self._spec = full_spec
        if self.page_ids:
            self._spec = self._filter_spec_pages(full_spec, self.page_ids)
        query_triggers = [trigger for trigger in self._spec["triggers"] if _is_query_trigger(trigger)]
        self._query_total = len(query_triggers)
        self._query_auto, self._query_skip = classify_triggers(query_triggers)
        self._vis_items = collect_visibility_items(self._spec)
        self._avail_items = collect_availability_items(self._spec)

    def _require_spec(self) -> None:
        if self._spec is None:
            raise RuntimeError("Call load_spec() first.")

    def _filter_spec_pages(self, spec: dict, page_ids: set[str]) -> dict:
        pages = {page_id: fields for page_id, fields in spec["pages"].items() if page_id in page_ids}
        item_pages = {
            field.get("itemId"): page_id
            for page_id, fields in pages.items()
            for field in fields
            if field.get("itemId")
        }

        def trigger_matches(trigger: dict) -> bool:
            page_id = trigger.get("pageId")
            if page_id in page_ids:
                return True
            issue = trigger.get("issue") or {}
            item_ids = issue.get("itemId") or []
            if isinstance(item_ids, str):
                item_ids = [item_ids]
            item_ids = [item_id for item_id in item_ids if isinstance(item_id, str)]
            return any(item_pages.get(item_id) in page_ids for item_id in item_ids)

        return {
            **spec,
            "pages": pages,
            "triggers": [trigger for trigger in spec["triggers"] if trigger_matches(trigger)],
        }

    def summary(self):
        """Return a pandas DataFrame summarising non-query CRF structure counts."""
        import pandas as pd

        self._require_spec()
        return pd.DataFrame(
            [
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

    def build_plan(
        self,
        *,
        include_query: bool = True,
        include_visibility: bool = True,
        include_availability: bool = True,
    ) -> CRFPlan:
        """Build a grouped scenario plan from the loaded CRF spec."""
        return CRFPlan(
            query_expected=self.query_cases(expect_query=True) if include_query else [],
            no_query_expected=self.query_cases(expect_query=False) if include_query else [],
            visibility=self.visibility_cases() if include_visibility else [],
            availability=self.availability_cases() if include_availability else [],
        )

    def plan(
        self,
        *,
        include_query: bool = True,
        include_visibility: bool = True,
        include_availability: bool = True,
    ) -> CRFPlan:
        """Short alias for ``build_plan``."""
        return self.build_plan(
            include_query=include_query,
            include_visibility=include_visibility,
            include_availability=include_availability,
        )

    def build_scenarios(
        self,
        *,
        include_query: bool = True,
        include_visibility: bool = True,
        include_availability: bool = True,
    ) -> list[CRFCase]:
        """Build and flatten a scenario plan."""
        return self.build_plan(
            include_query=include_query,
            include_visibility=include_visibility,
            include_availability=include_availability,
        ).all

    def cases(
        self,
        *,
        include_query: bool = True,
        include_visibility: bool = True,
        include_availability: bool = True,
    ) -> list[CRFCase]:
        """Short alias for flattened generated cases."""
        return self.build_scenarios(
            include_query=include_query,
            include_visibility=include_visibility,
            include_availability=include_availability,
        )

    def query_cases(self, *, expect_query: bool | None = None) -> list[CRFCase]:
        """Generate Query and/or No Query scenarios from parseable triggers."""
        self._require_spec()
        cases: list[CRFCase] = []
        modes = [True, False] if expect_query is None else [expect_query]
        for mode in modes:
            for trigger in self._query_auto:
                cases.extend(self.build_query_cases_for_trigger(trigger, expect_query=mode))
        return cases

    def visibility_cases(self) -> list[CRFCase]:
        """Generate visibility scenarios from CRF visibility rules."""
        self._require_spec()
        return [self.build_visibility_case(f) for f in self._vis_items]

    def availability_cases(self) -> list[CRFCase]:
        """Generate availability scenarios from CRF availability rules."""
        self._require_spec()
        return [self.build_availability_case(f) for f in self._avail_items]

    def query_scenarios(self, *, expect_query: bool | None = None) -> list[CRFCase]:
        return self.query_cases(expect_query=expect_query)

    def visibility_scenarios(self) -> list[CRFCase]:
        return self.visibility_cases()

    def availability_scenarios(self) -> list[CRFCase]:
        return self.availability_cases()

    def all_scenarios(self) -> list[CRFCase]:
        """Return Query, No Query, Visibility, and Availability scenarios."""
        return self.build_scenarios()

    def to_dataframe(self, scenarios: list[CRFCase] | CRFPlan):
        """Convert generated scenarios or a scenario plan to a pandas DataFrame."""
        import pandas as pd

        if isinstance(scenarios, CRFPlan):
            scenarios = scenarios.all
        return pd.DataFrame([s.as_dict() for s in scenarios])

    def build_query_case(self, trigger: dict, *, expect_query: bool) -> CRFCase:
        """Build one Query/No Query validation scenario without executing it."""
        return self._build_query_case(trigger, expect_query=expect_query)

    def build_query_cases_for_trigger(self, trigger: dict, *, expect_query: bool) -> list[CRFCase]:
        """Build all input variants for one Query/No Query trigger."""
        self._require_spec()
        variants = extract_input_variants(
            trigger.get("conditional"),
            trigger["pageId"],
            self._field_map,
            use_violation=expect_query,
        )
        if not variants:
            return [self._build_query_case(trigger, expect_query=expect_query, inputs=[])]
        if len(variants) == 1:
            return [self._build_query_case(trigger, expect_query=expect_query, inputs=variants[0])]
        return [
            self._build_query_case(
                trigger,
                expect_query=expect_query,
                inputs=inputs,
                case_id=f"{trigger['id']}_{idx}",
            )
            for idx, inputs in enumerate(variants, start=1)
        ]

    def _build_query_case(
        self,
        trigger: dict,
        *,
        expect_query: bool,
        inputs: list[tuple[str, str, str, str, str]] | None = None,
        case_id: str | None = None,
    ) -> CRFCase:
        self._require_spec()
        if inputs is None:
            inputs = extract_inputs(
                trigger.get("conditional"),
                trigger["pageId"],
                self._field_map,
                use_violation=expect_query,
            )
        kind = "query_expected" if expect_query else "no_query_expected"
        expected = "Query" if expect_query else "No Query"
        case = CRFCase(
            kind=kind,
            id=case_id or trigger["id"],
            page=trigger["pageId"],
            note=trigger.get("note", ""),
            expect=expected,
        )
        if not inputs:
            case.errors.append("Could not generate input values from trigger conditional.")
            return case

        for role, item_id, visit_id, page_id, value in inputs:
            fd = self._resolve_field(page_id, item_id)
            if fd is None:
                case.errors.append(f"Field not found: {page_id}.{item_id}")
                continue
            case.steps.append(Step("go_to_page", [self._nav_segment(visit_id, page_id)], note=role))
            if role == "MAIN":
                self._append_precondition_steps(case, fd, visit_id=visit_id)
            before_set_step = len(case.steps)
            self._append_set_field_steps(case, fd, value, visit_id=visit_id, note=role)
            case.steps.append(Step("click_save", [], {"page_id": page_id, "visit_id": visit_id or None}))
            if role == "MAIN" and len(case.steps) > before_set_step:
                case.checks.append(Check("query", expected, note="after save", after_step=len(case.steps)))

        last_page = inputs[-1][3]
        case.steps.append(Step("go_to_page", [last_page], note="Return to trigger page"))
        case.steps.append(Step("click_save", [], {"page_id": last_page}))
        case.checks.append(Check("query", expected, after_step=len(case.steps)))
        return case

    def build_query_scenario(self, trigger: dict, *, expect_query: bool) -> CRFCase:
        return self.build_query_case(trigger, expect_query=expect_query)

    def build_visibility_case(self, field: dict) -> CRFCase:
        """Build one visibility validation scenario without executing it."""
        self._require_spec()
        rules = parse_visibility(field.get("visibility"))
        label = field["label"]
        page = field["pageId"]
        case = CRFCase(kind="visibility", id=field["itemId"], page=page, label=label)
        if not rules:
            case.errors.append("Could not parse visibility rule.")
            return case

        rule = rules[0]
        on_seg = self._visit_seg(rule["visit_num"])
        expected_check = "visible" if rule["condition"] == "=" else "not_visible"
        case.steps.append(Step("go_to_page", [f"{on_seg}/{page}"]))
        case.checks.append(
            Check(expected_check, True, label=label, note=f"visit={on_seg}", after_step=len(case.steps))
        )

        off_visit = next((n for n in self.visit_map if n != rule["visit_num"]), None)
        if off_visit is not None:
            off_seg = self._visit_seg(off_visit)
            case.steps.append(Step("go_to_page", [f"{off_seg}/{page}"]))
            case.checks.append(
                Check("not_visible", True, label=label, note=f"visit={off_seg}", after_step=len(case.steps))
            )
        return case

    def build_visibility_scenario(self, field: dict) -> CRFCase:
        return self.build_visibility_case(field)

    def build_availability_case(self, field: dict) -> CRFCase:
        """Build one availability validation scenario without executing it."""
        self._require_spec()
        parsed = parse_availability(field.get("availability"))
        label = field["label"]
        page = field["pageId"]
        case = CRFCase(kind="availability", id=field["itemId"], page=page, label=label)
        if not parsed:
            case.errors.append("Could not parse availability rule.")
            return case

        ctrl_fd = self._resolve_field(page, parsed["ctrl_item_id"])
        if ctrl_fd is None:
            case.errors.append(f"Control field not found: {parsed['ctrl_item_id']}")
            return case

        case.steps.append(Step("go_to_page", [page]))
        self._append_set_field_steps(case, ctrl_fd, parsed["enable_val"])
        case.checks.append(
            Check("visible", True, label=label, note="after enable value", after_step=len(case.steps))
        )
        self._append_set_field_steps(case, ctrl_fd, parsed["disable_val"])
        case.checks.append(
            Check("not_visible", True, label=label, note="after disable value", after_step=len(case.steps))
        )
        return case

    def build_availability_scenario(self, field: dict) -> CRFCase:
        return self.build_availability_case(field)

    # Backward-compatible names. They now generate scenarios instead of running
    # browser automation.
    def sim_query(self, trigger: dict, *, expect_query: bool) -> CRFCase:
        return self.build_query_case(trigger, expect_query=expect_query)

    def sim_visibility(self, field: dict) -> CRFCase:
        return self.build_visibility_case(field)

    def sim_availability(self, field: dict) -> CRFCase:
        return self.build_availability_case(field)

    def run_all(self) -> list[CRFCase]:
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
        case: CRFCase,
        fd: FieldDef,
        value: Any,
        *,
        visit_id: str | None = None,
        note: str = "",
    ) -> None:
        method = fd.agent_action
        if method == "SKIP":
            case.errors.append(f"Field is not directly editable: {fd.item_id}")
            return
        str_val = str(value)
        kwargs = {"page_id": fd.page_id, "visit_id": visit_id}
        label = self._label_for_field(fd)
        if method == "set_date":
            case.steps.append(Step("set_date", [label, str_val], kwargs, note=note))
        elif method == "set_text":
            case.steps.append(Step("set_text", [label, str_val], kwargs, note=note))
        elif method in ("select_radio", "select_option"):
            matched = next((o for o in fd.options if str(o.get("dbVal")) == str_val), None)
            if matched is None and fd.options:
                case.errors.append(f"Option not found: {fd.item_id}={str_val}")
                return
            ui_val = matched.get("uiVal", str_val) if matched else str_val
            ui_val = self._option_for_field(fd, str(ui_val))
            case.steps.append(Step(method, [label, ui_val], kwargs, note=note))

    def _label_for_field(self, fd: FieldDef) -> str:
        aliases = self._overrides.label_aliases(fd.item_id)
        return aliases[0] if aliases else fd.label

    def _option_for_field(self, fd: FieldDef, canonical: str) -> str:
        aliases = self._overrides.option_aliases(fd.item_id, canonical)
        return aliases[0] if aliases else canonical

    def _append_precondition_steps(self, case: CRFCase, fd: FieldDef, *, visit_id: str | None) -> None:
        """Add page-level prerequisites needed before a target field can be edited.

        Preconditions are looked up from the override JSON first
        (key = ``"<pageId>.<itemId>"``).  The legacy hard-coded fallback for
        ``DM.BFYN`` is still applied when no override entry is present, so
        existing notebooks continue to work without migration.
        """
        override_key = f"{fd.page_id}.{fd.item_id}"
        steps = self._overrides.preconditions(override_key)

        if steps:
            # Override-driven preconditions: each step has itemId + value
            for step in steps:
                raw_id = step.get("itemId", "")
                # itemId may be "pageId.itemId" or bare "itemId"
                if "." in raw_id:
                    p_id, i_id = raw_id.split(".", 1)
                else:
                    p_id, i_id = fd.page_id, raw_id
                self._append_known_field_step(
                    case, p_id, i_id, step["value"],
                    visit_id=visit_id, note="PRECOND",
                )
            return

        # ── legacy fallback (hard-coded knowledge for DM.BFYN) ───────────────
        if fd.page_id == "DM" and fd.item_id == "BFYN":
            self._append_known_field_step(
                case,
                "DM",
                "BRTHDAT",
                _birthdate_at_least_age(_default_visit_date(), 19),
                visit_id=visit_id,
                note="PRECOND",
            )
            self._append_known_field_step(case, "DM", "SEX", "2", visit_id=visit_id, note="PRECOND")
            self._append_known_field_step(case, "DM", "PGYN", "1", visit_id=visit_id, note="PRECOND")

    def _append_known_field_step(
        self,
        case: CRFCase,
        page_id: str,
        item_id: str,
        value: Any,
        *,
        visit_id: str | None,
        note: str,
    ) -> None:
        fd = self._resolve_field(page_id, item_id)
        if fd is None:
            case.errors.append(f"Precondition field not found: {page_id}.{item_id}")
            return
        self._append_set_field_steps(case, fd, value, visit_id=visit_id, note=note)


def _default_visit_date() -> date:
    return date(2024, 1, 1)


def _birthdate_at_least_age(visit_date: date, age: int) -> str:
    return date(visit_date.year - age, visit_date.month, visit_date.day).isoformat()
