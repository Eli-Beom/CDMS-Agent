"""Tests for overrides.py: load/save/apply/validate."""

import json
import tempfile
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from cdm_agent_client.crf.quality.overrides import (
    StudyOverrides,
    OverrideValidationError,
    _validate_errors,
    load_overrides,
)


@pytest.fixture
def tmp_dir(tmp_path):
    return tmp_path


def _make_overrides(tmp_dir, study_id="TEST_STUDY", data: dict | None = None) -> StudyOverrides:
    ov = StudyOverrides(study_id, tmp_dir)
    if data is not None:
        (tmp_dir / f"{study_id}.json").write_text(
            json.dumps(data), encoding="utf-8"
        )
    return ov


# ── load/save ─────────────────────────────────────────────────────────────────

class TestLoadSave:
    def test_missing_file_returns_empty(self, tmp_dir):
        ov = _make_overrides(tmp_dir)
        ov.load()
        assert ov.as_dict() == {"studyId": "TEST_STUDY"}

    def test_load_existing_file(self, tmp_dir):
        data = {"studyId": "TEST_STUDY", "labelAliases": {"BRTHDAT": ["Birth Date"]}}
        ov = _make_overrides(tmp_dir, data=data)
        ov.load()
        assert ov.label_aliases("BRTHDAT") == ["Birth Date"]

    def test_save_creates_file(self, tmp_dir):
        ov = _make_overrides(tmp_dir)
        ov.load()
        ov.add_label_alias("SEXCD", "성별")
        ov.save()
        assert (tmp_dir / "TEST_STUDY.json").exists()
        saved = json.loads((tmp_dir / "TEST_STUDY.json").read_text(encoding="utf-8"))
        assert saved["labelAliases"]["SEXCD"] == ["성별"]

    def test_save_creates_parent_dirs(self, tmp_path):
        nested = tmp_path / "a" / "b"
        ov = StudyOverrides("S", nested)
        ov.load()
        ov.add_label_alias("X", "y")
        ov.save()
        assert (nested / "S.json").exists()


# ── label aliases ─────────────────────────────────────────────────────────────

class TestLabelAliases:
    def test_add_label_alias_idempotent(self, tmp_dir):
        ov = _make_overrides(tmp_dir)
        ov.load()
        ov.add_label_alias("X", "foo")
        ov.add_label_alias("X", "foo")  # duplicate
        assert ov.label_aliases("X") == ["foo"]

    def test_multiple_aliases(self, tmp_dir):
        ov = _make_overrides(tmp_dir)
        ov.load()
        ov.add_label_alias("X", "a")
        ov.add_label_alias("X", "b")
        assert ov.label_aliases("X") == ["a", "b"]

    def test_missing_item_returns_empty(self, tmp_dir):
        ov = _make_overrides(tmp_dir)
        ov.load()
        assert ov.label_aliases("NONEXISTENT") == []


# ── option aliases ─────────────────────────────────────────────────────────────

class TestOptionAliases:
    def test_add_option_alias(self, tmp_dir):
        ov = _make_overrides(tmp_dir)
        ov.load()
        ov.add_option_alias("SEX", "Male", "남성")
        assert ov.option_aliases("SEX", "Male") == ["남성"]

    def test_resolve_option(self, tmp_dir):
        ov = _make_overrides(tmp_dir)
        ov.load()
        ov.add_option_alias("SEX", "Male", "남")
        assert ov.resolve_option("SEX", "남") == "Male"
        assert ov.resolve_option("SEX", "Male") == "Male"
        assert ov.resolve_option("SEX", "unknown") is None


# ── preconditions ─────────────────────────────────────────────────────────────

class TestPreconditions:
    def test_add_precondition(self, tmp_dir):
        ov = _make_overrides(tmp_dir)
        ov.load()
        step = {"itemId": "DM.SEX", "value": "1", "note": "test"}
        ov.add_precondition("DM.BFYN", step)
        assert ov.preconditions("DM.BFYN") == [step]

    def test_precondition_idempotent(self, tmp_dir):
        ov = _make_overrides(tmp_dir)
        ov.load()
        step = {"itemId": "DM.SEX", "value": "1"}
        ov.add_precondition("DM.BFYN", step)
        ov.add_precondition("DM.BFYN", step)
        assert len(ov.preconditions("DM.BFYN")) == 1


# ── trigger overrides ─────────────────────────────────────────────────────────

class TestTriggerOverrides:
    def test_set_and_get(self, tmp_dir):
        ov = _make_overrides(tmp_dir)
        ov.load()
        ov.set_trigger_override("T_001", {"skip": True, "reason": "dynamic"})
        assert ov.trigger_override("T_001") == {"skip": True, "reason": "dynamic"}
        assert ov.trigger_override("MISSING") is None


# ── manual cases ──────────────────────────────────────────────────────────────

class TestManualCases:
    def test_add_manual_case(self, tmp_dir):
        ov = _make_overrides(tmp_dir)
        ov.load()
        case = {"triggerId": "T_001", "reason": "repeated table", "steps": []}
        ov.add_manual_case(case)
        assert ov.manual_case("T_001") == case

    def test_add_manual_case_idempotent(self, tmp_dir):
        ov = _make_overrides(tmp_dir)
        ov.load()
        case = {"triggerId": "T_001", "reason": "r", "steps": []}
        ov.add_manual_case(case)
        ov.add_manual_case(case)
        assert len(ov.manual_cases()) == 1


# ── validation ─────────────────────────────────────────────────────────────────

class TestValidation:
    def test_valid_empty(self):
        assert _validate_errors({"studyId": "X"}) == []

    def test_unknown_keys(self):
        errs = _validate_errors({"unknownField": 1})
        assert any("Unknown keys" in e for e in errs)

    def test_bad_label_aliases_type(self):
        errs = _validate_errors({"labelAliases": "not-a-dict"})
        assert any("labelAliases" in e for e in errs)

    def test_bad_label_alias_value_type(self):
        errs = _validate_errors({"labelAliases": {"X": "string-not-list"}})
        assert any("must be a list" in e for e in errs)

    def test_bad_precondition_missing_value(self):
        errs = _validate_errors({
            "preconditions": {"DM.X": [{"itemId": "Y"}]}  # missing "value"
        })
        assert any("value" in e for e in errs)

    def test_bad_manual_case_missing_triggerId(self):
        errs = _validate_errors({"manualCases": [{"reason": "x"}]})
        assert any("triggerId" in e for e in errs)

    def test_raises_on_load_with_bad_data(self, tmp_dir):
        (tmp_dir / "BAD.json").write_text(
            json.dumps({"unknownKey": 123}), encoding="utf-8"
        )
        ov = StudyOverrides("BAD", tmp_dir)
        with pytest.raises(OverrideValidationError):
            ov.load()
