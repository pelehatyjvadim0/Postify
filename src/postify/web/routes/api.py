from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response

from postify.web.dependencies import WebContainer
from postify.web.schemas import (
    BootstrapResponse,
    ChannelRequest,
    ConfigurationSettingsRequest,
    MainSettingsRequest,
    PackagePlanRequest,
    OperationPollingResponse,
    RouteRequest,
    ScheduleSettingsRequest,
    SourceRequest,
)
from postify.web.security import SESSION_COOKIE, capability, new_session


router = APIRouter(prefix="/api/v1")


def container_for(request: Request) -> WebContainer:
    return request.app.state.container


Container = Annotated[WebContainer, Depends(container_for)]


def _safe(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _safe(item)
            for key, item in value.items()
            if key.casefold() in {"secretconfigured", "csrftoken"}
            or ("token" not in key.casefold() and "secret" not in key.casefold())
        }
    if isinstance(value, tuple | list):
        return [_safe(item) for item in value]
    return value


def _response(value: object, *, status_code: int = 200):
    return JSONResponse(content=jsonable_encoder(_safe(value)), status_code=status_code)


@router.get("/bootstrap")
def bootstrap(request: Request, container: Container):
    session = request.cookies.get(SESSION_COOKIE)
    if not session or len(session) > 256:
        session = new_session()
    payload = dict(container.api.bootstrap())
    payload["csrfToken"] = capability(request.app.state.csrf_secret, session)
    safe_payload = BootstrapResponse.model_validate(payload).model_dump(
        mode="json",
        by_alias=True,
        exclude_none=True,
    )
    response = JSONResponse(content=safe_payload)
    response.set_cookie(
        SESSION_COOKIE,
        session,
        httponly=True,
        samesite="strict",
        path="/",
    )
    return response


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


@router.patch("/projects/{project_id}/packages/{package_id}/plan")
def save_plan(project_id: int, package_id: int, body: PackagePlanRequest, container: Container):
    return _response(container.api.save_plan(
        project_id, package_id, scheduled_at=body.scheduled_at, route_id=body.route_id
    ))


@router.post("/projects/{project_id}/packages/{package_id}/approve")
def approve(project_id: int, package_id: int, container: Container):
    return _response(container.api.approve(project_id, package_id))


async def _require_empty_body(request: Request) -> None:
    if await request.body():
        raise HTTPException(status_code=422, detail="request_body_not_allowed")


@router.post("/projects/{project_id}/attempts/{attempt_id}/retry-analysis", status_code=202)
async def retry_analysis(project_id: int, attempt_id: int, request: Request, container: Container):
    await _require_empty_body(request)
    return _response(container.api.retry_analysis(project_id, attempt_id), status_code=202)


@router.post("/projects/{project_id}/packages/{package_id}/return-to-analysis", status_code=202)
async def return_to_analysis(project_id: int, package_id: int, request: Request, container: Container):
    await _require_empty_body(request)
    return _response(container.api.return_to_analysis(project_id, package_id), status_code=202)


@router.post("/projects/{project_id}/packages/{package_id}/regenerate", status_code=202)
async def regenerate_post(project_id: int, package_id: int, request: Request, container: Container):
    await _require_empty_body(request)
    return _response(container.api.regenerate_post(project_id, package_id), status_code=202)


@router.post("/projects/{project_id}/deliveries/{delivery_id}/retry", status_code=202)
async def retry_delivery(project_id: int, delivery_id: int, request: Request, container: Container):
    await _require_empty_body(request)
    return _response(container.api.retry_delivery(project_id, delivery_id), status_code=202)


@router.post("/projects/{project_id}/packages/{package_id}/reject")
async def reject(project_id: int, package_id: int, request: Request, container: Container):
    await _require_empty_body(request)
    return _response(container.api.reject(project_id, package_id))


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


@router.get(
    "/projects/{project_id}/operations/{operation_run_id}",
    response_model=OperationPollingResponse,
)
def operation(
    project_id: int, operation_run_id: int, container: Container
) -> OperationPollingResponse:
    return OperationPollingResponse.model_validate(
        container.api.operation(project_id, operation_run_id)
    )


@router.post("/projects/{project_id}/operations/run-once", status_code=202)
def run_once(project_id: int, container: Container):
    return _response(container.api.run_once(project_id), status_code=202)


@router.post("/projects/{project_id}/operations/search", status_code=202)
async def manual_search(project_id: int, request: Request, container: Container):
    await _require_empty_body(request)
    return _response(container.api.manual_search(project_id), status_code=202)


