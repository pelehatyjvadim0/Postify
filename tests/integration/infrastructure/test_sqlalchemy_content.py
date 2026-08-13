from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker


pytestmark = pytest.mark.integration
NOW = datetime(2026, 8, 8, 9, tzinfo=UTC)


def _api():
    from postify.domain.content.models import ContentLimits
    from postify.infrastructure.repositories.sqlalchemy_content import SqlAlchemyContentRepository

    return ContentLimits, SqlAlchemyContentRepository


def _limits(ContentLimits, analysis_limit: int = 12, package_limit: int = 3):
    return ContentLimits(
        analysis_limit=analysis_limit,
        package_limit=package_limit,
        freshness_days=14,
        fresh_share=90,
        reserve_share=10,
    )


def _seed_selected(engine, discovered_values: list[datetime]) -> list[int]:
    identifiers: list[int] = []
    with engine.begin() as connection:
        for index, discovered_at in enumerate(discovered_values):
            candidate_id = connection.execute(
                text(
                    "INSERT INTO candidates "
                    "(project_id, source_name, source_id, title, url, discovered_at, raw_payload) "
                    "VALUES (1, 'hn', :source_id, :title, :url, :discovered_at, '{}'::jsonb) "
                    "RETURNING id"
                ),
                {
                    "source_id": f"content-{index}-{discovered_at.timestamp()}",
                    "title": f"Candidate {index}",
                    "url": f"https://source.test/{index}-{int(discovered_at.timestamp())}",
                    "discovered_at": discovered_at,
                },
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO candidate_decisions "
                    "(project_id, candidate_id, status, reason, explanation, signals, policy_version, decided_at) "
                    "VALUES (1, :candidate_id, 'selected', 'eligible_for_ai', 'eligible', "
                    "'{}'::jsonb, 'v1', :decided_at)"
                ),
                {"candidate_id": candidate_id, "decided_at": NOW},
            )
            identifiers.append(candidate_id)
    return identifiers


def test_claim_enforces_daily_limit_and_never_claims_candidate_twice(
    migrated_database_url: str,
) -> None:
    # Поломка (gate 1/3): повторный run превышает 12 или дублирует attempt.
    ContentLimits, Repository = _api()
    engine = create_engine(migrated_database_url)
    _seed_selected(engine, [NOW - timedelta(days=1)] * 20)
    repository = Repository(sessionmaker(engine))

    try:
        first = repository.claim(now=NOW, day=NOW.date(), limits=_limits(ContentLimits))
        second = repository.claim(now=NOW, day=NOW.date(), limits=_limits(ContentLimits))
        with engine.connect() as connection:
            usage = connection.execute(
                text("SELECT analyses_started, packages_created FROM content_daily_usage")
            ).one()
            rows = connection.execute(
                text("SELECT candidate_id, attempt_no FROM content_attempts")
            ).all()

        assert len(first) == 12
        assert second == ()
        assert usage == (12, 0)
        assert len(rows) == 12
        assert len(set(rows)) == 12
        assert {attempt.attempt_no for attempt in first} == {1}
    finally:
        engine.dispose()


