from __future__ import annotations

import json

from sqlalchemy import text

from postify.domain.delivery.models import DeliveryClaim, PublishFailureKind


class SqlAlchemyDeliveryRepository:
    """
    Доставки постов проекта в его единственный канал.

    Проект равен одному каналу, поэтому адресация доставки — это пара
    «проект + канал»; маршрутов между форматом и каналом больше нет.
    ``post_id`` и ``delivery_id`` сужают выборку до одной цели: так работает
    публикация по кнопке и повтор конкретной доставки.
    """

    def __init__(
        self,
        session_factory,
        project_id: int,
        *,
        channel_id: int | None = None,
        channel_snapshot: dict[str, object] | None = None,
        post_id: int | None = None,
        delivery_id: int | None = None,
    ) -> None:
        self.sf = session_factory
        self.project_id = project_id
        self.channel_id = channel_id
        self.channel_snapshot = channel_snapshot or {}
        # Отрицательное значение означает «цель не задана»: SQL сравнивает его
        # с единицей и так отключает фильтр, не собирая запрос строками.
        self.post_id = post_id or -1
        self.delivery_id = delivery_id or -1

    def is_retryable(self, delivery_id: int) -> bool:
        with self.sf() as session:
            return (
                session.execute(
                    text(
                        "SELECT 1 FROM deliveries WHERE project_id=:project "
                        "AND id=:delivery AND status='retryable'"
                    ),
                    {"project": self.project_id, "delivery": delivery_id},
                ).scalar_one_or_none()
                is not None
            )

    def reserve_next(self, *, now, post_id: int | None = None, delivery_id: int | None = None):
        post_id = self.post_id if post_id is None else post_id
        delivery_id = self.delivery_id if delivery_id is None else delivery_id
        with self.sf() as session:
            try:
                row = session.execute(text("""
                    SELECT p.id, p.post_text, p.media_path, p.media_mime,
                           EXISTS (SELECT 1 FROM media_assets a
                                   WHERE a.project_id=p.project_id
                                     AND a.file_path=p.media_path) AS retain_media,
                           d.id AS delivery_id, d.status, d.attempt_no
                    FROM posts p
                    JOIN content_plan_slots s ON s.project_id=p.project_id
                                             AND s.post_id=p.id
                    LEFT JOIN deliveries d ON d.post_id = p.id AND d.project_id = p.project_id
                    WHERE p.project_id=:project AND p.status='approved'
                      AND s.status<>'skipped' AND s.publish_at <= :now
                      AND EXISTS (
                          SELECT 1 FROM channel_connections c
                          WHERE c.project_id=p.project_id AND c.id=:channel_id AND c.enabled
                      )
                      AND (:post_id < 1 OR p.id=:post_id)
                      AND (:delivery_id < 1 OR d.id=:delivery_id)
                      AND (d.id IS NULL OR d.status='retryable')
                    ORDER BY s.publish_at, p.id
                    FOR UPDATE OF p SKIP LOCKED LIMIT 1
                """), {
                    "project": self.project_id,
                    "channel_id": self.channel_id,
                    "post_id": post_id,
                    "delivery_id": delivery_id,
                    "now": now,
                }).mappings().first()
                if row is None:
                    session.commit()
                    return None
                if row.delivery_id is None:
                    delivery_id = session.execute(text("""
                        INSERT INTO deliveries
                        (project_id,post_id,channel_id,channel_snapshot,
                         status,attempt_no,sending_started_at,created_at,updated_at)
                        VALUES (:project,:post_id,:channel_id,
                                CAST(:channel_snapshot AS jsonb),'sending',1,:now,:now,:now)
                        RETURNING id
                    """), {
                        "project": self.project_id,
                        "post_id": row.id,
                        "channel_id": self.channel_id,
                        "channel_snapshot": json.dumps(
                            self.channel_snapshot, ensure_ascii=False
                        ),
                        "now": now,
                    }).scalar_one()
                    attempt_no = 1
                else:
                    attempt_no = row.attempt_no + 1
                    delivery_id = row.delivery_id
                    session.execute(text("""
                        UPDATE deliveries SET status='sending', attempt_no=:attempt_no,
                        sending_started_at=:now, failure_code=NULL, failure_reason=NULL,
                        updated_at=:now
                        WHERE project_id=:project AND id=:id AND status='retryable'
                    """), {
                        "project": self.project_id,
                        "id": delivery_id,
                        "attempt_no": attempt_no,
                        "now": now,
                    })
                session.commit()
                return DeliveryClaim(
                    delivery_id,
                    row.id,
                    attempt_no,
                    row.post_text,
                    row.media_path,
                    row.media_mime,
                    row.retain_media,
                )
            except:
                session.rollback()
                raise

    def record_failure(self, claim, *, kind: PublishFailureKind, code: str, reason: str, now) -> None:
        with self.sf() as session:
            try:
                delivery = self._locked_delivery(session, claim)
                session.execute(text("""INSERT INTO delivery_attempts
                    (project_id,delivery_id,attempt_no,outcome,code,reason,started_at,finished_at)
                    VALUES (:project,:delivery_id,:attempt_no,:outcome,:code,:reason,:started_at,:now)"""),
                    {"project": self.project_id, "delivery_id": claim.delivery_id, "attempt_no": claim.attempt_no, "outcome": kind.value, "code": code, "reason": reason, "started_at": delivery.sending_started_at, "now": now})
                session.execute(text("""UPDATE deliveries SET status=:status, failure_code=:code,
                    failure_reason=:reason, updated_at=:now WHERE project_id=:project AND id=:id"""),
                    {"project": self.project_id, "status": kind.value, "code": code, "reason": reason, "now": now, "id": claim.delivery_id})
                session.commit()
            except:
                session.rollback()
                raise

    def confirm_published(self, claim, *, message_id: int, now) -> None:
        if type(message_id) is not int or message_id <= 0:
            raise ValueError("Нужен положительный message_id")
        with self.sf() as session:
            try:
                delivery = self._locked_delivery(session, claim)
                session.execute(text("""INSERT INTO delivery_attempts
                    (project_id,delivery_id,attempt_no,outcome,started_at,finished_at,message_id)
                    VALUES (:project,:delivery_id,:attempt_no,'published',:started_at,:now,:message_id)"""),
                    {"project": self.project_id, "delivery_id": claim.delivery_id, "attempt_no": claim.attempt_no, "started_at": delivery.sending_started_at, "now": now, "message_id": message_id})
                session.execute(text("""UPDATE deliveries SET status='published', message_id=:message_id,
                    confirmed_at=:now, failure_code=NULL, failure_reason=NULL, updated_at=:now
                    WHERE project_id=:project AND id=:id"""), {"project": self.project_id, "id": claim.delivery_id, "message_id": message_id, "now": now})
                session.execute(text("""UPDATE posts SET status='published', updated_at=:now
                    WHERE project_id=:project AND id=:id AND status='approved'"""), {"project": self.project_id, "id": claim.post_id, "now": now})
                session.execute(text("""INSERT INTO post_status_history(project_id,post_id,status,reason,created_at)
                    VALUES (:project,:id,'published','channel_confirmed',:now)"""), {"project": self.project_id, "id": claim.post_id, "now": now})
                session.commit()
            except:
                session.rollback()
                raise

    def mark_stale_sending_uncertain(self, *, stale_before, now) -> int:
        with self.sf() as session:
            try:
                rows = session.execute(text("""SELECT id,attempt_no,sending_started_at FROM deliveries
                    WHERE project_id=:project AND status='sending' AND sending_started_at < :stale_before FOR UPDATE"""), {"project": self.project_id, "stale_before": stale_before}).mappings().all()
                for row in rows:
                    session.execute(text("""INSERT INTO delivery_attempts(project_id,delivery_id,attempt_no,outcome,code,reason,started_at,finished_at)
                        VALUES (:project,:id,:attempt_no,'uncertain','stale_sending','Обнаружена незавершённая отправка',:started_at,:now)"""), {"project": self.project_id, "id": row.id, "attempt_no": row.attempt_no, "started_at": row.sending_started_at, "now": now})
                    session.execute(text("""UPDATE deliveries SET status='uncertain', failure_code='stale_sending',
                        failure_reason='Обнаружена незавершённая отправка', updated_at=:now WHERE project_id=:project AND id=:id"""), {"project": self.project_id, "id": row.id, "now": now})
                session.commit()
                return len(rows)
            except:
                session.rollback()
                raise

    def pending_cleanup(self):
        with self.sf() as session:
            row = session.execute(text("""SELECT d.id AS delivery_id,p.id AS post_id,d.attempt_no,p.post_text,p.media_path,p.media_mime,
                EXISTS (SELECT 1 FROM media_assets a WHERE a.project_id=p.project_id AND a.file_path=p.media_path) AS retain_media
                FROM deliveries d JOIN posts p ON p.id=d.post_id AND p.project_id=d.project_id
                WHERE d.project_id=:project AND d.status='published' AND d.media_deleted_at IS NULL
                ORDER BY d.confirmed_at, d.id
                FOR UPDATE OF d SKIP LOCKED LIMIT 1"""), {"project": self.project_id}).mappings().first()
            session.commit()
            return None if row is None else DeliveryClaim(row.delivery_id, row.post_id, row.attempt_no, row.post_text, row.media_path, row.media_mime, row.retain_media)

    def mark_media_deleted(self, delivery_id: int, *, now) -> None:
        with self.sf() as session:
            try:
                post_id = session.execute(text("SELECT post_id FROM deliveries WHERE project_id=:project AND id=:id AND status='published' FOR UPDATE"), {"project": self.project_id, "id": delivery_id}).scalar_one()
                session.execute(text("UPDATE deliveries SET media_deleted_at=:now, updated_at=:now WHERE project_id=:project AND id=:id"), {"project": self.project_id, "id": delivery_id, "now": now})
                session.execute(text("UPDATE posts SET media_deleted_at=:now, updated_at=:now WHERE project_id=:project AND id=:id"), {"project": self.project_id, "id": post_id, "now": now})
                session.commit()
            except:
                session.rollback()
                raise

    def mark_media_retained(self, delivery_id: int, *, now) -> None:
        """Закрывает cleanup доставки, не помечая канонический файл пула удалённым."""
        with self.sf() as session:
            updated = session.execute(
                text(
                    "UPDATE deliveries SET media_deleted_at=:now,updated_at=:now"
                    " WHERE project_id=:project AND id=:id AND status='published'"
                ),
                {"project": self.project_id, "id": delivery_id, "now": now},
            )
            if updated.rowcount != 1:
                session.rollback()
                raise LookupError(delivery_id)
            session.commit()

    def _locked_delivery(self, session, claim):
        """Блокирует доставку и отвергает claim, устаревший после чужой записи."""
        delivery = session.execute(
            text(
                "SELECT post_id,status,attempt_no,sending_started_at FROM deliveries "
                "WHERE project_id=:project AND id=:id FOR UPDATE"
            ),
            {"project": self.project_id, "id": claim.delivery_id},
        ).mappings().one()
        if (
            delivery.post_id != claim.post_id
            or delivery.status != "sending"
            or delivery.attempt_no != claim.attempt_no
        ):
            raise ValueError("Некорректное состояние доставки")
        return delivery
