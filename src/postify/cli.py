from __future__ import annotations

from datetime import UTC, datetime
from ipaddress import ip_address

import typer
import uvicorn

from postify.cli_media import app as media_app


app = typer.Typer(no_args_is_help=True)
app.add_typer(media_app, name="media")

# Системный промпт сервера пользователю недоступен: в API его нет вовсе
# (раздел 13 контракта), поэтому CLI — единственный способ править его, кроме
# прямого доступа к базе.
system_prompt_app = typer.Typer(
    no_args_is_help=True, help="Системный промпт сервера: общий для всех агентов."
)
app.add_typer(system_prompt_app, name="system-prompt")


@app.callback()
def main() -> None:
    pass


@system_prompt_app.command("show")
def show_system_prompt() -> None:
    """Показать текущий системный промпт сервера."""
    typer.echo(prompt_repository().system_prompt())


@system_prompt_app.command("set")
def set_system_prompt(
    prompt: str = typer.Argument(..., help="Новый текст промпта целиком"),
) -> None:
    """Заменить системный промпт сервера целиком."""
    saved = prompt_repository().set_system_prompt(prompt, now=datetime.now(UTC))
    typer.echo(f"Системный промпт обновлён, символов: {len(saved)}")


def prompt_repository():
    """Хранилище промптов, собранное из настроек. Тесты подменяют его целиком."""
    from sqlalchemy.orm import sessionmaker

    from postify.config import Settings
    from postify.infrastructure.database.engine import create_engine_from_settings
    from postify.infrastructure.repositories.sqlalchemy_prompts import (
        SqlAlchemyPromptRepository,
    )

    engine = create_engine_from_settings(Settings())
    return SqlAlchemyPromptRepository(sessionmaker(engine, expire_on_commit=False))


@app.command()
def ui(
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8000, min=1, max=65535),
    unsafe_external_bind: bool = typer.Option(
        False,
        "--unsafe-external-bind",
        help="Разрешить внешний bind только за аутентифицирующим reverse proxy.",
    ),
) -> None:
    """Запустить локальный HTTP-интерфейс Postify."""
    from postify.web.app import create_app

    if not _is_loopback_host(host) and not unsafe_external_bind:
        raise typer.BadParameter(
            "Внешний bind запрещён; нужен --unsafe-external-bind и auth proxy"
        )
    web_app = create_app() if _is_loopback_host(host) else create_app(trusted_hosts=("*",))
    uvicorn.run(web_app, host=host, port=port)


def _is_loopback_host(host: str) -> bool:
    if host.casefold() == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False