def test_project_cleanup_preserves_other_projects_active_media(
    migrated_database_url: str, tmp_path: Path
) -> None:
    # Поломка: run project 1 сканирует общий media root и удаляет active-файл project 2.
    import httpx

    from postify.adapters.http.public_url_policy import PublicHttpUrlPolicy
    from postify.adapters.media.local_media_provider import LocalMediaProvider
    from postify.application.content.process_content import ProcessContent
    from postify.domain.content.models import ContentLimits
    from postify.infrastructure.repositories.sqlalchemy_content import (
        SqlAlchemyContentRepository,
    )

    engine = create_engine(migrated_database_url)
    media_path = tmp_path / "other-project-active.png"
    media_path.write_bytes(b"project-2-media")
    old = (NOW - timedelta(days=4)).timestamp()
    os.utime(media_path, (old, old))
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """INSERT INTO content_projects
                    (id,name,topic,language,audience,timezone,configuration,created_at,updated_at)
                    VALUES (2,'Второй','AI','ru','Команды','UTC','{}'::jsonb,:now,:now)"""
                ),
                {"now": NOW},
            )
            candidate_id = connection.execute(
                text(
                    """INSERT INTO candidates
                    (project_id,source_name,source_id,title,url,discovered_at,raw_payload)
                    VALUES (2,'source','other-active','Other','https://example.com/other',:now,'{}'::jsonb)
                    RETURNING id"""
                ),
                {"now": NOW},
            ).scalar_one()
            attempt_id = connection.execute(
                text(
                    """INSERT INTO content_attempts
                    (project_id,candidate_id,attempt_no,tier,status,source_url,started_at)
                    VALUES (2,:candidate,1,'fresh','packaged','https://example.com/other',:now)
                    RETURNING id"""
                ),
                {"candidate": candidate_id, "now": NOW},
            ).scalar_one()
            connection.execute(
                text(
                    """INSERT INTO content_packages
                    (project_id,attempt_id,source_url,context,analysis,post_text,media_path,
                     media_mime,review_required,status,generation_snapshot,created_at,updated_at)
                    VALUES (2,:attempt,'https://example.com/other','ctx','analysis','post',:path,
                            'image/png',true,'approved','{}'::jsonb,:now,:now)"""
                ),
                {"attempt": attempt_id, "path": str(media_path), "now": NOW},
            )

        class Unused:
            def __getattr__(self, name):
                raise AssertionError(name)

        repository = SqlAlchemyContentRepository(sessionmaker(engine), project_id=1)
        with httpx.Client() as client:
            processor = ProcessContent(
                repository,
                Unused(),
                Unused(),
                LocalMediaProvider(
                    client,
                    tmp_path,
                    1_000_000,
                    None,
                    url_policy=PublicHttpUrlPolicy(),
                ),
                limits=ContentLimits(1, 1, 1, 100, 0),
                review_required=True,
                timezone="UTC",
                clock=lambda: NOW,
            )

            result = processor.execute()

        assert result.claimed == 0
        assert media_path.read_bytes() == b"project-2-media"
    finally:
        engine.dispose()


def test_postgresql_weighted_claim_persists_exact_54_6_over_five_days(
    migrated_database_url: str,
) -> None:
    # Поломка (gate 2): DB claim не хранит credits между днями.
    ContentLimits, Repository = _api()
    engine = create_engine(migrated_database_url)
    _seed_selected(
        engine,
        [NOW - timedelta(days=1)] * 70 + [NOW - timedelta(days=100)] * 30,
    )
    repository = Repository(sessionmaker(engine))

    try:
        daily: list[tuple[int, int]] = []
        for offset in range(5):
            current = NOW + timedelta(days=offset)
            claimed = repository.claim(
                now=current,
                day=current.date(),
                limits=_limits(ContentLimits),
            )
            daily.append(
                (
                    sum(item.tier == "fresh" for item in claimed),
                    sum(item.tier == "reserve" for item in claimed),
                )
            )

        assert sum(item[0] for item in daily) == 54
        assert sum(item[1] for item in daily) == 6
        assert len(set(daily)) > 1
    finally:
        engine.dispose()


