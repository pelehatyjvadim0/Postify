"""Роутеры API, разрезанные по доменам контракта.

Каждый роутер с ``project_id`` объявляет ``owned_project`` в зависимостях
роутера, а не отдельных обработчиков: так новый эндпоинт не может появиться
без проверки владения.
"""

from postify.web import image_search

from postify.web.routes import (
    media,
    operations,
    plan,
    posts,
    projects,
    prompts,
    rubrics,
    rules,
)


API_ROUTERS = (
    projects.collection,
    projects.router,
    rubrics.router,
    plan.router,
    posts.router,
    media.router,
    image_search.router,
    operations.router,
    prompts.router,
    rules.router,
)


__all__ = ["API_ROUTERS"]
