from types import SimpleNamespace


def settings():
    return SimpleNamespace(
        content_batch_size=12,
        content_media_max_bytes=10_000_000,
        content_analysis_timeout_seconds=60,
        content_analyzer="codex",
        content_model="gpt-5.6-terra",
        content_source_language="ar",
        content_tone="Нейтральный",
        content_analysis_reasoning_effort="medium",
        project_topic="Культура",
        project_language="ru",
        project_audience="Читатели",
        postify_timezone="UTC",
    )