def test_due_retry_waits_six_hours_consumes_slot_and_second_failure_is_terminal(
    migrated_database_url: str,
) -> None:
    # Поломка (gate 5): retry слишком рано/не входит в budget/повторяется третий раз.
    ContentLimits, Repository = _api()
    engine = create_engine(migrated_database_url)
    _seed_selected(engine, [NOW - timedelta(days=1)])
    repository = Repository(sessionmaker(engine))

    try:
        first = repository.claim(now=NOW, day=NOW.date(), limits=_limits(ContentLimits))[0]
        repository.schedule_article_retry(first.id, retry_at=NOW + timedelta(hours=6), now=NOW)

        assert repository.claim(
            now=NOW + timedelta(hours=5, minutes=59),
            day=NOW.date(),
            limits=_limits(ContentLimits),
        ) == ()
        retry = repository.claim(
            now=NOW + timedelta(hours=6),
            day=NOW.date(),
            limits=_limits(ContentLimits),
        )[0]
        assert retry.candidate_id == first.candidate_id
        assert retry.attempt_no == 2
        repository.fail_attempt(retry.id, code="article_unavailable", now=NOW + timedelta(hours=6))

        assert repository.claim(
            now=NOW + timedelta(days=1),
            day=(NOW + timedelta(days=1)).date(),
            limits=_limits(ContentLimits),
        ) == ()
        with engine.connect() as connection:
            started = connection.execute(
                text(
                    "SELECT analyses_started FROM content_daily_usage "
                    "WHERE day = :day"
                ),
                {"day": NOW.date()},
            ).scalar_one()
        assert started == 2
    finally:
        engine.dispose()


def test_two_concurrent_claims_share_budget_without_duplicates(
    migrated_database_url: str,
) -> None:
    # Поломка (gate 1/3): concurrent transactions обе видят свободные 12 слотов.
    ContentLimits, Repository = _api()
    engine = create_engine(migrated_database_url, pool_size=4)
    _seed_selected(engine, [NOW - timedelta(days=1)] * 24)
    repository = Repository(sessionmaker(engine))

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            batches = list(
                executor.map(
                    lambda _: repository.claim(
                        now=NOW,
                        day=NOW.date(),
                        limits=_limits(ContentLimits),
                    ),
                    range(2),
                )
            )
        claimed = [item for batch in batches for item in batch]
        with engine.connect() as connection:
            total = connection.execute(text("SELECT count(*) FROM content_attempts")).scalar_one()

        assert len(claimed) == 12
        assert total == 12
        assert len({item.candidate_id for item in claimed}) == 12
    finally:
        engine.dispose()


def test_claim_sql_failure_rolls_back_usage_quota_and_attempts(
    migrated_database_url: str,
) -> None:
    # Поломка (gate 11): partial claim съедает budget/credit после SQL rollback.
    ContentLimits, Repository = _api()
    engine = create_engine(migrated_database_url)
    _seed_selected(engine, [NOW - timedelta(days=1)] * 2)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE FUNCTION fail_content_attempt_insert() RETURNS trigger LANGUAGE plpgsql AS $$ "
                "BEGIN RAISE EXCEPTION 'forced claim failure'; END $$"
            )
        )
        connection.execute(
            text(
                "CREATE TRIGGER fail_content_attempt BEFORE INSERT ON content_attempts "
                "FOR EACH ROW EXECUTE FUNCTION fail_content_attempt_insert()"
            )
        )
    repository = Repository(sessionmaker(engine))

    try:
        with pytest.raises(DBAPIError):
            repository.claim(now=NOW, day=NOW.date(), limits=_limits(ContentLimits))

        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM content_attempts")).scalar_one() == 0
            assert connection.execute(text("SELECT count(*) FROM content_daily_usage")).scalar_one() == 0
            assert connection.execute(text("SELECT count(*) FROM content_quota_state")).scalar_one() == 0
    finally:
        engine.dispose()


def _analysis_api():
    from postify.domain.content.models import (
        AnalyzedTopic,
        BatchAnalysis,
        ExtractedArticle,
    )

    return AnalyzedTopic, BatchAnalysis, ExtractedArticle


def _article_and_topic(identifier: int):
    AnalyzedTopic, _, ExtractedArticle = _analysis_api()
    article = ExtractedArticle(
        source_url=f"https://source.test/{identifier}",
        title=f"Article {identifier}",
        text=f"ARTICLE-BODY-{identifier} practical full source context.",
        image_candidates=(("og", f"https://cdn.test/{identifier}.jpg"),),
    )
    topic = AnalyzedTopic(
        attempt_id=identifier,
        analysis=f"Анализ {identifier}",
        usefulness=80,
        post_text=f"Пост {identifier}",
        media_query=f"query {identifier}",
    )
    return article, topic


