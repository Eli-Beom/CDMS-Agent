"""Override JSON management for per-study CRF knowledge.

Only *human-approved* facts live here. Runtime browser state is handled by
the browser-assisted harness instead of being accumulated in this package.

Override file location (default)::

    <agent_root>/overrides/<studyId>.json

Schema (all fields optional)::

    {
        "studyId": "20260325_PRACTICE_GSB",
        "labelAliases": {
            "<itemId>": ["alias1", "alias2"]
        },
        "optionAliases": {
            "<itemId>": {
                "<canonicalOptionLabel>": ["alias1", "alias2"]
            }
        },
        "preconditions": {
            "<pageId.itemId>": [
                {"itemId": "<pageId.itemId>", "value": "<value>", "note": "..."}
            ]
        },
        "triggerOverrides": {
            "<triggerId>": {"skip": true, "reason": "..."}
        },
        "manualCases": [
            {
                "triggerId": "<triggerId>",
                "reason": "...",
                "steps": []
            }
        ]
    }
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_REQUIRED_KEYS: set[str] = set()
_ALLOWED_KEYS = {
    "studyId",
    "labelAliases",
    "optionAliases",
    "preconditions",
    "triggerOverrides",
    "manualCases",
}


class OverrideValidationError(ValueError):
    pass


def _default_overrides_dir() -> Path:
    """Return the default overrides/ directory relative to this package's root."""
    return Path(__file__).resolve().parents[3] / "overrides"


class StudyOverrides:
    """Load, query, and update the per-study JSON override file.

    Parameters
    ----------
    study_id:
        The study folder name (e.g. ``"20260325_PRACTICE_GSB"``).
    overrides_dir:
        Directory that contains ``<studyId>.json`` files.  Defaults to
        ``<agent_root>/overrides/``.
    """

    def __init__(
        self,
        study_id: str,
        overrides_dir: str | Path | None = None,
    ) -> None:
        self.study_id = study_id
        self._dir = Path(overrides_dir) if overrides_dir else _default_overrides_dir()
        self._path = self._dir / f"{study_id}.json"
        self._data: dict[str, Any] = {}
        self._loaded = False

    # ── lifecycle ──────────────────────────────────────────────────────────────

    def load(self) -> "StudyOverrides":
        """Read the override file.  Missing file → empty overrides (not an error)."""
        if self._path.exists():
            raw = self._path.read_text(encoding="utf-8")
            self._data = json.loads(raw)
            _validate(self._data)
        else:
            self._data = {"studyId": self.study_id}
        self._loaded = True
        return self

    def save(self) -> None:
        """Write back to disk, creating directories as needed."""
        self._require_loaded()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _require_loaded(self) -> None:
        if not self._loaded:
            self.load()

    # ── read helpers ───────────────────────────────────────────────────────────

    def label_aliases(self, item_id: str) -> list[str]:
        """Return alias labels for an itemId (empty list if none)."""
        self._require_loaded()
        return list(self._data.get("labelAliases", {}).get(item_id, []))

    def resolve_label(self, item_id: str, label: str) -> str:
        """Return the canonical label for *label*, falling back to *label* itself."""
        self._require_loaded()
        aliases = self._data.get("labelAliases", {})
        # Direct itemId lookup
        if item_id in aliases and label in aliases[item_id]:
            return label  # already canonical if the list contains it
        # Reverse lookup: value is an alias → return the label from field map
        for canonical, alias_list in aliases.items():
            if label in alias_list:
                return label  # alias matched; caller resolves via field_map
        return label

    def option_aliases(self, item_id: str, canonical_option: str) -> list[str]:
        """Return alias strings for a canonical option label."""
        self._require_loaded()
        return list(
            self._data.get("optionAliases", {})
            .get(item_id, {})
            .get(canonical_option, [])
        )

    def resolve_option(self, item_id: str, option_label: str) -> str | None:
        """Return the canonical option label that *option_label* maps to, or None."""
        self._require_loaded()
        for canonical, aliases in (
            self._data.get("optionAliases", {}).get(item_id, {}).items()
        ):
            if option_label == canonical or option_label in aliases:
                return canonical
        return None

    def preconditions(self, key: str) -> list[dict[str, Any]]:
        """Return precondition steps for a ``pageId.itemId`` key."""
        self._require_loaded()
        return list(self._data.get("preconditions", {}).get(key, []))

    def trigger_override(self, trigger_id: str) -> dict[str, Any] | None:
        """Return trigger-level override dict or None."""
        self._require_loaded()
        return self._data.get("triggerOverrides", {}).get(trigger_id)

    def manual_cases(self) -> list[dict[str, Any]]:
        """Return all manual case definitions."""
        self._require_loaded()
        return list(self._data.get("manualCases", []))

    def manual_case(self, trigger_id: str) -> dict[str, Any] | None:
        """Return the manual case for a trigger_id, or None."""
        for mc in self.manual_cases():
            if mc.get("triggerId") == trigger_id:
                return mc
        return None

    # ── write helpers ────────────────────────────────────────────────────────

    def add_label_alias(self, item_id: str, alias: str) -> None:
        """Add *alias* to the labelAliases list for *item_id* (idempotent)."""
        self._require_loaded()
        bucket = self._data.setdefault("labelAliases", {})
        aliases = bucket.setdefault(item_id, [])
        if alias not in aliases:
            aliases.append(alias)

    def add_option_alias(self, item_id: str, canonical: str, alias: str) -> None:
        """Add *alias* for a canonical option (idempotent)."""
        self._require_loaded()
        bucket = (
            self._data.setdefault("optionAliases", {})
            .setdefault(item_id, {})
        )
        aliases = bucket.setdefault(canonical, [])
        if alias not in aliases:
            aliases.append(alias)

    def add_precondition(self, key: str, step: dict[str, Any]) -> None:
        """Add a precondition step for *key* if not already present."""
        self._require_loaded()
        bucket = self._data.setdefault("preconditions", {}).setdefault(key, [])
        existing = {(s.get("itemId"), s.get("value")) for s in bucket}
        if (step.get("itemId"), step.get("value")) not in existing:
            bucket.append(step)

    def set_trigger_override(self, trigger_id: str, override: dict[str, Any]) -> None:
        """Upsert a trigger-level override entry."""
        self._require_loaded()
        self._data.setdefault("triggerOverrides", {})[trigger_id] = override

    def add_manual_case(self, case: dict[str, Any]) -> None:
        """Add a manual case definition (idempotent by triggerId)."""
        self._require_loaded()
        tid = case.get("triggerId")
        bucket = self._data.setdefault("manualCases", [])
        if tid and any(mc.get("triggerId") == tid for mc in bucket):
            return
        bucket.append(case)

    # ── schema validation ──────────────────────────────────────────────────────

    def validate(self) -> list[str]:
        """Return a list of validation errors (empty → valid)."""
        self._require_loaded()
        return _validate_errors(self._data)

    # ── convenience ────────────────────────────────────────────────────────────

    def as_dict(self) -> dict[str, Any]:
        self._require_loaded()
        return dict(self._data)

    def __repr__(self) -> str:
        return f"StudyOverrides(study_id={self.study_id!r}, path={self._path})"


