from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from postify.application.delivery.publish_content import PublishContent
from postify.application.content.manual_operations import ManualContentOperations
from postify.application.scheduling.project_scheduler import ProjectScheduler, ScheduledCommand
from postify.domain.content.models import InvalidContentTransition
from postify.domain.delivery.models import PublishFailureKind, TelegramMessage
from postify.infrastructure.repositories.sqlalchemy_content import SqlAlchemyContentRepository
from postify.infrastructure.repositories.sqlalchemy_dashboard import SqlAlchemyDashboardRepository
from postify.infrastructure.repositories.sqlalchemy_delivery import SqlAlchemyDeliveryRepository
from postify.infrastructure.repositories.sqlalchemy_schedule import SqlAlchemyScheduleRepository
from tests.integration.infrastructure.test_sqlalchemy_delivery import NOW, _seed_package
from tests.integration.infrastructure.test_sqlalchemy_schedule import _seed_schedule_graph

pytestmark = pytest.mark.integration


@pytest.fixture
def graph(migrated_database_url):
    _seed_schedule_graph(migrated_database_url)
    engine = create_engine(migrated_database_url)
    with engine.begin() as connection:
        connection.execute(text("UPDATE content_projects SET configuration=configuration || '{\"delivery_lateness_seconds\": 60}'::jsonb WHERE id=1"))
    yield engine
    engine.dispose()


def review(engine):
    return SqlAlchemyContentRepository(sessionmaker(engine))


def delivery(engine, **kwargs):
    return SqlAlchemyDeliveryRepository(sessionmaker(engine), route_id=401, channel_id=301, **kwargs)


def planned(engine, *, at=NOW + timedelta(minutes=5)):
    package = _seed_package(engine, status="awaiting_review")
    repository = review(engine)
    repository.save_plan(package, scheduled_at=at, route_id=401, now=NOW)
    repository.approve(package, now=NOW)
    return package


def test_review_requires_saved_future_plan_and_is_idempotent(graph):
    package = _seed_package(graph, status="awaiting_review")
    repository = review(graph)
    with pytest.raises(InvalidContentTransition, match="дату"):
        repository.approve(package, now=NOW)
    saved = repository.save_plan(package, scheduled_at=NOW + timedelta(minutes=5), route_id=401, now=NOW)
    assert saved.status == "awaiting_review"
    assert saved.scheduled_at == NOW + timedelta(minutes=5)
    assert review(graph).get_package(package).route_id == 401
    assert repository.approve(package, now=NOW).status == "approved"
    assert repository.approve(package, now=NOW).status == "approved"
    with pytest.raises(InvalidContentTransition):
        repository.reject(package, now=NOW)
    with graph.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM content_package_status_history WHERE package_id=:id AND status='approved'"), {"id": package}).scalar_one() == 1


def test_regeneration_rechecks_approval_before_creating_an_attempt(graph):
    package = _seed_package(graph, status="awaiting_review")
    repository = review(graph)
    repository.save_plan(package, scheduled_at=NOW + timedelta(minutes=5), route_id=401, now=NOW)
    context = ManualContentOperations(repository).regenerate_post(package)
    # The editor approves after the command is accepted but before its worker runs.
    repository.approve(package, now=NOW)
    repository.claim(now=NOW, batch_size=1, context=context)
    with graph.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM content_attempts")).scalar_one() == 1
        assert tuple(connection.execute(text("SELECT id,status,scheduled_at,route_id FROM content_packages")).one()) == (
            package, "approved", NOW + timedelta(minutes=5), 401,
        )
    reserved = delivery(graph).reserve_next(now=NOW + timedelta(minutes=5), package_id=package)
    assert reserved.package_id == package


def test_plan_rejects_past_naive_disabled_and_foreign_routes(graph):
    package = _seed_package(graph, status="awaiting_review")
    repository = review(graph)
    for at, route in [(NOW, 401), (NOW.replace(tzinfo=None), 401), (NOW + timedelta(minutes=5), 402), (NOW + timedelta(minutes=5), 999)]:
        with pytest.raises(ValueError):
            repository.save_plan(package, scheduled_at=at, route_id=route, now=NOW)
    assert repository.get_package(package).scheduled_at is None


