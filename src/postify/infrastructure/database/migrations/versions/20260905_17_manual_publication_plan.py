"""Store source text and an editor-owned publication plan."""
from alembic import op
import sqlalchemy as sa

revision = "20260905_17"
down_revision = "20260817_16"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("candidates", sa.Column("source_text", sa.Text()))
    op.add_column("candidates", sa.Column("published_at", sa.DateTime(timezone=True)))
    op.add_column("candidates", sa.Column("source_connection_id", sa.BigInteger()))
    op.create_unique_constraint("uq_source_connections_project_id_id", "source_connections", ["project_id", "id"])
    op.create_foreign_key("fk_candidates_project_source", "candidates", "source_connections", ["project_id", "source_connection_id"], ["project_id", "id"])
    op.drop_constraint("uq_candidates_project_source_name_source_id", "candidates", type_="unique")
    op.create_index("uq_candidates_project_source_name_source_id", "candidates", ["project_id", "source_name", "source_id"], unique=True, postgresql_where=sa.text("source_connection_id IS NULL"))
    op.create_index("uq_candidates_connection_message", "candidates", ["project_id", "source_connection_id", "source_id"], unique=True, postgresql_where=sa.text("source_connection_id IS NOT NULL"))
    op.add_column("content_packages", sa.Column("scheduled_at", sa.DateTime(timezone=True)))
    op.add_column("content_packages", sa.Column("route_id", sa.BigInteger()))
    op.create_foreign_key("fk_content_packages_project_route", "content_packages", "publication_routes", ["project_id", "route_id"], ["project_id", "id"])
    op.create_check_constraint("ck_content_packages_plan_pair", "content_packages", "(scheduled_at IS NULL) = (route_id IS NULL)")
    op.create_index("ix_content_packages_due", "content_packages", ["scheduled_at", "id"], postgresql_where=sa.text("status = 'approved'"))
    # Existing approvals have no editor-owned plan and cannot be sent by the new runtime.
    for table in ("scheduled_jobs", "schedule_slot_claims"):
        op.add_column(table, sa.Column("package_id", sa.BigInteger()))
        op.create_foreign_key(f"fk_{table}_project_package", table, "content_packages", ["project_id", "package_id"], ["project_id", "id"])
    op.drop_index("uq_schedule_slot_claims_route_slot", table_name="schedule_slot_claims")
    op.create_index("uq_schedule_slot_claims_route_slot", "schedule_slot_claims", ["project_id", "kind", "scheduled_for", sa.text("COALESCE(route_id, 0)"), sa.text("COALESCE(package_id, 0)")], unique=True)


def downgrade() -> None:
    op.drop_index("uq_schedule_slot_claims_route_slot", table_name="schedule_slot_claims")
    op.create_index("uq_schedule_slot_claims_route_slot", "schedule_slot_claims", ["project_id", "kind", "scheduled_for", sa.text("COALESCE(route_id, 0)")], unique=True)
    for table in ("scheduled_jobs", "schedule_slot_claims"):
        op.drop_constraint(f"fk_{table}_project_package", table, type_="foreignkey")
        op.drop_column(table, "package_id")
    op.drop_index("ix_content_packages_due", table_name="content_packages")
    op.drop_constraint("ck_content_packages_plan_pair", "content_packages", type_="check")
    op.drop_constraint("fk_content_packages_project_route", "content_packages", type_="foreignkey")
    op.drop_column("content_packages", "route_id")
    op.drop_column("content_packages", "scheduled_at")
    op.drop_index("uq_candidates_connection_message", table_name="candidates")
    op.drop_index("uq_candidates_project_source_name_source_id", table_name="candidates")
    op.create_unique_constraint("uq_candidates_project_source_name_source_id", "candidates", ["project_id", "source_name", "source_id"])
    op.drop_constraint("fk_candidates_project_source", "candidates", type_="foreignkey")
    op.drop_constraint("uq_source_connections_project_id_id", "source_connections", type_="unique")
    for column in ("source_connection_id", "published_at", "source_text"):
        op.drop_column("candidates", column)
