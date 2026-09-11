from __future__ import annotations
from fastapi import APIRouter, Depends
from postify.web.auth import owned_project
from postify.web.dependencies import Container
from postify.web.schemas.operations import AcceptedOperationResponse
from postify.web.schemas.rules import RuleResponse, RulesRequest

router = APIRouter(prefix="/api/projects/{project_id}/rules", tags=["rules"], dependencies=[Depends(owned_project)])

def _view(rule):
    return {"id": rule.id, "text": rule.text, "severity": rule.severity, "enabled": rule.enabled, "origin": rule.origin, "position": rule.position}

@router.get("", response_model=list[RuleResponse])
def list_rules(project_id: int, container: Container):
    return [_view(x) for x in container.api.rules(project_id)]

@router.put("", response_model=list[RuleResponse])
def replace_rules(project_id: int, body: RulesRequest, container: Container):
    return [_view(x) for x in container.api.replace_rules(project_id, [x.model_dump() for x in body.rules])]

@router.post("/derive", response_model=AcceptedOperationResponse, status_code=202)
def derive_rules(project_id: int, container: Container):
    return container.api.derive_rules(project_id)
