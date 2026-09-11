"""Слоты контент-плана, запас времени на генерацию и режим публикации.

Календарь из мокапа — единственный источник состояния плана, поэтому слот
хранит и время публикации, и время старта генерации. ``generate_at``
материализован колонкой, а не считается на лету: планировщик выбирает по нему
«пора генерировать» индексом, а правка запаса времени в настройках проекта не
должна задним числом сдвигать уже стоящие в плане слоты.

Ссылки на рубрику и пост составные, через ``project_id``: рубрика или пост
чужого проекта в слот физически не попадут.

``(project_id, publish_at)`` уникален: проект равен одному каналу, и две
публикации на одну и ту же минуту в один канал — не план, а ошибка ввода.
Нужны две публикации подряд — они различаются минутой.

Здесь же две колонки проекта: ``generation_lead_minutes`` нужен слоту для
``generate_at``, ``publication_mode`` — треку публикации.

Расписание получает ``slot_id``: задача ``generate_post`` привязана к слоту,
а не к посту — поста в этот момент ещё нет.

Revision ID: 20260911_03
Revises: 20260911_02
"""

from alembic import op
import sqlalchemy as sa


revision = "20260911_03"
down_revision = "20260911_02"
branch_labels = None
depends_on = None


SLOT_STATUSES = (
    "'no_topic','planned','generating','needs_review','approved','published',"
    "'failed','skipped'"
)


def upgrade() -> None:
    op.add_column(
        "content_projects",
        sa.Column(
            "generation_lead_minutes",
            sa.Integer(),
            nullable=False,
            server_default="1440",
        ),
    )
    op.add_column(
        "content_projects",
        sa.Column(
            "publication_mode",
            sa.String(),
            nullable=False,
            server_default="review",
        ),
    )
    op.create_check_constraint(
        "ck_content_projects_publication_mode",
        "content_projects",
        "publication_mode IN ('review','auto')",
    )

    op.create_table(
        "content_plan_slots",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "project_id",
            sa.BigInteger(),
            sa.ForeignKey("content_projects.id"),
            nullable=False,
        ),
        sa.Column("publish_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("generate_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rubric_id", sa.BigInteger()),
        # Пустая тема допустима: слот заводится в календаре раньше, чем
        # придумана тема, и живёт со статусом no_topic.
        sa.Column("topic", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("post_id", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"status IN ({SLOT_STATUSES})", name="ck_content_plan_slots_status"
        ),
        sa.UniqueConstraint(
            "project_id", "id", name="uq_content_plan_slots_project_id_id"
        ),
        sa.UniqueConstraint(
            "project_id", "publish_at", name="uq_content_plan_slots_project_publish_at"
        ),
        # Пост рождается ровно из одного слота: обратная ссылка post.slot_id
        # обязана быть однозначной.
        sa.UniqueConstraint(
            "project_id", "post_id", name="uq_content_plan_slots_project_post_id"
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "rubric_id"],
            ["project_rubrics.project_id", "project_rubrics.id"],
            name="fk_content_plan_slots_project_rubric",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "post_id"],
            ["posts.project_id", "posts.id"],
            name="fk_content_plan_slots_project_post",
        ),
    )
    # Выборку диапазона календаря закрывает индекс уникальности
    # (project_id, publish_at); отдельный индекс на то же место не нужен.
    op.create_index(
        "ix_content_plan_slots_due",
        "content_plan_slots",
        ["project_id", "generate_at"],
        postgresql_where=sa.text("status = 'planned'"),
    )
    # Рубрика в использовании: удаление рубрики спрашивает именно об этом.
    op.create_index(
        "ix_content_plan_slots_rubric",
        "content_plan_slots",
        ["project_id", "rubric_id"],
    )

    for table in ("scheduled_jobs", "schedule_slot_claims"):
        op.add_column(table, sa.Column("slot_id", sa.BigInteger()))
        op.create_foreign_key(
            f"fk_{table}_project_slot",
            table,
            "content_plan_slots",
            ["project_id", "slot_id"],
            ["project_id", "id"],
        )
    # Идемпотентность расписания теперь различает задачи и по слоту: у
    # generate_post поста ещё нет, и без slot_id все они слиплись бы в одну.
    op.drop_index("uq_schedule_slot_claims_slot", table_name="schedule_slot_claims")
    op.create_index(
        "uq_schedule_slot_claims_slot",
        "schedule_slot_claims",
        [
            "project_id",
            "kind",
            "scheduled_for",
            sa.text("COALESCE(post_id, 0)"),
            sa.text("COALESCE(slot_id, 0)"),
        ],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_schedule_slot_claims_slot", table_name="schedule_slot_claims")
    op.create_index(
        "uq_schedule_slot_claims_slot",
        "schedule_slot_claims",
        ["project_id", "kind", "scheduled_for", sa.text("COALESCE(post_id, 0)")],
        unique=True,
    )
    for table in ("scheduled_jobs", "schedule_slot_claims"):
        op.drop_constraint(f"fk_{table}_project_slot", table, type_="foreignkey")
        op.drop_column(table, "slot_id")
    op.drop_index("ix_content_plan_slots_rubric", table_name="content_plan_slots")
    op.drop_index("ix_content_plan_slots_due", table_name="content_plan_slots")
    op.drop_table("content_plan_slots")
    op.drop_constraint(
        "ck_content_projects_publication_mode", "content_projects", type_="check"
    )
    op.drop_column("content_projects", "publication_mode")
    op.drop_column("content_projects", "generation_lead_minutes")
