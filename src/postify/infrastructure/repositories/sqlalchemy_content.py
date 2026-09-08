from __future__ import annotations
from dataclasses import dataclass
from datetime import UTC
import json
from sqlalchemy import text
from postify.domain.content.models import AUTOMATIC_CONTEXT, ContentPackage, InvalidContentTransition, validate_transition
from postify.application.ports.content_repository import PackageDraft


@dataclass(frozen=True, slots=True)
class ClaimedAttempt:
    id: int
    candidate_id: int
    attempt_no: int
    source_url: str
    title: str
    snippet: str = ""
    source_text: str | None = None


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

    def claim(self, *, now, batch_size: int, context=AUTOMATIC_CONTEXT):
        with self.sf() as s:
            try:
                slots = context.batch_size or batch_size
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
                                   OR (:purpose = 'regenerate_post' AND p.status IN ('awaiting_review','rejected')))
                              AND NOT EXISTS (
                                  SELECT 1 FROM content_packages newer
                                  JOIN content_attempts newer_attempt ON newer_attempt.id=newer.attempt_id AND newer_attempt.project_id=newer.project_id
                                  WHERE newer.project_id=p.project_id AND newer_attempt.candidate_id=a.candidate_id
                                    AND newer.id>p.id AND newer.status NOT IN ('failed','processing')
                              )
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
                            INSERT INTO content_attempts(project_id,candidate_id,attempt_no,status,source_url,started_at)
                            VALUES (:project,:candidate,:attempt_no,'processing',:url,:now)
                            RETURNING id
                        """), {"project": self.project_id, "candidate": target.candidate_id, "attempt_no": attempt_no, "url": target.source_url, "now": now})
                        claimed_ids.append(claimed_id.scalar_one())
                        rows.append((target.candidate_id, attempt_no, target.source_url, target.title))
                if not targeted:
                    candidates = s.execute(
                        text(
                            "SELECT c.id,c.url,c.title FROM candidates c "
                            "WHERE c.project_id=:project AND c.source_text IS NOT NULL "
                            "AND NOT EXISTS (SELECT 1 FROM content_attempts a WHERE a.project_id=c.project_id AND a.candidate_id=c.id) "
                            "ORDER BY c.id LIMIT :slots FOR UPDATE OF c SKIP LOCKED"
                        ),
                        {"project": self.project_id, "slots": slots},
                    ).all()
                    for candidate in candidates:
                        claimed_ids.append(s.execute(
                            text(
                                "INSERT INTO content_attempts(project_id,candidate_id,attempt_no,status,source_url,started_at) "
                                "VALUES (:project,:candidate,1,'processing',:url,:now) RETURNING id"
                            ),
                            {"project": self.project_id, "candidate": candidate.id, "url": candidate.url, "now": now},
                        ).scalar_one())
                s.flush()
                if not claimed_ids:
                    s.commit()
                    return ()
                ids = s.execute(
                    text(
                        "SELECT a.id,a.candidate_id,a.attempt_no,a.source_url,c.title,c.source_text FROM content_attempts a JOIN candidates c ON c.id=a.candidate_id AND c.project_id=a.project_id WHERE a.project_id=:project AND a.id = ANY(:ids) ORDER BY a.id"
                    ),
                    {"project": self.project_id, "ids": claimed_ids},
                ).all()
                s.commit()
                return tuple(
                    ClaimedAttempt(
                        x.id,
                        x.candidate_id,
                        x.attempt_no,
                        x.source_url,
                        x.title,
                        source_text=x.source_text,
                    )
                    for x in ids
                )
            except:
                s.rollback()
                raise

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

    def save_analysis_and_create_packages(
        self,
        batch,
        *,
        articles,
        generation_snapshot=None,
        now,
        context=AUTOMATIC_CONTEXT,
    ):
        with self.sf() as s:
            try:
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

                out = []
                for topic in batch.selected_topics:
                    a = articles[topic.attempt_id]
                    pid = s.execute(
                        text(
                            "INSERT INTO content_packages(project_id,attempt_id,previous_package_id,source_url,context,analysis,post_text,status,generation_snapshot,created_at,updated_at) VALUES (:project,:i,:previous,:u,:c,:a,:p,'processing',CAST(:snapshot AS jsonb),:n,:n) RETURNING id"
                        ),
                        {
                            "i": topic.attempt_id,
                            "previous": context.target_package_id,
                            "u": a.source_url,
                            "c": a.text,
                            "a": topic.analysis,
                            "p": topic.post_text,
                            "snapshot": json.dumps(
                                generation_snapshot or {}, ensure_ascii=False
                            ),
                            "n": now,
                            "project": self.project_id,
                        },
                    ).scalar_one()
                    if context.target_package_id is not None:
                        s.execute(
                            text("UPDATE content_packages p SET scheduled_at=previous.scheduled_at,route_id=previous.route_id FROM content_packages previous WHERE p.project_id=:project AND p.id=:id AND previous.project_id=p.project_id AND previous.id=:previous"),
                            {"project": self.project_id, "id": pid, "previous": context.target_package_id},
                        )
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
                    {"project": self.project_id, "id": id, "p": media.local_path if media else None, "m": media.mime if media else None,
                     "t": media.source_type if media else None, "u": media.source_url if media else None, "s": status, "n": now},
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
                status=p["status"],
                # Stored editorial text is preserved independently of retired CTA settings.
                source_url_allowed=True,
                history=list(h),
                scheduled_at=p["scheduled_at"],
                route_id=p["route_id"],
                previous_package_id=p["previous_package_id"],
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

    def save_plan(self, id, *, scheduled_at, route_id, now):
        if scheduled_at.tzinfo is None or scheduled_at.utcoffset() is None:
            raise ValueError("Дата должна содержать часовой пояс")
        scheduled_at = scheduled_at.astimezone(UTC)
        if scheduled_at <= now:
            raise ValueError("Назначьте время в будущем")
        if type(route_id) is not int or route_id < 1:
            raise ValueError("Выберите маршрут публикации")
        with self.sf() as s:
            with s.begin():
                package = s.execute(text("SELECT status,scheduled_at,route_id,post_text,media_path FROM content_packages WHERE project_id=:project AND id=:id FOR UPDATE"), {"project": self.project_id, "id": id}).mappings().one()
                if package.status not in {"awaiting_review", "approved"}:
                    raise InvalidContentTransition("План этого поста нельзя изменить")
                delivery = s.execute(text("SELECT status FROM deliveries WHERE project_id=:project AND package_id=:id"), {"project": self.project_id, "id": id}).scalar_one_or_none()
                if delivery in {"sending", "uncertain", "published"}:
                    raise InvalidContentTransition("Отправка начата или её результат не определён")
                self._validate_route(s, route_id)
                if package.scheduled_at == scheduled_at and package.route_id == route_id:
                    return self.get_package(id)
                # A new plan requires explicit approval again. Failed/retryable sends may be replanned.
                if delivery is not None and package.route_id != route_id:
                    raise InvalidContentTransition("После попытки отправки канал нельзя изменить")
                s.execute(text("UPDATE content_packages SET scheduled_at=:at,route_id=:route,status='awaiting_review',updated_at=:now WHERE project_id=:project AND id=:id"), {"project": self.project_id, "id": id, "at": scheduled_at, "route": route_id, "now": now})
                if delivery == "failed":
                    s.execute(text("UPDATE deliveries SET status='retryable',updated_at=:now WHERE project_id=:project AND package_id=:id"), {"project": self.project_id, "id": id, "now": now})
                s.execute(text("INSERT INTO content_package_status_history(project_id,package_id,status,reason,created_at) VALUES (:project,:id,'awaiting_review','plan_changed',:now)"), {"project": self.project_id, "id": id, "now": now})
        return self.get_package(id)

    def _validate_route(self, session, route_id):
        available = session.execute(text("SELECT r.id FROM publication_routes r JOIN channel_connections c ON c.project_id=r.project_id AND c.id=r.channel_id WHERE r.project_id=:project AND r.id=:route AND r.enabled AND c.enabled FOR SHARE OF r,c"), {"project": self.project_id, "route": route_id}).scalar_one_or_none()
        if available is None:
            raise ValueError("Маршрут или канал недоступен в этом проекте")

    def _review(self, id, status, now, *, reason="review"):
        with self.sf() as s:
            with s.begin():
                p = s.execute(text("SELECT status,scheduled_at,route_id,post_text,media_path FROM content_packages WHERE project_id=:project AND id=:id FOR UPDATE"), {"project": self.project_id, "id": id}).mappings().one()
                if p.status == status:
                    return self.get_package(id)
                if p.status != "awaiting_review":
                    raise InvalidContentTransition("Пост уже обработан редактором")
                if status == "approved":
                    blocked = s.execute(text("""
                        SELECT EXISTS (
                            SELECT 1 FROM content_attempts active
                            WHERE active.project_id=a.project_id AND active.candidate_id=a.candidate_id
                              AND active.status IN ('processing','retry_scheduled')
                        ) OR EXISTS (
                            SELECT 1 FROM content_packages newer
                            JOIN content_attempts newer_attempt ON newer_attempt.id=newer.attempt_id AND newer_attempt.project_id=newer.project_id
                            WHERE newer.project_id=p.project_id AND newer_attempt.candidate_id=a.candidate_id
                              AND newer.id>p.id AND newer.status NOT IN ('failed','processing')
                        )
                        FROM content_packages p
                        JOIN content_attempts a ON a.id=p.attempt_id AND a.project_id=p.project_id
                        WHERE p.project_id=:project AND p.id=:id
                    """), {"project": self.project_id, "id": id}).scalar_one()
                    if blocked:
                        raise InvalidContentTransition("Готовится или уже создана новая версия поста")
                    limit = 1024 if p.media_path else 4096
                    if not p.post_text.strip() or len(p.post_text.encode("utf-16-le")) // 2 > limit:
                        raise InvalidContentTransition(f"Текст публикации должен содержать от 1 до {limit} символов")
                    if p.scheduled_at is None or p.route_id is None:
                        raise InvalidContentTransition("Сначала сохраните дату и канал публикации")
                    if p.scheduled_at <= now:
                        raise InvalidContentTransition("Время прошло: перенесите публикацию")
                    self._validate_route(s, p.route_id)
                s.execute(text("UPDATE content_packages SET status=:s,updated_at=:n WHERE project_id=:project AND id=:id"), {"project": self.project_id, "s": status, "n": now, "id": id})
                s.execute(text("INSERT INTO content_package_status_history(project_id,package_id,status,reason,created_at) VALUES (:project,:id,:s,:reason,:n)"), {"project": self.project_id, "id": id, "s": status, "reason": reason, "n": now})
        return self.get_package(id)
