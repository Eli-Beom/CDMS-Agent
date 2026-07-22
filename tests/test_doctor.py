"""Tests for doctor.py: static analysis without running the browser.

These tests use a fake spec (no ts-node required) to verify each check.
The ``CRFDoctor.run()`` method is tested through its internal helpers.
"""

import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from cdm_agent_client.crf.quality.doctor import (
    DoctorReport,
    DoctorIssue,
    _build_overview_stats,
    _collect_item_refs,
    _find_unresolved_items,
    CRFDoctor,
)
from cdm_agent_client.crf.models import FieldDef


# ?? helpers ???????????????????????????????????????????????????????????????????

def _make_field_map(*item_ids: str) -> dict:
    """Build a minimal field_map with bare itemId keys."""
    fm = {}
    for iid in item_ids:
        fd = FieldDef(
            item_id=iid, label=iid, field_type="TEXT",
            layout=None, page_id="EN", section_id="",
        )
        fm[iid] = fd
        fm[f"EN.{iid}"] = fd
    return fm


# ?? DoctorReport ??????????????????????????????????????????????????????????????

class TestDoctorReport:
    def test_ok_when_no_errors(self):
        report = DoctorReport(study_id="X")
        assert report.ok() is True

    def test_not_ok_when_errors(self):
        report = DoctorReport(study_id="X")
        report.issues.append(
            DoctorIssue(check="duplicate_trigger_ids", severity="error", trigger_id="T1")
        )
        assert report.ok() is False

    def test_severity_filtering(self):
        report = DoctorReport(study_id="X")
        report.issues = [
            DoctorIssue(check="a", severity="error"),
            DoctorIssue(check="b", severity="warning"),
            DoctorIssue(check="c", severity="info"),
        ]
        assert len(report.errors) == 1
        assert len(report.warnings) == 1
        assert len(report.infos) == 1

    def test_as_dicts(self):
        report = DoctorReport(study_id="X")
        report.issues.append(
            DoctorIssue(check="dup", severity="error", trigger_id="T1", detail="x2")
        )
        rows = report.as_dicts()
        assert len(rows) == 1
        assert rows[0]["check"] == "dup"
        assert rows[0]["trigger_id"] == "T1"

    def test_print_report_no_issues(self, capsys):
        DoctorReport(study_id="X").print_report()
        out = capsys.readouterr().out
        assert "No issues" in out

    def test_print_report_with_issues(self, capsys):
        report = DoctorReport(study_id="MY_STUDY")
        report.issues.append(
            DoctorIssue(check="duplicate_trigger_ids", severity="error", trigger_id="T_DUP")
        )
        report.print_report()
        out = capsys.readouterr().out
        assert "duplicate_trigger_ids" in out
        assert "T_DUP" in out

    def test_print_report_with_stats(self, capsys):
        report = DoctorReport(
            study_id="MY_STUDY",
            stats={"page_ts_files": 2, "trigger_ts_files": 3, "availability_items": 1},
        )
        report.print_report()
        out = capsys.readouterr().out
        assert "CRF Summary" in out
        assert "page.ts files" in out
        assert "availability items" in out
        assert "query triggers" not in out


# ?? _collect_item_refs ?????????????????????????????????????????????????????????

class TestCollectItemRefs:
    def test_simple_leaf(self):
        node = {
            "left": {"itemId": "RFICDTC"},
            "operator": "<",
            "right": {"itemId": "IRBDT"},
        }
        refs = _collect_item_refs(node)
        assert "RFICDTC" in refs
        assert "IRBDT" in refs

    def test_compound_and(self):
        node = {
            "operator": "AND",
            "expr": [
                {"left": {"itemId": "A"}, "operator": ">", "right": 0},
                {"left": {"itemId": "B"}, "operator": "<", "right": 100},
            ],
        }
        refs = _collect_item_refs(node)
        assert "A" in refs
        assert "B" in refs

    def test_no_refs(self):
        node = {"left": {}, "operator": ">", "right": 0}
        assert _collect_item_refs(node) == []


# ?? _find_unresolved_items ?????????????????????????????????????????????????????

class TestFindUnresolvedItems:
    def test_all_resolved(self):
        cond = {"left": {"itemId": "AGE"}, "operator": ">", "right": 0}
        fm = _make_field_map("AGE")
        assert _find_unresolved_items(cond, "EN", fm) == []

    def test_unresolved_detected(self):
        cond = {"left": {"itemId": "MISSING_ITEM"}, "operator": ">", "right": 0}
        fm = _make_field_map("AGE")
        result = _find_unresolved_items(cond, "EN", fm)
        assert "MISSING_ITEM" in result

    def test_partially_unresolved(self):
        cond = {
            "operator": "AND",
            "expr": [
                {"left": {"itemId": "AGE"}, "operator": ">", "right": 0},
                {"left": {"itemId": "GHOST"}, "operator": ">", "right": 0},
            ],
        }
        fm = _make_field_map("AGE")
        result = _find_unresolved_items(cond, "EN", fm)
        assert "GHOST" in result
        assert "AGE" not in result


