from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select, text

from postify.application.scheduling.project_scheduler import (
    ProjectSchedule,
    RouteSchedule,
    ScheduledCommand,
    SourceSchedule,
)
from postify.infrastructure.database.models import (
    ContentProjectModel,
    PublicationRouteModel,
    SourceConnectionModel,
)


class SqlAlchemyScheduleRepository:
    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    def list_schedules(self) -> tuple[ProjectSchedule, ...]:
        with self._session_factory() as session:
            projects = session.execute(
                select(ContentProjectModel.id, ContentProjectModel.timezone).order_by(
                    ContentProjectModel.id
                )
            ).all()
            source_rows = session.execute(
                select(
                    SourceConnectionModel.project_id,
                    SourceConnectionModel.schedule,
                )
                .where(SourceConnectionModel.enabled.is_(True))
                .order_by(SourceConnectionModel.project_id, SourceConnectionModel.id)
            ).all()
            route_rows = session.execute(
                select(
                    PublicationRouteModel.project_id,
                    PublicationRouteModel.schedule,
                )
                .where(PublicationRouteModel.enabled.is_(True))
                .order_by(PublicationRouteModel.project_id, PublicationRouteModel.id)
            ).all()

        sources = defaultdict(list)
        for project_id, cron in source_rows:
            sources[project_id].append(SourceSchedule(enabled=True, cron=cron))
        routes = defaultdict(list)
        for project_id, schedule in route_rows:
            values = schedule if isinstance(schedule, dict) else {}
            routes[project_id].append(
                RouteSchedule(
                    enabled=True,
                    autopublish=values.get("autopublish") is True,
                    slots=tuple(values.get("slots", ())),
                )
            )
        return tuple(
            ProjectSchedule(
                project_id=project_id,
                timezone=timezone,
                sources=tuple(sources[project_id]),
                routes=tuple(routes[project_id]),
            )
            for project_id, timezone in projects
        )

    def claim(self, command: ScheduledCommand) -> bool:
        with self._session_factory() as session:
            try:
                session.execute(
                    text("SELECT pg_advisory_xact_lock(:project_id)"),
                    {"project_id": command.project_id},
                )
                inserted = session.execute(
                    text(
                        """
                        INSERT INTO schedule_slot_claims
                            (project_id, kind, scheduled_for)
                        VALUES (:project_id, :kind, :scheduled_for)
                        ON CONFLICT (project_id, kind, scheduled_for) DO NOTHING
                        RETURNING true
                        """
                    ),
                    {
                        "project_id": command.project_id,
                        "kind": command.kind,
                        "scheduled_for": command.scheduled_for,
                    },
                ).scalar_one_or_none()
                session.commit()
                return inserted is True
            except BaseException:
                session.rollback()
                raise
