from datetime import UTC, datetime

from alembic import command
import pytest
from sqlalchemy import create_engine, text


pytestmark = pytest.mark.integration
NOW = datetime(2026, 9, 5, 12, tzinfo=UTC)


def test_cleanup_preserves_editorial_data_and_converts_legacy_configuration(alembic_config, isolated_database_url):
    command.upgrade(alembic_config, "20260905_18")
    engine = create_engine(isolated_database_url)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("""
                UPDATE content_projects SET configuration='{
                    "daily_analysis_limit":2,"daily_package_limit":1,
                    "selection_rules":["advertising"],"topic_terms":["old"],
                    "media_max_bytes":10000000,"analysis_timeout_seconds":60,
                    "analysis_model":"gpt-5.6-terra","analysis_reasoning_effort":"medium",
                    "source_language":"ar","tone":"Кратко","delivery_lateness_seconds":null
                }'::jsonb WHERE id=1
            """)
            seed_sql = """
                INSERT INTO source_connections(id,project_id,provider,name,enabled,configuration,schedule,created_at,updated_at)
                VALUES (11,1,'telegram_account','Источник',true,'{}','0 8 * * *',:now,:now);
                INSERT INTO telegram_source_state VALUES (1,11,'group-11',42);
                INSERT INTO content_formats(id,project_id,name,kind,instructions,enabled,created_at,updated_at)
                VALUES (21,1,'Пост','text','Факты',true,:now,:now);
                INSERT INTO channel_connections(id,project_id,provider,name,enabled,configuration,connection_status,created_at,updated_at)
                VALUES (31,1,'telegram','Канал',true,'{}','unknown',:now,:now);
                INSERT INTO calls_to_action(id,project_id,name,text,link_mode,enabled,created_at,updated_at)
                VALUES (41,1,'Старый CTA','Подпишись','none',true,:now,:now);
                INSERT INTO publication_routes(id,project_id,format_id,channel_id,cta_id,enabled,schedule,created_at,updated_at)
                VALUES (51,1,21,31,41,true,'{}',:now,:now);
                INSERT INTO candidates(id,project_id,source_name,source_id,title,url,discovered_at,source_text,source_connection_id,raw_payload)
                VALUES (61,1,'telegram_account','43','Материал','',:now,'Исходный текст',11,'{}');
                INSERT INTO content_attempts(id,project_id,candidate_id,attempt_no,tier,status,source_url,started_at)
                VALUES (71,1,61,1,'fresh','packaged','',:now);
                INSERT INTO content_packages(id,project_id,attempt_id,source_url,context,analysis,post_text,review_required,status,created_at,updated_at,scheduled_at,route_id,generation_snapshot)
                VALUES (81,1,71,'','Контекст','Анализ','Готовый текст',true,'approved',:now,:now,:now,51,'{"cta":{"text":"Исторический CTA"}}');
                INSERT INTO deliveries(id,project_id,package_id,route_id,channel_id,status,attempt_no,message_id,sending_started_at,confirmed_at,created_at,updated_at)
                VALUES (91,1,81,51,31,'published',1,101,:now,:now,:now,:now);
                INSERT INTO operation_runs(id,project_id,operation,status,started_at)
                VALUES (111,1,'load_more','running',:now)
            """
            for statement in seed_sql.split(";"):
                connection.execute(text(statement), {"now": NOW})

        command.upgrade(alembic_config, "head")
        with engine.connect() as connection:
            config = connection.execute(text("SELECT configuration FROM content_projects WHERE id=1")).scalar_one()
            assert config == {
                "analysis_batch_size": 2, "media_max_bytes": 10000000,
                "analysis_timeout_seconds": 60, "analysis_model": "gpt-5.6-terra",
                "analysis_reasoning_effort": "medium", "source_language": "ar",
                "tone": "Кратко", "delivery_lateness_seconds": None,
            }
            row = connection.execute(text("""
                SELECT c.id,c.source_text,p.id,p.post_text,p.status,p.scheduled_at,p.route_id,
                       p.generation_snapshot,d.id,d.message_id,s.initial_after_message_id
                FROM candidates c JOIN content_attempts a ON a.candidate_id=c.id
                JOIN content_packages p ON p.attempt_id=a.id
                JOIN deliveries d ON d.package_id=p.id
                JOIN telegram_source_state s ON s.source_connection_id=c.source_connection_id
                WHERE p.id=81
            """)).one()
            assert tuple(row) == (61,"Исходный текст",81,"Готовый текст","approved",NOW,51,
                                  {"cta":{"text":"Исторический CTA"}},91,101,42)
            assert tuple(connection.execute(text("SELECT status,failure_code FROM operation_runs WHERE id=111")).one()) == ("failed","load_more_failed")
    finally:
        engine.dispose()
