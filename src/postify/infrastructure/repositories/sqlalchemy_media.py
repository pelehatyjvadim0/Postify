"""Пул изображений одного проекта: чтение, правка и подбор.

Каждый запрос фильтрует по ``project_id`` — это изоляция данных: чужой проект
обязан выглядеть пустым, а чужой ``asset_id`` — несуществующим.

Доступность актива считает база, а не Python: политика повторов зависит от
``content_projects.media_reuse_days``, и вычислять её в приложении означало бы
тянуть все строки, чтобы отбросить большую часть.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import text

from postify.application.media.models import (
    MediaAsset,
    MediaCandidate,
    MediaCounts,
    MediaPage,
)


# Политика повторов и готовность подписи: ровно это значит ``available``
# в разделе 10 контракта.
_AVAILABLE = (
    "(a.enabled AND a.caption_status = 'ready' AND a.embedding IS NOT NULL"
    " AND (NOT p.media_reuse_blocked OR a.last_used_at IS NULL"
    "      OR a.last_used_at < :now - make_interval(days => p.media_reuse_days)))"
)

_COLUMNS = (
    "a.id, a.project_id, a.file_path, a.thumb_path, a.mime, a.bytes,"
    " a.width, a.height, a.content_hash, a.caption, a.caption_model,"
    " a.caption_status, (a.embedding IS NOT NULL) AS has_embedding,"
    " a.uploaded_at, a.last_used_at, a.use_count, a.enabled,"
    f" {_AVAILABLE} AS available"
)

_FROM = (
    " FROM media_assets a"
    " JOIN content_projects p ON p.id = a.project_id"
    " WHERE a.project_id = :project"
)

LIMIT_MAX = 100


class SqlAlchemyMediaRepository:
    """Изображения одного проекта."""

    def __init__(self, session_factory, project_id: int) -> None:
        self.sf = session_factory
        self.project_id = project_id

    # --- запись -----------------------------------------------------------

    def create(
        self,
        *,
        file_path: str,
        thumb_path: str | None,
        mime: str,
        bytes: int,
        width: int,
        height: int,
        content_hash: str,
        now: datetime,
    ) -> tuple[int, bool]:
        """Заводит актив. Возвращает ``(id, создан ли впервые)``.

        Повторная загрузка того же содержимого в тот же проект не плодит
        дубли: уникальность по ``(project_id, content_hash)`` разрешает
        конфликт молча, а вызывающая сторона узнаёт об этом по флагу.
        """
        with self.sf() as session:
            try:
                created = session.execute(
                    text(
                        "INSERT INTO media_assets(project_id,file_path,thumb_path,"
                        "mime,bytes,width,height,content_hash,caption_status,"
                        "uploaded_at,use_count,enabled)"
                        " VALUES (:project,:file_path,:thumb_path,:mime,:bytes,"
                        ":width,:height,:content_hash,'pending',:now,0,true)"
                        " ON CONFLICT (project_id,content_hash) DO NOTHING"
                        " RETURNING id"
                    ),
                    {
                        "project": self.project_id,
                        "file_path": file_path,
                        "thumb_path": thumb_path,
                        "mime": mime,
                        "bytes": bytes,
                        "width": width,
                        "height": height,
                        "content_hash": content_hash,
                        "now": now,
                    },
                ).scalar_one_or_none()
                if created is None:
                    created = session.execute(
                        text(
                            "SELECT id FROM media_assets"
                            " WHERE project_id=:project AND content_hash=:content_hash"
                        ),
                        {"project": self.project_id, "content_hash": content_hash},
                    ).scalar_one()
                    session.commit()
                    return created, False
                session.commit()
                return created, True
            except BaseException:
                session.rollback()
                raise

    def save_caption(
        self,
        asset_id: int,
        *,
        caption: str,
        caption_model: str,
        embedding: Sequence[float] | None,
        now: datetime,
    ) -> None:
        """Записывает подпись, имя модели и вектор.

        ``caption_model`` хранится всегда: по нему потом находят всё, что
        подписала заглушка, и перевыпускают.
        """
        encoded = encode_vector(embedding)
        self._update(
            "SET caption=:caption, caption_model=:model, caption_status=:status,"
            " embedding=CAST(:embedding AS vector)",
            asset_id,
            {
                "caption": caption,
                "model": caption_model,
                # Без вектора актив в подбор не идёт: статус остаётся незавершённым.
                "status": "pending" if encoded is None else "ready",
                "embedding": encoded,
                "now": now,
            },
        )

    def mark_caption_failed(self, asset_id: int) -> None:
        """Провайдер не ответил: изображение остаётся, подписи нет."""
        self._update("SET caption_status='failed'", asset_id, {})

    def update(
        self,
        asset_id: int,
        *,
        caption: str | None = None,
        enabled: bool | None = None,
        now: datetime,
    ) -> MediaAsset:
        """Ручная правка подписи и флага включённости.

        Подпись, введённая человеком, — не подпись модели: ``caption_model``
        становится ``manual``, и перевыпуск заглушки её не затирает. Вектор
        при этом обнуляется: он посчитан по старому тексту, а пересчёт требует
        обращения к модели и идёт отдельной операцией.
        """
        assignments = []
        parameters: dict[str, object] = {"now": now}
        if caption is not None:
            assignments.append(
                "caption=:caption, caption_model='manual',"
                " caption_status='pending', embedding=NULL"
            )
            parameters["caption"] = caption
        if enabled is not None:
            assignments.append("enabled=:enabled")
            parameters["enabled"] = enabled
        if assignments:
            self._update("SET " + ", ".join(assignments), asset_id, parameters)
        return self.get(asset_id, now=now)

    def delete(self, asset_id: int) -> tuple[str, str | None]:
        """Удаляет запись и отдаёт пути файлов, которые надо стереть с диска."""
        with self.sf() as session:
            try:
                in_use = session.execute(
                    text(
                        "SELECT 1 FROM media_assets a JOIN posts p"
                        " ON p.project_id=a.project_id AND p.media_path=a.file_path"
                        " WHERE a.project_id=:project AND a.id=:id LIMIT 1"
                    ),
                    {"project": self.project_id, "id": asset_id},
                ).scalar_one_or_none()
                if in_use is not None:
                    raise RuntimeError("media_in_use")
                row = (
                    session.execute(
                        text(
                            "DELETE FROM media_assets"
                            " WHERE project_id=:project AND id=:id"
                            " RETURNING file_path, thumb_path"
                        ),
                        {"project": self.project_id, "id": asset_id},
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None:
                    session.rollback()
                    raise LookupError(asset_id)
                session.commit()
                return row["file_path"], row["thumb_path"]
            except BaseException:
                session.rollback()
                raise

    def mark_used(self, asset_id: int, *, post_id: int, now: datetime) -> None:
        """Отмечает использование: счётчик, дата и строка журнала повторов."""
        with self.sf() as session:
            try:
                updated = session.execute(
                    text(
                        "UPDATE media_assets SET use_count=use_count+1,"
                        " last_used_at=:now WHERE project_id=:project AND id=:id"
                    ),
                    {"project": self.project_id, "id": asset_id, "now": now},
                )
                if updated.rowcount != 1:
                    session.rollback()
                    raise LookupError(asset_id)
                session.execute(
                    text(
                        "INSERT INTO media_usages(project_id,asset_id,post_id,used_at)"
                        " VALUES (:project,:asset,:post,:now)"
                    ),
                    {
                        "project": self.project_id,
                        "asset": asset_id,
                        "post": post_id,
                        "now": now,
                    },
                )
                session.commit()
            except BaseException:
                session.rollback()
                raise

    # --- чтение -----------------------------------------------------------

    def get(self, asset_id: int, *, now: datetime) -> MediaAsset:
        with self.sf() as session:
            row = (
                session.execute(
                    text(f"SELECT {_COLUMNS}{_FROM} AND a.id = :id"),
                    {"project": self.project_id, "id": asset_id, "now": now},
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise LookupError(asset_id)
        return _asset(row)

    def list(
        self,
        *,
        now: datetime,
        available: bool | None = None,
        query: str | None = None,
        limit: int = 60,
        cursor: str | None = None,
    ) -> MediaPage:
        """Страница пула от свежих к старым; курсор — идентификатор последней.

        Поиск ``q`` идёт по тексту подписи, а не по вектору: векторный путь
        живёт в ``shortlist`` и нужен агенту, а не человеку, который ищет
        глазами по словам.
        """
        if type(limit) is not int or not 1 <= limit <= LIMIT_MAX:
            raise ValueError("limit должен быть в диапазоне 1–100")
        conditions = ""
        parameters: dict[str, object] = {
            "project": self.project_id,
            "now": now,
            "limit": limit + 1,
        }
        if available is True:
            conditions += f" AND {_AVAILABLE}"
        elif available is False:
            conditions += f" AND NOT {_AVAILABLE}"
        if query:
            conditions += " AND a.caption ILIKE :pattern"
            parameters["pattern"] = "%" + _escape_like(query) + "%"
        if cursor is not None:
            conditions += " AND a.id < :cursor"
            parameters["cursor"] = _cursor(cursor)
        with self.sf() as session:
            rows = (
                session.execute(
                    text(
                        f"SELECT {_COLUMNS}{_FROM}{conditions}"
                        " ORDER BY a.id DESC LIMIT :limit"
                    ),
                    parameters,
                )
                .mappings()
                .all()
            )
        items = tuple(_asset(row) for row in rows[:limit])
        next_cursor = str(items[-1].id) if len(rows) > limit else None
        return MediaPage(items=items, next_cursor=next_cursor)

    def shortlist(
        self,
        embedding: Sequence[float],
        *,
        now: datetime,
        limit: int = 5,
    ) -> tuple[MediaCandidate, ...]:
        """Ближайшие доступные изображения проекта по косинусному расстоянию.

        Фильтр доступности стоит до сортировки намеренно: выдать агенту
        изображение, использованное на прошлой неделе, — это ровно риск Р3,
        ради которого политика повторов и заведена. На пуле в сотни строк
        точный проход дешевле, чем риск получить пустой шортлист из-за того,
        что индекс вернул только недавно использованные.
        """
        if type(limit) is not int or not 1 <= limit <= LIMIT_MAX:
            raise ValueError("limit должен быть в диапазоне 1–100")
        with self.sf() as session:
            rows = (
                session.execute(
                    text(
                        f"SELECT {_COLUMNS},"
                        " a.embedding <=> CAST(:query AS vector) AS distance"
                        f"{_FROM} AND {_AVAILABLE}"
                        " ORDER BY distance ASC, a.id DESC LIMIT :limit"
                    ),
                    {
                        "project": self.project_id,
                        "now": now,
                        "query": encode_vector(embedding),
                        "limit": limit,
                    },
                )
                .mappings()
                .all()
            )
        return tuple(
            MediaCandidate(asset=_asset(row), distance=float(row["distance"]))
            for row in rows
        )

    def counts(self, *, now: datetime) -> MediaCounts:
        """``media: {total, available}`` для карточки проекта."""
        with self.sf() as session:
            row = (
                session.execute(
                    text(
                        "SELECT count(*) AS total,"
                        f" count(*) FILTER (WHERE {_AVAILABLE}) AS available"
                        f"{_FROM}"
                    ),
                    {"project": self.project_id, "now": now},
                )
                .mappings()
                .one()
            )
        return MediaCounts(total=int(row["total"]), available=int(row["available"]))

    def ids_captioned_by(self, caption_model: str) -> tuple[int, ...]:
        """Идентификаторы всего, что подписала указанная модель.

        Это и есть точка перевыпуска: после появления ключа находят всё с
        ``caption_model='mock'`` и подписывают заново.
        """
        with self.sf() as session:
            rows = session.scalars(
                text(
                    "SELECT id FROM media_assets"
                    " WHERE project_id=:project AND caption_model=:model"
                    " ORDER BY id"
                ),
                {"project": self.project_id, "model": caption_model},
            ).all()
        return tuple(rows)

    def file(self, asset_id: int, *, thumb: bool) -> tuple[str, str]:
        """Путь и mime файла для отдачи. Превью считается при загрузке."""
        with self.sf() as session:
            row = (
                session.execute(
                    text(
                        "SELECT file_path, thumb_path, mime FROM media_assets"
                        " WHERE project_id=:project AND id=:id"
                    ),
                    {"project": self.project_id, "id": asset_id},
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise LookupError(asset_id)
        if thumb and row["thumb_path"]:
            # Превью всегда JPEG: один путь конвертации для всех форматов.
            return row["thumb_path"], "image/jpeg"
        return row["file_path"], row["mime"]

    # --- внутреннее -------------------------------------------------------

    def _update(
        self, assignment: str, asset_id: int, parameters: dict[str, object]
    ) -> None:
        with self.sf() as session:
            try:
                updated = session.execute(
                    text(
                        f"UPDATE media_assets {assignment}"
                        " WHERE project_id=:project AND id=:id"
                    ),
                    {**parameters, "project": self.project_id, "id": asset_id},
                )
                if updated.rowcount != 1:
                    session.rollback()
                    raise LookupError(asset_id)
                session.commit()
            except BaseException:
                session.rollback()
                raise


def encode_vector(values: Sequence[float] | None) -> str | None:
    """Текстовое представление ``vector``: его принимает CAST и отдаёт SELECT."""
    if values is None:
        return None
    return "[" + ",".join(repr(float(value)) for value in values) + "]"


def _asset(row) -> MediaAsset:
    return MediaAsset(
        id=row["id"],
        project_id=row["project_id"],
        file_path=row["file_path"],
        thumb_path=row["thumb_path"],
        mime=row["mime"],
        bytes=int(row["bytes"]),
        width=int(row["width"]),
        height=int(row["height"]),
        content_hash=row["content_hash"],
        caption=row["caption"],
        caption_model=row["caption_model"],
        caption_status=row["caption_status"],
        has_embedding=bool(row["has_embedding"]),
        uploaded_at=row["uploaded_at"],
        last_used_at=row["last_used_at"],
        use_count=int(row["use_count"]),
        enabled=bool(row["enabled"]),
        available=bool(row["available"]),
    )


def _cursor(value: str) -> int:
    """Курсор приходит от клиента, поэтому проверяется, а не подставляется."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError("Неверный курсор постраничности") from None
    if parsed <= 0:
        raise ValueError("Неверный курсор постраничности")
    return parsed


def _escape_like(value: str) -> str:
    """Экранирует спецсимволы LIKE: иначе ``%`` из запроса ломает поиск."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
