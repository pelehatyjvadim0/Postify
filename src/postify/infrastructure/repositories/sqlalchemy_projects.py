from dataclasses import asdict

from sqlalchemy import select

from postify.domain.projects.models import ContentProject, ProjectConfiguration
from postify.infrastructure.database.models import ContentProjectModel


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

