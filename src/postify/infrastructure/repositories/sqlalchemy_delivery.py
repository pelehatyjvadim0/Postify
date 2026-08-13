from __future__ import annotations

import json

from sqlalchemy import text

from postify.domain.delivery.models import DeliveryClaim, PublishFailureKind


class SqlAlchemyDeliveryRepository:
    def __init__(
        self,
        session_factory,
        project_id: int = 1,
        *,
        route_id: int | None = None,
        channel_id: int | None = None,
        channel_snapshot: dict[str, object] | None = None,
    ) -> None:
        self.sf = session_factory
        self.project_id = project_id
        self.route_id = route_id
        self.channel_id = channel_id
        self.channel_snapshot = channel_snapshot or {}

    def reserve_next(self, *, now):
        with self.sf() as session:
            try:
                row = session.execute(text("""
                    SELECT p.id, p.post_text, p.media_path, p.media_mime, d.id AS delivery_id,
                           d.status, d.attempt_no
                    FROM content_packages p
                    LEFT JOIN deliveries d ON d.package_id = p.id AND d.project_id=p.project_id
                    WHERE p.project_id=:project AND p.status = 'approved' AND (d.id IS NULL OR d.status = 'retryable')
                    ORDER BY p.created_at, p.id
                    FOR UPDATE OF p SKIP LOCKED LIMIT 1
                """), {"project": self.project_id}).mappings().first()
                if row is None:
                    session.commit()
                    return None
                if row.delivery_id is None:
                    delivery_id = session.execute(text("""
                        INSERT INTO deliveries
                        (project_id,package_id,route_id,channel_id,channel_snapshot,
                         status,attempt_no,sending_started_at,created_at,updated_at)
                        VALUES (:project,:package_id,:route_id,:channel_id,
                                CAST(:channel_snapshot AS jsonb),'sending',1,:now,:now,:now)
                        RETURNING id
                    """), {
                        "project": self.project_id,
                        "package_id": row.id,
                        "route_id": self.route_id,
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
                        sending_started_at=:now, failure_code=NULL, failure_reason=NULL, updated_at=:now
                        WHERE project_id=:project AND id=:id AND status='retryable'
                    """), {"project": self.project_id, "id": delivery_id, "attempt_no": attempt_no, "now": now})
                session.commit()
                return DeliveryClaim(delivery_id, row.id, attempt_no, row.post_text, row.media_path, row.media_mime)
            except:
                session.rollback()
                raise

    def record_failure(self, claim, *, kind: PublishFailureKind, code: str, reason: str, now) -> None:
        with self.sf() as session:
            try:
                delivery = session.execute(text("SELECT package_id,status,attempt_no,sending_started_at FROM deliveries WHERE project_id=:project AND id=:id FOR UPDATE"), {"project": self.project_id, "id": claim.delivery_id}).mappings().one()
                if delivery.package_id != claim.package_id or delivery.status != "sending" or delivery.attempt_no != claim.attempt_no:
                    raise ValueError("Некорректное состояние доставки")
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
                delivery = session.execute(text("SELECT package_id,status,attempt_no,sending_started_at FROM deliveries WHERE project_id=:project AND id=:id FOR UPDATE"), {"project": self.project_id, "id": claim.delivery_id}).mappings().one()
                if delivery.package_id != claim.package_id or delivery.status != "sending" or delivery.attempt_no != claim.attempt_no:
                    raise ValueError("Некорректное состояние доставки")
                session.execute(text("""INSERT INTO delivery_attempts
                    (project_id,delivery_id,attempt_no,outcome,started_at,finished_at,message_id)
                    VALUES (:project,:delivery_id,:attempt_no,'published',:started_at,:now,:message_id)"""),
                    {"project": self.project_id, "delivery_id": claim.delivery_id, "attempt_no": claim.attempt_no, "started_at": delivery.sending_started_at, "now": now, "message_id": message_id})
                session.execute(text("""UPDATE deliveries SET status='published', message_id=:message_id,
                    confirmed_at=:now, failure_code=NULL, failure_reason=NULL, updated_at=:now WHERE project_id=:project AND id=:id"""), {"project": self.project_id, "id": claim.delivery_id, "message_id": message_id, "now": now})
                session.execute(text("UPDATE content_packages SET status='published', updated_at=:now WHERE project_id=:project AND id=:id AND status='approved'"), {"project": self.project_id, "id": claim.package_id, "now": now})
                session.execute(text("""INSERT INTO content_package_status_history(project_id,package_id,status,reason,created_at)
                    VALUES (:project,:id,'published','channel_confirmed',:now)"""), {"project": self.project_id, "id": claim.package_id, "now": now})
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
            row = session.execute(text("""SELECT d.id AS delivery_id,p.id AS package_id,d.attempt_no,p.post_text,p.media_path,p.media_mime
                FROM deliveries d JOIN content_packages p ON p.id=d.package_id AND p.project_id=d.project_id
                WHERE d.project_id=:project AND d.status='published' AND d.media_deleted_at IS NULL ORDER BY d.confirmed_at, d.id
                FOR UPDATE OF d SKIP LOCKED LIMIT 1"""), {"project": self.project_id}).mappings().first()
            session.commit()
            return None if row is None else DeliveryClaim(row.delivery_id, row.package_id, row.attempt_no, row.post_text, row.media_path, row.media_mime)

    def mark_media_deleted(self, delivery_id: int, *, now) -> None:
        with self.sf() as session:
            try:
                package_id = session.execute(text("SELECT package_id FROM deliveries WHERE project_id=:project AND id=:id AND status='published' FOR UPDATE"), {"project": self.project_id, "id": delivery_id}).scalar_one()
                session.execute(text("UPDATE deliveries SET media_deleted_at=:now, updated_at=:now WHERE project_id=:project AND id=:id"), {"project": self.project_id, "id": delivery_id, "now": now})
                session.execute(text("UPDATE content_packages SET media_deleted_at=:now, updated_at=:now WHERE project_id=:project AND id=:id"), {"project": self.project_id, "id": package_id, "now": now})
                session.commit()
            except:
                session.rollback()
                raise
