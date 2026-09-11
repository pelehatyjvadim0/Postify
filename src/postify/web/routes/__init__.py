"""Роутеры API, разрезанные по доменам контракта.

Каждый роутер с ``project_id`` объявляет ``owned_project`` в зависимостях
роутера, а не отдельных обработчиков: так новый эндпоинт не может появиться
без проверки владения.
"""

from postify.web.routes import media, operations, posts, projects, rubrics


API_ROUTERS = (
    projects.collection,
    projects.router,
    rubrics.router,
    posts.router,
    media.router,
    operations.router,
)


__all__ = ["API_ROUTERS"]