def test_concurrent_package_reservation_never_exceeds_three(
    migrated_database_url: str,
) -> None:
    # Поломка (gate 1/3): два AI batch одновременно создают 4 пакета при лимите 3.
    ContentLimits, Repository = _api()
    _, BatchAnalysis, _ = _analysis_api()
    engine = create_engine(migrated_database_url, pool_size=4)
    _seed_selected(engine, [NOW - timedelta(days=1)] * 4)
    repository = Repository(sessionmaker(engine))

    try:
        claimed = repository.claim(
            now=NOW,
            day=NOW.date(),
            limits=_limits(ContentLimits),
        )
        articles: dict[int, object] = {}
        topics: dict[int, object] = {}
        for attempt in claimed:
            article, topic = _article_and_topic(attempt.id)
            articles[attempt.id] = article
            topics[attempt.id] = topic
            repository.save_extracted(attempt.id, article)

        batches = [
            BatchAnalysis(
                topics=tuple(topics[item.id] for item in pair),
                requested_attempt_ids=tuple(item.id for item in pair),
                package_limit=3,
            )
            for pair in (claimed[:2], claimed[2:])
        ]

        def save(batch):
            batch_articles = {topic.attempt_id: articles[topic.attempt_id] for topic in batch.topics}
            return repository.save_analysis_and_create_packages(
                batch,
                articles=batch_articles,
                review_required=True,
                now=NOW,
                day=NOW.date(),
                package_limit=3,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            drafts = [draft for batch in executor.map(save, batches) for draft in batch]

        with engine.connect() as connection:
            packages = connection.execute(text("SELECT count(*) FROM content_packages")).scalar_one()
            histories = connection.execute(
                text("SELECT count(*) FROM content_package_status_history")
            ).scalar_one()
            package_usage = connection.execute(
                text("SELECT packages_created FROM content_daily_usage WHERE day = :day"),
                {"day": NOW.date()},
            ).scalar_one()
        assert len(drafts) == 3
        assert packages == 3
        assert histories == 6
        assert package_usage == 3
    finally:
        engine.dispose()


def test_package_history_sql_failure_rolls_back_analysis_package_and_budget(
    migrated_database_url: str,
) -> None:
    # Поломка (gate 11): history INSERT падает после пакета, оставляя partial state/budget.
    ContentLimits, Repository = _api()
    _, BatchAnalysis, _ = _analysis_api()
    engine = create_engine(migrated_database_url)
    _seed_selected(engine, [NOW - timedelta(days=1)])
    repository = Repository(sessionmaker(engine))

    try:
        attempt = repository.claim(
            now=NOW,
            day=NOW.date(),
            limits=_limits(ContentLimits),
        )[0]
        article, topic = _article_and_topic(attempt.id)
        repository.save_extracted(attempt.id, article)
        batch = BatchAnalysis(
            topics=(topic,),
            requested_attempt_ids=(attempt.id,),
            package_limit=3,
        )
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE FUNCTION fail_content_history_insert() RETURNS trigger LANGUAGE plpgsql AS $$ "
                    "BEGIN RAISE EXCEPTION 'forced history failure'; END $$"
                )
            )
            connection.execute(
                text(
                    "CREATE TRIGGER fail_content_history BEFORE INSERT "
                    "ON content_package_status_history FOR EACH ROW "
                    "EXECUTE FUNCTION fail_content_history_insert()"
                )
            )

        with pytest.raises(DBAPIError):
            repository.save_analysis_and_create_packages(
                batch,
                articles={attempt.id: article},
                review_required=True,
                now=NOW,
                day=NOW.date(),
                package_limit=3,
            )

        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM content_packages")).scalar_one() == 0
            assert connection.execute(
                text("SELECT count(*) FROM content_package_status_history")
            ).scalar_one() == 0
            row = connection.execute(
                text(
                    "SELECT analysis, packages_created FROM content_attempts a "
                    "JOIN content_daily_usage u ON u.day = :day WHERE a.id = :id"
                ),
                {"day": NOW.date(), "id": attempt.id},
            ).one()
        assert row == (None, 0)
    finally:
        engine.dispose()


