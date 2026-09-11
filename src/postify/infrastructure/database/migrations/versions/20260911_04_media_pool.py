"""Пул изображений проекта: активы, журнал использований, политика повторов.

Подпись и эмбеддинг считаются асинхронно, поэтому ``caption``, ``caption_model``
и ``embedding`` допускают NULL: изображение сохраняется до обращения к модели и
существует без подписи, если провайдер недоступен (трейс, раздел 5).

``embedding`` — ровно ``vector(768)``: заглушка и настоящий провайдер отдают
одну размерность специально, чтобы появление ключа Gemini не требовало
миграции. ``caption_model`` хранит имя модели (у заглушки ровно ``mock``) —
по нему находят и перевыпускают всё, что подписала заглушка.

Расширение ``vector`` включает стартовая миграция.

Revision ID: 20260911_04
Revises: 20260911_02
"""

from alembic import op
import sqlalchemy as sa

from postify.infrastructure.database.models.media import Vector


revision = "20260911_04"
down_revision = "20260911_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Расширение ``vector`` включает стартовая миграция. Но оно глобально на
    # базу, а схема у него своя: при накате в отдельную схему (так работают
    # интеграционные тесты) тип ``vector`` может оказаться вне search_path, и
    # создание колонки упадёт на «type vector does not exist». Добавляем схему
    # расширения в путь на время этой транзакции — таблицы всё равно лягут в
    # первую схему пути, она не меняется.
    op.execute(
        "SELECT set_config('search_path',"
        " current_setting('search_path') || ',' || quote_ident(n.nspname), true)"
        " FROM pg_extension e JOIN pg_namespace n ON n.oid = e.extnamespace"
        " WHERE e.extname = 'vector'"
    )

    op.create_table(
        "media_assets",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "project_id",
            sa.BigInteger(),
            sa.ForeignKey("content_projects.id"),
            nullable=False,
        ),
        # Путь на диске строит сервер из хеша содержимого; имя файла из запроса
        # в путь не превращается никогда — загруженное имя недоверенное.
        sa.Column("file_path", sa.Text(), nullable=False),
        # Превью считается один раз при загрузке и лежит рядом с оригиналом.
        sa.Column("thumb_path", sa.Text()),
        sa.Column("mime", sa.String(), nullable=False),
        sa.Column("bytes", sa.BigInteger(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        # SHA-256 содержимого: повторная загрузка того же файла в тот же проект
        # не заводит вторую запись.
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("caption", sa.Text()),
        sa.Column("caption_model", sa.String()),
        sa.Column(
            "caption_status",
            sa.String(),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("embedding", Vector(768), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column(
            "use_count", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.UniqueConstraint("project_id", "id", name="uq_media_assets_project_id_id"),
        sa.UniqueConstraint(
            "project_id", "content_hash", name="uq_media_assets_project_id_content_hash"
        ),
        sa.CheckConstraint(
            "caption_status IN ('pending','ready','failed')",
            name="ck_media_assets_caption_status",
        ),
    )
    # Список пула идёт от свежих к старым и постранично по курсору.
    op.create_index(
        "ix_media_assets_project_id_id",
        "media_assets",
        ["project_id", sa.text("id DESC")],
    )
    # Подбор изображения ищет ближайшие по косинусному расстоянию.
    #
    # HNSW, а не IVFFlat: IVFFlat строит списки по уже лежащим строкам и на
    # пустой таблице бесполезен, а пул начинается пустым и растёт загрузками —
    # его пришлось бы периодически перестраивать. HNSW строится инкрементально.
    # Параметры оставлены умолчанием pgvector (m=16, ef_construction=64): для
    # пула в сотни изображений это заведомо с запасом, а память под индекс
    # такого размера пренебрежима. Замеров на этом объёме нет — подбирать
    # параметры до появления настоящих векторов не на чем (трейс, раздел 16).
    op.execute(
        "CREATE INDEX ix_media_assets_embedding ON media_assets"
        " USING hnsw (embedding vector_cosine_ops)"
    )

    op.create_table(
        "media_usages",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "project_id",
            sa.BigInteger(),
            sa.ForeignKey("content_projects.id"),
            nullable=False,
        ),
        sa.Column("asset_id", sa.BigInteger(), nullable=False),
        sa.Column("post_id", sa.BigInteger(), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=False),
        # Составные ключи: изображение и пост обязаны принадлежать тому же
        # проекту, что и запись об использовании.
        sa.ForeignKeyConstraint(
            ["project_id", "asset_id"],
            ["media_assets.project_id", "media_assets.id"],
            name="fk_media_usages_project_asset",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "post_id"],
            ["posts.project_id", "posts.id"],
            name="fk_media_usages_project_post",
        ),
    )
    op.create_index(
        "ix_media_usages_project_id_asset_id", "media_usages", ["project_id", "asset_id"]
    )

    # Политика повторов: изображение не предлагается снова, пока с последнего
    # использования не прошло столько дней. Умолчание из контракта, раздел 4.
    op.add_column(
        "content_projects",
        sa.Column(
            "media_reuse_days",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("30"),
        ),
    )


def downgrade() -> None:
    op.drop_column("content_projects", "media_reuse_days")
    op.drop_index("ix_media_usages_project_id_asset_id", table_name="media_usages")
    op.drop_table("media_usages")
    op.execute("DROP INDEX IF EXISTS ix_media_assets_embedding")
    op.drop_index("ix_media_assets_project_id_id", table_name="media_assets")
    op.drop_table("media_assets")
