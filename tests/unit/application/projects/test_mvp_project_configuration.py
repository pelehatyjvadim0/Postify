from datetime import UTC, datetime
from types import SimpleNamespace

from postify.application.projects.bootstrap_project import BootstrapProject
from postify.application.projects.manage_resources import ManageProjectResources
from postify.application.projects.runtime_configuration import ProjectRuntimeGraph
from postify.domain.projects.models import ContentFormat, ContentProject, ProjectConfiguration


NOW = datetime(2026, 9, 5, tzinfo=UTC)


def configuration() -> ProjectConfiguration:
    return ProjectConfiguration(
        media_max_bytes=10_000_000,
        analysis_timeout_seconds=60,
        analysis_batch_size=12,
        analysis_model="gpt-5.6-terra",
        analysis_reasoning_effort="medium",
        source_language="ar",
        tone="Спокойный",
    )


def test_runtime_brief_uses_project_and_format_without_cta() -> None:
    project = ContentProject(1, "Проект", "Культура", "ru", "Читатели", "UTC", configuration(), NOW, NOW)
    runtime = ProjectRuntimeGraph(project, (), (ContentFormat(1, 1, "Короткий", "text", "До 500 знаков", True),), (), ())

    effective = runtime.effective_generation()

    assert effective.brief.topic == "Культура"
    assert effective.brief.tone == "Спокойный"
    assert set(effective.snapshot) == {"topic", "language", "audience", "format"}


class Repository:
    def __init__(self) -> None:
        self.graph = None
        self.validated = None

    def active_project(self):
        return None

    def create_project_graph(self, graph):
        self.graph = graph
        return graph.project

    def get(self, project_id):
        return object()

    def validate_route_references(self, project_id, format_id, channel_id):
        self.validated = (project_id, format_id, channel_id)

    def create_resource(self, project_id, resource, payload, now):
        return payload


def test_bootstrap_has_no_seed_source_or_cta() -> None:
    repository = Repository()
    settings = SimpleNamespace(
        content_batch_size=12, content_media_max_bytes=10_000_000,
        content_analysis_timeout_seconds=60, content_model="gpt-5.6-terra",
        content_source_language="ar", content_tone="Спокойный",
        content_analysis_reasoning_effort="medium", project_topic="Культура",
        project_language="ru", project_audience="Читатели", postify_timezone="UTC",
    )
    BootstrapProject(repository, object(), object(), cipher=None, clock=lambda: NOW).execute(settings, None)

    assert not hasattr(repository.graph, "sources")
    assert not hasattr(repository.graph, "ctas")


def test_route_validation_uses_only_format_and_channel() -> None:
    repository = Repository()
    action = ManageProjectResources(repository, object(), object(), cipher=None, clock=lambda: NOW)
    action.create(1, "routes", {"format_id": 2, "channel_id": 3, "enabled": True})

    assert repository.validated == (1, 2, 3)