@router.get("/projects/{project_id}/settings")
def settings(project_id: int, container: Container):
    return _response(container.api.settings(project_id))


@router.put("/projects/{project_id}/settings/{section}")
def update_settings(
    project_id: int,
    section: str,
    body: MainSettingsRequest | ConfigurationSettingsRequest | ScheduleSettingsRequest,
    container: Container,
):
    expected = {
        "main": MainSettingsRequest,
        "configuration": ConfigurationSettingsRequest,
        "schedule": ScheduleSettingsRequest,
    }
    if section not in expected or not isinstance(body, expected[section]):
        raise ValueError("unknown_settings_section")
    payload = body.model_dump(mode="json", exclude_none=True)
    if isinstance(body, ConfigurationSettingsRequest) and "delivery_lateness_seconds" in body.model_fields_set:
        payload["delivery_lateness_seconds"] = body.delivery_lateness_seconds
    return _response(container.api.update_settings(project_id, section, payload))


def _resources(project_id: int, resource: str, container: Container):
    return _response(container.api.resources(project_id, resource))


def _create_resource(project_id: int, resource: str, body, container: Container):
    return _response(
        container.api.create_resource(
            project_id, resource, body.model_dump(mode="json", exclude_none=True)
        ),
        status_code=201,
    )


def _update_resource(
    project_id: int, resource: str, resource_id: int, body, container: Container
):
    return _response(
        container.api.update_resource(
            project_id,
            resource,
            resource_id,
            body.model_dump(mode="json", exclude_none=True),
        )
    )


def _delete_resource(
    project_id: int, resource: str, resource_id: int, container: Container
) -> Response:
    container.api.delete_resource(project_id, resource, resource_id)
    return Response(status_code=204)


@router.get("/projects/{project_id}/sources")
def sources(project_id: int, container: Container):
    return _resources(project_id, "sources", container)


@router.post("/projects/{project_id}/sources", status_code=201)
def create_source(project_id: int, body: SourceRequest, container: Container):
    return _create_resource(project_id, "sources", body, container)


@router.put("/projects/{project_id}/sources/{resource_id}")
def update_source(
    project_id: int, resource_id: int, body: SourceRequest, container: Container
):
    return _update_resource(project_id, "sources", resource_id, body, container)


@router.delete("/projects/{project_id}/sources/{resource_id}", status_code=204)
def delete_source(project_id: int, resource_id: int, container: Container) -> Response:
    return _delete_resource(project_id, "sources", resource_id, container)


@router.get("/projects/{project_id}/channels")
def channels(project_id: int, container: Container):
    return _resources(project_id, "channels", container)


@router.post("/projects/{project_id}/channels", status_code=201)
def create_channel(project_id: int, body: ChannelRequest, container: Container):
    return _create_resource(project_id, "channels", body, container)


@router.put("/projects/{project_id}/channels/{resource_id}")
def update_channel(
    project_id: int, resource_id: int, body: ChannelRequest, container: Container
):
    return _update_resource(project_id, "channels", resource_id, body, container)


@router.delete("/projects/{project_id}/channels/{resource_id}", status_code=204)
def delete_channel(project_id: int, resource_id: int, container: Container) -> Response:
    return _delete_resource(project_id, "channels", resource_id, container)


@router.get("/projects/{project_id}/routes")
def routes(project_id: int, container: Container):
    return _resources(project_id, "routes", container)


@router.post("/projects/{project_id}/routes", status_code=201)
def create_route(project_id: int, body: RouteRequest, container: Container):
    return _create_resource(project_id, "routes", body, container)


@router.put("/projects/{project_id}/routes/{resource_id}")
def update_route(
    project_id: int, resource_id: int, body: RouteRequest, container: Container
):
    return _update_resource(project_id, "routes", resource_id, body, container)


@router.delete("/projects/{project_id}/routes/{resource_id}", status_code=204)
def delete_route(project_id: int, resource_id: int, container: Container) -> Response:
    return _delete_resource(project_id, "routes", resource_id, container)


@router.post("/projects/{project_id}/channels/{channel_id}/check")
def check_channel(project_id: int, channel_id: int, container: Container):
    return _response(container.api.check_channel(project_id, channel_id))


@router.post("/projects/{project_id}/channels/{channel_id}/secret/remove")
def remove_channel_secret(project_id: int, channel_id: int, container: Container):
    return _response(container.api.remove_channel_secret(project_id, channel_id))


@router.get("/projects/{project_id}/media/packages/{package_id}")
def package_media(project_id: int, package_id: int, container: Container) -> Response:
    body, media_type = container.api.package_media(project_id, package_id)
    return Response(content=body, media_type=media_type)
