"""Shared settings fixture retained for integration contours after HN removal."""

from postify.config import Settings


def configured_settings(database_url: str) -> Settings:
    return Settings(
        database_url=database_url,
        content_media_dir="/tmp/postify-test-media",
        postify_secret_key="2G3vFJDo4_4KsGUHKXWLWSMQe_R3oIGfq9hnv18gPXo=",
    )