def test_repository_returns_full_package_and_review_history_atomically(
    migrated_database_url: str,
) -> None:
    # Поломка (gate 6/7/11): show теряет audit-поле или approve не добавляет history.
    _, Repository = _api()
    engine = create_engine(migrated_database_url)
    candidate_id = _seed_selected(engine, [NOW - timedelta(days=1)])[0]
    with engine.begin() as connection:
        attempt_id = connection.execute(
            text(
                "INSERT INTO content_attempts "
                "(project_id, candidate_id, attempt_no, tier, status, source_url, article_title, article_text, "
                "analysis, failure_code, retry_at, started_at, finished_at) VALUES "
                "(1, :candidate_id, 1, 'fresh', 'completed', :url, 'Article', :context, :analysis, "
                "NULL, NULL, :now, :now) RETURNING id"
            ),
            {
                "candidate_id": candidate_id,
                "url": "https://source.test/audit",
                "context": "ARTICLE-BODY audit context",
                "analysis": "Анализ",
                "now": NOW,
            },
        ).scalar_one()
        package_id = connection.execute(
            text(
                "INSERT INTO content_packages "
                "(project_id, attempt_id, source_url, context, analysis, post_text, media_path, media_mime, "
                "media_source_type, media_source_url, review_required, status, media_deleted_at, "
                "created_at, updated_at) VALUES "
                "(1, :attempt_id, :url, :context, :analysis, :post, :path, 'image/jpeg', 'og', "
                ":media_url, true, 'awaiting_review', NULL, :now, :now) RETURNING id"
            ),
            {
                "attempt_id": attempt_id,
                "url": "https://source.test/audit",
                "context": "ARTICLE-BODY audit context",
                "analysis": "Анализ",
                "post": "Пост без URL",
                "path": "/media/audit.jpg",
                "media_url": "https://cdn.test/audit.jpg",
                "now": NOW,
            },
        ).scalar_one()
        for status in ("not_started", "processing", "awaiting_review"):
            connection.execute(
                text(
                    "INSERT INTO content_package_status_history "
                    "(project_id, package_id, status, reason, created_at) VALUES "
                    "(1, :package_id, :status, 'test', :now)"
                ),
                {"package_id": package_id, "status": status, "now": NOW},
            )
    repository = Repository(sessionmaker(engine))

    try:
        package = repository.get_package(package_id)
        assert package.source_url == "https://source.test/audit"
        assert package.context == "ARTICLE-BODY audit context"
        assert package.analysis == "Анализ"
        assert package.post_text == "Пост без URL"
        assert package.media_path == "/media/audit.jpg"
        assert package.media_source_type == "og"
        assert package.media_source_url == "https://cdn.test/audit.jpg"
        assert [item.status for item in package.history] == [
            "not_started", "processing", "awaiting_review"
        ]

        approved = repository.approve(package_id, now=NOW + timedelta(minutes=1))
        assert approved.status == "approved"
        assert [item.status for item in approved.history][-1] == "approved"
        with engine.connect() as connection:
            stored = connection.execute(
                text(
                    "SELECT p.status, count(h.id) FROM content_packages p "
                    "JOIN content_package_status_history h ON h.package_id = p.id "
                    "WHERE p.id = :id GROUP BY p.status"
                ),
                {"id": package_id},
            ).one()
        assert stored == ("approved", 4)
    finally:
        engine.dispose()


