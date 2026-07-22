from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from ..models import FieldDef


def extract_spec(study: str, maven_root: str | Path, timeout: int = 90) -> dict:
    """Execute ts-node extract_crf_spec.ts and return the parsed JSON spec.

    Returns:
        {"pages": {pageId: [field, ...]}, "triggers": [...]}
    """
    # Windows에서 npx는 npx.cmd로 등록되어 있어 shell=True 또는 .cmd 확장자 필요
    npx = "npx.cmd" if sys.platform == "win32" else "npx"
    maven_root = Path(maven_root)
    script = maven_root / "scripts" / "extract_crf_spec.ts"
    if script.exists():
        command = [npx, "ts-node", "--project", "tsconfig.json", "scripts/extract_crf_spec.ts", study]
    else:
        command = [
            npx,
            "ts-node",
            "--transpile-only",
            "-r",
            "tsconfig-paths/register",
            "--project",
            "tsconfig.json",
            "-e",
            _inline_extract_script(),
            study,
        ]

    result = subprocess.run(
        command,
        cwd=maven_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(f"extract_crf_spec failed:\n{result.stderr[:500]}")
    stdout = result.stdout.lstrip()
    json_start = stdout.find("{")
    if json_start > 0:
        stdout = stdout[json_start:]
    data = json.loads(stdout)
    data["visitMap"] = _coerce_visit_map(data.get("visitMap") or data.get("visit_map") or {})
    return data


def _coerce_visit_map(value: object) -> dict[int, str]:
    """Normalize extracted visit mapping to ``{visitCode: visitId}``."""
    if not isinstance(value, dict):
        return {}
    out: dict[int, str] = {}
    for key, val in value.items():
        if val is None:
            continue
        try:
            visit_code = int(key)
        except (TypeError, ValueError):
            continue
        out[visit_code] = str(val)
    return out


def _inline_extract_script() -> str:
    script = r"""
const study = process.argv[process.argv.length - 1];
const mod = require(process.cwd() + "/src/crfs/" + study + "/index.ts");
const spec = mod[Object.keys(mod)[0]];

function scalar(value) {
  if (typeof value === "bigint") return value.toString();
  return value;
}

function labelText(label) {
  if (typeof label === "string") return label;
  if (label && typeof label === "object") {
    return label.text || label.en || label.ko || label.reserved || JSON.stringify(label);
  }
  return "";
}

function itemOptions(item) {
  const code = item.itemCode;
  if (!code) return [];
  const codes = Array.isArray(code.codes) ? code.codes : [];
  return codes.map((c) => ({
    uiVal: scalar(c.uiVal),
    dbVal: scalar(c.dbVal),
    calcVal: scalar(c.calcVal),
  }));
}

function flattenPage(pageId, page) {
  const out = [];
  function flattenItems(items, sectionId) {
    for (const item of items || []) {
      if (!item || typeof item !== "object") continue;
      if (item.id) {
        out.push({
          pageId,
          sectionId,
          itemId: item.id || "",
          label: labelText(item.label),
          type: item.type || "",
          layout: item.layout || null,
          options: itemOptions(item),
          visibility: item.visibility || null,
          availability: item.availability || null,
          disability: item.disability || null,
          format: item.format || null,
          calculate: item.calculate || null,
        });
      }
      if (Array.isArray(item.items)) flattenItems(item.items, sectionId);
      if (item.children && Array.isArray(item.children.items)) {
        flattenItems(item.children.items, sectionId);
      }
      if (Array.isArray(item.sections)) {
        for (const childSection of item.sections) {
          flattenItems(childSection.items || [], childSection.id || sectionId);
        }
      }
    }
  }
  for (const section of page.sections || []) {
    flattenItems(section.items || [], section.id || "");
  }
  return out;
}

function refPageId(ref) {
  if (!ref || typeof ref !== "object") return "";
  if (Array.isArray(ref.id) && ref.id.length > 3) return ref.id[3] || "";
  return ref.crfPageId || ref.pageId || "";
}

function firstConditionalPageId(node) {
  if (!node || typeof node !== "object") return "";
  if (Array.isArray(node.expr)) {
    for (const child of node.expr) {
      const found = firstConditionalPageId(child);
      if (found) return found;
    }
  }
  return refPageId(node.left) || refPageId(node.right);
}

function issuePageId(issue) {
  const itemIds = issue && issue.itemId;
  if (Array.isArray(itemIds)) {
    for (const item of itemIds) {
      const found = refPageId(item);
      if (found) return found;
    }
  }
  return "";
}

function extractVisitMap(folders) {
  const out = {};

  function walk(node) {
    if (!node || typeof node !== "object") return;
    if (Array.isArray(node)) {
      for (const child of node) walk(child);
      return;
    }

    const code = node.code ?? node.visitCode ?? node.no ?? null;
    const id = node.id ?? node.visitId ?? node.name ?? null;
    if (code !== null && id !== null) out[String(code)] = String(id);

    for (const key of ["visits", "children", "folders"]) {
      if (Array.isArray(node[key])) walk(node[key]);
    }
  }

  walk(folders || []);
  return out;
}

const pages = {};
for (const [pageId, page] of Object.entries(spec.pages || {})) {
  pages[pageId] = flattenPage(pageId, page);
}

const triggers = (spec.triggers || []).map((trigger) => ({
  id: trigger.id || "",
  note: trigger.note || "",
  type: trigger.type || "",
  pageId: trigger.pageId || trigger.crfPageId || issuePageId(trigger.issue) || firstConditionalPageId(trigger.conditional) || "",
  issue: trigger.issue || null,
  conditional: trigger.conditional || null,
}));

const visitMap = extractVisitMap(spec.folders || spec.folder || spec.visitFolders || []);

console.log(JSON.stringify({ pages, triggers, visitMap }));
"""
    return " ".join(line.strip() for line in script.splitlines() if line.strip())


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
                disability=f.get("disability"),
                format=f.get("format"),
                calculate=f.get("calculate"),
            )
            field_map[f"{page_id}.{f['itemId']}"] = fd
            field_map.setdefault(f["itemId"], fd)
    return field_map
