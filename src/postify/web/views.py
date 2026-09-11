"""Помощники представления, общие для фасадов веб-слоя.

Два правила контракта, которые нельзя повторять в каждом фасаде по-разному:
время наружу отдаётся в таймзоне проекта (раздел 1), а ``jsonb`` из базы
приходит обёрнутым и в таком виде не сериализуется.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo


def at(value: datetime | None, zone: ZoneInfo) -> datetime | None:
    """База хранит время в UTC, контракт отдаёт его в таймзоне проекта."""
    return None if value is None else value.astimezone(zone)


def plain(value: object) -> dict[str, Any]:
    """Снимает MappingProxyType, который не переживает сериализацию JSON."""
    if isinstance(value, Mapping):
        return {str(key): plain_value(item) for key, item in value.items()}
    return {}


def plain_value(value: object) -> object:
    if isinstance(value, Mapping):
        return plain(value)
    if isinstance(value, (tuple, list)):
        return [plain_value(item) for item in value]
    return value


def checks_summary(report: dict[str, Any] | None) -> dict[str, Any]:
    """Сводит последний отчёт к счётчикам карточки плана или поста."""
    if not report:
        return {"passed": False, "blocking": 0, "warnings": 0}
    blocking = 0
    warnings = 0
    failed_verdicts = {"unsupported", "contradicted", "weak", "mismatch"}
    for layer in report.get("layers", ()):
        for item in layer.get("items", ()):
            failed = item.get("passed") is False or item.get("verdict") in failed_verdicts
            if not failed:
                continue
            if item.get("severity") == "warn":
                warnings += 1
            else:
                blocking += 1
    return {
        "passed": bool(report.get("passed")),
        "blocking": blocking,
        "warnings": warnings,
    }