def test_due_fresh_retry_consumes_persisted_weighted_credit_before_new_claim(
    migrated_database_url: str,
) -> None:
    # Поломка re-review 3: due retry занимает слот, но не изменяет persisted credits.
    ContentLimits, Repository = _api()
    engine = create_engine(migrated_database_url)
    _seed_selected(engine, [NOW - timedelta(days=1)] * 2)
    repository = Repository(sessionmaker(engine))

    try:
        first = repository.claim(
            now=NOW,
            day=NOW.date(),
            limits=_limits(ContentLimits, analysis_limit=1),
        )[0]
        repository.schedule_article_retry(
            first.id,
            retry_at=NOW + timedelta(hours=6),
            now=NOW,
        )
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE content_quota_state SET fresh_credit=0,reserve_credit=0 "
                    "WHERE id=1"
                )
            )

        next_day = NOW + timedelta(days=1)
        claimed = repository.claim(
            now=next_day,
            day=next_day.date(),
            limits=_limits(ContentLimits, analysis_limit=2),
        )
        with engine.connect() as connection:
            credits = connection.execute(
                text(
                    "SELECT fresh_credit,reserve_credit FROM content_quota_state "
                    "WHERE id=1"
                )
            ).one()

        assert [(item.attempt_no, item.tier) for item in claimed] == [
            (2, "fresh"),
            (1, "fresh"),
        ]
        assert credits == (-20, 20)
    finally:
        engine.dispose()


def _seed_processing_package(engine) -> tuple[int, int]:
    candidate_id = _seed_selected(engine, [NOW - timedelta(days=1)])[0]
    with engine.begin() as connection:
        attempt_id = connection.execute(
            text(
                "INSERT INTO content_attempts "
                "(project_id,candidate_id,attempt_no,tier,status,source_url,article_title,article_text,"
                "analysis,started_at) VALUES "
                "(1,:candidate_id,1,'fresh','processing',:url,'Article',:body,:analysis,:now) "
                "RETURNING id"
            ),
            {
                "candidate_id": candidate_id,
                "url": "https://source.test/atomic",
                "body": "ARTICLE-BODY atomic context",
                "analysis": "Атомарный анализ",
                "now": NOW,
            },
        ).scalar_one()
        package_id = connection.execute(
            text(
                "INSERT INTO content_packages "
                "(project_id,attempt_id,source_url,context,analysis,post_text,review_required,status,"
                "created_at,updated_at) VALUES "
                "(1,:attempt_id,:url,:body,:analysis,:post,true,'processing',:now,:now) "
                "RETURNING id"
            ),
            {
                "attempt_id": attempt_id,
                "url": "https://source.test/atomic",
                "body": "ARTICLE-BODY atomic context",
                "analysis": "Атомарный анализ",
                "post": "Русский пост",
                "now": NOW,
            },
        ).scalar_one()
        for status in ("not_started", "processing"):
            connection.execute(
                text(
                    "INSERT INTO content_package_status_history "
                    "(project_id,package_id,status,reason,created_at) "
                    "VALUES (1,:package_id,:status,'generated',:now)"
                ),
                {"package_id": package_id, "status": status, "now": NOW},
            )
    return attempt_id, package_id


def test_complete_package_rejects_nonterminal_target_without_mutating_state(
    migrated_database_url: str,
) -> None:
    # Поломка fix round 1: processing -> processing завершает attempt и пишет history.
    _, Repository = _api()
    from postify.domain.content.models import (
        ContentValidationError,
        InvalidContentTransition,
        StoredMedia,
    )

    engine = create_engine(migrated_database_url)
    attempt_id, package_id = _seed_processing_package(engine)
    repository = Repository(sessionmaker(engine))

    def snapshot():
        with engine.connect() as connection:
            package = connection.execute(
                text(
                    "SELECT status,media_path,media_mime,media_source_type,media_source_url "
                    "FROM content_packages WHERE id=:id"
                ),
                {"id": package_id},
            ).one()
            attempt = connection.execute(
                text(
                    "SELECT status,failure_code,finished_at FROM content_attempts "
                    "WHERE id=:id"
                ),
                {"id": attempt_id},
            ).one()
            history_count = connection.execute(
                text(
                    "SELECT count(*) FROM content_package_status_history "
                    "WHERE package_id=:id"
                ),
                {"id": package_id},
            ).scalar_one()
        return package, attempt, history_count

    try:
        before = snapshot()
        error: ContentValidationError | None = None
        try:
            repository.complete_package(
                package_id,
                media=StoredMedia(
                    "/media/must-not-stick.jpg",
                    "image/jpeg",
                    "og",
                    "https://cdn.test/must-not-stick.jpg",
                ),
                status="processing",
                now=NOW + timedelta(minutes=1),
            )
        except ContentValidationError as caught:
            error = caught

        assert snapshot() == before
        assert isinstance(error, InvalidContentTransition)
    finally:
        engine.dispose()