def test_delivery_is_addressed_due_approved_and_locked_against_replanning(graph):
    early = planned(graph, at=NOW + timedelta(minutes=10))
    due = planned(graph)
    awaiting = _seed_package(graph, status="awaiting_review")
    rejected = _seed_package(graph, status="rejected")
    legacy = _seed_package(graph)
    repository = delivery(graph)
    for package in (early, awaiting, rejected, legacy):
        assert repository.reserve_next(now=NOW + timedelta(minutes=5), package_id=package) is None
    assert SqlAlchemyDeliveryRepository(sessionmaker(graph), route_id=402, channel_id=301).reserve_next(now=NOW + timedelta(minutes=5), package_id=due) is None
    claim = repository.reserve_next(now=NOW + timedelta(minutes=5), package_id=due)
    assert claim.package_id == due
    assert repository.reserve_next(now=NOW + timedelta(minutes=5), package_id=due) is None
    with pytest.raises(InvalidContentTransition, match="Отправка"):
        review(graph).save_plan(due, scheduled_at=NOW + timedelta(hours=1), route_id=401, now=NOW)


def test_parallel_reservation_and_restart_uncertain_never_duplicate(graph):
    package = planned(graph)
    now = NOW + timedelta(minutes=5)
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: delivery(graph).reserve_next(now=now, package_id=package), range(2)))
    assert sum(claim is not None for claim in claims) == 1
    fresh = delivery(graph)
    assert fresh.mark_stale_sending_uncertain(stale_before=now + timedelta(seconds=1), now=now + timedelta(seconds=2)) == 1
    assert fresh.reserve_next(now=now + timedelta(seconds=2), package_id=package) is None
    with graph.connect() as connection:
        state = connection.execute(text("SELECT status,attempt_no FROM deliveries WHERE package_id=:id"), {"id": package}).one()
        assert tuple(state) == ("uncertain", 1)
    with pytest.raises(InvalidContentTransition):
        review(graph).save_plan(package, scheduled_at=now + timedelta(hours=1), route_id=401, now=now)


def test_changed_plan_requires_new_approval_and_is_visible_in_queue(graph):
    package = planned(graph)
    at = NOW + timedelta(minutes=8)
    saved = review(graph).save_plan(package, scheduled_at=at, route_id=401, now=NOW)
    assert saved.status == "awaiting_review"
    assert delivery(graph).reserve_next(now=at, package_id=package) is None
    dashboard = SqlAlchemyDashboardRepository(sessionmaker(graph))
    rows = dashboard.queue(1, at.date())
    assert len(rows) == 1
    assert (rows[0].package_id, rows[0].scheduled_at, rows[0].status) == (package, at, "awaiting_review")
    assert dashboard.package(1, package).scheduled_at == at


def test_durable_jobs_preserve_package_and_repeated_ticks_do_not_resend(graph):
    package = planned(graph)
    now = NOW + timedelta(minutes=5)
    repository = SqlAlchemyScheduleRepository(sessionmaker(graph))
    submitted = []
    scheduler = ProjectScheduler(repository, submitted.append)
    scheduler.tick(now)
    assert len(submitted) == 1
    first = submitted[0]
    assert (first.package_id, first.route_id, first.scheduled_for) == (package, 401, now)
    assert first.job_id is not None
    # A new process reclaims the same durable target after the lease expires.
    recovered = SqlAlchemyScheduleRepository(sessionmaker(graph)).claim_pending(now=now + timedelta(minutes=6))
    assert len(recovered) == 1
    assert recovered[0].package_id == package
    assert recovered[0].job_id == first.job_id
    scheduler.tick(now + timedelta(seconds=1))
    assert len(submitted) == 1


def test_failed_pre_delivery_job_is_released_once_after_cooldown(graph):
    package = planned(graph)
    now = NOW + timedelta(minutes=5)
    repository = SqlAlchemyScheduleRepository(sessionmaker(graph))
    accepted = repository.accept(
        ScheduledCommand(1, "publish_once", now, route_id=401, package_id=package)
    )
    leased = repository.claim_job(accepted.job_id, now=now)
    repository.acknowledge(leased.job_id, succeeded=False, now=now)

    recovered = repository.claim_pending(now=now + timedelta(minutes=1))

    assert len(recovered) == 1
    assert recovered[0].job_id == leased.job_id
    assert recovered[0].operation_run_id != leased.operation_run_id


