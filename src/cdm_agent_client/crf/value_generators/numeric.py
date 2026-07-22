from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import FieldDef


def numeric_step(fd: "FieldDef | None") -> float:
    fmt = fd.format if fd else None
    if isinstance(fmt, dict):
        scale = fmt.get("scale")
        if isinstance(scale, int) and scale > 0:
            return 10 ** -scale
    return 1.0


def format_numeric_value(value: float, fd: "FieldDef | None" = None) -> str:
    fmt = fd.format if fd else None
    if isinstance(fmt, dict):
        scale = fmt.get("scale")
        if isinstance(scale, int) and scale > 0:
            return f"{value:.{scale}f}"
    return str(int(value)) if float(value).is_integer() else str(value)


def violation_value(op: str, threshold: float, fd: "FieldDef | None" = None) -> float:
    t = float(threshold)
    step = numeric_step(fd)
    if op == "<":
        return t - step
    if op == ">":
        return t + step
    if op == "<=":
        return t
    if op == ">=":
        return t
    if op == "!=":
        return t
    return t


def valid_value(op: str, threshold: float, fd: "FieldDef | None" = None) -> float:
    t = float(threshold)
    step = numeric_step(fd)
    if op in ("<", "<="):
        return t if op == "<" else t + step
    if op in (">", ">="):
        return t if op == ">" else t - step
    if op == "=":
        return t + step
    if op == "!=":
        return t
    return t
