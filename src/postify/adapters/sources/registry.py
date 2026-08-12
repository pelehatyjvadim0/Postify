from urllib.parse import urlsplit

from postify.domain.projects.models import UnsupportedProvider


class SourceProviderRegistry:
    def validate(self, provider: str, configuration: object) -> dict[str, object]:
        if provider != "hn_algolia":
            raise UnsupportedProvider(f"Источник {provider} не поддерживается")
        if not isinstance(configuration, dict):
            raise ValueError("Конфигурация источника должна быть объектом")
        extra = set(configuration) - {"url", "query", "tags", "hits"}
        if extra:
            raise ValueError("Неизвестные параметры HN Algolia")
        url = str(configuration.get("url", "")).strip()
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.netloc:
            raise ValueError("Нужен абсолютный HTTPS URL источника")
        query = " ".join(str(configuration.get("query", "")).split())
        tags = " ".join(str(configuration.get("tags", "")).split())
        hits = configuration.get("hits")
        if not query or not tags:
            raise ValueError("query и tags не могут быть пустыми")
        if type(hits) is not int or not 1 <= hits <= 1000:
            raise ValueError("hits должен быть от 1 до 1000")
        return {"url": url, "query": query, "tags": tags, "hits": hits}