def test_failed_pre_delivery_job_does_not_reclaim_after_uncertain_delivery(graph):
    package = planned(graph)
    now = NOW + timedelta(minutes=5)
    repository = SqlAlchemyScheduleRepository(sessionmaker(graph))
    accepted = repository.accept(
        ScheduledCommand(1, "publish_once", now, route_id=401, package_id=package)
    )
    leased = repository.claim_job(accepted.job_id, now=now)
    repository.acknowledge(leased.job_id, succeeded=False, now=now)
    assert delivery(graph).reserve_next(now=now, package_id=package) is not None

    assert repository.claim_pending(now=now + timedelta(minutes=1)) == ()


def test_failed_pre_delivery_job_waits_for_other_running_operation(graph):
    package = planned(graph)
    now = NOW + timedelta(minutes=5)
    repository = SqlAlchemyScheduleRepository(sessionmaker(graph))
    accepted = repository.accept(
        ScheduledCommand(1, "publish_once", now, route_id=401, package_id=package)
    )
    leased = repository.claim_job(accepted.job_id, now=now)
    repository.acknowledge(leased.job_id, succeeded=False, now=now)
    with graph.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO operation_runs(project_id,operation,status,mode,actor,started_at) "
                "VALUES (1,'run_once','running','automatic','scheduler',:now)"
            ),
            {"now": now},
        )

    assert repository.claim_pending(now=now + timedelta(minutes=1)) == ()


def test_text_publication_confirms_once_without_media_cleanup(graph):
    package = planned(graph)
    with graph.begin() as connection:
        connection.execute(text("UPDATE content_packages SET media_path=NULL,media_mime=NULL WHERE id=:id"), {"id": package})
    sent = []
    class Publisher:
        def publish(self, claim):
            sent.append(claim)
            return TelegramMessage(987)
    class Media:
        def delete(self, path):
            pytest.fail("A text post has no file to delete")
    action = PublishContent(delivery(graph), Publisher(), Media(), timeout_seconds=60, clock=lambda: NOW + timedelta(minutes=5))
    assert action.execute(package_id=package).message_id == 987
    assert action.execute(package_id=package).outcome == "empty"
    assert len(sent) == 1
    assert review(graph).get_package(package).status == "published"


@pytest.mark.parametrize("policy", ["null", "missing"])
def test_default_startup_sends_all_approved_backlog_once_and_recovers_uncertain(graph, policy):
    from postify.infrastructure.repositories.sqlalchemy_observability import SqlAlchemyOperationRunRepository
    first = planned(graph)
    second = planned(graph, at=NOW + timedelta(minutes=7))
    unfinished = planned(graph, at=NOW + timedelta(minutes=1))
    assert delivery(graph).reserve_next(now=NOW + timedelta(minutes=1), package_id=unfinished) is not None
    awaiting = _seed_package(graph, status="awaiting_review")
    review(graph).save_plan(awaiting, scheduled_at=NOW + timedelta(minutes=10), route_id=401, now=NOW)
    rejected = _seed_package(graph, status="awaiting_review")
    review(graph).save_plan(rejected, scheduled_at=NOW + timedelta(minutes=11), route_id=401, now=NOW)
    review(graph).reject(rejected, now=NOW)
    with graph.begin() as connection:
        expression = "configuration - 'delivery_lateness_seconds'" if policy == "missing" else "configuration || jsonb_build_object('delivery_lateness_seconds', CAST(NULL AS integer))"
        connection.execute(text(f"UPDATE content_projects SET configuration={expression} WHERE id=1"))
    startup = NOW + timedelta(days=7, hours=1)
    sent = []
    class Publisher:
        def publish(self, claim):
            sent.append(claim.package_id)
            return TelegramMessage(900 + len(sent))
    class Media:
        def delete(self, path):
            pass
    schedules = SqlAlchemyScheduleRepository(sessionmaker(graph))
    journal = SqlAlchemyOperationRunRepository(sessionmaker(graph), project_id=1)
    def execute(command):
        result = PublishContent(delivery(graph), Publisher(), Media(), timeout_seconds=60, clock=lambda: startup).execute(package_id=command.package_id)
        journal.succeed(command.operation_run_id, outcome=result.outcome, now=startup)
        schedules.acknowledge(command.job_id, succeeded=True, now=startup)
    commands = ProjectScheduler(schedules, execute).tick(startup)
    assert [command.package_id for command in commands] == [first, second]
    assert sent == [first, second]
    assert review(graph).get_package(first).status == "published"
    assert review(graph).get_package(second).status == "published"
    assert review(graph).get_package(awaiting).status == "awaiting_review"
    assert review(graph).get_package(rejected).status == "rejected"
    with graph.connect() as connection:
        assert connection.execute(text("SELECT status,attempt_no FROM deliveries WHERE package_id=:id"), {"id":unfinished}).one() == ("uncertain", 1)
    assert delivery(graph).reserve_next(now=startup, package_id=unfinished) is None
    assert ProjectScheduler(SqlAlchemyScheduleRepository(sessionmaker(graph)), execute).tick(startup + timedelta(minutes=10)) == ()
    assert sent == [first, second]


