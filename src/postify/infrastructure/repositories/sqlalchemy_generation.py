"""SQL-шов конвейера генерации с постом, слотом и медиа-пулом."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text

from postify.application.generation.models import (
    GeneratedContent,
    GenerationBrief,
    GenerationError,
)
from postify.application.ports.validation import DraftMedia, DraftSlot
from postify.application.prompts.compose_context import PlanSlot


class SqlAlchemyGenerationRepository:
    """Все операции сужены до одного ``project_id``."""

    def __init__(self, session_factory, project_id: int) -> None:
        self._sessions = session_factory
        self._project_id = project_id

    def brief_for_slot(self, slot_id: int) -> GenerationBrief:
        return self._brief("s.id=:target", slot_id)

    def brief_for_post(self, post_id: int) -> GenerationBrief:
        return self._brief("s.post_id=:target", post_id)

    def _brief(self, condition: str, target_id: int) -> GenerationBrief:
        with self._sessions() as session:
            row = (
                session.execute(
                    text(
                        "SELECT s.id,s.publish_at,s.topic,s.rubric_id,"
                        "cp.owner_id,cp.project_prompt,cp.timezone,cp.configuration,"
                        "cp.publication_mode,"
                        "COALESCE(r.name,'') AS rubric_name,"
                        "COALESCE(CASE WHEN r.enabled THEN r.instructions END,'') "
                        "AS rubric_instructions,"
                        "COALESCE(a.system_prompt,'') AS system_prompt,"
                        "COALESCE(u.common_prompt,'') AS common_prompt "
                        "FROM content_plan_slots s "
                        "JOIN content_projects cp ON cp.id=s.project_id "
                        "LEFT JOIN project_rubrics r ON r.project_id=s.project_id "
                        "AND r.id=s.rubric_id "
                        "LEFT JOIN app_settings a ON a.id=1 "
                        "LEFT JOIN user_settings u ON u.user_id=cp.owner_id "
                        f"WHERE s.project_id=:project AND {condition}"
                    ),
                    {"project": self._project_id, "target": target_id},
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise LookupError(target_id)
            plan_rows = (
                session.execute(
                    text(
                        "SELECT s.publish_at,s.topic,COALESCE(r.name,'') AS rubric,"
                        "CASE WHEN s.status='skipped' THEN s.status "
                        "ELSE COALESCE(p.status,s.status) END AS status "
                        "FROM content_plan_slots s "
                        "LEFT JOIN project_rubrics r ON r.project_id=s.project_id "
                        "AND r.id=s.rubric_id "
                        "LEFT JOIN posts p ON p.project_id=s.project_id "
                        "AND p.id=s.post_id "
                        "WHERE s.project_id=:project AND s.id<>:slot "
                        "AND s.status<>'skipped' ORDER BY s.publish_at,s.id"
                    ),
                    {"project": self._project_id, "slot": row["id"]},
                )
                .mappings()
                .all()
            )
        zone = ZoneInfo(row["timezone"])
        configuration = row["configuration"] or {}
        return GenerationBrief(
            project_id=self._project_id,
            user_id=row["owner_id"],
            slot=DraftSlot(
                slot_id=row["id"],
                publish_at=row["publish_at"].astimezone(zone),
                topic=row["topic"],
                rubric_name=row["rubric_name"],
                rubric_instructions=row["rubric_instructions"],
            ),
            plan=tuple(
                PlanSlot(
                    publish_at=item["publish_at"].astimezone(zone),
                    topic=item["topic"],
                    rubric=item["rubric"],
                    status=item["status"],
                )
                for item in plan_rows
            ),
            system_prompt=row["system_prompt"],
            common_prompt=row["common_prompt"],
            project_prompt=row["project_prompt"],
            publication_mode=row["publication_mode"],
            model=configuration.get("analysis_model") or "gpt-5.6-terra",
            reasoning_effort=configuration.get(
                "analysis_reasoning_effort", "medium"
            ) or "medium",
        )

    def begin_generation(self, slot_id: int, *, now: datetime) -> int:
        with self._sessions() as session:
            try:
                slot = (
                    session.execute(
                        text(
                            "SELECT publish_at,topic,status,post_id "
                            "FROM content_plan_slots WHERE project_id=:project "
                            "AND id=:slot FOR UPDATE"
                        ),
                        {"project": self._project_id, "slot": slot_id},
                    )
                    .mappings()
                    .one_or_none()
                )
                if slot is None:
                    raise LookupError(slot_id)
                if not slot["topic"].strip():
                    raise GenerationError("slot_topic_required")
                if slot["post_id"] is not None:
                    raise GenerationError("post_already_generated")
                post_id = session.execute(
                    text(
                        "INSERT INTO posts(project_id,post_text,status,scheduled_at,"
                        "generation,created_at,updated_at) VALUES "
                        "(:project,'','generating',:scheduled_at,'{}'::jsonb,:now,:now) "
                        "RETURNING id"
                    ),
                    {
                        "project": self._project_id,
                        "scheduled_at": slot["publish_at"],
                        "now": now,
                    },
                ).scalar_one()
                session.execute(
                    text(
                        "UPDATE content_plan_slots SET post_id=:post,updated_at=:now "
                        "WHERE project_id=:project AND id=:slot"
                    ),
                    {
                        "project": self._project_id,
                        "slot": slot_id,
                        "post": post_id,
                        "now": now,
                    },
                )
                self._history(session, post_id, "generating", "generation", now)
                session.commit()
                return post_id
            except BaseException:
                session.rollback()
                raise

    def begin_regeneration(self, post_id: int, *, now: datetime) -> None:
        with self._sessions() as session:
            try:
                post = (
                    session.execute(
                        text(
                            "SELECT p.status FROM posts p "
                            "JOIN content_plan_slots s ON s.project_id=p.project_id "
                            "AND s.post_id=p.id WHERE p.project_id=:project "
                            "AND p.id=:post FOR UPDATE OF p"
                        ),
                        {"project": self._project_id, "post": post_id},
                    )
                    .mappings()
                    .one_or_none()
                )
                if post is None:
                    raise LookupError(post_id)
                if post["status"] not in {
                    "needs_review",
                    "approved",
                    "rejected",
                    "failed",
                }:
                    raise GenerationError("post_cannot_be_regenerated")
                delivery_started = session.execute(
                    text(
                        "SELECT 1 FROM deliveries WHERE project_id=:project "
                        "AND post_id=:post AND status IN "
                        "('sending','published','uncertain')"
                    ),
                    {"project": self._project_id, "post": post_id},
                ).scalar_one_or_none()
                if delivery_started is not None:
                    raise GenerationError("post_delivery_started")
                session.execute(
                    text(
                        "UPDATE posts SET status='generating',updated_at=:now, "
                        "generation=generation - 'error_code' - 'error_message' "
                        "WHERE project_id=:project AND id=:post"
                    ),
                    {"project": self._project_id, "post": post_id, "now": now},
                )
                self._history(session, post_id, "generating", "regeneration", now)
                session.commit()
            except BaseException:
                session.rollback()
                raise

    def complete(
        self,
        post_id: int,
        *,
        content: GeneratedContent,
        media: DraftMedia | None,
        generation: Mapping[str, object],
        status: str = "needs_review",
        now: datetime,
    ) -> None:
        with self._sessions() as session:
            try:
                asset = None
                if media is not None:
                    asset = (
                        session.execute(
                            text(
                                "SELECT a.file_path,a.mime,a.enabled,a.caption_status,"
                                "a.embedding,a.last_used_at,p.media_reuse_days "
                                "FROM media_assets a JOIN content_projects p "
                                "ON p.id=a.project_id WHERE a.project_id=:project "
                                "AND a.id=:asset FOR UPDATE OF a"
                            ),
                            {"project": self._project_id, "asset": media.asset_id},
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if asset is None:
                        raise LookupError(media.asset_id)
                    if (
                        not asset["enabled"]
                        or asset["caption_status"] != "ready"
                        or asset["embedding"] is None
                        or (
                            asset["last_used_at"] is not None
                            and asset["last_used_at"]
                            >= now - timedelta(days=asset["media_reuse_days"])
                        )
                    ):
                        raise GenerationError(
                            "media_no_longer_available",
                            "Изображение больше не проходит политику пула",
                        )
                updated = session.execute(
                    text(
                        "UPDATE posts SET post_text=:post_text,media_path=:path,"
                        "media_mime=:mime,media_deleted_at=NULL,status=:status,"
                        "generation=CAST(:generation AS jsonb),updated_at=:now "
                        "WHERE project_id=:project AND id=:post "
                        "AND status='generating'"
                    ),
                    {
                        "project": self._project_id,
                        "post": post_id,
                        "post_text": content.post_text,
                        "path": asset["file_path"] if asset else None,
                        "mime": asset["mime"] if asset else None,
                        "generation": json.dumps(dict(generation), ensure_ascii=False),
                        "status": status,
                        "now": now,
                    },
                )
                if updated.rowcount != 1:
                    raise GenerationError("generation_not_running")
                if media is not None:
                    session.execute(
                        text(
                            "UPDATE media_assets SET use_count=use_count+1,"
                            "last_used_at=:now WHERE project_id=:project AND id=:asset"
                        ),
                        {
                            "project": self._project_id,
                            "asset": media.asset_id,
                            "now": now,
                        },
                    )
                    session.execute(
                        text(
                            "INSERT INTO media_usages(project_id,asset_id,post_id,used_at) "
                            "VALUES (:project,:asset,:post,:now)"
                        ),
                        {
                            "project": self._project_id,
                            "asset": media.asset_id,
                            "post": post_id,
                            "now": now,
                        },
                    )
                self._history(session, post_id, status, "generated", now)
                session.commit()
            except BaseException:
                session.rollback()
                raise

    def fail(self, post_id: int, *, now: datetime, error_code: str = "generation_failed", error_message: str = "") -> None:
        with self._sessions() as session:
            try:
                updated = session.execute(
                    text(
                        "UPDATE posts SET status='failed',updated_at=:now, "
                        "generation=generation || CAST(:error AS jsonb) "
                        "WHERE project_id=:project AND id=:post "
                        "AND status='generating'"
                    ),
                    {"project": self._project_id, "post": post_id, "now": now, "error": json.dumps({"error_code": error_code, "error_message": error_message})},
                )
                if updated.rowcount == 1:
                    self._history(session, post_id, "failed", "generation_failed", now)
                session.commit()
            except BaseException:
                session.rollback()
                raise

    def _history(self, session, post_id, status, reason, now) -> None:
        session.execute(
            text(
                "INSERT INTO post_status_history"
                "(project_id,post_id,status,reason,created_at) "
                "VALUES (:project,:post,:status,:reason,:now)"
            ),
            {
                "project": self._project_id,
                "post": post_id,
                "status": status,
                "reason": reason,
                "now": now,
            },
        )
