"""Решение о статусе сгенерированного поста перед публикацией."""

from __future__ import annotations

from typing import Literal


PublicationStatus = Literal["needs_review", "approved"]


def generated_post_status(
    publication_mode: str, *, validation_passed: bool
) -> PublicationStatus:
    """Фиксирует решение в момент генерации, не читая режим позже.

    В ``review`` любой пост ждёт редактора. В ``auto`` только полностью
    прошедший проверки пост сразу становится ``approved``. Поэтому последующая
    смена режима проекта не отправит старые посты, оставленные на ревью.
    """
    if publication_mode not in {"review", "auto"}:
        raise ValueError("Неизвестный режим публикации")
    if type(validation_passed) is not bool:
        raise ValueError("Результат проверки должен быть boolean")
    if publication_mode == "auto" and validation_passed:
        return "approved"
    return "needs_review"
