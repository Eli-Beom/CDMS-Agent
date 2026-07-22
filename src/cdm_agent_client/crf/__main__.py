"""Entry point for ``python -m cdm_agent_client.crf`` and ``cdms-crf``.

Commands
--------
gen-notebook   Generate a Jupyter validation notebook.
doctor         Static analysis of a CRF spec.

Usage examples::

    cdms-crf doctor "C:/Users/SunbeomGwon/maven-crfs/src/crfs/20260325_PRACTICE_GSB"
    cdms-crf gen-notebook
"""

from __future__ import annotations

import sys
from collections.abc import Callable


def _cmd_doctor(args: list[str]) -> int:
    """cdms-crf doctor <crf_path> [--timeout N] [--overrides-dir <path>]"""
    if not args or args[0].startswith("-"):
        print("Usage: cdms-crf doctor <crf_path> [--timeout <seconds>] [--overrides-dir <path>]")
        return 1

    crf_path = args[0]
    timeout = 90
    overrides_dir = None
    remaining = args[1:]
    while remaining:
        if remaining[0] == "--timeout" and len(remaining) > 1:
            try:
                timeout = int(remaining[1])
            except ValueError:
                print(f"Invalid timeout: {remaining[1]!r}")
                return 1
            remaining = remaining[2:]
        elif remaining[0] == "--overrides-dir" and len(remaining) > 1:
            overrides_dir = remaining[1]
            remaining = remaining[2:]
        else:
            remaining = remaining[1:]

    from .quality.doctor import run_doctor

    try:
        report = run_doctor(crf_path, overrides_dir=overrides_dir, extract_timeout=timeout)
    except Exception as exc:
        print(f"[doctor] Error: {exc}")
        return 1

    report.print_report()
    return 0 if report.ok() else 1


def _cmd_gen_notebook(_args: list[str]) -> int:
    """Interactive notebook generation."""
    from .cli import main as notebook_main

    notebook_main()
    return 0


_COMMANDS: dict[str, Callable[[list[str]], int]] = {
    "doctor": _cmd_doctor,
    "gen-notebook": _cmd_gen_notebook,
    "gen_notebook": _cmd_gen_notebook,
    "notebook": _cmd_gen_notebook,
}


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]

    if not args or args[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0

    cmd_name = args[0]
    handler = _COMMANDS.get(cmd_name)
    if handler is None:
        print(f"Unknown command: {cmd_name!r}")
        print(f"Available commands: {', '.join(sorted(_COMMANDS))}")
        return 1

    return handler(args[1:])


if __name__ == "__main__":
    sys.exit(main())
