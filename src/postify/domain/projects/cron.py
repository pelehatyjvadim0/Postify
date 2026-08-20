from __future__ import annotations

from datetime import datetime


def normalize_cron(expression: str) -> str:
    if not isinstance(expression, str):
        raise ValueError("Cron должен быть строкой")
    fields = expression.split()
    if len(fields) != 5:
        raise ValueError("Cron должен содержать 5 полей")
    for field, minimum, maximum in zip(
        fields,
        (0, 0, 1, 1, 0),
        (59, 23, 31, 12, 7),
        strict=True,
    ):
        for part in field.split(","):
            _validate_part(part, minimum, maximum)
    return " ".join(fields)


def cron_matches(expression: str, local: datetime) -> bool:
    minute, hour, day, month, weekday = normalize_cron(expression).split()
    cron_weekday = (local.weekday() + 1) % 7
    if not all(
        (
            _field_matches(minute, local.minute, 0, 59),
            _field_matches(hour, local.hour, 0, 23),
            _field_matches(month, local.month, 1, 12),
        )
    ):
        return False
    day_matches = _field_matches(day, local.day, 1, 31)
    weekday_matches = _field_matches(
        weekday, cron_weekday, 0, 7, sunday=True
    )
    if day == "*":
        return weekday_matches
    if weekday == "*":
        return day_matches
    return day_matches or weekday_matches


def _validate_part(part: str, minimum: int, maximum: int) -> None:
    base, separator, step_text = part.partition("/")
    if separator:
        if "/" in step_text or not step_text.isdigit() or int(step_text) <= 0:
            raise ValueError("Некорректный шаг cron")
    if base == "*":
        return
    if "-" in base:
        pieces = base.split("-")
        if len(pieces) != 2 or not all(piece.isdigit() for piece in pieces):
            raise ValueError("Некорректный диапазон cron")
        start, end = (int(piece) for piece in pieces)
    elif base.isdigit():
        start = end = int(base)
    else:
        raise ValueError("Некорректное значение cron")
    if not minimum <= start <= end <= maximum:
        raise ValueError("Значение cron вне допустимого диапазона")


def _field_matches(
    field: str,
    value: int,
    minimum: int,
    maximum: int,
    *,
    sunday: bool = False,
) -> bool:
    return any(
        _part_matches(part, value, minimum, maximum, sunday=sunday)
        for part in field.split(",")
    )


def _part_matches(
    part: str,
    value: int,
    minimum: int,
    maximum: int,
    *,
    sunday: bool,
) -> bool:
    base, separator, step_text = part.partition("/")
    step = int(step_text) if separator else 1
    if base == "*":
        start, end = minimum, maximum
    elif "-" in base:
        start, end = (int(piece) for piece in base.split("-"))
    else:
        start = end = int(base)
    comparable = 7 if sunday and value == 0 and start == 7 else value
    return start <= comparable <= end and (comparable - start) % step == 0
