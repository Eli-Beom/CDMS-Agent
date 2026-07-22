"""CRF Doctor: static analysis of a CRF spec without running the browser.

Checks
------
- duplicate_trigger_ids   : two or more triggers share the same ``id``
- missing_page_ids        : triggers with an empty ``pageId``
- unresolved_item_ids     : conditional references to itemIds not in the field_map
- unparseable_triggers    : QUERY triggers that ``can_parse()`` returns False for
- dynamic_context         : triggers whose conditionals reference dynamic refs
                            (visitId dict, reserved-only rights, etc.)
- override_schema         : JSON override file schema errors (if file exists)
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .extractor import build_field_map, extract_spec
from .overrides import StudyOverrides, _validate_errors
from .parser import (
    can_parse,
    collect_availability_items,
)

# Patterns hinting at dynamic / repeated-table context in trigger raw JSON
_DYNAMIC_HINT = re.compile(
    r"\b(EACH|CURRENT|SIBLING|NEIGHBOR|REPEATED|TABLE|ROW_INDEX)\b",
    re.IGNORECASE,
)


@dataclass
class DoctorIssue:
    """One diagnostic finding."""
    check: str          # e.g. "duplicate_trigger_ids"
    severity: str       # "error" | "warning" | "info"
    trigger_id: str = ""
    page_id: str = ""
    item_id: str = ""
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "check": self.check,
            "severity": self.severity,
            "trigger_id": self.trigger_id,
            "page_id": self.page_id,
            "item_id": self.item_id,
            "detail": self.detail,
        }


@dataclass
class DoctorReport:
    """Aggregated diagnostic results for one CRF."""
    study_id: str
    issues: list[DoctorIssue] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)

    @property
    def errors(self) -> list[DoctorIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[DoctorIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def infos(self) -> list[DoctorIssue]:
        return [i for i in self.issues if i.severity == "info"]

    def ok(self) -> bool:
        return len(self.errors) == 0

    def as_dicts(self) -> list[dict[str, Any]]:
        return [i.as_dict() for i in self.issues]

    def to_dataframe(self):
        import pandas as pd
        return pd.DataFrame(self.as_dicts())

    def print_report(self) -> None:
        """Pretty-print the report to stdout."""
        icon = {"error": "ERROR", "warning": "WARN", "info": "INFO"}
        print(f"\n{'=' * 60}")
        print(f"  cdms-crf doctor  -  {self.study_id}")
        print(f"{'=' * 60}")
        if self.stats:
            print("\n  CRF Summary")
            labels = {
                "page_ts_files": "page.ts files",
                "trigger_ts_files": "trigger.ts files",
                "availability_items": "availability items",
            }
            for key, label in labels.items():
                if key in self.stats:
                    print(f"    {label:22s}: {self.stats[key]}")
        if not self.issues:
            print("  No issues found.\n")
            return

        by_check: dict[str, list[DoctorIssue]] = {}
        for issue in self.issues:
            by_check.setdefault(issue.check, []).append(issue)

        for check, items in by_check.items():
            first = items[0]
            label = icon.get(first.severity, "INFO")
            print(f"\n  [{label}] {check}  ({len(items)} issue(s))")
            for item in items[:10]:
                parts = []
                if item.trigger_id:
                    parts.append(f"trigger={item.trigger_id}")
                if item.page_id:
                    parts.append(f"page={item.page_id}")
                if item.item_id:
                    parts.append(f"item={item.item_id}")
                if item.detail:
                    parts.append(item.detail)
                print(f"       {', '.join(parts)}")
            if len(items) > 10:
                print(f"       and {len(items) - 10} more")

        print(f"\n  Summary: {len(self.errors)} error(s), "
              f"{len(self.warnings)} warning(s), "
              f"{len(self.infos)} info(s)\n")

class CRFDoctor:
    """Run static checks on an extracted CRF spec.

    Parameters
    ----------
    crf_path:
        Path to the CRF study folder (``maven-crfs/src/crfs/<study>``).
    overrides_dir:
        Optional override JSON directory.
    """

    def __init__(
        self,
        crf_path: str | Path,
        *,
        overrides_dir: str | Path | None = None,
    ) -> None:
        from .runner import resolve_crf_location

        self._crf_path = Path(crf_path)
        self._maven_root, self._study_id = resolve_crf_location(crf_path=crf_path)
        self._overrides_dir = Path(overrides_dir) if overrides_dir else None

    def run(self, *, extract_timeout: int = 90) -> DoctorReport:
        """Extract the CRF spec and run all checks.  Returns a :class:`DoctorReport`."""
        report = DoctorReport(study_id=self._study_id)

        # ── extract spec ──────────────────────────────────────────────────────
        try:
            spec = extract_spec(self._study_id, self._maven_root, timeout=extract_timeout)
        except Exception as exc:
            report.issues.append(DoctorIssue(
                check="spec_extraction",
                severity="error",
                detail=str(exc)[:200],
            ))
            return report

        field_map = build_field_map(spec)
        triggers = spec.get("triggers", [])
        query_triggers = [
            t for t in triggers
            if t.get("type") == "QUERY" and not str(t.get("id", "")).startswith("SYSTEM_")
        ]
        report.stats = _build_overview_stats(self._crf_path, spec, query_triggers)

        # ── check 1: duplicate trigger IDs ────────────────────────────────────
        id_counts: Counter[str] = Counter(str(t.get("id", "")) for t in triggers if t.get("id"))
        id_locations = _trigger_id_locations(self._crf_path)
        for tid, count in id_counts.items():
            if count > 1:
                locations = id_locations.get(tid, [])
                detail = f"appears {count} times"
                if locations:
                    detail += "; " + ", ".join(locations)
                report.issues.append(DoctorIssue(
                    check="duplicate_trigger_ids",
                    severity="error",
                    trigger_id=tid,
                    detail=detail,
                ))

        # ── check 2: missing pageIds ──────────────────────────────────────────
        for t in query_triggers:
            if not t.get("pageId"):
                report.issues.append(DoctorIssue(
                    check="missing_page_ids",
                    severity="warning",
                    trigger_id=str(t.get("id", "")),
                    detail="pageId is empty",
                ))

        # ── check 3: unresolved itemIds in conditionals ───────────────────────
        for t in query_triggers:
            cond = t.get("conditional")
            if cond is None:
                continue
            page_id = t.get("pageId", "")
            unresolved = _find_unresolved_items(cond, page_id, field_map)
            for item_id in unresolved:
                report.issues.append(DoctorIssue(
                    check="unresolved_item_ids",
                    severity="warning",
                    trigger_id=str(t.get("id", "")),
                    page_id=page_id,
                    item_id=item_id,
                    detail=f"itemId not found in field_map",
                ))

        # ── check 4: unparseable triggers ─────────────────────────────────────
        for t in query_triggers:
            cond = t.get("conditional")
            if cond and not can_parse(cond):
                report.issues.append(DoctorIssue(
                    check="unparseable_triggers",
                    severity="info",
                    trigger_id=str(t.get("id", "")),
                    page_id=t.get("pageId", ""),
                    detail="can_parse() returned False - manual case needed",
                ))

        # ── check 5: dynamic context ──────────────────────────────────────────
        import json as _json
        for t in query_triggers:
            cond_str = _json.dumps(t.get("conditional") or {})
            if _DYNAMIC_HINT.search(cond_str):
                report.issues.append(DoctorIssue(
                    check="dynamic_context",
                    severity="info",
                    trigger_id=str(t.get("id", "")),
                    page_id=t.get("pageId", ""),
                    detail="conditional references dynamic visitId/EACH/SIBLING",
                ))

        # ── check 6: override JSON schema ─────────────────────────────────────
        ov = StudyOverrides(self._study_id, self._overrides_dir)
        if ov._path.exists():
            try:
                ov.load()
                errors = ov.validate()
                for err in errors:
                    report.issues.append(DoctorIssue(
                        check="override_schema",
                        severity="error",
                        detail=err,
                    ))
            except Exception as exc:
                report.issues.append(DoctorIssue(
                    check="override_schema",
                    severity="error",
                    detail=f"Failed to parse override JSON: {exc}",
                ))

        return report


# ── helpers ───────────────────────────────────────────────────────────────────

def _build_overview_stats(crf_path: Path, spec: dict, query_triggers: list[dict]) -> dict[str, int]:
    """Build high-level CRF source/spec counts for doctor output."""
    return {
        "page_ts_files": _count_page_ts_files(crf_path),
        "trigger_ts_files": _count_trigger_ts_files(crf_path),
        "availability_items": len(collect_availability_items(spec)),
    }


def _count_page_ts_files(crf_path: Path) -> int:
    pages_dir = crf_path / "pages"
    return len(list(pages_dir.glob("*.ts"))) if pages_dir.exists() else 0


def _count_trigger_ts_files(crf_path: Path) -> int:
    count = 1 if (crf_path / "trigger.ts").exists() else 0
    triggers_dir = crf_path / "triggers"
    if triggers_dir.exists():
        count += len(list(triggers_dir.glob("*.ts")))
    return count


def _collect_item_refs(node: Any) -> list[str]:
    """Recursively collect all itemId references from a conditional node."""
    if not isinstance(node, dict):
        return []
    refs: list[str] = []
    if "expr" in node:
        for child in node["expr"]:
            refs.extend(_collect_item_refs(child))
        return refs
    for side_key in ("left", "right"):
        side = node.get(side_key)
        if isinstance(side, dict):
            # itemId can be a string or a list of dicts
            raw_id = side.get("itemId")
            if isinstance(raw_id, str) and raw_id:
                refs.append(raw_id)
            elif isinstance(raw_id, list):
                for entry in raw_id:
                    if isinstance(entry, dict):
                        entry_id = entry.get("itemId") or entry.get("id")
                        if isinstance(entry_id, str) and entry_id:
                            refs.append(entry_id)
            ref_id = side.get("id")
            if isinstance(ref_id, str) and ref_id:
                refs.append(ref_id)
            elif isinstance(ref_id, list) and len(ref_id) >= 2:
                item_candidate = ref_id[-2]
                if isinstance(item_candidate, str) and item_candidate:
                    refs.append(item_candidate)
            refs.extend(_collect_item_refs(side))
    return refs


def _trigger_id_locations(crf_path: Path) -> dict[str, list[str]]:
    """Return ``{triggerId: ["relative/path.ts:line", ...]}`` for active id lines."""
    roots = []
    trigger_file = crf_path / "trigger.ts"
    if trigger_file.exists():
        roots.append(trigger_file)
    trigger_dir = crf_path / "triggers"
    if trigger_dir.exists():
        roots.extend(sorted(trigger_dir.glob("*.ts")))

    locations: dict[str, list[str]] = {}
    pattern = re.compile(r'\bid\s*:\s*["\']([^"\']+)["\']')
    for file_path in roots:
        try:
            lines = file_path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
        for line_no, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped.startswith("//") or stripped.startswith("*"):
                continue
            match = pattern.search(line)
            if not match:
                continue
            trigger_id = match.group(1)
            rel = file_path.relative_to(crf_path).as_posix()
            locations.setdefault(trigger_id, []).append(f"{rel}:{line_no}")
    return locations


def _find_unresolved_items(
    cond: dict,
    page_id: str,
    field_map: dict[str, Any],
) -> list[str]:
    """Return itemIds referenced in *cond* that are absent from *field_map*."""
    refs = _collect_item_refs(cond)
    unresolved: list[str] = []
    for item_id in refs:
        full_key = f"{page_id}.{item_id}"
        if full_key not in field_map and item_id not in field_map:
            unresolved.append(item_id)
    return list(dict.fromkeys(unresolved))  # deduplicate, preserve order


def run_doctor(
    crf_path: str | Path,
    *,
    overrides_dir: str | Path | None = None,
    extract_timeout: int = 90,
) -> DoctorReport:
    """Convenience function: create a :class:`CRFDoctor` and run it."""
    return CRFDoctor(crf_path, overrides_dir=overrides_dir).run(
        extract_timeout=extract_timeout
    )

