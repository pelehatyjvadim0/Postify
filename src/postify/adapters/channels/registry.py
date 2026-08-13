from postify.domain.projects.models import UnsupportedProvider


class ChannelProviderRegistry:
    def catalog(self) -> tuple[dict[str, object], ...]:
        return ({
            "code": "telegram",
            "label": "Telegram",
            "fields": (
                {"name": "chat_id", "label": "ID чата", "type": "text", "required": True},
            ),
            "credential": {
                "name": "token",
                "label": "Токен бота",
                "input_type": "password",
            },
        },)

    def validate(self, provider: str, configuration: object) -> dict[str, object]:
        if provider != "telegram":
            raise UnsupportedProvider(f"Канал {provider} не поддерживается")
        if not isinstance(configuration, dict):
            raise ValueError("Конфигурация канала должна быть объектом")
        extra = set(configuration) - {"chat_id"}
        if extra:
            raise ValueError("Неизвестные параметры Telegram")
        chat_id = " ".join(str(configuration.get("chat_id", "")).split())
        if not chat_id:
            raise ValueError("Нужен chat_id")
        return {"chat_id": chat_id}

    def create_publisher(self, channel, *, decrypted_secret: str, client):
        from postify.adapters.telegram.bot_api import TelegramBotApiPublisher

        configuration = self.validate(channel.provider, channel.configuration)
        factories = {
            "telegram": lambda: TelegramBotApiPublisher(
                client,
                bot_token=decrypted_secret,
                chat_id=configuration["chat_id"],
            )
        }
        try:
            return factories[channel.provider]()
        except KeyError:
            raise UnsupportedProvider(
                f"Канал {channel.provider} не поддерживается"
            ) from None
