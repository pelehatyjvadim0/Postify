from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from postify.application.ai.gateway import CallResult
from postify.application.generation.models import (
    GENERATION_OUTPUT_SCHEMA,
    GeneratedContent,
    GenerationBrief,
    GenerationError,
)
from postify.application.generation.service import GeneratePost
from postify.application.media.models import MediaAsset, MediaCandidate
from postify.application.ports.validation import (
    DraftSlot,
    ValidationReport,
    Violation,
)
from postify.application.prompts.compose_context import PlanSlot


NOW = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)


def _json(text: str, asset_id: int = 2, rationale: str = "Подходит") -> str:
    return json.dumps(
        {
            "post_text": text,
            "media_asset_id": asset_id,
            "media_rationale": rationale,
        },
        ensure_ascii=False,
    )


def _asset(asset_id: int, caption: str) -> MediaAsset:
    return MediaAsset(
        id=asset_id,
        project_id=7,
        file_path=f"/media/{asset_id}.jpg",
        thumb_path=None,
        mime="image/jpeg",
        bytes=100,
        width=10,
        height=10,
        content_hash=f"hash-{asset_id}",
        caption=caption,
        caption_model="vision",
        caption_status="ready",
        has_embedding=True,
        uploaded_at=NOW,
        last_used_at=None,
        use_count=0,
        enabled=True,
        available=True,
    )


CANDIDATES = (
    MediaCandidate(_asset(1, "Поле"), 0.2),
    MediaCandidate(_asset(2, "Силосы"), 0.1),
)


def _brief() -> GenerationBrief:
    return GenerationBrief(
        project_id=7,
        user_id=4,
        slot=DraftSlot(
            slot_id=41,
            publish_at=NOW,
            topic="5 ошибок хранения зерна",
            rubric_name="Подборка",
            rubric_instructions="Сделай нумерованный список",
        ),
        plan=(
            PlanSlot(
                publish_at=NOW,
                topic="Следующая тема",
                rubric="Новости",
                status="planned",
            ),
        ),
        system_prompt="Системный",
        common_prompt="Общий",
        project_prompt="Проектный",
        publication_mode="review",
        model="gpt-test",
        reasoning_effort="medium",
    )


class Repository:
    def __init__(self) -> None:
        self.brief = _brief()
        self.events = []
        self.completed = None

    def brief_for_slot(self, slot_id):
        self.events.append(("brief_slot", slot_id))
        return self.brief

    def brief_for_post(self, post_id):
        self.events.append(("brief_post", post_id))
        return self.brief

    def begin_generation(self, slot_id, *, now):
        self.events.append(("begin", slot_id))
        return 77

    def begin_regeneration(self, post_id, *, now):
        self.events.append(("regenerate", post_id))

    def complete(self, post_id, **values):
        self.events.append(("complete", post_id))
        self.completed = values

    def fail(self, post_id, *, now):
        self.events.append(("fail", post_id))


