from __future__ import annotations
from dataclasses import dataclass
from datetime import timedelta
import json
from sqlalchemy import text
from postify.domain.content.models import AUTOMATIC_CONTEXT, ContentPackage, validate_transition
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
    def __init__(self, session_factory, project_id: int = 1):
        self.sf = session_factory
        self.project_id = project_id

    def attempt_status(self, attempt_id: int) -> str | None:
        with self.sf() as session:
            return session.execute(
                text(
                    "SELECT status FROM content_attempts "
                    "WHERE project_id=:project AND id=:attempt"
                ),
                {"project": self.project_id, "attempt": attempt_id},
            ).scalar_one_or_none()

    def awaiting_review_package_ids(self, *, limit: int) -> tuple[int, ...]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit должен быть в диапазоне 1–100")
        with self.sf() as session:
            return tuple(
                session.execute(
                    text(
                        "SELECT id FROM content_packages "
                        "WHERE project_id=:project AND status='awaiting_review' "
                        "ORDER BY id LIMIT :limit"
                    ),
                    {"project": self.project_id, "limit": limit},
                ).scalars()
            )

    def claim(self, *, now, day, limits, context=AUTOMATIC_CONTEXT):
        with self.sf() as s:
            try:
                s.execute(
                    text(
                        "INSERT INTO content_daily_usage(project_id,day,analyses_started,packages_created) VALUES (:project,:d,0,0) ON CONFLICT (project_id,day) DO NOTHING"
                    ),
                    {"project": self.project_id, "d": day},
                )
                usage = s.execute(
                    text(
                        "SELECT analyses_started FROM content_daily_usage WHERE project_id=:project AND day=:d FOR UPDATE"
                    ),
                    {"project": self.project_id, "d": day},
                ).scalar_one()
                slots = (context.batch_size or limits.analysis_limit) if context.is_manual else limits.analysis_limit - usage
                if slots <= 0:
                    s.commit()
                    return ()
                if not context.is_manual:
                    s.execute(
                    text(
                        "INSERT INTO content_quota_state(project_id,id,fresh_credit,reserve_credit,updated_at) VALUES (:project,1,0,0,:n) ON CONFLICT (project_id,id) DO NOTHING"
                    ),
                    {"project": self.project_id, "n": now},
                    )
                credits = s.execute(
                    text(
                        "SELECT fresh_credit,reserve_credit FROM content_quota_state WHERE project_id=:project AND id=1 FOR UPDATE"
                    ),
                    {"project": self.project_id},
                ).one() if not context.is_manual else (0, 0)
                state = QuotaState(*credits)
                rows = []
                claimed_ids = []
                targeted = context.is_manual and bool(context.target_attempt_id or context.target_package_id)
                if targeted:
                    if context.target_attempt_id:
                        target = s.execute(text("""
                            SELECT a.candidate_id,a.source_url,c.title
                            FROM content_attempts a JOIN candidates c ON c.id=a.candidate_id AND c.project_id=a.project_id
                            WHERE a.project_id=:project AND a.id=:target
                              AND a.status IN ('failed','retry_scheduled')
                              AND NOT EXISTS (SELECT 1 FROM content_attempts active WHERE active.project_id=a.project_id AND active.candidate_id=a.candidate_id AND active.id<>a.id AND active.status IN ('processing','retry_scheduled'))
                            FOR UPDATE OF a, c
                        """), {"project": self.project_id, "target": context.target_attempt_id}).mappings().first()
                    else:
                        target = s.execute(text("""
                            SELECT a.candidate_id,a.source_url,c.title
                            FROM content_packages p JOIN content_attempts a ON a.id=p.attempt_id AND a.project_id=p.project_id
                            JOIN candidates c ON c.id=a.candidate_id AND c.project_id=a.project_id
                            WHERE p.project_id=:project AND p.id=:target
                              AND ((:purpose = 'return_to_analysis' AND p.status='rejected')
                                   OR (:purpose = 'regenerate_post' AND p.status IN ('awaiting_review','rejected','approved')))
                              AND NOT EXISTS (SELECT 1 FROM content_attempts active WHERE active.project_id=a.project_id AND active.candidate_id=a.candidate_id AND active.status IN ('processing','retry_scheduled'))
                            FOR UPDATE OF p, a, c
                        """), {"project": self.project_id, "target": context.target_package_id, "purpose": context.purpose or "return_to_analysis"}).mappings().first()
                    if target is not None:
                        if context.target_attempt_id is not None:
                            s.execute(
                                text(
                                    "UPDATE content_attempts SET status='retried',retry_at=NULL "
                                    "WHERE project_id=:project AND id=:target "
                                    "AND status IN ('failed','retry_scheduled')"
                                ),
                                {
                                    "project": self.project_id,
                                    "target": context.target_attempt_id,
                                },
                            )
                        attempt_no = s.execute(text("SELECT COALESCE(max(attempt_no), 0) + 1 FROM content_attempts WHERE project_id=:project AND candidate_id=:candidate"), {"project": self.project_id, "candidate": target.candidate_id}).scalar_one()
                        claimed_id = s.execute(text("""
                            INSERT INTO content_attempts(project_id,candidate_id,attempt_no,tier,status,source_url,started_at)
                            VALUES (:project,:candidate,:attempt_no,'manual','processing',:url,:now)
                            RETURNING id
                        """), {"project": self.project_id, "candidate": target.candidate_id, "attempt_no": attempt_no, "url": target.source_url, "now": now})
                        claimed_ids.append(claimed_id.scalar_one())
                        rows.append((target.candidate_id, attempt_no, "manual", target.source_url, target.title))
                retry = () if context.is_manual else s.execute(
                    text(
                        "SELECT a.id,a.candidate_id,a.attempt_no,a.source_url,c.title FROM content_attempts a JOIN candidates c ON c.id=a.candidate_id AND c.project_id=a.project_id WHERE a.project_id=:project AND a.status='retry_scheduled' AND a.retry_at<=:n ORDER BY a.retry_at FOR UPDATE SKIP LOCKED"
                    ),
                    {"project": self.project_id, "n": now},
                ).all()
                for r in (() if rows else retry):
                    if len(rows) >= slots:
                        break
                    tier = (
                        "fresh"
                        if s.execute(
                            text(
                                "SELECT discovered_at >= :cut FROM candidates WHERE project_id=:project AND id=:id"
                            ),
                            {
                                "cut": now - timedelta(days=limits.freshness_days),
                                "id": r.candidate_id,
                                "project": self.project_id,
                            },
                        ).scalar()
                        else "reserve"
                    )
                    if not context.is_manual:
                        state = consume_tier_credit(state, tier=tier, fresh_share=limits.fresh_share, reserve_share=limits.reserve_share)
                    if r.attempt_no == 1:
                        s.execute(
                            text(
                                "UPDATE content_attempts SET status='retried' WHERE project_id=:project AND id=:id"
                            ),
                            {"project": self.project_id, "id": r.id},
                        )
                        claimed_ids.append(s.execute(
                            text(
                                "INSERT INTO content_attempts(project_id,candidate_id,attempt_no,tier,status,source_url,started_at) VALUES (:project,:c,2,:t,'processing',:u,:n) RETURNING id"
                            ),
                            {"project": self.project_id, "c": r.candidate_id, "t": tier, "u": r.source_url, "n": now},
                        ).scalar_one())
                    else:
                        s.execute(
                            text(
                                "UPDATE content_attempts SET tier=:t,status='processing',failure_code=NULL,retry_at=NULL,started_at=:n,finished_at=NULL WHERE project_id=:project AND id=:id"
                            ),
                            {
                                "project": self.project_id,
                                "id": r.id,
                                "t": tier,
                                "n": now,
                            },
                        )
                        claimed_ids.append(r.id)
                    rows.append((r.candidate_id, 2, tier, r.source_url, r.title))
                candidates = s.execute(
                    text(
                        "SELECT c.id,c.url,c.title,c.discovered_at FROM candidates c JOIN candidate_decisions d ON d.candidate_id=c.id AND d.project_id=c.project_id AND d.status='selected' WHERE c.project_id=:project AND NOT EXISTS (SELECT 1 FROM content_attempts a WHERE a.project_id=c.project_id AND a.candidate_id=c.id) ORDER BY c.id FOR UPDATE OF c SKIP LOCKED"
                    ),
                    {"project": self.project_id},
                ).all()
                fresh = [
                    r
                    for r in candidates
                    if r.discovered_at >= now - timedelta(days=limits.freshness_days)
                ]
                reserve = [r for r in candidates if r not in fresh]
                while not targeted and len(rows) < slots and (fresh or reserve):
                    if context.is_manual:
                        tier = "fresh" if fresh else "reserve"
                    else:
                        tier, state = choose_tier(state, fresh_available=bool(fresh), reserve_available=bool(reserve), fresh_share=limits.fresh_share, reserve_share=limits.reserve_share)
                    pool = fresh if tier == "fresh" else reserve
                    r = pool.pop(0)
                    claimed_ids.append(s.execute(
                        text(
                            "INSERT INTO content_attempts(project_id,candidate_id,attempt_no,tier,status,source_url,started_at) VALUES (:project,:c,1,:t,'processing',:u,:n) RETURNING id"
                        ),
                        {"project": self.project_id, "c": r.id, "t": tier, "u": r.url, "n": now},
                    ).scalar_one())
                    rows.append((r.id, 1, tier, r.url, r.title))
                s.execute(
                    text("UPDATE content_daily_usage SET " + ("manual_analyses_started" if context.is_manual else "analyses_started") + "=" + ("manual_analyses_started" if context.is_manual else "analyses_started") + "+:n WHERE project_id=:project AND day=:d"),
                    {"project": self.project_id, "n": len(rows), "d": day},
                )
                if not context.is_manual:
                    s.execute(
                    text(
                        "UPDATE content_quota_state SET fresh_credit=:f,reserve_credit=:r,updated_at=:n WHERE project_id=:project AND id=1"
                    ),
                    {"project": self.project_id, "f": state.fresh_credit, "r": state.reserve_credit, "n": now},
                    )
                s.flush()
                if not claimed_ids:
                    s.commit()
                    return ()
                ids = s.execute(
                    text(
                        "SELECT id,candidate_id,attempt_no,tier,source_url FROM content_attempts WHERE project_id=:project AND id = ANY(:ids) ORDER BY id"
                    ),
                    {"project": self.project_id, "ids": claimed_ids},
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
            "UPDATE content_attempts SET status='retry_scheduled',retry_at=:r,finished_at=:n WHERE project_id=:project AND id=:id",
            project=self.project_id,
            id=id,
            r=retry_at,
            n=now,
        )

    def fail_attempt(self, id, *, code, now):
        self._execute(
            "UPDATE content_attempts SET status='failed',failure_code=:c,finished_at=:n WHERE project_id=:project AND id=:id",
            project=self.project_id,
            id=id,
            c=str(code),
            n=now,
        )

    def save_extracted(self, id, article):
        self._execute(
            "UPDATE content_attempts SET article_title=:t,article_text=:x WHERE project_id=:project AND id=:id",
            project=self.project_id,
            id=id,
            t=article.title,
            x=article.text,
        )

    def package_slots_remaining(self, *, day, limit, context=AUTOMATIC_CONTEXT):
        if context.is_manual:
            return context.batch_size or 3
        with self.sf() as s:
            return limit - (
                s.execute(
                    text(
                        "SELECT packages_created FROM content_daily_usage WHERE project_id=:project AND day=:d"
                    ),
                    {"project": self.project_id, "d": day},
                ).scalar()
                or 0
            )

    def save_analysis_and_create_packages(
        self,
        batch,
        *,
        articles,
        review_required,
        generation_snapshot=None,
        now,
        day,
        package_limit,
        context=AUTOMATIC_CONTEXT,
    ):
        with self.sf() as s:
            try:
                s.execute(
                    text(
                        "INSERT INTO content_daily_usage(project_id,day,analyses_started,packages_created) VALUES (:project,:d,0,0) ON CONFLICT (project_id,day) DO NOTHING"
                    ),
                    {"project": self.project_id, "d": day},
                )
                used = s.execute(
                    text(
                        "SELECT packages_created FROM content_daily_usage WHERE project_id=:project AND day=:d FOR UPDATE"
                    ),
                    {"project": self.project_id, "d": day},
                ).scalar_one()
                for topic in batch.topics:
                    s.execute(
                        text(
                            "UPDATE content_attempts SET analysis=:a,"
                            "status=CASE WHEN :selected THEN status ELSE 'analyzed_not_selected' END,"
                            "failure_code=CASE WHEN :selected THEN failure_code ELSE NULL END,"
                            "finished_at=CASE WHEN :selected THEN finished_at ELSE :n END WHERE project_id=:project AND id=:id"
                        ),
                        {
                            "a": topic.analysis,
                            "selected": topic.selected,
                            "n": now,
                            "id": topic.attempt_id,
                            "project": self.project_id,
                        },
                    )

                available = (context.batch_size or 3) if context.is_manual else max(0, package_limit - used)
                selected_topics = batch.selected_topics
                packaged_topics = selected_topics[:available]
                for topic in selected_topics[available:]:
                    s.execute(
                        text(
                            "UPDATE content_attempts SET status='analyzed_not_selected',"
                            "failure_code=NULL,finished_at=:n WHERE project_id=:project AND id=:id"
                        ),
                        {"project": self.project_id, "n": now, "id": topic.attempt_id},
                    )

                out = []
                for topic in packaged_topics:
                    a = articles[topic.attempt_id]
                    pid = s.execute(
                        text(
                            "INSERT INTO content_packages(project_id,attempt_id,previous_package_id,source_url,context,analysis,post_text,review_required,status,generation_snapshot,created_at,updated_at) VALUES (:project,:i,:previous,:u,:c,:a,:p,:r,'processing',CAST(:snapshot AS jsonb),:n,:n) RETURNING id"
                        ),
                        {
                            "i": topic.attempt_id,
                            "previous": context.target_package_id,
                            "u": a.source_url,
                            "c": a.text,
                            "a": topic.analysis,
                            "p": topic.post_text,
                            "r": review_required,
                            "snapshot": json.dumps(
                                generation_snapshot or {}, ensure_ascii=False
                            ),
                            "n": now,
                            "project": self.project_id,
                        },
                    ).scalar_one()
                    for st in ("not_started", "processing"):
                        s.execute(
                            text(
                                "INSERT INTO content_package_status_history(project_id,package_id,status,reason,created_at) VALUES (:project,:p,:s,'generated',:n)"
                            ),
                            {"project": self.project_id, "p": pid, "s": st, "n": now},
                        )
                    out.append(
                        PackageDraft(topic.attempt_id, pid, a, topic.media_query)
                    )
                s.execute(
                    text("UPDATE content_daily_usage SET " + ("manual_packages_created" if context.is_manual else "packages_created") + "=" + ("manual_packages_created" if context.is_manual else "packages_created") + "+:n WHERE project_id=:project AND day=:d"),
                    {"project": self.project_id, "n": len(out), "d": day},
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
                        "SELECT attempt_id,status FROM content_packages WHERE project_id=:project AND id=:id FOR UPDATE"
                    ),
                    {"project": self.project_id, "id": id},
                ).one()
                if package.status != "processing":
                    from postify.domain.content.models import InvalidContentTransition

                    raise InvalidContentTransition("invalid")
                validate_transition(package.status, status)
                attempt_id = package.attempt_id
                s.execute(
                    text(
                        "UPDATE content_packages SET media_path=:p,media_mime=:m,"
                        "media_source_type=:t,media_source_url=:u,status=:s,updated_at=:n "
                        "WHERE project_id=:project AND id=:id"
                    ),
                    {"project": self.project_id, "id": id, "p": media.local_path, "m": media.mime,
                     "t": media.source_type, "u": media.source_url, "s": status, "n": now},
                )
                s.execute(
                    text(
                        "UPDATE content_attempts SET status='packaged',failure_code=NULL,"
                        "finished_at=:n WHERE project_id=:project AND id=:id"
                    ),
                    {"project": self.project_id, "id": attempt_id, "n": now},
                )
                s.execute(
                    text(
                        "INSERT INTO content_package_status_history(project_id,package_id,status,reason,created_at) "
                        "VALUES (:project,:id,:s,'status_change',:n)"
                    ),
                    {"project": self.project_id, "id": id, "s": status, "n": now},
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
                        "SELECT attempt_id,status FROM content_packages WHERE project_id=:project AND id=:id FOR UPDATE"
                    ),
                    {"project": self.project_id, "id": id},
                ).one()
                if package.status != "processing":
                    from postify.domain.content.models import InvalidContentTransition

                    raise InvalidContentTransition("invalid")
                attempt_id = package.attempt_id
                s.execute(
                    text("UPDATE content_packages SET status='failed',updated_at=:n WHERE project_id=:project AND id=:id"),
                    {"project": self.project_id, "id": id, "n": now},
                )
                s.execute(
                    text(
                        "UPDATE content_attempts SET status='failed',failure_code=:c,"
                        "finished_at=:n WHERE project_id=:project AND id=:id"
                    ),
                    {"project": self.project_id, "id": attempt_id, "c": str(code), "n": now},
                )
                s.execute(
                    text(
                        "INSERT INTO content_package_status_history(project_id,package_id,status,reason,created_at) "
                        "VALUES (:project,:id,'failed','status_change',:n)"
                    ),
                    {"project": self.project_id, "id": id, "n": now},
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
                        "SELECT media_path FROM content_packages WHERE status IN ('processing','awaiting_review','approved') AND media_path IS NOT NULL UNION SELECT media_path FROM content_package_media_versions WHERE project_id=:project"
                    ),
                    {"project": self.project_id},
                ).all()
            )

    def replace_media(self, id, *, media, now):
        with self.sf() as s:
            try:
                package = s.execute(text("SELECT media_path,media_mime,media_source_type,media_source_url,status FROM content_packages WHERE project_id=:project AND id=:id FOR UPDATE"), {"project": self.project_id, "id": id}).mappings().one()
                if package.status not in {"awaiting_review", "rejected", "approved"}:
                    raise ValueError("Пакет нельзя изменить")
                if package.media_path:
                    s.execute(text("INSERT INTO content_package_media_versions(project_id,package_id,media_path,media_mime,media_source_type,media_source_url,created_at) VALUES (:project,:id,:path,:mime,:type,:url,:now)"), {"project": self.project_id, "id": id, "path": package.media_path, "mime": package.media_mime, "type": package.media_source_type, "url": package.media_source_url, "now": now})
                s.execute(text("UPDATE content_packages SET media_path=:path,media_mime=:mime,media_source_type=:type,media_source_url=:url,updated_at=:now WHERE project_id=:project AND id=:id"), {"project": self.project_id, "id": id, "path": media.local_path, "mime": media.mime, "type": media.source_type, "url": media.source_url, "now": now})
                s.execute(text("INSERT INTO content_package_status_history(project_id,package_id,status,reason,created_at) VALUES (:project,:id,:status,'manual_media_replaced',:now)"), {"project": self.project_id, "id": id, "status": package.status, "now": now})
                s.commit()
            except:
                s.rollback()
                raise

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
            "INSERT INTO content_package_status_history(project_id,package_id,status,reason,created_at) VALUES (:project,:id,:s,'status_change',:n)",
            project=self.project_id,
            id=id,
            s=status,
            n=now,
        )

    def get_package(self, id):
        with self.sf() as s:
            p = (
                s.execute(
                    text("SELECT * FROM content_packages WHERE project_id=:project AND id=:id"), {"project": self.project_id, "id": id}
                )
                .mappings()
                .one()
            )
            h = s.execute(
                text(
                    "SELECT status,created_at FROM content_package_status_history WHERE project_id=:project AND package_id=:id ORDER BY id"
                ),
                {"project": self.project_id, "id": id},
            ).all()
            snapshot = p["generation_snapshot"] or {}
            cta = snapshot.get("cta", {}) if isinstance(snapshot, dict) else {}
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
                source_url_allowed=isinstance(cta, dict)
                and cta.get("link_mode") == "source",
                history=list(h),
            )

    def list_packages(self):
        with self.sf() as s:
            ids = s.scalars(
                text("SELECT id FROM content_packages WHERE project_id=:project ORDER BY id"),
                {"project": self.project_id},
            ).all()
        return tuple(self.get_package(i) for i in ids)

    def approve(self, id, *, now):
        return self._review(id, "approved", now)

    def reject(self, id, *, now, reason=None):
        return self._review(id, "rejected", now, reason=reason)

    def _review(self, id, status, now, *, reason="review"):
        with self.sf() as s:
            try:
                p = s.execute(
                    text("SELECT status FROM content_packages WHERE project_id=:project AND id=:id FOR UPDATE"),
                    {"project": self.project_id, "id": id},
                ).scalar_one()
                if p != "awaiting_review":
                    from postify.domain.content.models import InvalidContentTransition

                    raise InvalidContentTransition("invalid")
                s.execute(
                    text(
                        "UPDATE content_packages SET status=:s,updated_at=:n WHERE project_id=:project AND id=:id"
                    ),
                    {"project": self.project_id, "s": status, "n": now, "id": id},
                )
                s.execute(
                    text(
                        "INSERT INTO content_package_status_history(project_id,package_id,status,reason,created_at) VALUES (:project,:id,:s,:reason,:n)"
                    ),
                    {"project": self.project_id, "id": id, "s": status, "reason": reason, "n": now},
                )
                s.commit()
            except:
                s.rollback()
                raise
        return self.get_package(id)
