from __future__ import annotations
from dataclasses import dataclass
from datetime import timedelta
from sqlalchemy import text
from postify.domain.content.models import ContentPackage
from postify.domain.content.quota import QuotaState, choose_tier, consume_tier_credit
from postify.application.ports.content_repository import PackageDraft


@dataclass(frozen=True, slots=True)
class ClaimedAttempt:
    id: int
    candidate_id: int
    attempt_no: int
    tier: str
    source_url: str
    title: str
    snippet: str = ""


class SqlAlchemyContentRepository:
    def __init__(self, session_factory):
        self.sf = session_factory

    def claim(self, *, now, day, limits):
        with self.sf() as s:
            try:
                s.execute(
                    text(
                        "INSERT INTO content_daily_usage(day,analyses_started,packages_created) VALUES (:d,0,0) ON CONFLICT (day) DO NOTHING"
                    ),
                    {"d": day},
                )
                usage = s.execute(
                    text(
                        "SELECT analyses_started FROM content_daily_usage WHERE day=:d FOR UPDATE"
                    ),
                    {"d": day},
                ).scalar_one()
                slots = limits.analysis_limit - usage
                if slots <= 0:
                    s.commit()
                    return ()
                s.execute(
                    text(
                        "INSERT INTO content_quota_state(id,fresh_credit,reserve_credit,updated_at) VALUES (1,0,0,:n) ON CONFLICT (id) DO NOTHING"
                    ),
                    {"n": now},
                )
                credits = s.execute(
                    text(
                        "SELECT fresh_credit,reserve_credit FROM content_quota_state WHERE id=1 FOR UPDATE"
                    )
                ).one()
                state = QuotaState(*credits)
                retry = s.execute(
                    text(
                        "SELECT a.id,a.candidate_id,2,a.source_url,c.title FROM content_attempts a JOIN candidates c ON c.id=a.candidate_id WHERE a.status='retry_scheduled' AND a.retry_at<=:n ORDER BY a.retry_at FOR UPDATE SKIP LOCKED"
                    ),
                    {"n": now},
                ).all()
                rows = []
                for r in retry:
                    if len(rows) >= slots:
                        break
                    tier = (
                        "fresh"
                        if s.execute(
                            text(
                                "SELECT discovered_at >= :cut FROM candidates WHERE id=:id"
                            ),
                            {
                                "cut": now - timedelta(days=limits.freshness_days),
                                "id": r.candidate_id,
                            },
                        ).scalar()
                        else "reserve"
                    )
                    state = consume_tier_credit(
                        state,
                        tier=tier,
                        fresh_share=limits.fresh_share,
                        reserve_share=limits.reserve_share,
                    )
                    s.execute(
                        text(
                            "UPDATE content_attempts SET status='retried' WHERE id=:id"
                        ),
                        {"id": r.id},
                    )
                    s.execute(
                        text(
                            "INSERT INTO content_attempts(candidate_id,attempt_no,tier,status,source_url,started_at) VALUES (:c,2,:t,'processing',:u,:n)"
                        ),
                        {"c": r.candidate_id, "t": tier, "u": r.source_url, "n": now},
                    )
                    rows.append((r.candidate_id, 2, tier, r.source_url, r.title))
                candidates = s.execute(
                    text(
                        "SELECT c.id,c.url,c.title,c.discovered_at FROM candidates c JOIN candidate_decisions d ON d.candidate_id=c.id AND d.status='selected' WHERE NOT EXISTS (SELECT 1 FROM content_attempts a WHERE a.candidate_id=c.id) ORDER BY c.id FOR UPDATE OF c SKIP LOCKED"
                    )
                ).all()
                fresh = [
                    r
                    for r in candidates
                    if r.discovered_at >= now - timedelta(days=limits.freshness_days)
                ]
                reserve = [r for r in candidates if r not in fresh]
                while len(rows) < slots and (fresh or reserve):
                    tier, state = choose_tier(
                        state,
                        fresh_available=bool(fresh),
                        reserve_available=bool(reserve),
                        fresh_share=limits.fresh_share,
                        reserve_share=limits.reserve_share,
                    )
                    pool = fresh if tier == "fresh" else reserve
                    r = pool.pop(0)
                    s.execute(
                        text(
                            "INSERT INTO content_attempts(candidate_id,attempt_no,tier,status,source_url,started_at) VALUES (:c,1,:t,'processing',:u,:n)"
                        ),
                        {"c": r.id, "t": tier, "u": r.url, "n": now},
                    )
                    rows.append((r.id, 1, tier, r.url, r.title))
                s.execute(
                    text(
                        "UPDATE content_daily_usage SET analyses_started=analyses_started+:n WHERE day=:d"
                    ),
                    {"n": len(rows), "d": day},
                )
                s.execute(
                    text(
                        "UPDATE content_quota_state SET fresh_credit=:f,reserve_credit=:r,updated_at=:n WHERE id=1"
                    ),
                    {"f": state.fresh_credit, "r": state.reserve_credit, "n": now},
                )
                s.flush()
                ids = s.execute(
                    text(
                        "SELECT id,candidate_id,attempt_no,tier,source_url FROM content_attempts WHERE started_at=:n ORDER BY id"
                    ),
                    {"n": now},
                ).all()
                s.commit()
                titles = {x[0]: x[4] for x in rows}
                return tuple(
                    ClaimedAttempt(
                        x.id,
                        x.candidate_id,
                        x.attempt_no,
                        x.tier,
                        x.source_url,
                        titles.get(x.candidate_id, ""),
                    )
                    for x in ids
                )
            except:
                s.rollback()
                raise

    def schedule_article_retry(self, id, *, retry_at, now):
        self._execute(
            "UPDATE content_attempts SET status='retry_scheduled',retry_at=:r,finished_at=:n WHERE id=:id",
            id=id,
            r=retry_at,
            n=now,
        )

    def fail_attempt(self, id, *, code, now):
        self._execute(
            "UPDATE content_attempts SET status='failed',failure_code=:c,finished_at=:n WHERE id=:id",
            id=id,
            c=str(code),
            n=now,
        )

    def save_extracted(self, id, article):
        self._execute(
            "UPDATE content_attempts SET article_title=:t,article_text=:x WHERE id=:id",
            id=id,
            t=article.title,
            x=article.text,
        )

    def package_slots_remaining(self, *, day, limit):
        with self.sf() as s:
            return limit - (
                s.execute(
                    text(
                        "SELECT packages_created FROM content_daily_usage WHERE day=:d"
                    ),
                    {"d": day},
                ).scalar()
                or 0
            )

    def save_analysis_and_create_packages(
        self, batch, *, articles, review_required, now, day, package_limit
    ):
        with self.sf() as s:
            try:
                s.execute(
                    text(
                        "INSERT INTO content_daily_usage(day,analyses_started,packages_created) VALUES (:d,0,0) ON CONFLICT DO NOTHING"
                    ),
                    {"d": day},
                )
                used = s.execute(
                    text(
                        "SELECT packages_created FROM content_daily_usage WHERE day=:d FOR UPDATE"
                    ),
                    {"d": day},
                ).scalar_one()
                for topic in batch.topics:
                    s.execute(
                        text(
                            "UPDATE content_attempts SET analysis=:a,"
                            "status=CASE WHEN :selected THEN status ELSE 'analyzed_not_selected' END,"
                            "failure_code=CASE WHEN :selected THEN failure_code ELSE NULL END,"
                            "finished_at=CASE WHEN :selected THEN finished_at ELSE :n END WHERE id=:id"
                        ),
                        {
                            "a": topic.analysis,
                            "selected": topic.selected,
                            "n": now,
                            "id": topic.attempt_id,
                        },
                    )

                available = max(0, package_limit - used)
                selected_topics = batch.selected_topics
                packaged_topics = selected_topics[:available]
                for topic in selected_topics[available:]:
                    s.execute(
                        text(
                            "UPDATE content_attempts SET status='analyzed_not_selected',"
                            "failure_code=NULL,finished_at=:n WHERE id=:id"
                        ),
                        {"n": now, "id": topic.attempt_id},
                    )

                out = []
                for topic in packaged_topics:
                    a = articles[topic.attempt_id]
                    pid = s.execute(
                        text(
                            "INSERT INTO content_packages(attempt_id,source_url,context,analysis,post_text,review_required,status,created_at,updated_at) VALUES (:i,:u,:c,:a,:p,:r,'processing',:n,:n) RETURNING id"
                        ),
                        {
                            "i": topic.attempt_id,
                            "u": a.source_url,
                            "c": a.text,
                            "a": topic.analysis,
                            "p": topic.post_text,
                            "r": review_required,
                            "n": now,
                        },
                    ).scalar_one()
                    for st in ("not_started", "processing"):
                        s.execute(
                            text(
                                "INSERT INTO content_package_status_history(package_id,status,reason,created_at) VALUES (:p,:s,'generated',:n)"
                            ),
                            {"p": pid, "s": st, "n": now},
                        )
                    out.append(
                        PackageDraft(topic.attempt_id, pid, a, topic.media_query)
                    )
                s.execute(
                    text(
                        "UPDATE content_daily_usage SET packages_created=packages_created+:n WHERE day=:d"
                    ),
                    {"n": len(out), "d": day},
                )
                s.commit()
                return tuple(out)
            except:
                s.rollback()
                raise

    def complete_package(self, id, *, media, status, now):
        with self.sf() as s:
            try:
                package = s.execute(
                    text(
                        "SELECT attempt_id,status FROM content_packages WHERE id=:id FOR UPDATE"
                    ),
                    {"id": id},
                ).one()
                if package.status != "processing":
                    from postify.domain.content.models import InvalidContentTransition

                    raise InvalidContentTransition("invalid")
                attempt_id = package.attempt_id
                s.execute(
                    text(
                        "UPDATE content_packages SET media_path=:p,media_mime=:m,"
                        "media_source_type=:t,media_source_url=:u,status=:s,updated_at=:n "
                        "WHERE id=:id"
                    ),
                    {"id": id, "p": media.local_path, "m": media.mime,
                     "t": media.source_type, "u": media.source_url, "s": status, "n": now},
                )
                s.execute(
                    text(
                        "UPDATE content_attempts SET status='packaged',failure_code=NULL,"
                        "finished_at=:n WHERE id=:id"
                    ),
                    {"id": attempt_id, "n": now},
                )
                s.execute(
                    text(
                        "INSERT INTO content_package_status_history(package_id,status,reason,created_at) "
                        "VALUES (:id,:s,'status_change',:n)"
                    ),
                    {"id": id, "s": status, "n": now},
                )
                s.commit()
            except:
                s.rollback()
                raise

    def fail_package(self, id, *, code, now):
        with self.sf() as s:
            try:
                package = s.execute(
                    text(
                        "SELECT attempt_id,status FROM content_packages WHERE id=:id FOR UPDATE"
                    ),
                    {"id": id},
                ).one()
                if package.status != "processing":
                    from postify.domain.content.models import InvalidContentTransition

                    raise InvalidContentTransition("invalid")
                attempt_id = package.attempt_id
                s.execute(
                    text("UPDATE content_packages SET status='failed',updated_at=:n WHERE id=:id"),
                    {"id": id, "n": now},
                )
                s.execute(
                    text(
                        "UPDATE content_attempts SET status='failed',failure_code=:c,"
                        "finished_at=:n WHERE id=:id"
                    ),
                    {"id": attempt_id, "c": str(code), "n": now},
                )
                s.execute(
                    text(
                        "INSERT INTO content_package_status_history(package_id,status,reason,created_at) "
                        "VALUES (:id,'failed','status_change',:n)"
                    ),
                    {"id": id, "n": now},
                )
                s.commit()
            except:
                s.rollback()
                raise

    def active_media_paths(self):
        with self.sf() as s:
            return set(
                s.scalars(
                    text(
                        "SELECT media_path FROM content_packages WHERE status IN ('processing','awaiting_review','approved') AND media_path IS NOT NULL"
                    )
                ).all()
            )

    def _execute(self, q, **p):
        with self.sf() as s:
            try:
                s.execute(text(q), p)
                s.commit()
            except:
                s.rollback()
                raise

    def _history(self, id, status, now):
        self._execute(
            "INSERT INTO content_package_status_history(package_id,status,reason,created_at) VALUES (:id,:s,'status_change',:n)",
            id=id,
            s=status,
            n=now,
        )

    def get_package(self, id):
        with self.sf() as s:
            p = (
                s.execute(
                    text("SELECT * FROM content_packages WHERE id=:id"), {"id": id}
                )
                .mappings()
                .one()
            )
            h = s.execute(
                text(
                    "SELECT status,created_at FROM content_package_status_history WHERE package_id=:id ORDER BY id"
                ),
                {"id": id},
            ).all()
            return ContentPackage(
                id=p["id"],
                attempt_id=p["attempt_id"],
                source_url=p["source_url"],
                context=p["context"],
                analysis=p["analysis"],
                post_text=p["post_text"],
                media_path=p["media_path"],
                media_source_type=p["media_source_type"],
                media_source_url=p["media_source_url"],
                review_required=p["review_required"],
                status=p["status"],
                history=list(h),
            )

    def list_packages(self):
        with self.sf() as s:
            ids = s.scalars(text("SELECT id FROM content_packages ORDER BY id")).all()
        return tuple(self.get_package(i) for i in ids)

    def approve(self, id, *, now):
        return self._review(id, "approved", now)

    def reject(self, id, *, now):
        return self._review(id, "rejected", now)

    def _review(self, id, status, now):
        with self.sf() as s:
            try:
                p = s.execute(
                    text("SELECT status FROM content_packages WHERE id=:id FOR UPDATE"),
                    {"id": id},
                ).scalar_one()
                if p != "awaiting_review":
                    from postify.domain.content.models import InvalidContentTransition

                    raise InvalidContentTransition("invalid")
                s.execute(
                    text(
                        "UPDATE content_packages SET status=:s,updated_at=:n WHERE id=:id"
                    ),
                    {"s": status, "n": now, "id": id},
                )
                s.execute(
                    text(
                        "INSERT INTO content_package_status_history(package_id,status,reason,created_at) VALUES (:id,:s,'review',:n)"
                    ),
                    {"id": id, "s": status, "n": now},
                )
                s.commit()
            except:
                s.rollback()
                raise
        return self.get_package(id)
