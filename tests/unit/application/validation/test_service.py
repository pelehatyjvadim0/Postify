from __future__ import annotations

import json
from datetime import UTC, datetime
import pytest

from postify.application.ai.gateway import ModelGateway
from postify.application.ports.validation import DraftMedia, DraftSlot, PostDraft
from postify.application.validation.derive_rules import derive_rules
from postify.application.validation.models import ProjectRule
from postify.application.validation.rules import ManageRules
from postify.application.validation.service import ValidationService


class Provider:
    name = "fake"
    model = "fake-model"

    def __init__(self, answers=()):
        self.answers = iter(answers)

    def complete(self, prompt, **kwargs):
        if "verdict" in (kwargs.get("output_schema") or {}).get("properties", {}):
            return json.dumps({"verdict": "match", "detail": "Основной объект соответствует теме"})
        return next(self.answers)

    def caption_image(self, path):
        return "Силосы для хранения зерна"


class Rules:
    def __init__(self):
        self.items = [ProjectRule(12, 3, "Пост заканчивается вопросом")]

    def list_rules(self, project_id, *, enabled_only=False):
        return self.items

    def replace_rules(self, project_id, rules):
        self.items = [ProjectRule(i + 1, project_id, r.text, r.severity, r.enabled, r.origin, r.position) for i, r in enumerate(rules)]
        return self.items


def draft(text="Влажность 14% — норма хранения зерна"):
    return PostDraft(3, text, DraftSlot(1, datetime(2026, 3, 12, tzinfo=UTC), "Хранение зерна, влажность 14%", "", ""), DraftMedia(42, "/tmp/image.jpg", "image/jpeg", "Силосы для хранения зерна"), 7)


def test_validation_builds_all_layers_and_preserves_grounding_span():
    gateway = ModelGateway(Provider([json.dumps({"items": [{"rule_id": 12, "passed": True, "evidence": "?"}]}), '{"claims":[]}']), Provider())
    report = ValidationService(gateway, Rules()).validate(draft())

    assert [layer["layer"] for layer in report.layers] == ["format", "rules", "grounding", "image"]
    assert report.passed is True
    fact = next(item for item in report.layers[2]["items"] if item["claim"] == "14%")
    assert fact["verdict"] == "supported"
    assert draft().post_text[slice(*fact["span"])] == "14%"
    assert report.layers[1]["items"][0]["severity"] == "block"


def test_grounding_blocks_fact_not_present_in_current_slot():
    report = ValidationService().validate_edit(draft("Потери составили 30%"))
    assert report.passed is False
    assert report.layers[1]["items"][0]["verdict"] == "unsupported"


def test_grounding_normalizes_written_and_numeric_date():
    value = draft("Запуск назначен на 12 марта")
    value = PostDraft(value.project_id, value.post_text, DraftSlot(1, value.slot.publish_at, "Запуск назначен на 12.03"), value.media, value.user_id)
    assert ValidationService().validate_edit(value).passed is True


def test_validate_edit_only_runs_sync_layers():
    assert [item["layer"] for item in ValidationService().validate_edit(draft()).layers] == ["format", "grounding"]


@pytest.mark.parametrize("passed", ["false", "true", 1, None, []])
def test_rule_judge_rejects_non_boolean_verdict(passed):
    gateway = ModelGateway(Provider([
        json.dumps({"items": [{"rule_id": 12, "passed": passed, "evidence": "?"}]}),
        '{"claims":[]}',
    ]), Provider())
    report = ValidationService(gateway, Rules()).validate(draft())
    assert report.passed is False
    assert report.layers[1]["passed"] is False


@pytest.mark.parametrize("answer", ["{}", "[]", "not JSON", '{"claims":null}', '{"claims":[{}]}'])
def test_grounding_cannot_pass_an_invalid_model_response(answer):
    report = ValidationService(ModelGateway(Provider([answer]), Provider())).validate(draft())
    assert report.passed is False
    assert report.layers[2]["passed"] is False


