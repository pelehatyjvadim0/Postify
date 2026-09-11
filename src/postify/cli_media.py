"""CLI пула изображений: перевыпуск подписей и эмбеддингов.

Это вторая половина перехода с заглушки на настоящего провайдера. Первая —
настройка: появился ``GEMINI_API_KEY``, и ``AI_MEDIA_PROVIDER=auto`` сам
перестаёт выбирать заглушку. Но всё, что заглушка уже подписала, осталось в
базе с ``caption_model='mock'``: подписи не описывают снимки, а векторы
выведены из хеша текста и для поиска бесполезны. Эта команда находит такие
активы и подписывает их заново.

Живёт отдельным модулем, а не в ``cli.py``: тот в этой волне занят другим
треком. Подключается одной строкой в приложении Typer — см. отчёт трека.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text
import typer
from sqlalchemy.orm import sessionmaker

from postify.application.ai.factory import build_model_gateway, resolve_media_provider
from postify.application.media.captioning import CaptionMedia, RecaptionAssets
from postify.config import Settings
from postify.infrastructure.database.engine import create_engine_from_settings
from postify.infrastructure.repositories.sqlalchemy_media import (
    SqlAlchemyMediaRepository,
)


app = typer.Typer(no_args_is_help=True, help="Пул изображений проекта.")

MOCK_CAPTION_MODEL = "mock"


@app.command("recaption")
def recaption(
    project: int | None = typer.Option(
        None, "--project", help="Только этот проект. По умолчанию — все проекты."
    ),
    caption_model: str = typer.Option(
        MOCK_CAPTION_MODEL,
        "--caption-model",
        help="Какие подписи перевыпускать. По умолчанию сделанные заглушкой.",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Только показать, сколько активов затронет."
    ),
) -> None:
    """Перевыпустить подписи и эмбеддинги изображений.

    Без ``--project`` проходит по всем проектам. Печатает сводку по каждому и
    завершается ненулевым кодом, если хотя бы одна подпись не удалась: молча
    оставить половину пула непереведённой хуже, чем сообщить об этом.
    """
    settings = Settings()
    provider = resolve_media_provider(settings)
    if provider == "mock" and caption_model == MOCK_CAPTION_MODEL:
        # Иначе команда перевыпустила бы заглушку заглушкой и отрапортовала успех.
        raise typer.BadParameter(
            "Провайдер медиа — заглушка: перевыпускать нечем. "
            "Задайте GEMINI_API_KEY или AI_MEDIA_PROVIDER=gemini."
        )

    engine = create_engine_from_settings(settings)
    sessions = sessionmaker(engine)
    gateway = build_model_gateway(settings)
    failures = 0
    try:
        for project_id in _projects(sessions, project):
            repository = SqlAlchemyMediaRepository(sessions, project_id)
            asset_ids = repository.ids_captioned_by(caption_model)
            if not asset_ids:
                continue
            if dry_run:
                typer.echo(f"проект {project_id}: {len(asset_ids)} к перевыпуску")
                continue
            report = RecaptionAssets(
                repository,
                CaptionMedia(
                    repository,
                    gateway,
                    project_id=project_id,
                    clock=lambda: datetime.now(UTC),
                ),
                project_id=project_id,
            ).execute(asset_ids)
            failures += report.failed
            typer.echo(
                f"проект {project_id}: перевыпущено {report.captioned}"
                f" из {report.requested}, неудач {report.failed}"
            )
            for error in report.errors:
                typer.echo(f"  актив {error.get('asset_id')}: {error.get('code')}")
    finally:
        engine.dispose()

    if failures:
        raise typer.Exit(code=1)


def _projects(sessions, project: int | None) -> tuple[int, ...]:
    if project is not None:
        return (project,)
    with sessions() as session:
        return tuple(
            session.scalars(text("SELECT id FROM content_projects ORDER BY id")).all()
        )
