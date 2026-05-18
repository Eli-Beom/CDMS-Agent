from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from .models import FieldDef


def extract_spec(study: str, maven_root: str | Path, timeout: int = 90) -> dict:
    """Execute ts-node extract_crf_spec.ts and return the parsed JSON spec.

    Returns:
        {"pages": {pageId: [field, ...]}, "triggers": [...]}
    """
    # Windows에서 npx는 npx.cmd로 등록되어 있어 shell=True 또는 .cmd 확장자 필요
    npx = "npx.cmd" if sys.platform == "win32" else "npx"
    result = subprocess.run(
        [npx, "ts-node", "--project", "tsconfig.json",
         "scripts/extract_crf_spec.ts", study],
        cwd=Path(maven_root),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(f"extract_crf_spec failed:\n{result.stderr[:500]}")
    return json.loads(result.stdout)


def build_field_map(spec: dict) -> dict[str, FieldDef]:
    """Return two-key lookup: ``{pageId.itemId: FieldDef}`` and ``{itemId: FieldDef}``.

    The ``itemId``-only key is set to the first definition encountered, so
    cross-page lookups work when a page is not known.
    """
    field_map: dict[str, FieldDef] = {}
    for page_id, fields in spec["pages"].items():
        for f in fields:
            if not f.get("itemId"):
                continue
            fd = FieldDef(
                item_id=f["itemId"],
                label=f["label"],
                field_type=f["type"],
                layout=f.get("layout"),
                page_id=page_id,
                section_id=f["sectionId"],
                options=f.get("options", []),
                visibility=f.get("visibility"),
                availability=f.get("availability"),
            )
            field_map[f"{page_id}.{f['itemId']}"] = fd
            field_map.setdefault(f["itemId"], fd)
    return field_map
