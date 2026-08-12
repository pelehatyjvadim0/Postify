from dataclasses import asdict

from sqlalchemy import select

from postify.domain.projects.models import ContentProject, ProjectConfiguration
from postify.infrastructure.database.models import (
    CallToActionModel,
    ChannelConnectionModel,
    ContentFormatModel,
    ContentProjectModel,
    PublicationRouteModel,
    SourceConnectionModel,
)


class SqlAlchemyProjectRepository:
    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    def get(self, project_id: int) -> ContentProject:
        with self._session_factory() as session:
            model = session.scalar(
                select(ContentProjectModel).where(ContentProjectModel.id == project_id)
            )
            if model is None:
                raise LookupError(project_id)
            return _project(model)

    def active_project(self) -> ContentProject | None:
        with self._session_factory() as session:
            model = session.scalar(
                select(ContentProjectModel).order_by(ContentProjectModel.id).limit(1)
            )
            if model is None or not model.configuration:
                return None
            return _project(model)

    def create_project_graph(self, graph) -> ContentProject:
        with self._session_factory() as session:
            try:
                model = session.get(ContentProjectModel, graph.project.id)
                if model is not None and model.configuration:
                    session.rollback()
                    return _project(model)
                values = {
                    "name": graph.project.name,
                    "topic": graph.project.topic,
                    "language": graph.project.language,
                    "audience": graph.project.audience,
                    "timezone": graph.project.timezone,
                    "configuration": asdict(graph.project.configuration),
                    "created_at": graph.project.created_at,
                    "updated_at": graph.project.updated_at,
                }
                if model is None:
                    session.add(ContentProjectModel(id=graph.project.id, **values))
                else:
                    for name, value in values.items():
                        setattr(model, name, value)
                for source in graph.sources:
                    session.add(
                        SourceConnectionModel(
                            id=source.id,
                            project_id=source.project_id,
                            provider=source.provider,
                            name=source.name,
                            enabled=source.enabled,
                            configuration=source.configuration,
                            schedule=source.schedule,
                            created_at=graph.project.created_at,
                            updated_at=graph.project.updated_at,
                        )
                    )
                for content_format in graph.formats:
                    session.add(
                        ContentFormatModel(
                            id=content_format.id,
                            project_id=content_format.project_id,
                            name=content_format.name,
                            kind=content_format.kind,
                            instructions=content_format.instructions,
                            enabled=content_format.enabled,
                            created_at=graph.project.created_at,
                            updated_at=graph.project.updated_at,
                        )
                    )
                for cta in graph.ctas:
                    session.add(
                        CallToActionModel(
                            id=cta.id,
                            project_id=cta.project_id,
                            name=cta.name,
                            text=cta.text,
                            link_mode=cta.link_mode,
                            custom_url=cta.custom_url,
                            enabled=cta.enabled,
                            created_at=graph.project.created_at,
                            updated_at=graph.project.updated_at,
                        )
                    )
                for channel in graph.channels:
                    session.add(
                        ChannelConnectionModel(
                            id=channel.id,
                            project_id=channel.project_id,
                            provider=channel.provider,
                            name=channel.name,
                            enabled=channel.enabled,
                            configuration=channel.configuration,
                            encrypted_secret=channel.encrypted_secret,
                            connection_status=channel.connection_status,
                            last_checked_at=None,
                            created_at=graph.project.created_at,
                            updated_at=graph.project.updated_at,
                        )
                    )
                for route in graph.routes:
                    session.add(
                        PublicationRouteModel(
                            id=route.id,
                            project_id=route.project_id,
                            format_id=route.format_id,
                            channel_id=route.channel_id,
                            cta_id=route.cta_id,
                            enabled=route.enabled,
                            schedule={
                                "autopublish": True,
                                "slots": ["09:00", "14:00", "19:00"],
                            },
                            created_at=graph.project.created_at,
                            updated_at=graph.project.updated_at,
                        )
                    )
                session.commit()
            except BaseException:
                session.rollback()
                raise
        return self.get(graph.project.id)

    def save(self, project: ContentProject) -> ContentProject:
        with self._session_factory() as session:
            try:
                model = session.get(ContentProjectModel, project.id)
                if model is None:
                    raise LookupError(project.id)
                for name in ("name", "topic", "language", "audience", "timezone"):
                    setattr(model, name, getattr(project, name))
                model.configuration = asdict(project.configuration)
                model.updated_at = project.updated_at
                session.commit()
            except BaseException:
                session.rollback()
                raise
        return self.get(project.id)

    def replace_default(
        self,
        *,
        name: str,
        topic: str,
        language: str,
        audience: str,
        timezone: str,
        configuration: ProjectConfiguration,
        now,
    ) -> ContentProject:
        project = ContentProject(
            1,
            name,
            topic,
            language,
            audience,
            timezone,
            configuration,
            now,
            now,
        )
        with self._session_factory() as session:
            try:
                model = session.get(ContentProjectModel, 1)
                if model is None:
                    session.add(
                        ContentProjectModel(
                            id=1,
                            name=project.name,
                            topic=project.topic,
                            language=project.language,
                            audience=project.audience,
                            timezone=project.timezone,
                            configuration=asdict(project.configuration),
                            created_at=now,
                            updated_at=now,
                        )
                    )
                else:
                    model.name = project.name
                    model.topic = project.topic
                    model.language = project.language
                    model.audience = project.audience
                    model.timezone = project.timezone
                    model.configuration = asdict(project.configuration)
                    model.updated_at = now
                session.commit()
            except BaseException:
                session.rollback()
                raise
        return self.get(1)


def _project(model: ContentProjectModel) -> ContentProject:
    return ContentProject(
        model.id,
        model.name,
        model.topic,
        model.language,
        model.audience,
        model.timezone,
        ProjectConfiguration(**model.configuration),
        model.created_at,
        model.updated_at,
    )
