from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from postify.application.ports.validation import ValidationReport
from postify.application.validation.models import ProjectRule
from postify.infrastructure.repositories.sqlalchemy_validation import (
    SqlAlchemyRulesRepository,
    SqlAlchemyValidationJournal,
)


pytestmark = pytest.mark.integration
NOW = datetime(2026, 9, 12, tzinfo=UTC)


@pytest.fixture
def engine(migrated_database_url):
    value = create_engine(migrated_database_url)
    try:
        yield value
    finally:
        value.dispose()


def seed(engine):
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO users(id,telegram_user_id,telegram_username,display_name,created_at,is_active) VALUES (1,'1','u','u',:now,true)"), {"now": NOW})
        connection.execute(text("INSERT INTO content_projects(id,owner_id,name,timezone,language,audience,project_prompt,configuration,created_at,updated_at) VALUES (1,1,'p','UTC','ru','','','{}',:now,:now)"), {"now": NOW})
        connection.execute(text("INSERT INTO posts(id,project_id,post_text,status,created_at,updated_at) VALUES (1,1,'post','generating',:now,:now)"), {"now": NOW})


def test_rules_are_replaced_atomically_and_ordered(engine):
    seed(engine)
    repository = SqlAlchemyRulesRepository(sessionmaker(engine))
    repository.replace_rules(1, [ProjectRule(0, 1, "second", "warn", True, "manual", 0), ProjectRule(0, 1, "first", "block", True, "derived", 1)])
    result = repository.list_rules(1)
    assert [r.text for r in result] == ["second", "first"]


def test_journal_returns_latest_iteration(engine):
    seed(engine)
    journal = SqlAlchemyValidationJournal(sessionmaker(engine))
    journal.save(1, iteration=0, report=ValidationReport(False, layers=({"layer": "format", "passed": False, "items": []},)), now=NOW)
    journal.save(1, iteration=1, report=ValidationReport(True, layers=({"layer": "format", "passed": True, "items": []},)), now=NOW)
    assert journal.report(1) == {"passed": True, "iterations": 1, "layers": [{"layer": "format", "passed": True, "items": []}]}