def test_concurrent_approve_and_reject_preserve_single_editor_decision(graph):
    package = _seed_package(graph, status="awaiting_review")
    review(graph).save_plan(package, scheduled_at=NOW + timedelta(minutes=5), route_id=401, now=NOW)
    def decide(status):
        try:
            action = getattr(review(graph), status)
            return action(package, now=NOW).status
        except InvalidContentTransition:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(decide, ("approve", "reject")))
    assert outcomes.count("conflict") == 1
    final = review(graph).get_package(package).status
    assert final in {"approved", "rejected"}
    assert final in outcomes
    with graph.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM content_package_status_history WHERE package_id=:id AND status IN ('approved','rejected')"), {"id": package}).scalar_one() == 1


def test_scheduler_restart_recovers_sending_even_without_a_due_job(graph):
    package = planned(graph)
    at = NOW + timedelta(minutes=5)
    assert delivery(graph).reserve_next(now=at, package_id=package) is not None
    submitted = []
    with graph.begin() as connection:
        connection.execute(text("UPDATE content_projects SET configuration=configuration || '{\"analysis_timeout_seconds\": 1}'::jsonb WHERE id=1"))
    repository = SqlAlchemyScheduleRepository(sessionmaker(graph))
    ProjectScheduler(repository, submitted.append).tick(at + timedelta(seconds=2))
    assert submitted == []
    with graph.connect() as connection:
        assert connection.execute(text("SELECT status FROM deliveries WHERE package_id=:id"), {"id": package}).scalar_one() == "uncertain"
    assert delivery(graph).reserve_next(now=at + timedelta(seconds=3), package_id=package) is None


@pytest.mark.parametrize(("media_path", "length", "allowed"), [(None,4096,True),(None,4097,False),("/media/card.png",1024,True),("/media/card.png",1025,False)])
def test_approval_respects_telegram_text_and_caption_limits(graph, media_path, length, allowed):
    package = _seed_package(graph, status="awaiting_review")
    with graph.begin() as connection:
        connection.execute(text("UPDATE content_packages SET post_text=:text,media_path=:path WHERE id=:id"), {"id": package, "text": "Я" * length, "path": media_path})
    repository = review(graph)
    repository.save_plan(package, scheduled_at=NOW + timedelta(minutes=5), route_id=401, now=NOW)
    if allowed:
        assert repository.approve(package, now=NOW).status == "approved"
    else:
        with pytest.raises(InvalidContentTransition, match="символов"):
            repository.approve(package, now=NOW)
        assert repository.get_package(package).status == "awaiting_review"


