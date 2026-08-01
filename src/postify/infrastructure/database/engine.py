from __future__ import annotations

from sqlalchemy import Engine, create_engine

from postify.config import Settings


def create_engine_from_settings(settings: Settings) -> Engine:
    return create_engine(str(settings.database_url))