@pytest.mark.parametrize("operation", ["complete", "fail"])
def test_package_terminal_history_failure_rolls_back_package_and_attempt(
    migrated_database_url: str, operation: str
) -> None:
    # Поломка re-review 4: package/attempt commit происходит до terminal history INSERT.
    _, Repository = _api()
    from postify.domain.content.models import StoredMedia

    engine = create_engine(migrated_database_url)
    attempt_id, package_id = _seed_processing_package(engine)
    repository = Repository(sessionmaker(engine))
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE FUNCTION fail_terminal_history_insert() RETURNS trigger "
                "LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'forced terminal history failure'; "
                "END $$"
            )
        )
        connection.execute(
            text(
                "CREATE TRIGGER fail_terminal_history BEFORE INSERT "
                "ON content_package_status_history FOR EACH ROW "
                "EXECUTE FUNCTION fail_terminal_history_insert()"
            )
        )

    try:
        with pytest.raises(DBAPIError):
            if operation == "complete":
                repository.complete_package(
                    package_id,
                    media=StoredMedia(
                        "/media/atomic.jpg",
                        "image/jpeg",
                        "og",
                        "https://cdn.test/atomic.jpg",
                    ),
                    status="awaiting_review",
                    now=NOW + timedelta(minutes=1),
                )
            else:
                repository.fail_package(
                    package_id,
                    code="media_failed",
                    now=NOW + timedelta(minutes=1),
                )

        with engine.connect() as connection:
            package = connection.execute(
                text(
                    "SELECT status,media_path,media_mime,media_source_type,media_source_url "
                    "FROM content_packages WHERE id=:id"
                ),
                {"id": package_id},
            ).one()
            attempt = connection.execute(
                text(
                    "SELECT status,failure_code,finished_at FROM content_attempts WHERE id=:id"
                ),
                {"id": attempt_id},
            ).one()
            history_count = connection.execute(
                text(
                    "SELECT count(*) FROM content_package_status_history "
                    "WHERE package_id=:id"
                ),
                {"id": package_id},
            ).scalar_one()
        assert package == ("processing", None, None, None, None)
        assert attempt == ("processing", None, None)
        assert history_count == 2
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("operation", "expected_package", "expected_attempt", "expected_code"),
    [
        ("complete", "awaiting_review", "packaged", None),
        ("fail", "failed", "failed", "media_failed"),
    ],
)
def test_package_terminal_operation_updates_attempt_and_history_together(
    migrated_database_url: str,
    operation: str,
    expected_package: str,
    expected_attempt: str,
    expected_code: str | None,
) -> None:
    # Поломка re-review 4/8: terminal package оставляет attempt processing без outcome.
    _, Repository = _api()
    from postify.domain.content.models import StoredMedia

    engine = create_engine(migrated_database_url)
    attempt_id, package_id = _seed_processing_package(engine)
    repository = Repository(sessionmaker(engine))
    finished_at = NOW + timedelta(minutes=1)

    try:
        if operation == "complete":
            repository.complete_package(
                package_id,
                media=StoredMedia(
                    "/media/atomic.jpg",
                    "image/jpeg",
                    "og",
                    "https://cdn.test/atomic.jpg",
                ),
                status=expected_package,
                now=finished_at,
            )
        else:
            repository.fail_package(
                package_id,
                code="media_failed",
                now=finished_at,
            )

        with engine.connect() as connection:
            package = connection.execute(
                text(
                    "SELECT status,media_path FROM content_packages WHERE id=:id"
                ),
                {"id": package_id},
            ).one()
            attempt = connection.execute(
                text(
                    "SELECT status,failure_code,finished_at FROM content_attempts WHERE id=:id"
                ),
                {"id": attempt_id},
            ).one()
            history = connection.execute(
                text(
                    "SELECT status FROM content_package_status_history "
                    "WHERE package_id=:id ORDER BY id"
                ),
                {"id": package_id},
            ).scalars().all()
        assert package[0] == expected_package
        assert package[1] == (
            "/media/atomic.jpg" if operation == "complete" else None
        )
        assert attempt == (expected_attempt, expected_code, finished_at)
        assert history == ["not_started", "processing", expected_package]
    finally:
        engine.dispose()


