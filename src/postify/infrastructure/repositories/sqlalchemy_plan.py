"""Слоты контент-плана одного проекта.

Репозиторий создаётся под конкретный ``project_id``, и он же стоит в каждом
запросе: слот чужого проекта не читается и не правится даже по известному id.

SQL здесь текстовый, как в соседних репозиториях: запросы плана джойнят пост и
рубрику ради одной карточки календаря, и на ORM-выражениях это только длиннее.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from postify.domain.plan.models import (
    ContentPlanSlot,
    SlotStatus,
    SlotTimeTaken,
    validate_range,
)


# Столько символов поста показывает карточка предпросмотра календаря.
EXCERPT_LIMIT = 160

# Поля слота, которые правит PATCH. Статус пересчитывается сценарием.
UPDATABLE = ("publish_at", "generate_at", "rubric_id", "topic", "status")

_COLUMNS = """
    s.id,s.project_id,s.publish_at,s.generate_at,s.rubric_id,s.topic,s.status,
    s.post_id,s.created_at,s.updated_at,
    r.name AS rubric_name,
    p.status AS post_status,
    left(p.post_text,:excerpt) AS post_excerpt,
    (p.media_path IS NOT NULL AND p.media_deleted_at IS NULL) AS post_media
"""

_FROM = """
    FROM content_plan_slots s
    LEFT JOIN project_rubrics r
        ON r.project_id=s.project_id AND r.id=s.rubric_id
    LEFT JOIN posts p ON p.project_id=s.project_id AND p.id=s.post_id