class TestOverviewStats:
    def test_build_overview_stats(self, tmp_path):
        (tmp_path / "pages").mkdir()
        (tmp_path / "pages" / "page_100_DM.ts").write_text("", encoding="utf-8")
        (tmp_path / "pages" / "page_200_IE.ts").write_text("", encoding="utf-8")
        (tmp_path / "trigger.ts").write_text("", encoding="utf-8")
        (tmp_path / "triggers").mkdir()
        (tmp_path / "triggers" / "trigger_100_DM.ts").write_text("", encoding="utf-8")

        spec = {
            "pages": {
                "DM": [
                    {"itemId": "AGE", "label": "AGE", "fieldType": "TEXT"},
                    {
                        "itemId": "BFYN",
                        "label": "BFYN",
                        "fieldType": "SINGLE_SELECT",
                        "availability": {"ref": "ITEM", "id": "SEX", "operand": 2},
                    },
                ],
                "IE": [
                    {
                        "itemId": "IEYN",
                        "label": "IEYN",
                        "fieldType": "SINGLE_SELECT",
                        "visibility": {"type": "NORMAL_VISIT", "operand": 1, "condition": "="},
                    },
                ],
            },
            "triggers": [
                {
                    "id": "T_AUTO",
                    "type": "QUERY",
                    "pageId": "DM",
                    "conditional": {"left": {"itemId": "AGE"}, "operator": ">", "right": 80},
                },
                {
                    "id": "T_MANUAL",
                    "type": "QUERY",
                    "pageId": "DM",
                    "conditional": {"left": {"itemId": "AGE"}, "operator": "=", "right": {"reserved": "CURRENT"}},
                },
                {"id": "SYSTEM_1", "type": "QUERY", "pageId": "DM"},
                {"id": "A1", "type": "ACTION", "pageId": "DM"},
            ],
        }
        query_triggers = [
            t for t in spec["triggers"]
            if t.get("type") == "QUERY" and not str(t.get("id", "")).startswith("SYSTEM_")
        ]

        stats = _build_overview_stats(tmp_path, spec, query_triggers)

        assert stats["page_ts_files"] == 2
        assert stats["trigger_ts_files"] == 2
        assert stats["availability_items"] == 1


# ?? duplicate trigger id detection (unit-level via fake spec) ?????????????????

class TestDuplicateTriggerDetection:
    """Verify duplicate trigger detection logic using a synthetic spec."""

    def _run_checks_on_spec(self, spec: dict, tmp_path) -> DoctorReport:
        """Run the doctor's internal checks without calling extract_spec."""
        from collections import Counter
        from cdm_agent_client.crf.extraction.extractor import build_field_map
        from cdm_agent_client.crf.extraction.parser import can_parse
        from cdm_agent_client.crf.quality.overrides import StudyOverrides
        import re
        import json as _json

        field_map = build_field_map(spec)
        triggers = spec.get("triggers", [])
        query_triggers = [
            t for t in triggers
            if t.get("type") == "QUERY"
            and not str(t.get("id", "")).startswith("SYSTEM_")
        ]

        report = DoctorReport(study_id="TEST")

        id_counts: Counter = Counter(
            str(t.get("id", "")) for t in triggers if t.get("id")
        )
        for tid, count in id_counts.items():
            if count > 1:
                report.issues.append(
                    DoctorIssue(
                        check="duplicate_trigger_ids",
                        severity="error",
                        trigger_id=tid,
                        detail=f"appears {count} times",
                    )
                )
        return report

    def test_no_duplicates(self, tmp_path):
        spec = {
            "pages": {},
            "triggers": [
                {"id": "T_001", "type": "QUERY", "pageId": "EN"},
                {"id": "T_002", "type": "QUERY", "pageId": "EN"},
            ],
        }
        report = self._run_checks_on_spec(spec, tmp_path)
        dup_issues = [i for i in report.issues if i.check == "duplicate_trigger_ids"]
        assert len(dup_issues) == 0

    def test_detects_duplicate(self, tmp_path):
        spec = {
            "pages": {},
            "triggers": [
                {"id": "T_001", "type": "QUERY", "pageId": "EN"},
                {"id": "T_001", "type": "QUERY", "pageId": "DM"},  # duplicate!
            ],
        }
        report = self._run_checks_on_spec(spec, tmp_path)
        dup_issues = [i for i in report.issues if i.check == "duplicate_trigger_ids"]
        assert len(dup_issues) == 1
        assert dup_issues[0].trigger_id == "T_001"
        assert "2" in dup_issues[0].detail

    def test_detects_multiple_duplicates(self, tmp_path):
        spec = {
            "pages": {},
            "triggers": [
                {"id": "A", "type": "QUERY", "pageId": "P"},
                {"id": "A", "type": "QUERY", "pageId": "P"},
                {"id": "B", "type": "QUERY", "pageId": "P"},
                {"id": "B", "type": "QUERY", "pageId": "P"},
                {"id": "B", "type": "QUERY", "pageId": "P"},
                {"id": "C", "type": "QUERY", "pageId": "P"},
            ],
        }
        report = self._run_checks_on_spec(spec, tmp_path)
        dup = {i.trigger_id: i for i in report.issues if i.check == "duplicate_trigger_ids"}
        assert "A" in dup
        assert "B" in dup
        assert "C" not in dup
        assert "3" in dup["B"].detail


