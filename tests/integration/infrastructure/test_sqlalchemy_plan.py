"""Хранение слотов контент-плана.

Проверяется то, что нельзя проверить без базы: границы диапазона в таймзоне
проекта, выборка «пора генерировать», изоляция по ``project_id`` и
ограничения, которые контракт обещает пользователю.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from postify.domain.plan.models import PlanValidationError, SlotTimeTaken
from postify.infrastructure.repositories.sqlalchemy_plan import (
    SqlAlchemyPlanRepository,
)
from postify.infrastructure.repositories.sqlalchemy_projects import (
    SqlAlchemyProjectRepository,
)
from postify.infrastructure.repositories.sqlalchemy_schedule import (
    SqlAlchemyScheduleRepository,
)


pytestmark = pytest.mark.integration

NOW = datetime(2026, 10, 1, 9, tzinfo=UTC)
# 2026-10-31 23:30 по Москве — последние полчаса октября в UTC уже 20:30.
LAST_MOSCOW_EVENING = datetime(2026, 10, 31, 20, 30, tzinfo=UTC)
FIRST_NOVEMBER_NIGHT = datetime(2026, 10, 31, 21, 30, tzinfo=UTC)


@pytest.fixture
def plan_database_url(alembic_config: Config, isolated_database_url: str) -> str:
    # Ветки треков этой волны ещё не выстроены в цепочку, поэтому апгрейд до
    # своей ревизии, а не до head.
    command.upgrade(alembic_config, "20260911_03")
    return isolated_database_url


def _prompt_column(connection) -> str:
    """Трек промптов переименовывает ``topic`` в ``project_prompt``.

    Колонка обязательная, поэтому имя берётся из схемы: иначе тест ломается от
    чужой ревизии, а не от своей.
    """
    return connection.execute(
        text(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_schema=current_schema() AND table_name='content_projects'"
            " AND column_name IN ('topic','project_prompt')"
        )
    ).scalar_one()


def _seed(engine, *, projects: int = 1) -> None:
    with engine.begin() as connection:
        prompt = _prompt_column(connection)
        connection.execute(
            text(
                "INSERT INTO users(id,telegram_user_id,telegram_username,display_name,"
                "created_at,is_active) VALUES (1,'101','','',:now,true)"
            ),
            {"now": NOW},
        )
        for project_id in range(1, projects + 1):
            connection.execute(
                text(
                    f"INSERT INTO content_projects(id,owner_id,name,{prompt},language,"
                    "audience,timezone,configuration,created_at,updated_at)"
                    " VALUES (:id,1,'Агротех','Тема','ru','Все','Europe/Moscow',"
                    "'{}'::jsonb,:now,:now)"
                ),
                {"id": project_id, "now": NOW},
            )
            connection.execute(
                text(
                    "INSERT INTO project_rubrics(id,project_id,name,instructions,"
                    "enabled,created_at,updated_at)"
                    " VALUES (:id,:project,'Подборка','Как есть',true,:now,:now)"
                ),
                {"id": project_id, "project": project_id, "now": NOW},
            )


def _repository(engine, project_id: int = 1) -> SqlAlchemyPlanRepository:
    return SqlAlchemyPlanRepository(sessionmaker(engine), project_id)


def _create(repository, publish_at: datetime, *, topic: str = "Тема", rubric_id=None):
    return repository.create(
        publish_at=publish_at,
        generate_at=publish_at - timedelta(minutes=1440),
        rubric_id=rubric_id,
        topic=topic,
        status="planned" if topic else "no_topic",
        now=NOW,
    )


def test_project_settings_bring_the_lead_time_and_the_mode(plan_database_url: str) -> None:
    engine = create_engine(plan_database_url)
    try:
        _seed(engine)

        settings = _repository(engine).settings()
    finally:
        engine.dispose()

    assert settings.timezone == "Europe/Moscow"
    assert settings.generation_lead_minutes == 1440
    assert settings.publication_mode == "review"


def test_range_bounds_follow_the_project_timezone(plan_database_url: str) -> None:
    # Поломка: на границе месяца по UTC вечерний слот выпадает из календаря.
    engine = create_engine(plan_database_url)
    try:
        _seed(engine)
        repository = _repository(engine)
        _create(repository, LAST_MOSCOW_EVENING)
        _create(repository, FIRST_NOVEMBER_NIGHT)

        october = repository.list_range(
            date_from=date(2026, 10, 1),
            date_to=date(2026, 10, 31),
            timezone="Europe/Moscow",
        )
        utc_view = repository.list_range(
            date_from=date(2026, 10, 1), date_to=date(2026, 10, 31), timezone="UTC"
        )
    finally:
        engine.dispose()

    assert [row.slot.publish_at for row in october] == [LAST_MOSCOW_EVENING]
    # В UTC те же сутки заканчиваются на три часа раньше — попадают оба слота.
    assert len(utc_view) == 2


def test_range_longer_than_the_contract_window_is_refused(plan_database_url: str) -> None:
    engine = create_engine(plan_database_url)
    try:
        _seed(engine)

        with pytest.raises(PlanValidationError, match="92"):
            _repository(engine).list_range(
                date_from=date(2026, 1, 1),
                date_to=date(2026, 4, 5),
                timezone="Europe/Moscow",
            )
    finally:
        engine.dispose()


def test_slot_keeps_its_rubric_and_post_card(plan_database_url: str) -> None:
    engine = create_engine(plan_database_url)
    try:
        _seed(engine)
        repository = _repository(engine)
        created = _create(repository, LAST_MOSCOW_EVENING, rubric_id=1)
        with engine.begin() as connection:
            post_id = connection.execute(
                text(
                    "INSERT INTO posts(project_id,post_text,status,created_at,updated_at)"
                    " VALUES (1,'Влажность выше 14% — главная причина','needs_review',"
                    ":now,:now) RETURNING id"
                ),
                {"now": NOW},
            ).scalar_one()
        # Пост к слоту привязывает трек генерации; здесь достаточно ссылки.
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE content_plan_slots SET post_id=:post WHERE id=:id"),
                {"post": post_id, "id": created.slot.id},
            )
        row = repository.get(created.slot.id)
    finally:
        engine.dispose()

    assert row.rubric_name == "Подборка"
    assert row.post_status == "needs_review"
    assert row.post_excerpt.startswith("Влажность")
    assert row.post_media is False


def test_two_slots_on_the_same_minute_are_refused(plan_database_url: str) -> None:
    engine = create_engine(plan_database_url)
    try:
        _seed(engine)
        repository = _repository(engine)
        _create(repository, LAST_MOSCOW_EVENING)

        with pytest.raises(SlotTimeTaken):
            _create(repository, LAST_MOSCOW_EVENING, topic="Другая тема")
    finally:
        engine.dispose()


def test_rubric_of_another_project_cannot_be_attached(plan_database_url: str) -> None:
    # Поломка: чужая рубрика утекла бы в контекст генерации соседнего проекта.
    engine = create_engine(plan_database_url)
    try:
        _seed(engine, projects=2)

        with pytest.raises(LookupError):
            _create(_repository(engine, 1), LAST_MOSCOW_EVENING, rubric_id=2)
    finally:
        engine.dispose()


def test_slots_of_another_project_are_invisible_and_unchangeable(
    plan_database_url: str,
) -> None:
    engine = create_engine(plan_database_url)
    try:
        _seed(engine, projects=2)
        created = _create(_repository(engine, 1), LAST_MOSCOW_EVENING)
        foreign = _repository(engine, 2)

        assert (
            foreign.list_range(
                date_from=date(2026, 10, 1),
                date_to=date(2026, 10, 31),
                timezone="Europe/Moscow",
            )
            == ()
        )
        for call in (
            lambda: foreign.get(created.slot.id),
            lambda: foreign.update(
                created.slot.id, values={"topic": "Чужая"}, now=NOW
            ),
            lambda: foreign.delete(created.slot.id),
        ):
            with pytest.raises(LookupError):
                call()

        assert _repository(engine, 1).get(created.slot.id).slot.topic == "Тема"
    finally:
        engine.dispose()


def test_only_planned_slots_with_a_due_time_are_taken_for_generation(
    plan_database_url: str,
) -> None:
    engine = create_engine(plan_database_url)
    try:
        _seed(engine)
        repository = _repository(engine)
        due = _create(repository, datetime(2026, 10, 2, 9, tzinfo=UTC))
        _create(repository, datetime(2026, 10, 9, 9, tzinfo=UTC))
        without_topic = _create(
            repository, datetime(2026, 10, 2, 10, tzinfo=UTC), topic=""
        )
        skipped = _create(repository, datetime(2026, 10, 2, 11, tzinfo=UTC))
        repository.skip(skipped.slot.id, now=NOW)

        slots = repository.due_generations(now=NOW)
    finally:
        engine.dispose()

    assert [slot.id for slot in slots] == [due.slot.id]
    assert without_topic.slot.status == "no_topic"


def test_rubric_in_use_is_counted_for_the_project_only(plan_database_url: str) -> None:
    engine = create_engine(plan_database_url)
    try:
        _seed(engine, projects=2)
        _create(_repository(engine, 1), LAST_MOSCOW_EVENING, rubric_id=1)
        projects = SqlAlchemyProjectRepository(sessionmaker(engine))

        assert projects.count_rubric_slots(1, 1) == 1
        assert projects.count_rubric_slots(2, 2) == 0
    finally:
        engine.dispose()


def test_due_slot_becomes_a_generate_command_claimed_once(
    plan_database_url: str,
) -> None:
    # Само выполнение генерации приносит свой трек: планировщик обязан занять
    # слот ровно один раз и не спутать цель — у генерации это slot_id.
    engine = create_engine(plan_database_url)
    try:
        _seed(engine)
        created = _create(_repository(engine), datetime(2026, 10, 2, 9, tzinfo=UTC))
        schedule = SqlAlchemyScheduleRepository(sessionmaker(engine))

        commands = schedule.due_generations(project_id=1, now=NOW)
        accepted = schedule.accept(commands[0])
        repeated = schedule.accept(commands[0])
        leased = schedule.claim_job(accepted.job_id, now=NOW)
    finally:
        engine.dispose()

    assert [(item.kind, item.slot_id, item.post_id) for item in commands] == [
        ("generate_post", created.slot.id, None)
    ]
    assert commands[0].scheduled_for == created.slot.generate_at
    assert accepted is not None and accepted.job_id is not None
    assert repeated is None
    assert leased.slot_id == created.slot.id


def test_generation_job_without_a_slot_fails_instead_of_hanging(
    plan_database_url: str,
) -> None:
    # Поломка: задача без цели вечно висит в queued, а UI вечно опрашивает
    # running-операцию.
    engine = create_engine(plan_database_url)
    try:
        _seed(engine)
        with engine.begin() as connection:
            run_id = connection.execute(
                text(
                    "INSERT INTO operation_runs(project_id,operation,status,mode,actor,"
                    "started_at) VALUES (1,'generate_post','running','automatic',"
                    "'scheduler',:now) RETURNING id"
                ),
                {"now": NOW},
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO scheduled_jobs(project_id,kind,scheduled_for,"
                    "operation_run_id,status,attempt_count,created_at,updated_at)"
                    " VALUES (1,'generate_post',:now,:run,'queued',0,:now,:now)"
                ),
                {"run": run_id, "now": NOW},
            )

        claimed = SqlAlchemyScheduleRepository(sessionmaker(engine)).claim_pending(
            now=NOW
        )
        with engine.connect() as connection:
            run = connection.execute(
                text(
                    "SELECT status,failure_code FROM operation_runs WHERE id=:id"
                ),
                {"id": run_id},
            ).one()
    finally:
        engine.dispose()

    assert claimed == ()
    assert (run.status, run.failure_code) == ("failed", "generate_post_failed")
