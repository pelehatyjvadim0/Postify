from __future__ import annotations

from ipaddress import ip_address

import typer
import uvicorn


app = typer.Typer(no_args_is_help=True)


@app.callback()
def main() -> None:
    pass


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