def test_repository_finishes_every_analyzed_attempt_with_selected_outcome(
    migrated_database_url: str,
) -> None:
    # Поломка re-review 8: nonselected/selected AI successes остаются processing.
    ContentLimits, Repository = _api()
    AnalyzedTopic, BatchAnalysis, _ = _analysis_api()
    from postify.domain.content.models import StoredMedia

    engine = create_engine(migrated_database_url)
    _seed_selected(engine, [NOW - timedelta(days=1)] * 3)
    repository = Repository(sessionmaker(engine))

    try:
        claimed = repository.claim(
            now=NOW,
            day=NOW.date(),
            limits=_limits(ContentLimits),
        )
        articles: dict[int, object] = {}
        topics = []
        for index, attempt in enumerate(claimed):
            article, _ = _article_and_topic(attempt.id)
            articles[attempt.id] = article
            repository.save_extracted(attempt.id, article)
            selected = index < 2
            topics.append(
                AnalyzedTopic(
                    attempt_id=attempt.id,
                    analysis=f"Полный анализ {attempt.id}",
                    usefulness=90 - index,
                    selected=selected,
                    post_text=f"Русский пост {attempt.id}" if selected else None,
                    media_query=f"query {attempt.id}" if selected else None,
                )
            )
        batch = BatchAnalysis(
            topics=tuple(topics),
            requested_attempt_ids=tuple(item.id for item in claimed),
            package_limit=2,
        )
        drafts = repository.save_analysis_and_create_packages(
            batch,
            articles=articles,
            review_required=True,
            now=NOW,
            day=NOW.date(),
            package_limit=2,
        )
        repository.complete_package(
            drafts[0].package_id,
            media=StoredMedia(
                "/media/selected.jpg",
                "image/jpeg",
                "og",
                "https://cdn.test/selected.jpg",
            ),
            status="awaiting_review",
            now=NOW + timedelta(minutes=1),
        )
        repository.fail_package(
            drafts[1].package_id,
            code="media_failed",
            now=NOW + timedelta(minutes=1),
        )

        with engine.connect() as connection:
            outcomes = connection.execute(
                text(
                    "SELECT id,status,analysis,failure_code,finished_at "
                    "FROM content_attempts ORDER BY id"
                )
            ).all()
            package_count = connection.execute(
                text("SELECT count(*) FROM content_packages")
            ).scalar_one()
        assert [row.status for row in outcomes] == [
            "packaged",
            "failed",
            "analyzed_not_selected",
        ]
        assert all(row.analysis for row in outcomes)
        assert outcomes[0].failure_code is None
        assert outcomes[1].failure_code == "media_failed"
        assert outcomes[2].failure_code is None
        assert all(row.finished_at == NOW + timedelta(minutes=1) for row in outcomes[:2])
        assert outcomes[2].finished_at == NOW
        assert package_count == 2
        assert "processing" not in {row.status for row in outcomes}
    finally:
        engine.dispose()
