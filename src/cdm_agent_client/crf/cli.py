from __future__ import annotations

from pathlib import Path

from .notebook import BROWSER_ASSISTED, BROWSER_ASSISTED_COMBINED_DISCOVERY, STATIC, gen_notebook


def _prompt_path(label: str, *, default: Path | None = None, must_exist: bool = False) -> Path:
    while True:
        suffix = f" [{default}]" if default else ""
        value = input(f"{label}{suffix}: ").strip().strip('"')
        if not value and default is not None:
            path = default
        else:
            path = Path(value)

        if not str(path):
            print("값을 입력해 주세요.")
            continue
        if must_exist and not path.exists():
            print(f"경로를 찾을 수 없습니다: {path}")
            continue
        return path


def _prompt_optional(label: str) -> str | None:
    value = input(f"{label} (Enter=자동/전체): ").strip()
    return value or None


def _parse_page_ids(value: str | None) -> set[str] | None:
    if not value:
        return None
    page_ids = {part.strip() for part in value.split(",") if part.strip()}
    return page_ids or None


_VALID_MODES = {BROWSER_ASSISTED, BROWSER_ASSISTED_COMBINED_DISCOVERY, STATIC}
_MODE_HELP = (
    "browser-assisted (기본) | combined (query+availability 함께) | static (정적 생성)"
)


def _prompt_generation_mode() -> str:
    value = input(f"4. generation mode [{BROWSER_ASSISTED_COMBINED_DISCOVERY}]\n   {_MODE_HELP}\n   입력: ").strip()
    if not value:
        return BROWSER_ASSISTED_COMBINED_DISCOVERY
    normalized = value.lower().replace("_", "-")
    if normalized == "combined":
        return BROWSER_ASSISTED_COMBINED_DISCOVERY
    if normalized in _VALID_MODES:
        return normalized
    print(f"Unknown mode; using {BROWSER_ASSISTED_COMBINED_DISCOVERY!r}: {value}")
    return BROWSER_ASSISTED_COMBINED_DISCOVERY


def main() -> None:
    print("CDMS-Agent CRF notebook 생성")
    print("Enter만 누르면 기본값 또는 자동 추론을 사용합니다.\n")

    crf_path = _prompt_path(
        "1. CRF 과제 경로",
        must_exist=True,
    )
    default_output = crf_path / "CDMS-Agent_test.ipynb"
    output_path = _prompt_path(
        "2. 생성할 notebook 경로",
        default=default_output,
    )
    page_ids = _parse_page_ids(_prompt_optional("3. 특정 page만 생성할 경우 page id 입력, 예: DM 또는 DM,SV"))

    generation_mode = _prompt_generation_mode()

    result = gen_notebook(
        output_path=output_path,
        crf_path=crf_path,
        page_ids=page_ids,
        max_case_cells=200 if generation_mode != STATIC else 3,
        generation_mode=generation_mode,
    )

    print("\n생성 완료")
    print(f"notebook: {result}")


if __name__ == "__main__":
    main()
