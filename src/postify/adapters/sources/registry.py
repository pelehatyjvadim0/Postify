from postify.domain.projects.models import UnsupportedProvider


class SourceProviderRegistry:
    def catalog(self) -> tuple[dict[str, object], ...]:
        return ({
            "code": "telegram_group",
            "label": "Telegram-группа",
            "fields": ({"name": "group_id", "label": "Группа", "type": "text", "required": True},),
        },)

    def validate(self, provider: str, configuration: object) -> dict[str, object]:
        if provider == "telegram_group":
            if not isinstance(configuration, dict) or set(configuration) != {"group_id"}:
                raise ValueError("Нужен идентификатор Telegram-группы")
            group_id = configuration["group_id"]
            if not isinstance(group_id, str) or not group_id.strip():
                raise ValueError("Нужен идентификатор Telegram-группы")
            return {"group_id": group_id.strip()}
        raise UnsupportedProvider(f"Источник {provider} не поддерживается")

    def create(self, connection, *, client, telegram_reader=None):
        configuration = self.validate(connection.provider, connection.configuration)
        if connection.provider == "telegram_group":
            from postify.adapters.sources.telegram_group import TelegramGroupSource
            return TelegramGroupSource(connection_id=connection.id, group_id=configuration["group_id"], reader=telegram_reader)
        raise UnsupportedProvider(f"Источник {connection.provider} не поддерживается")
