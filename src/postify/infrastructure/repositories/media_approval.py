"""Атомарный учёт изображения только после одобрения поста."""
from datetime import timedelta
from sqlalchemy import text
from postify.domain.posts.models import InvalidPostTransition


def record_approval(session, project_id, post_id, path, now):
    asset = session.execute(text(
        "SELECT a.id,a.last_used_at,p.media_reuse_days,p.media_reuse_blocked "
        "FROM media_assets a JOIN content_projects p ON p.id=a.project_id "
        "WHERE a.project_id=:project AND a.file_path=:path FOR UPDATE OF a"
    ), {"project": project_id, "path": path}).mappings().one_or_none()
    if asset is None:
        return
    own_usage = session.execute(text(
        "SELECT 1 FROM media_usages WHERE project_id=:project AND asset_id=:asset "
        "AND post_id=:post LIMIT 1"
    ), {"project": project_id, "asset": asset.id, "post": post_id}).first()
    if own_usage:
        return
    if asset.media_reuse_blocked and asset.last_used_at is not None and asset.last_used_at >= now - timedelta(days=asset.media_reuse_days):
        raise InvalidPostTransition("Изображение уже одобрено для другого поста. Выберите другое или отключите блокировку повторов в настройках.")
    session.execute(text("INSERT INTO media_usages(project_id,asset_id,post_id,used_at) VALUES (:project,:asset,:post,:now)"),
                    {"project": project_id, "asset": asset.id, "post": post_id, "now": now})
    session.execute(text("UPDATE media_assets SET use_count=use_count+1,last_used_at=:now WHERE id=:asset"), {"asset": asset.id, "now": now})
