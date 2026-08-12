from datetime import UTC, datetime
from types import SimpleNamespace

from pydantic import SecretStr

from postify.adapters.channels.registry import ChannelProviderRegistry
from postify.adapters.sources.registry import SourceProviderRegistry
from postify.application.projects.bootstrap_project import BootstrapProject
from postify.infrastructure.security.secrets import SecretCipher


class MemoryBootstrapRepository:
    def __init__(self) -> None:
        self.project = None
        self.sources = []
        self.channels = []
        self.formats = []
        self.ctas = []
        self.routes = []

    def active_project(self):
        return self.project

    def create_project_graph(self, graph):
        if self.project is not None:
            return self.project
        self.project = graph.project
        self.sources.extend(graph.sources)
        self.channels.extend(graph.channels)
        self.formats.extend(graph.formats)
        self.ctas.extend(graph.ctas)
        self.routes.extend(graph.routes)
        return self.project


def settings():
    return SimpleNamespace(
        hn_algolia_url="https://hn.algolia.com/api/v1/search_by_date",
        hn_query="python",
        hn_tags="story",
        hn_hits_per_page=100,
        postify_on_calendar="0 7 * * 1-5",
        postify_timezone="Europe/Moscow",
        selection_policy_version="generic-v1",
        selection_language="ru",
        selection_audience="Продуктовые команды",
        selection_rules=("advertising", "out_of_scope"),
        selection_topic_terms=("практика",),
        selection_topic_exclusion_terms=("лотерея",),
        selection_advertising_terms=("реклама",),
        selection_hiring_terms=(),
        selection_technical_release_terms=(),
        selection_practical_terms=(),
        selection_freshness_days=30,
        content_daily_analysis_limit=12,
        content_daily_package_limit=3,
        content_priority_freshness_days=14,
        content_fresh_share_percent=90,
        content_reserve_share_percent=10,
        content_review_required=True,
        content_article_max_bytes=2_000_000,
        content_media_max_bytes=10_000_000,
        content_codex_timeout_seconds=600,
    )


def test_bootstrap_is_idempotent_and_creates_provider_neutral_graph() -> None:
    repository = MemoryBootstrapRepository()
    action = BootstrapProject(
        repository,
        SourceProviderRegistry(),
        ChannelProviderRegistry(),
        cipher=None,
        clock=lambda: datetime(2026, 8, 12, 9, tzinfo=UTC),
    )

    first = action.execute(settings(), telegram=None)
    second = action.execute(settings(), telegram=None)

    assert first is second
    assert len(repository.sources) == 1
    assert repository.sources[0].provider == "hn_algolia"
    assert len(repository.formats) == 1
    assert repository.formats[0].name == "Практический разбор B"
    assert repository.channels == []
    assert repository.routes == []


def test_bootstrap_encrypts_telegram_token_and_keeps_it_out_of_configuration() -> None:
    from cryptography.fernet import Fernet

    repository = MemoryBootstrapRepository()
    cipher = SecretCipher(Fernet.generate_key().decode())
    telegram = SimpleNamespace(
        telegram_chat_id="-100123",
        telegram_bot_token=SecretStr("123:token"),
    )

    BootstrapProject(
        repository,
        SourceProviderRegistry(),
        ChannelProviderRegistry(),
        cipher=cipher,
        clock=lambda: datetime(2026, 8, 12, 9, tzinfo=UTC),
    ).execute(settings(), telegram)

    channel = repository.channels[0]
    assert channel.configuration == {"chat_id": "-100123"}
    assert "token" not in str(channel.configuration).casefold()
    assert cipher.decrypt(channel.encrypted_secret) == "123:token"
    assert repository.routes[0].channel_id == channel.id


def test_bootstrap_stays_readable_without_cipher_and_skips_secret_channel() -> None:
    repository = MemoryBootstrapRepository()
    telegram = SimpleNamespace(
        telegram_chat_id="-100123",
        telegram_bot_token=SecretStr("123:token"),
    )

    project = BootstrapProject(
        repository,
        SourceProviderRegistry(),
        ChannelProviderRegistry(),
        cipher=None,
        clock=lambda: datetime(2026, 8, 12, 9, tzinfo=UTC),
    ).execute(settings(), telegram)

    assert project.id == 1
    assert repository.channels == []
