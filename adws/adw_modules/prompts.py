"""Рендеринг prompt: загрузить системные/пользовательские ссылки из конфигурации, заменить {{placeholders}}."""

from __future__ import annotations

from pathlib import Path


def render(template_path: str | Path, variables: dict[str, str]) -> str:
    text = Path(template_path).read_text()
    for key, value in variables.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def save(directory: str | Path, name: str, content: str) -> Path:
    """Сохранить точный отправленный prompt до выполнения — копию для аудита."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(content)
    return path