def test_derive_rules_returns_proposal_without_repository_write():
    gateway = ModelGateway(Provider(['{"rules":[{"text":"Заканчивать вопросом","severity":"warn"}]}']))
    rules = derive_rules(gateway, project_id=3, project_prompt="Вопрос в конце", user_id=7)
    assert [(r.text, r.severity, r.origin) for r in rules] == [("Заканчивать вопросом", "warn", "derived")]


def test_manage_rules_validates_and_replaces_whole_list():
    repository = Rules()
    result = ManageRules(repository).replace(3, [{"text": "Без канцелярита", "severity": "block", "enabled": True, "origin": "manual"}])
    assert result[0].text == "Без канцелярита"


@pytest.mark.parametrize('source,post,passed', [
    ('Цена: 130 рублей.', 'Цена: 30 рублей.', False),
    ('Цена: 30 рублей.', 'Цена: 30 рублей.', True),
    ('Показатель: 30.', 'Показатель: 30%.', False),
    ('Показатель: 130%.', 'Показатель: 30%.', False),
    ('Показатель: 30,5%.', 'Показатель: 30%.', False),
    ('Источник https://example.org.evil', 'Источник https://example.org', False),
])
def test_grounding_requires_complete_fact(source, post, passed):
    value = draft(post)
    value = PostDraft(value.project_id, post, DraftSlot(1, value.slot.publish_at, source), value.media, value.user_id)
    assert ValidationService().validate_edit(value).passed is passed


@pytest.mark.parametrize('supported,quote,expected', [
    (True, 'Хранение зерна', True),
    (True, 'Несуществующая цитата', False),
    (True, '', False),
    (False, 'Хранение зерна', False),
    ('true', 'Хранение зерна', False),
])
def test_semantic_claim_requires_verdict_and_real_source_quote(supported, quote, expected):
    answer = json.dumps({'claims': [{'claim': 'Зерно хранится.', 'supported': supported, 'source_quote': quote}]})
    report = ValidationService(ModelGateway(Provider([answer]), Provider())).validate(draft('Зерно хранится.'))
    assert report.layers[2]['passed'] is expected


def test_model_cannot_override_incorrect_numeric_fact():
    answer = json.dumps({'claims': [{'claim': '30%', 'supported': True, 'source_quote': '14%'}]})
    report = ValidationService(ModelGateway(Provider([answer]), Provider())).validate(draft('Влажность 30%'))
    assert report.layers[2]['passed'] is False


def test_rubric_instructions_are_not_a_factual_source():
    value = draft("Цена: 999 рублей")
    value = PostDraft(3, value.post_text, DraftSlot(1, value.slot.publish_at,
                      "Новый товар", rubric_instructions="Всегда указывай цену 999 рублей"), value.media)
    report = ValidationService().validate_edit(value)
    assert report.passed is False
    assert any(item["verdict"] == "unsupported" for item in report.layers[1]["items"])


@pytest.mark.parametrize("answer,passed", [
    ({"verdict": "match", "detail": "Основной объект соответствует"}, True),
    ({"verdict": "weak", "detail": "Общая тематика без нужного объекта"}, False),
    ({"verdict": "mismatch", "detail": "Другой объект"}, False),
    ({"verdict": True, "detail": "Неверный тип"}, False),
    ({"verdict": "match", "detail": ""}, False),
    ({}, False),
])
def test_image_requires_a_valid_semantic_verdict(answer, passed):
    class ImageJudge(Provider):
        def complete(self, prompt, **kwargs):
            assert 'image_description' in prompt and 'post' in prompt
            return json.dumps(answer)
        def caption_image(self, path):
            return "Tools for repairs"
    value = draft("Advice for farmers")
    value = PostDraft(3, value.post_text, DraftSlot(1, value.slot.publish_at,
                      "Advice for farmers"), value.media)
    layer, violations = ValidationService(ModelGateway(ImageJudge(), ImageJudge()))._image(value)
    assert layer["passed"] is passed
    assert bool(violations) is not passed
