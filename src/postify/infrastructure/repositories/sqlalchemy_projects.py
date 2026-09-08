from dataclasses import asdict
from datetime import datetime
from typing import Any

from sqlalchemy import select, text

from postify.domain.projects.models import (
    ChannelConnection,
    ContentFormat,
    ContentProject,
    ProjectConfiguration,
    PublicationRoute,
    SourceConnection,
)
from postify.application.projects.runtime_configuration import (
    ProjectRuntimeGraph,
    RuntimeChannel,
)
from postify.infrastructure.database.models import (
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

    def runtime_graph(self, project_id: int) -> ProjectRuntimeGraph:
        project = self.get(project_id)
        with self._session_factory() as session:
            sources = tuple(
                SourceConnection(
                    item.id,
                    item.project_id,
                    item.provider,
                    item.name,
                    item.enabled,
                    dict(item.configuration),
                    item.schedule,
                )
                for item in session.scalars(
                    select(SourceConnectionModel)
                    .where(SourceConnectionModel.project_id == project_id)
                    .order_by(SourceConnectionModel.id)
                ).all()
            )
            formats = tuple(
                ContentFormat(
                    item.id,
                    item.project_id,
                    item.name,
                    item.kind,
                    item.instructions,
                    item.enabled,
                )
                for item in session.scalars(
                    select(ContentFormatModel)
                    .where(ContentFormatModel.project_id == project_id)
                    .order_by(ContentFormatModel.id)
                ).all()
            )
            channels = tuple(
                RuntimeChannel(
                    ChannelConnection(
                        item.id,
                        item.project_id,
                        item.provider,
                        item.name,
                        item.enabled,
                        dict(item.configuration),
                        item.encrypted_secret is not None,
                        item.connection_status,
                    ),
                    item.encrypted_secret,
                )
                for item in session.scalars(
                    select(ChannelConnectionModel)
                    .where(ChannelConnectionModel.project_id == project_id)
                    .order_by(ChannelConnectionModel.id)
                ).all()
            )
            routes = tuple(
                PublicationRoute(
                    item.id,
                    item.project_id,
                    item.format_id,
                    item.channel_id,
                    item.enabled,
                )
                for item in session.scalars(
                    select(PublicationRouteModel)
                    .where(PublicationRouteModel.project_id == project_id)
                    .order_by(PublicationRouteModel.id)
                ).all()
            )
        return ProjectRuntimeGraph(project, sources, formats, channels, routes)

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
                            enabled=route.enabled,
                            created_at=graph.project.created_at,
                            updated_at=graph.project.updated_at,
                        )
                    )
                for table in (
                    "content_projects",
                    "source_connections",
                    "content_formats",
                    "channel_connections",
                    "publication_routes",
                ):
                    session.execute(
                        text(
                            f"""SELECT setval(
                            pg_get_serial_sequence('{table}', 'id'),
                            GREATEST(COALESCE((SELECT max(id) FROM {table}), 1), 1),
                            true)"""
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

    def list_resources(self, project_id: int, resource: str) -> tuple[dict[str, object], ...]:
        model = _resource_model(resource)
        with self._session_factory() as session:
            rows = session.scalars(
                select(model).where(model.project_id == project_id).order_by(model.id)
            ).all()
        return tuple(_resource_values(resource, row) for row in rows)

    def create_resource(
        self, project_id: int, resource: str, payload: dict[str, object], now: datetime
    ) -> dict[str, object]:
        model = _resource_model(resource)
        with self._session_factory() as session:
            try:
                values = _resource_persistence_values(resource, payload)
                if resource == "channels" and "connection_status" not in values:
                    values["connection_status"] = "unconfigured"
                item = model(
                    project_id=project_id,
                    **values,
                    created_at=now,
                    updated_at=now,
                )
                session.add(item)
                session.commit()
                session.refresh(item)
                return _resource_values(resource, item)
            except BaseException:
                session.rollback()
                raise

    def update_resource(
        self,
        project_id: int,
        resource: str,
        resource_id: int,
        payload: dict[str, object],
        now: datetime,
    ) -> dict[str, object]:
        model = _resource_model(resource)
        with self._session_factory() as session:
            try:
                item = session.scalar(
                    select(model).where(
                        model.project_id == project_id, model.id == resource_id
                    ).with_for_update()
                )
                if item is None:
                    raise LookupError(resource_id)
                values = _resource_persistence_values(resource, payload)
                destination_changed = (
                    resource == "routes" and values["channel_id"] != item.channel_id
                ) or (
                    resource == "channels" and (
                        values["provider"] != item.provider
                        or values["configuration"] != item.configuration
                    )
                )
                if destination_changed:
                    predicate = "r.id=:resource" if resource == "routes" else "r.channel_id=:resource"
                    active = session.execute(text(f"""
                        SELECT p.id FROM content_packages p
                        JOIN publication_routes r ON r.id=p.route_id AND r.project_id=p.project_id
                        LEFT JOIN deliveries d ON d.project_id=p.project_id AND d.package_id=p.id
                        WHERE p.project_id=:project AND {predicate}
                          AND (p.status='approved' OR d.status IN ('sending','uncertain')) LIMIT 1
                    """), {"project": project_id, "resource": resource_id}).scalar_one_or_none()
                    if active is not None:
                        raise ValueError("Назначение связано с принятым постом или незавершённой отправкой")
                for name, value in values.items():
                    if value is not None or name != "encrypted_secret":
                        setattr(item, name, value)
                item.updated_at = now
                session.commit()
                session.refresh(item)
                return _resource_values(resource, item)
            except BaseException:
                session.rollback()
                raise

    def delete_resource(self, project_id: int, resource: str, resource_id: int) -> None:
        model = _resource_model(resource)
        with self._session_factory() as session:
            try:
                item = session.scalar(
                    select(model).where(
                        model.project_id == project_id, model.id == resource_id
                    )
                )
                if item is None:
                    raise LookupError(resource_id)
                session.delete(item)
                session.commit()
            except BaseException:
                session.rollback()
                raise

    def update_schedules(
        self,
        project_id: int,
        sources: tuple[dict[str, object], ...],
        now: datetime,
    ) -> dict[str, int]:
        with self._session_factory() as session:
            try:
                source_models = {
                    item.id: item
                    for item in session.scalars(
                        select(SourceConnectionModel).where(
                            SourceConnectionModel.project_id == project_id,
                            SourceConnectionModel.id.in_(item["id"] for item in sources),
                        )
                    ).all()
                }
                if len(source_models) != len(sources):
                    raise LookupError("schedule_resource")
                for values in sources:
                    source = source_models[values["id"]]
                    source.schedule = values["schedule"]
                    source.updated_at = now
                session.commit()
            except BaseException:
                session.rollback()
                raise
        return {"sources": len(sources)}

    def get_resource(
        self, project_id: int, resource: str, resource_id: int
    ) -> dict[str, object]:
        model = _resource_model(resource)
        with self._session_factory() as session:
            item = session.scalar(
                select(model).where(
                    model.project_id == project_id, model.id == resource_id
                )
            )
        if item is None:
            raise LookupError(resource_id)
        values = _resource_values(resource, item)
        if resource == "channels":
            values["encrypted_secret"] = item.encrypted_secret
        return values

    def validate_route_references(
        self,
        project_id: int,
        format_id: int,
        channel_id: int,
    ) -> None:
        references = [
            (ContentFormatModel, format_id),
            (ChannelConnectionModel, channel_id),
        ]
        with self._session_factory() as session:
            for model, resource_id in references:
                found = session.scalar(
                    select(model.id).where(
                        model.project_id == project_id,
                        model.id == resource_id,
                    )
                )
                if found is None:
                    raise LookupError(resource_id)

    def set_channel_status(
        self, project_id: int, channel_id: int, status: str, now: datetime
    ) -> None:
        with self._session_factory() as session:
            try:
                item = session.scalar(
                    select(ChannelConnectionModel).where(
                        ChannelConnectionModel.project_id == project_id,
                        ChannelConnectionModel.id == channel_id,
                    )
                )
                if item is None:
                    raise LookupError(channel_id)
                item.connection_status = status
                item.last_checked_at = now
                item.updated_at = now
                session.commit()
            except BaseException:
                session.rollback()
                raise


    def remove_channel_secret(
        self, project_id: int, channel_id: int, now: datetime
    ) -> dict[str, object]:
        with self._session_factory() as session:
            try:
                item = session.scalar(
                    select(ChannelConnectionModel).where(
                        ChannelConnectionModel.project_id == project_id,
                        ChannelConnectionModel.id == channel_id,
                    )
                )
                if item is None:
                    raise LookupError(channel_id)
                item.encrypted_secret = None
                item.connection_status = "unconfigured"
                item.last_checked_at = None
                item.updated_at = now
                session.commit()
                session.refresh(item)
                return _resource_values("channels", item)
            except BaseException:
                session.rollback()
                raise


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


def _resource_model(resource: str):
    models = {
        "sources": SourceConnectionModel,
        "channels": ChannelConnectionModel,
        "routes": PublicationRouteModel,
    }
    try:
        return models[resource]
    except KeyError:
        raise ValueError("unknown_resource") from None


def _resource_persistence_values(resource: str, payload: dict[str, object]) -> dict[str, object]:
    if resource == "sources":
        return {name: payload[name] for name in ("provider", "name", "enabled", "configuration", "schedule")}
    if resource == "channels":
        values = {name: payload[name] for name in ("provider", "name", "enabled", "configuration")}
        if "encrypted_secret" in payload:
            values["encrypted_secret"] = payload["encrypted_secret"]
            values["connection_status"] = "configured"
        return values
    if resource == "routes":
        return {
            **{name: payload[name] for name in ("format_id", "channel_id", "enabled")},
        }
    raise ValueError("unknown_resource")


def _resource_values(resource: str, model: Any) -> dict[str, object]:
    if resource == "sources":
        return {name: getattr(model, name) for name in ("id", "provider", "name", "enabled", "configuration", "schedule")}
    if resource == "channels":
        return {
            name: getattr(model, name)
            for name in ("id", "provider", "name", "enabled", "configuration", "connection_status")
        } | {"secretConfigured": model.encrypted_secret is not None}
    if resource == "routes":
        return {name: getattr(model, name) for name in ("id", "format_id", "channel_id", "enabled")}
    raise ValueError("unknown_resource")
