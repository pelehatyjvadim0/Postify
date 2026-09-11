import pytest

from postify.domain.projects.models import ProjectConfiguration, ProjectRubric


def configuration(**overrides) -> ProjectConfiguration:
    values = {
        "media_max_bytes": 10_000_000,
        "analysis_timeout_seconds": 60,
        "analysis_model": "gpt-5.6-terra",
        "analysis_reasoning_effort": "medium",
        "tone": "Нейтральный",
    }
    values.update(overrides)
    return ProjectConfiguration(**values)


def test_configuration_rejects_non_positive_limits() -> None:
    with pytest.raises(ValueError, match="media_max_bytes"):
        configuration(media_max_bytes=0)


def test_rubric_requires_instructions_and_belongs_to_project() -> None:
    # Поломка: пустая инструкция уезжает в контекст генерации как валидная рубрика.
    with pytest.raises(ValueError, match="instructions"):
        ProjectRubric(1, 1, "Кейс", "   ", True)
    with pytest.raises(ValueError, match="project_id"):
        ProjectRubric(1, 0, "Кейс", "Разбор задачи клиента", True)


def test_rubric_normalises_whitespace() -> None:
    rubric = ProjectRubric(1, 1, "  Кейс  ", "Разбор\n  задачи", True)

    assert rubric.name == "Кейс"
    assert rubric.instructions == "Разбор задачи"