"""


@dataclass(frozen=True, slots=True)
class ProjectPlanSettings:
    """То, что плану нужно от проекта: таймзона и запас времени на генерацию."""

    timezone: str
    generation_lead_minutes: int
    publication_mode: str


@dataclass(frozen=True, slots=True)
class PlanSlotRow:
    """Слот вместе с рубрикой и постом — ровно карточка календаря."""

    slot: ContentPlanSlot
    rubric_name: str | None
    post_status: str | None
    post_excerpt: str | None
    post_media: bool


class SqlAlchemyPlanRepository:
    def __init__(self, session_factory, project_id: int) -> None:
        self._session_factory = session_factory
        self._project_id = project_id
        self._settings: ProjectPlanSettings | None = None

    # --- чтение -----------------------------------------------------------

    def settings(self) -> ProjectPlanSettings:
        """Читается запросом, а не через доменный проект: колонки плана в
        ``ContentProject`` не входят, а нужны здесь на каждое действие.

        Репозиторий живёт один запрос, поэтому результат запоминается: за один
        HTTP-запрос настройки проекта поменяться не могут.
        """
        if self._settings is not None:
            return self._settings
        with self._session_factory() as session:
            row = session.execute(
                text(
                    "SELECT timezone,generation_lead_minutes,publication_mode"
                    " FROM content_projects WHERE id=:project"
                ),
                {"project": self._project_id},
            ).one_or_none()
        if row is None:
            raise LookupError(self._project_id)
        self._settings = ProjectPlanSettings(
            row.timezone, row.generation_lead_minutes, row.publication_mode
        )
        return self._settings

    def list_range(self, *, date_from: date, date_to: date, timezone: str) -> tuple[PlanSlotRow, ...]:
        """Слоты за диапазон дат, границы включительно, в таймзоне проекта."""
        validate_range(date_from, date_to)
        zone = ZoneInfo(timezone)
        # Полуинтервал по началу следующих суток: так последний день попадает
        # целиком независимо от перевода часов внутри диапазона.
        start = datetime.combine(date_from, time.min, tzinfo=zone)
        end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=zone)
        with self._session_factory() as session:
            rows = (
                session.execute(
                    text(
                        f"SELECT {_COLUMNS} {_FROM}"
                        " WHERE s.project_id=:project"
                        " AND s.publish_at>=:start AND s.publish_at<:end"
                        " ORDER BY s.publish_at,s.id"
                    ),
                    {
                        "project": self._project_id,
                        "start": start,
                        "end": end,
                        "excerpt": EXCERPT_LIMIT,
                    },
                )
                .mappings()
                .all()
            )
        return tuple(_row(row) for row in rows)

    def get(self, slot_id: int) -> PlanSlotRow:
        with self._session_factory() as session:
            row = (
                session.execute(
                    text(
                        f"SELECT {_COLUMNS} {_FROM}"
                        " WHERE s.project_id=:project AND s.id=:id"
                    ),
                    {
                        "project": self._project_id,
                        "id": slot_id,
                        "excerpt": EXCERPT_LIMIT,
                    },
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise LookupError(slot_id)
        return _row(row)

    def due_generations(self, *, now: datetime) -> tuple[ContentPlanSlot, ...]:
        """Слоты, которым пора генерировать: тема есть, поста ещё нет."""
        with self._session_factory() as session:
            rows = (
                session.execute(
                    text(
                        "SELECT id,project_id,publish_at,generate_at,rubric_id,topic,"
                        "status,post_id,created_at,updated_at"
                        " FROM content_plan_slots"
                        " WHERE project_id=:project AND status='planned'"
                        " AND post_id IS NULL AND generate_at<=:now"
                        " ORDER BY generate_at,id"
                    ),
                    {"project": self._project_id, "now": now},
                )
                .mappings()
                .all()
            )
        return tuple(_slot(row) for row in rows)

    # --- запись -----------------------------------------------------------

    def create(
        self,
        *,
        publish_at: datetime,
        generate_at: datetime,
        rubric_id: int | None,
        topic: str,
        status: str,
        now: datetime,
    ) -> PlanSlotRow:
        with self._session_factory() as session:
            try:
                slot_id = session.execute(
                    text(
                        "INSERT INTO content_plan_slots"
                        "(project_id,publish_at,generate_at,rubric_id,topic,status,"
                        "created_at,updated_at)"
                        " VALUES (:project,:publish_at,:generate_at,:rubric_id,:topic,"
                        ":status,:now,:now) RETURNING id"
                    ),
                    {
                        "project": self._project_id,
                        "publish_at": publish_at,
                        "generate_at": generate_at,
                        "rubric_id": rubric_id,
                        "topic": topic,
                        "status": status,
                        "now": now,
                    },
                ).scalar_one()
                session.commit()
            except IntegrityError as error:
                session.rollback()
                raise _conflict(error) from error
            except BaseException:
                session.rollback()
                raise
        return self.get(slot_id)

    def update(self, slot_id: int, *, values: dict[str, object], now: datetime) -> PlanSlotRow:
        """Частичная правка: пишутся только пришедшие поля."""
        changed = {name: values[name] for name in UPDATABLE if name in values}
        if not changed:
            return self.get(slot_id)
        assignments = ",".join(f"{name}=:{name}" for name in changed)
        with self._session_factory() as session:
            try:
                updated = session.execute(
                    text(
                        f"UPDATE content_plan_slots SET {assignments},updated_at=:now"
                        " WHERE project_id=:project AND id=:id"
                    ),
                    {**changed, "now": now, "project": self._project_id, "id": slot_id},
                ).rowcount
                if updated != 1:
                    session.rollback()
                    raise LookupError(slot_id)
                session.commit()
            except IntegrityError as error:
                session.rollback()
                raise _conflict(error) from error
            except BaseException:
                session.rollback()
                raise
        return self.get(slot_id)

    def delete(self, slot_id: int) -> None:
        with self._session_factory() as session:
            try:
                deleted = session.execute(
                    text(
                        "DELETE FROM content_plan_slots"
                        " WHERE project_id=:project AND id=:id"
                    ),
                    {"project": self._project_id, "id": slot_id},
                ).rowcount
                if deleted != 1:
                    session.rollback()
                    raise LookupError(slot_id)
                session.commit()
            except BaseException:
                session.rollback()
                raise

    def skip(self, slot_id: int, *, now: datetime) -> PlanSlotRow:
        return self.update(slot_id, values={"status": SlotStatus.SKIPPED.value}, now=now)


def _conflict(error: IntegrityError) -> Exception:
    """Ограничения базы — тоже часть контракта, их надо объяснить человеку."""
    diagnostics = getattr(getattr(error, "orig", None), "diag", None)
    constraint = getattr(diagnostics, "constraint_name", None)
    if constraint == "uq_content_plan_slots_project_publish_at":
        return SlotTimeTaken("На это время в плане уже есть слот")
    if constraint == "fk_content_plan_slots_project_rubric":
        # Рубрика чужого проекта неотличима от несуществующей: 404.
        return LookupError("rubric_id")
    return error


def _slot(row) -> ContentPlanSlot:
    return ContentPlanSlot(
        id=row["id"],
        project_id=row["project_id"],
        publish_at=row["publish_at"],
        generate_at=row["generate_at"],
        rubric_id=row["rubric_id"],
        topic=row["topic"],
        status=row["status"],
        post_id=row["post_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row(row) -> PlanSlotRow:
    return PlanSlotRow(
        slot=_slot(row),
        rubric_name=row["rubric_name"],
        post_status=row["post_status"],
        post_excerpt=row["post_excerpt"],
        post_media=bool(row["post_media"]),
    )
