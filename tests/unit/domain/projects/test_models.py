from postify.domain.projects.models import ProjectConfiguration


def configuration(**overrides) -> ProjectConfiguration:
    values = {
        "media_max_bytes": 10_000_000,
        "analysis_timeout_seconds": 60,
        "analysis_batch_size": 12,
        "analysis_model": "gpt-5.6-terra",
        "analysis_reasoning_effort": "medium",
        "source_language": "ar",
        "tone": "Нейтральный",
    }
    values.update(overrides)
    return ProjectConfiguration(**values)
