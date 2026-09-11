"""Пул изображений проекта: активы и журнал использований.

Вектор подписи хранится колонкой расширения ``vector``. Собственный тип поверх
``UserDefinedType`` вместо зависимости ``pgvector``: от него нужен ровно один
DDL-фрагмент, а чтение и запись идут сырым SQL, как у соседних репозиториев.

Размерность фиксирована ``EMBEDDING_DIMENSIONS`` шлюза вызовов модели:
заглушка и настоящий провайдер отдают одну длину специально, чтобы появление
ключа не требовало миграции.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import UserDefinedType

from postify.application.ai.gateway import EMBEDDING_DIMENSIONS
from postify.infrastructure.database.models.base import Base


class Vector(UserDefinedType):
    """Колонка ``vector(n)`` расширения pgvector.

    Значения передаются и читаются строкой ``'[1,2,3]'`` — это текстовое
    представление типа, и оно же принимается при ``CAST(... AS vector)``.
    """

    cache_ok = True

    def __init__(self, dimensions: int = EMBEDDING_DIMENSIONS) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **_: object) -> str:
        return f"vector({self.dimensions})"


class MediaAssetModel(Base):
    """Изображение пула. Подпись и вектор появляются позже загрузки."""

    __tablename__ = "media_assets"
    __table_args__ = (
        UniqueConstraint("project_id", "id", name="uq_media_assets_project_id_id"),
        # Повторная загрузка того же файла в тот же проект не плодит дубли.
        UniqueConstraint(
            "project_id", "content_hash", name="uq_media_assets_project_id_content_hash"
        ),
        CheckConstraint(
            "caption_status IN ('pending','ready','failed')",
            name="ck_media_assets_caption_status",
        ),
        Index("ix_media_assets_project_id_id", "project_id", text("id DESC")),
        # Векторный индекс объявлен здесь, иначе autogenerate считает его
        # лишним и предлагает удалить при каждой следующей ревизии.
        Index(
            "ix_media_assets_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("content_projects.id"), nullable=False
    )
    # Путь строит сервер из хеша содержимого: имя файла из запроса недоверенное
    # и в путь на диске не превращается.
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    # Превью считается один раз при загрузке и лежит рядом с оригиналом.
    thumb_path: Mapped[str | None] = mapped_column(Text)
    mime: Mapped[str] = mapped_column(String, nullable=False)
    bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String, nullable=False)
    caption: Mapped[str | None] = mapped_column(Text)
    # Имя модели подписи; у заглушки ровно "mock" — по нему ищут, что
    # перевыпустить после появления ключа.
    caption_model: Mapped[str | None] = mapped_column(String)
    caption_status: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'pending'")
    )
    embedding: Mapped[str | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    use_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )


class MediaUsageModel(Base):
    """Факт использования изображения постом; питает политику повторов."""

    __tablename__ = "media_usages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "asset_id"],
            ["media_assets.project_id", "media_assets.id"],
            name="fk_media_usages_project_asset",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["project_id", "post_id"],
            ["posts.project_id", "posts.id"],
            name="fk_media_usages_project_post",
        ),
        Index("ix_media_usages_project_id_asset_id", "project_id", "asset_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("content_projects.id"), nullable=False
    )
    asset_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    post_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
