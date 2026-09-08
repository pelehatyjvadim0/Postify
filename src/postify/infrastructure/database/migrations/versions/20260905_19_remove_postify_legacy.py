"""Remove obsolete Postify settings and queues, preserving editorial records."""
from alembic import op

revision = "20260905_19"
down_revision = "20260905_18"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO content_formats(project_id,name,kind,instructions,enabled,created_at,updated_at)
        SELECT p.id,'Пост','text',
            'Сохрани смысл, имена, числа и факты оригинала. Не добавляй утверждений. Подготовь естественный текст.',
            true,now(),now()
        FROM content_projects p
        WHERE p.configuration <> '{}'::jsonb
          AND NOT EXISTS (
              SELECT 1 FROM content_formats f WHERE f.project_id=p.id
          )
    """)
    op.execute("""
        UPDATE content_projects SET configuration = jsonb_build_object(
            'analysis_batch_size', COALESCE(configuration->'analysis_batch_size', configuration->'daily_analysis_limit', '100'::jsonb),
            'media_max_bytes', COALESCE(configuration->'media_max_bytes', '10000000'::jsonb),
            'analysis_timeout_seconds', COALESCE(configuration->'analysis_timeout_seconds', '60'::jsonb),
            'analysis_model', COALESCE(configuration->'analysis_model', '"gpt-5.6-terra"'::jsonb),
            'analysis_reasoning_effort', COALESCE(configuration->'analysis_reasoning_effort', '"high"'::jsonb),
            'source_language', COALESCE(configuration->'source_language', '"ar"'::jsonb),
            'tone', COALESCE(configuration->'tone', '"Нейтральный"'::jsonb),
            'delivery_lateness_seconds', COALESCE(configuration->'delivery_lateness_seconds', 'null'::jsonb)
        )
        WHERE configuration <> '{}'::jsonb
    """)
    # Preserve historical journal entries, but never resume retired commands.
    op.execute("""
        UPDATE operation_runs SET status='failed', outcome=NULL,
            failure_code=operation || '_failed', finished_at=now()
        WHERE status='running' AND operation IN ('load_more','publish_now','replace_media')
    """)
    op.execute("""
        UPDATE operation_runs SET status='failed', outcome=NULL,
            failure_code='publish_once_failed', finished_at=now()
        WHERE status='running' AND id IN (
            SELECT operation_run_id FROM scheduled_jobs
            WHERE kind='publish_once' AND package_id IS NULL AND status IN ('queued','leased')
        )
    """)
    op.execute("""
        UPDATE scheduled_jobs SET status='failed', lease_expires_at=NULL, updated_at=now()
        WHERE kind='publish_once' AND package_id IS NULL AND status IN ('queued','leased')
    """)
    op.execute("""
        UPDATE content_attempts a SET status='failed',
            failure_code=CASE WHEN c.source_text IS NULL OR btrim(c.source_text)=''
                THEN 'source_text_unavailable' ELSE 'generation_retry_required' END,
            retry_at=NULL, finished_at=now()
        FROM candidates c WHERE c.id=a.candidate_id AND c.project_id=a.project_id
            AND a.status='retry_scheduled'
    """)
    # Keep connections referenced by historical materials, but disable fetching.
    op.execute("UPDATE source_connections SET enabled=false WHERE provider='hn_algolia'")
    op.execute("""
        DELETE FROM source_connections s WHERE provider='hn_algolia'
            AND NOT EXISTS (SELECT 1 FROM candidates c WHERE c.source_connection_id=s.id AND c.project_id=s.project_id)
    """)
    op.drop_column("publication_routes", "cta_id")
    op.drop_column("publication_routes", "schedule")
    op.drop_table("calls_to_action")
    op.drop_table("candidate_decisions")
    op.drop_table("content_daily_usage")
    op.drop_table("content_quota_state")
    op.drop_column("content_attempts", "tier")
    op.drop_column("content_packages", "review_required")


def downgrade() -> None:
    raise RuntimeError("Очистка удаляет устаревшие данные; восстановите резервную копию БД вместе с прежним кодом")
