from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

from sqlalchemy import delete, select, text

from postify.application.projects.runtime_configuration import (
    ProjectRuntimeGraph,
    RuntimeChannel,
)
from postify.domain.projects.models import (
    ChannelConnection,
    ContentProject,
    ProjectConfiguration,
    ProjectRubric,
)
from postify.infrastructure.database.models import (
    ChannelConnectionModel,
    ContentProjectModel,
    ProjectRubricModel,
)


class SqlAlchemyProjectRepository:
    """Проект, его рубрики и единственный канал доставки."""

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    # --- проект -----------------------------------------------------------

    def get(self, project_id: int) -> ContentProject:
        with self._session_factory() as session:
            model = session.get(ContentProjectModel, project_id)
            if model is None:
                raise LookupError(project_id)
            return _project(model)

    def list_projects(self, *, owner_id: int) -> tuple[ContentProject, ...]:
        """Только проекты владельца: это единственный маршрут без project_id,
        поэтому общая проверка владения здесь не срабатывает."""
        with self._session_factory() as session:
            models = session.scalars(
                select(ContentProjectModel)
                .where(ContentProjectModel.owner_id == owner_id)
                .order_by(ContentProjectModel.id)
            ).all()
        return tuple(_project(model) for model in models)

    def create(
        self,
        *,
        owner_id: int,
        name: str,
        project_prompt: str,
        language: str,
        audience: str,
        timezone: str,
        configuration: ProjectConfiguration,
        now: datetime,
    ) -> ContentProject:
        with self._session_factory() as session:
            try:
                model = ContentProjectModel(
                    owner_id=owner_id,
                    name=name,
                    project_prompt=project_prompt,
                    language=language,
                    audience=audience,
                    timezone=timezone,
                    configuration=asdict(configuration),
                    created_at=now,
                    updated_at=now,
                )
                session.add(model)
                session.commit()
                session.refresh(model)
                return _project(model)
            except BaseException:
                session.rollback()
                raise

    def save(self, project: ContentProject) -> ContentProject:
        with self._session_factory() as session:
            try:
                model = session.get(ContentProjectModel, project.id)
                if model is None:
                    raise LookupError(project.id)
                fields = (
                    "name",
                    "project_prompt",
                    "language",
                    "audience",
                    "timezone",
                    "generation_lead_minutes",
                    "publication_mode",
                    "media_reuse_days",
                    "media_reuse_blocked",
                )
                for name in fields:
                    setattr(model, name, getattr(project, name))
                model.configuration = asdict(project.configuration)
                model.updated_at = project.updated_at
                session.commit()
                session.refresh(model)
                return _project(model)
            except BaseException:
                session.rollback()
                raise

    def delete(self, project_id: int) -> tuple[str, ...]:
        with self._session_factory() as session:
            try:
                model = session.get(ContentProjectModel, project_id, with_for_update=True)
                if model is None:
                    raise LookupError(project_id)
                active = session.execute(text(
                    "SELECT 1 FROM operation_runs WHERE project_id=:project AND status='running'"
                    " UNION ALL SELECT 1 FROM deliveries WHERE project_id=:project"
                    " AND status IN ('sending','uncertain') LIMIT 1"
                ), {"project": project_id}).scalar_one_or_none()
                if active is not None:
                    raise RuntimeError("operation_busy")
                media_paths = tuple(session.execute(text(
                    "SELECT file_path FROM media_assets WHERE project_id=:project"
                    " UNION SELECT thumb_path FROM media_assets WHERE project_id=:project"
                    " AND thumb_path IS NOT NULL"
                ), {"project": project_id}).scalars())
                session.execute(text(
                    "DELETE FROM validation_reports WHERE post_id IN"
                    " (SELECT id FROM posts WHERE project_id=:project)"
                ), {"project": project_id})
                # Delete dependents before their parents; all statements share one transaction.
                for table in (
                    "delivery_attempts", "deliveries", "media_usages",
                    "schedule_slot_claims", "scheduled_jobs", "operation_runs",
                    "content_plan_slots", "post_status_history", "posts",
                    "project_rules", "media_assets", "project_rubrics", "channel_connections",
                ):
                    session.execute(text(f"DELETE FROM {table} WHERE project_id=:project"),
                                    {"project": project_id})
                session.delete(model)
                session.commit()
                return media_paths
            except BaseException:
                session.rollback()
                raise

    def runtime_graph(self, project_id: int) -> ProjectRuntimeGraph:
        project = self.get(project_id)
        with self._session_factory() as session:
            rubrics = tuple(
                _rubric(item)
                for item in session.scalars(
                    select(ProjectRubricModel)
                    .where(ProjectRubricModel.project_id == project_id)
                    .order_by(ProjectRubricModel.id)
                ).all()
            )
            channel_model = session.scalar(
                select(ChannelConnectionModel).where(
                    ChannelConnectionModel.project_id == project_id
                )
            )
            channel = (
                RuntimeChannel(_channel(channel_model), channel_model.encrypted_secret)
                if channel_model is not None
                else None
            )
        return ProjectRuntimeGraph(project, rubrics, channel)

    # --- рубрики ----------------------------------------------------------

    def list_rubrics(self, project_id: int) -> tuple[ProjectRubric, ...]:
        with self._session_factory() as session:
            rows = session.scalars(
                select(ProjectRubricModel)
                .where(ProjectRubricModel.project_id == project_id)
                .order_by(ProjectRubricModel.id)
            ).all()
        return tuple(_rubric(row) for row in rows)

    def create_rubric(
        self,
        project_id: int,
        *,
        name: str,
        instructions: str,
        enabled: bool,
        now: datetime,
    ) -> ProjectRubric:
        with self._session_factory() as session:
            try:
                item = ProjectRubricModel(
                    project_id=project_id,
                    name=name,
                    instructions=instructions,
                    enabled=enabled,
                    created_at=now,
                    updated_at=now,
                )
                session.add(item)
                session.commit()
                session.refresh(item)
                return _rubric(item)
            except BaseException:
                session.rollback()
                raise

    def update_rubric(
        self,
        project_id: int,
        rubric_id: int,
        *,
        values: dict[str, object],
        now: datetime,
    ) -> ProjectRubric:
        with self._session_factory() as session:
            try:
                item = session.scalar(
                    select(ProjectRubricModel)
                    .where(
                        ProjectRubricModel.project_id == project_id,
                        ProjectRubricModel.id == rubric_id,
                    )
                    .with_for_update()
                )
                if item is None:
                    raise LookupError(rubric_id)
                for name in ("name", "instructions", "enabled"):
                    if name in values:
                        setattr(item, name, values[name])
                item.updated_at = now
                session.commit()
                session.refresh(item)
                return _rubric(item)
            except BaseException:
                session.rollback()
                raise

    def delete_rubric(self, project_id: int, rubric_id: int) -> None:
        with self._session_factory() as session:
            try:
                item = session.scalar(
                    select(ProjectRubricModel).where(
                        ProjectRubricModel.project_id == project_id,
                        ProjectRubricModel.id == rubric_id,
                    )
                )
                if item is None:
                    raise LookupError(rubric_id)
                session.delete(item)
                session.commit()
            except BaseException:
                session.rollback()
                raise

    def count_rubric_slots(self, project_id: int, rubric_id: int) -> int:
        """Сколько слотов плана ссылается на рубрику.

        Удаление рубрики осиротило бы эти слоты, поэтому проверка удаления
        спрашивает именно об этом.
        """
        with self._session_factory() as session:
            return int(
                session.execute(
                    text(
                        "SELECT count(*) FROM content_plan_slots"
                        " WHERE project_id=:project AND rubric_id=:rubric"
                    ),
                    {"project": project_id, "rubric": rubric_id},
                ).scalar_one()
            )

    # --- канал ------------------------------------------------------------

    def get_channel(self, project_id: int) -> tuple[ChannelConnection, str | None] | None:
        with self._session_factory() as session:
            model = session.scalar(
                select(ChannelConnectionModel).where(
                    ChannelConnectionModel.project_id == project_id
                )
            )
            if model is None:
                return None
            return _channel(model), model.encrypted_secret

    def save_channel(
        self,
        project_id: int,
        *,
        provider: str,
        name: str,
        configuration: dict[str, object],
        encrypted_secret: str | None,
        now: datetime,
    ) -> ChannelConnection:
        """Один канал на проект: вставка или правка существующего."""
        with self._session_factory() as session:
            try:
                model = session.scalar(
                    select(ChannelConnectionModel)
                    .where(ChannelConnectionModel.project_id == project_id)
                    .with_for_update()
                )
                if model is None:
                    model = ChannelConnectionModel(
                        project_id=project_id,
                        provider=provider,
                        name=name,
                        enabled=True,
                        configuration=configuration,
                        encrypted_secret=encrypted_secret,
                        connection_status=(
                            "configured" if encrypted_secret else "unconfigured"
                        ),
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(model)
                else:
                    model.provider = provider
                    model.name = name
                    model.configuration = configuration
                    if encrypted_secret is not None:
                        model.encrypted_secret = encrypted_secret
                    model.connection_status = (
                        "configured" if model.encrypted_secret else "unconfigured"
                    )
                    model.last_checked_at = None
                    model.updated_at = now
                session.commit()
                session.refresh(model)
                return _channel(model)
            except BaseException:
                session.rollback()
                raise

    def set_channel_status(self, project_id: int, status: str, now: datetime) -> None:
        with self._session_factory() as session:
            try:
                model = session.scalar(
                    select(ChannelConnectionModel).where(
                        ChannelConnectionModel.project_id == project_id
                    )
                )
                if model is None:
                    raise LookupError(project_id)
                model.connection_status = status
                model.last_checked_at = now
                model.updated_at = now
                session.commit()
            except BaseException:
                session.rollback()
                raise

    def delete_channel(self, project_id: int) -> None:
        """Отключает канал, если по нему нет незавершённых отправок."""
        with self._session_factory() as session:
            try:
                session.scalar(select(ChannelConnectionModel)
                               .where(ChannelConnectionModel.project_id == project_id)
                               .with_for_update())
                active = session.execute(
                    text(
                        "SELECT 1 FROM deliveries WHERE project_id=:project"
                        " AND status IN ('sending','uncertain') LIMIT 1"
                    ),
                    {"project": project_id},
                ).scalar_one_or_none()
                if active is not None:
                    raise RuntimeError("channel_delivery_in_flight")
                session.execute(text(
                    "UPDATE deliveries SET channel_id=NULL WHERE project_id=:project"
                ), {"project": project_id})
                session.execute(
                    delete(ChannelConnectionModel).where(
                        ChannelConnectionModel.project_id == project_id
                    )
                )
                session.commit()
            except BaseException:
                session.rollback()
                raise

    # --- сводка -----------------------------------------------------------

    def post_counts(self, project_id: int) -> dict[str, int]:
        with self._session_factory() as session:
            rows = session.execute(
                text(
                    "SELECT status, count(*) AS total FROM posts"
                    " WHERE project_id=:project GROUP BY status"
                ),
                {"project": project_id},
            ).all()
        return {row.status: row.total for row in rows}


def _project(model: ContentProjectModel) -> ContentProject:
    return ContentProject(
        model.id,
        model.name,
        model.project_prompt,
        model.language,
        model.audience,
        model.timezone,
        ProjectConfiguration(**model.configuration),
        model.created_at,
        model.updated_at,
        model.owner_id,
        model.generation_lead_minutes,
        model.publication_mode,
        model.media_reuse_days,
        model.media_reuse_blocked,
    )


def _rubric(model: ProjectRubricModel) -> ProjectRubric:
    return ProjectRubric(
        model.id, model.project_id, model.name, model.instructions, model.enabled
    )


def _channel(model: ChannelConnectionModel) -> ChannelConnection:
    return ChannelConnection(
        model.id,
        model.project_id,
        model.provider,
        model.name,
        model.enabled,
        dict(model.configuration),
        model.encrypted_secret is not None,
        model.connection_status,
        model.last_checked_at,
    )