class Gateway:
    def __init__(self, outputs) -> None:
        self.outputs = iter(outputs)
        self.calls = []

    def complete(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        return CallResult(
            text=next(self.outputs),
            embedding=None,
            provider="codex",
            model=kwargs["model"],
            purpose=kwargs["context"].purpose,
            started_at=NOW,
            finished_at=NOW,
        )


class Shortlist:
    def __init__(self, candidates=CANDIDATES) -> None:
        self.candidates = candidates
        self.calls = []

    def execute(self, query, *, limit=5):
        self.calls.append((query, limit))
        return self.candidates


class Validator:
    def __init__(self, reports) -> None:
        self.reports = iter(reports)
        self.drafts = []

    def validate(self, draft):
        self.drafts.append(draft)
        return next(self.reports)


class Journal:
    def __init__(self) -> None:
        self.events = []

    def clear(self, post_id):
        self.events.append(("clear", post_id))

    def save(self, post_id, *, iteration, report, now):
        self.events.append(("save", post_id, iteration, report))


def _service(outputs, reports, *, repository=None, shortlist=None, model=None):
    repository = repository or Repository()
    gateway = Gateway(outputs)
    shortlist = shortlist or Shortlist()
    validator = Validator(reports)
    journal = Journal()
    service = GeneratePost(
        repository,
        gateway,
        shortlist,
        validator,
        journal,
        clock=lambda: NOW,
        model=model,
    )
    return service, repository, gateway, shortlist, validator, journal


def test_provider_model_overrides_codex_project_profile() -> None:
    service, repository, gateway, *_ = _service(
        [_json("Готовый пост")], [ValidationReport(True)], model="vendor/model"
    )
    result = service.generate(41)
    assert gateway.calls[0][1]["model"] == "vendor/model"
    assert result.model == "vendor/model"
    assert repository.completed["generation"]["model"] == "vendor/model"


def test_generates_structured_post_and_selects_only_shortlisted_media() -> None:
    passed = ValidationReport(True, layers=({"layer": "format", "passed": True},))
    service, repository, gateway, shortlist, validator, journal = _service(
        [_json("Готовый пост")], [passed]
    )

    result = service.generate(41)

    assert result.post_id == 77
    assert result.content == GeneratedContent("Готовый пост", 2, "Подходит")
    assert result.media.asset_id == 2
    assert result.repair_iterations == 0
    assert result.validation_passed is True
    assert shortlist.calls == [("5 ошибок хранения зерна", 5)]
    prompt, arguments = gateway.calls[0]
    assert arguments["output_schema"] == GENERATION_OUTPUT_SCHEMA
    assert arguments["context"].project_id == 7
    assert arguments["context"].user_id == 4
    assert (arguments["model"], arguments["reasoning_effort"]) == (
        "gpt-test",
        "medium",
    )
    assert prompt.index("Системный") < prompt.index("Общий") < prompt.index("Проектный")
    assert "Сделай нумерованный список" in prompt
    assert '"asset_id": 2' in prompt and "Силосы" in prompt
    assert validator.drafts[0].slot.slot_id == 41
    assert validator.drafts[0].media.asset_id == 2
    assert journal.events[:2] == [("clear", 77), ("save", 77, 0, passed)]
    assert repository.completed["generation"] == {
        "provider": "codex",
        "model": "gpt-test",
        "reasoning_effort": "medium",
        "iterations": 0,
        "generated_at": NOW.isoformat(),
        "media_asset_id": 2,
        "media_rationale": "Подходит",
        "validation_passed": True,
        "publication_mode": "review",
    }


def test_repairs_blocking_violations_and_journals_each_iteration() -> None:
    blocked = ValidationReport(
        False,
        (
            Violation("grounding", "block", "Удали неподтверждённые 30%"),
            Violation("rules", "warn", "Добавь вопрос"),
        ),
    )
    passed = ValidationReport(True)
    service, _, gateway, _, validator, journal = _service(
        [_json("Потери снизятся на 30%"), _json("Храните зерно бережно", 1)],
        [blocked, passed],
    )

    result = service.generate(41)

    assert result.repair_iterations == 1
    assert result.content.post_text == "Храните зерно бережно"
    assert result.media.asset_id == 1
    assert len(gateway.calls) == 2
    repair_prompt = gateway.calls[1][0]
    assert "Удали неподтверждённые 30%" in repair_prompt
    assert "Добавь вопрос" not in repair_prompt
    assert [event[2] for event in journal.events if event[0] == "save"] == [0, 1]
    assert [draft.media.asset_id for draft in validator.drafts] == [2, 1]


def test_stops_after_two_repairs_and_saves_blocked_result_for_review() -> None:
    blocked = ValidationReport(
        False, (Violation("format", "block", "Слишком длинно"),)
    )
    service, repository, gateway, _, _, journal = _service(
        [_json("v0"), _json("v1"), _json("v2")],
        [blocked, blocked, blocked],
    )

    result = service.generate(41)

    assert result.content.post_text == "v2"
    assert result.repair_iterations == 2
    assert result.validation_passed is False
    assert len(gateway.calls) == 3
    assert [event[2] for event in journal.events if event[0] == "save"] == [0, 1, 2]
    assert repository.completed["generation"]["validation_passed"] is False


@pytest.mark.parametrize(
    "output,code",
    [
        ("не json", "invalid_generation_output"),
        (_json("Текст", 999), "media_not_in_shortlist"),
    ],
)
def test_invalid_model_output_fails_the_started_post(output, code) -> None:
    service, repository, *_ = _service([output], [])

    with pytest.raises(GenerationError) as caught:
        service.generate(41)

    assert caught.value.code == code
    assert repository.events[-1] == ("fail", 77)


def test_regeneration_uses_existing_post_and_starts_report_at_zero() -> None:
    passed = ValidationReport(True)
    service, repository, _, _, _, journal = _service([_json("Новый")], [passed])

    result = service.regenerate(77)

    assert result.post_id == 77
    assert repository.events[:2] == [("brief_post", 77), ("regenerate", 77)]
    assert journal.events[:2] == [("clear", 77), ("save", 77, 0, passed)]


def test_parser_rejects_boolean_asset_id_and_unknown_fields() -> None:
    with pytest.raises(GenerationError):
        GeneratedContent.parse(
            json.dumps(
                {
                    "post_text": "x",
                    "media_asset_id": True,
                    "media_rationale": "x",
                }
            )
        )
    with pytest.raises(GenerationError):
        GeneratedContent.parse(
            json.dumps(
                {
                    "post_text": "x",
                    "media_asset_id": 1,
                    "media_rationale": "x",
                    "unexpected": 1,
                }
            )
        )


def test_run_requires_exactly_one_target() -> None:
    service, *_ = _service([], [])
    with pytest.raises(ValueError):
        service.run()
    with pytest.raises(ValueError):
        service.run(slot_id=41, post_id=77)
