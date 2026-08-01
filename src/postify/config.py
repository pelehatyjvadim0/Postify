from typing import Literal

from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    database_url: PostgresDsn
    hn_algolia_url: str = "https://hn.algolia.com/api/v1/search_by_date"
    hn_query: str = Field(min_length=1)
    hn_tags: str = "story"
    hn_hits_per_page: int = Field(default=100, ge=1)
    postgresql_systemd_unit: str = "postgresql.service"
    postgresql_ownership: Literal["dedicated", "shared_allowed"]
    postify_on_calendar: str = Field(min_length=1)
    postify_timezone: str = Field(min_length=1)

    @field_validator("postgresql_systemd_unit")
    @classmethod
    def validate_postgresql_systemd_unit(cls, value: str) -> str:
        if not value.endswith(".service"):
            raise ValueError("Имя systemd-unit должно оканчиваться на .service")
        return value
