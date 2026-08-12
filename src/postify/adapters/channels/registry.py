from postify.domain.projects.models import UnsupportedProvider


class ChannelProviderRegistry:
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