def test_approved_destination_cannot_change_but_harmless_names_can(graph):
    from postify.infrastructure.repositories.sqlalchemy_projects import SqlAlchemyProjectRepository
    package = planned(graph)
    repository = SqlAlchemyProjectRepository(sessionmaker(graph))
    channel = repository.get_resource(1, "channels", 301)
    renamed = {**channel, "name": "Новое имя канала"}
    assert repository.update_resource(1, "channels", 301, renamed, NOW)["name"] == "Новое имя канала"
    with pytest.raises(ValueError, match="Назначение"):
        repository.update_resource(1, "channels", 301, {**renamed, "configuration": {"chat_id": "-100999"}}, NOW)
    with graph.begin() as connection:
        connection.execute(text("INSERT INTO channel_connections(id,project_id,provider,name,enabled,configuration,connection_status,created_at,updated_at) VALUES (302,1,'telegram','Other',true,'{}','ok',:now,:now)"), {"now": NOW})
    route = repository.get_resource(1, "routes", 401)
    with pytest.raises(ValueError, match="Назначение"):
        repository.update_resource(1, "routes", 401, {**route, "channel_id":302}, NOW)
    assert review(graph).get_package(package).status == "approved"
    assert repository.get_resource(1, "routes", 401)["channel_id"] == 301


def test_queue_keeps_future_and_due_active_plans_visible(graph):
    actual_now = NOW + timedelta(minutes=7)
    tomorrow_at = NOW + timedelta(days=1)
    tomorrow = planned(graph, at=tomorrow_at)
    past = planned(graph)
    rejected = _seed_package(graph, status="awaiting_review")
    review(graph).save_plan(rejected, scheduled_at=NOW + timedelta(days=2), route_id=401, now=NOW)
    review(graph).reject(rejected, now=NOW)
    rows = SqlAlchemyDashboardRepository(sessionmaker(graph)).queue(1, actual_now.date())
    assert {row.package_id for row in rows} == {tomorrow, past}
    assert next(row for row in rows if row.package_id == tomorrow).scheduled_at == tomorrow_at
    assert next(row for row in rows if row.package_id == past).status == "approved"


def test_approval_counts_emoji_as_two_utf16_units(graph):
    package = _seed_package(graph, status="awaiting_review")
    with graph.begin() as connection:
        connection.execute(text("UPDATE content_packages SET post_text=:text,media_path=NULL WHERE id=:id"), {"id":package, "text":"😀" * 2049})
    repository = review(graph)
    repository.save_plan(package, scheduled_at=NOW + timedelta(minutes=5), route_id=401, now=NOW)
    with pytest.raises(InvalidContentTransition, match="4096"):
        repository.approve(package, now=NOW)


def test_legacy_unaddressed_publication_job_is_closed_without_blocking_new_plan(graph):
    from postify.application.scheduling.project_scheduler import ScheduledCommand
    repository = SqlAlchemyScheduleRepository(sessionmaker(graph))
    assert repository.accept(ScheduledCommand(1, "publish_once", NOW, route_id=401)) is None
    with graph.begin() as connection:
        run = connection.execute(text("INSERT INTO operation_runs(project_id,operation,status,mode,actor,started_at) VALUES (1,'publish_once','running','automatic','scheduler',:now) RETURNING id"), {"now":NOW}).scalar_one()
        job = connection.execute(text("INSERT INTO scheduled_jobs(project_id,kind,route_id,scheduled_for,operation_run_id,status,attempt_count,created_at,updated_at) VALUES (1,'publish_once',401,:now,:run,'queued',0,:now,:now) RETURNING id"), {"run":run,"now":NOW}).scalar_one()
    assert repository.claim_pending(now=NOW) == ()
    with graph.connect() as connection:
        assert connection.execute(text("SELECT status,attempt_count FROM scheduled_jobs WHERE id=:id"), {"id":job}).one() == ("failed", 0)
        assert connection.execute(text("SELECT status,failure_code FROM operation_runs WHERE id=:id"), {"id":run}).one() == ("failed", "publish_once_failed")
    assert repository.claim_pending(now=NOW + timedelta(seconds=1)) == ()
    package = planned(graph)
    accepted = repository.accept(ScheduledCommand(1, "publish_once", NOW + timedelta(minutes=5), route_id=401, package_id=package))
    assert accepted is not None and accepted.package_id == package
