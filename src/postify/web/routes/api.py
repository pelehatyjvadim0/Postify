from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response

from postify.web.dependencies import WebContainer
from postify.web.schemas import (
    ChannelRequest,
    ConfigurationSettingsRequest,
    CtaRequest,
    MainSettingsRequest,
    RejectRequest,
    RouteRequest,
    SourceRequest,
)


router = APIRouter(prefix="/api/v1")


def container_for(request: Request) -> WebContainer:
    return request.app.state.container


Container = Annotated[WebContainer, Depends(container_for)]


def _safe(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _safe(item)
            for key, item in value.items()
            if key.casefold() == "secretconfigured"
            or ("token" not in key.casefold() and "secret" not in key.casefold())
        }
    if isinstance(value, tuple | list):
        return [_safe(item) for item in value]
    return value


def _response(value: object, *, status_code: int = 200):
    return JSONResponse(content=jsonable_encoder(_safe(value)), status_code=status_code)


@router.get("/bootstrap")
def bootstrap(container: Container):
    return _response(container.api.bootstrap())


@router.get("/projects/{project_id}/dashboard")
def dashboard(project_id: int, container: Container):
    return _response(container.api.dashboard(project_id))


@router.get("/projects/{project_id}/materials")
def materials(
    project_id: int,
    container: Container,
    status: str | None = None,
    query: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    return _response(
        container.api.materials(
            project_id, status=status, query=query, limit=limit, offset=offset
        )
    )


@router.get("/projects/{project_id}/packages")
def packages(
    project_id: int,
    container: Container,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    return _response(
        container.api.packages(project_id, status=status, limit=limit, offset=offset)
    )


@router.get("/projects/{project_id}/packages/{package_id}")
def package(project_id: int, package_id: int, container: Container):
    return _response(container.api.package(project_id, package_id))


@router.post("/projects/{project_id}/packages/{package_id}/approve")
def approve(project_id: int, package_id: int, container: Container):
    return _response(container.api.approve(project_id, package_id))


@router.post("/projects/{project_id}/packages/{package_id}/reject")
def reject(
    project_id: int, package_id: int, body: RejectRequest, container: Container
):
    return _response(container.api.reject(project_id, package_id, body.reason))


@router.get("/projects/{project_id}/queue")
def queue(project_id: int, container: Container):
    return _response(container.api.queue(project_id))


@router.get("/projects/{project_id}/publications")
def publications(
    project_id: int, container: Container, limit: int = 50, offset: int = 0
):
    return _response(container.api.publications(project_id, limit=limit, offset=offset))


@router.get("/projects/{project_id}/operations")
def operations(
    project_id: int, container: Container, limit: int = 50, offset: int = 0
):
    return _response(container.api.operations(project_id, limit=limit, offset=offset))


@router.post("/projects/{project_id}/operations/run-once", status_code=202)
def run_once(project_id: int, container: Container):
    return _response(container.api.run_once(project_id), status_code=202)


@router.post("/projects/{project_id}/operations/publish-once")
def publish_once(project_id: int, container: Container):
    return _response(container.api.publish_once(project_id))


@router.get("/projects/{project_id}/settings")
def settings(project_id: int, container: Container):
    return _response(container.api.settings(project_id))


@router.put("/projects/{project_id}/settings/{section}")
def update_settings(
    project_id: int,
    section: str,
    body: MainSettingsRequest | ConfigurationSettingsRequest,
    container: Container,
):
    if section not in {"main", "configuration"}:
        raise ValueError("unknown_settings_section")
    return _response(
        container.api.update_settings(
            project_id, section, body.model_dump(exclude_none=True)
        )
    )


@router.get("/projects/{project_id}/{resource}")
def resources(project_id: int, resource: str, container: Container):
    _resource(resource)
    return _response(container.api.resources(project_id, resource))


@router.post("/projects/{project_id}/{resource}", status_code=201)
def create_resource(
    project_id: int,
    resource: str,
    body: SourceRequest | ChannelRequest | CtaRequest | RouteRequest,
    container: Container,
):
    _resource(resource)
    _body_matches_resource(resource, body)
    return _response(
        container.api.create_resource(project_id, resource, body.model_dump(mode="json")),
        status_code=201,
    )


@router.put("/projects/{project_id}/{resource}/{resource_id}")
def update_resource(
    project_id: int,
    resource: str,
    resource_id: int,
    body: SourceRequest | ChannelRequest | CtaRequest | RouteRequest,
    container: Container,
):
    _resource(resource)
    _body_matches_resource(resource, body)
    return _response(
        container.api.update_resource(
            project_id, resource, resource_id, body.model_dump(mode="json")
        )
    )


@router.delete("/projects/{project_id}/{resource}/{resource_id}", status_code=204)
def delete_resource(
    project_id: int, resource: str, resource_id: int, container: Container
) -> Response:
    _resource(resource)
    container.api.delete_resource(project_id, resource, resource_id)
    return Response(status_code=204)


@router.post("/projects/{project_id}/channels/{channel_id}/check")
def check_channel(project_id: int, channel_id: int, container: Container):
    return _response(container.api.check_channel(project_id, channel_id))


@router.get("/projects/{project_id}/media/packages/{package_id}")
def package_media(project_id: int, package_id: int, container: Container) -> Response:
    body, media_type = container.api.package_media(project_id, package_id)
    return Response(content=body, media_type=media_type)


def _resource(value: str) -> None:
    if value not in {"sources", "channels", "ctas", "routes"}:
        raise ValueError("unknown_resource")


def _body_matches_resource(value: str, body: object) -> None:
    expected = {
        "sources": SourceRequest,
        "channels": ChannelRequest,
        "ctas": CtaRequest,
        "routes": RouteRequest,
    }[value]
    if not isinstance(body, expected):
        raise ValueError("invalid_resource_payload")