# ── validation helpers ─────────────────────────────────────────────────────────

def _validate(data: dict[str, Any]) -> None:
    errors = _validate_errors(data)
    if errors:
        raise OverrideValidationError("\n".join(errors))


def _validate_errors(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["Root must be a JSON object"]

    unknown = set(data.keys()) - _ALLOWED_KEYS
    if unknown:
        errors.append(f"Unknown keys: {sorted(unknown)}")

    label_aliases = data.get("labelAliases", {})
    if not isinstance(label_aliases, dict):
        errors.append("labelAliases must be an object")
    else:
        for k, v in label_aliases.items():
            if not isinstance(v, list):
                errors.append(f"labelAliases[{k!r}] must be a list")

    option_aliases = data.get("optionAliases", {})
    if not isinstance(option_aliases, dict):
        errors.append("optionAliases must be an object")
    else:
        for k, v in option_aliases.items():
            if not isinstance(v, dict):
                errors.append(f"optionAliases[{k!r}] must be an object")

    preconditions = data.get("preconditions", {})
    if not isinstance(preconditions, dict):
        errors.append("preconditions must be an object")
    else:
        for k, v in preconditions.items():
            if not isinstance(v, list):
                errors.append(f"preconditions[{k!r}] must be a list")
            else:
                for i, step in enumerate(v):
                    if not isinstance(step, dict):
                        errors.append(f"preconditions[{k!r}][{i}] must be an object")
                    elif "itemId" not in step or "value" not in step:
                        errors.append(
                            f"preconditions[{k!r}][{i}] must have 'itemId' and 'value'"
                        )

    trigger_overrides = data.get("triggerOverrides", {})
    if not isinstance(trigger_overrides, dict):
        errors.append("triggerOverrides must be an object")

    manual_cases = data.get("manualCases", [])
    if not isinstance(manual_cases, list):
        errors.append("manualCases must be an array")
    else:
        for i, mc in enumerate(manual_cases):
            if not isinstance(mc, dict):
                errors.append(f"manualCases[{i}] must be an object")
            elif "triggerId" not in mc:
                errors.append(f"manualCases[{i}] must have 'triggerId'")

    return errors


def load_overrides(
    study_id: str,
    overrides_dir: str | Path | None = None,
) -> StudyOverrides:
    """Convenience factory: load (or create) the override file for *study_id*."""
    return StudyOverrides(study_id, overrides_dir).load()
