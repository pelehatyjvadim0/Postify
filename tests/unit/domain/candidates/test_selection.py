from __future__ import annotations

from datetime import UTC, datetime, timedelta
from collections.abc import Mapping
from typing import Any

import pytest

from postify.domain.candidates.models import Candidate


NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)


def _selection_api():
    from postify.domain.candidates.selection import SelectionProfile, evaluate_candidate
    from postify.domain.candidates.statuses import (
        CandidateDecision,
        DecisionReason,
        DecisionStatus,
        RejectionRule,
    )

    return (
        SelectionProfile,
        evaluate_candidate,
        CandidateDecision,
        DecisionReason,
        DecisionStatus,
        RejectionRule,
    )


def _decision_api():
    from postify.domain.candidates.statuses import (
        CandidateDecision,
        DecisionReason,
        DecisionStatus,
    )

    return CandidateDecision, DecisionReason, DecisionStatus


def _candidate(**overrides: object) -> Candidate:
    values: dict[str, object] = {
        "source_name": "generic_feed",
        "source_id": "candidate-1",
        "title": "Практическое руководство",
        "url": "https://example.test/articles/practical-guide",
        "discovered_at": NOW - timedelta(days=1),
        "raw_payload": {},
    }
    values.update(overrides)
    return Candidate(**values)  # type: ignore[arg-type]


def _developer_tools_profile(
    *, rules: tuple[object, ...] | None = None, **overrides: object
):
    SelectionProfile, _, _, _, _, RejectionRule = _selection_api()
    values: dict[str, object] = {
        "version": "developer-tools-v1",
        "language": "ru",
        "audience": "Разработчики прикладных инструментов",
        "rules": rules
        if rules is not None
        else (
            RejectionRule.ADVERTISING,
            RejectionRule.OUT_OF_SCOPE,
            RejectionRule.HIRING,
            RejectionRule.TECHNICAL_WITHOUT_USE,
        ),
        "topic_terms": ("инструмент", "postgresql"),
        "topic_exclusion_terms": ("рецепт", "кулинария"),
        "advertising_terms": ("реклама", "партнёрский материал", "partner"),
        "hiring_terms": ("вакансия", "нанимаем", "hiring"),
        "technical_release_terms": ("релиз", "версия", "release"),
        "practical_terms": ("руководство", "пример", "tutorial"),
        "freshness_window": timedelta(days=30),
    }
    values.update(overrides)
    return SelectionProfile(**values)


def _cooking_profile():
    SelectionProfile, _, _, _, _, RejectionRule = _selection_api()
    return SelectionProfile(
        version="cooking-v3",
        language="ru",
        audience="Домашние кулинары",
        rules=(RejectionRule.OUT_OF_SCOPE,),
        topic_terms=("рецепт", "выпечка"),
        topic_exclusion_terms=("postgresql", "sdk"),
        advertising_terms=("реклама",),
        hiring_terms=("вакансия",),
        technical_release_terms=("релиз",),
        practical_terms=("рецепт",),
        freshness_window=timedelta(days=14),
    )


def _signal_scalars(value: Any) -> list[str]:
    if isinstance(value, Mapping):
        return [item for nested in value.values() for item in _signal_scalars(nested)]
    if isinstance(value, (list, tuple)):
        return [item for nested in value for item in _signal_scalars(nested)]
    return [str(value).casefold()]


@pytest.mark.parametrize(
    ("title", "url", "expected_reason", "expected_signal"),
    [
        (
            "Партнёрский материал о базах данных",
            "https://example.test/database",
            "advertising",
            "партнёрский материал",
        ),
        (
            "Рецепт хлеба на закваске",
            "https://example.test/bread",
            "out_of_scope",
            "рецепт",
        ),
        (
            "Мы нанимаем инженера",
            "https://example.test/team",
            "hiring",
            "нанимаем",
        ),
        (
            "Релиз библиотеки 4.0",
            "https://example.test/changelog",
            "technical_without_use",
            "релиз",
        ),
    ],
)
def test_each_enabled_rule_produces_its_explainable_rejection(
    title: str,
    url: str,
    expected_reason: str,
    expected_signal: str,
) -> None:
    # Поломка: одна из четырёх независимых причин не создаёт объяснимый отказ.
    _, evaluate_candidate, _, DecisionReason, DecisionStatus, _ = _selection_api()

    decision = evaluate_candidate(
        41,
        _candidate(title=title, url=url),
        _developer_tools_profile(),
        now=NOW,
    )

    assert decision.status is DecisionStatus.REJECTED
    assert decision.reason is DecisionReason(expected_reason)
    assert expected_signal.casefold() in _signal_scalars(decision.signals)
    assert decision.explanation.strip()


def test_disabled_rule_has_no_effect() -> None:
    # Поломка: движок применяет рекламу, хотя профиль включил только найм.
    _, evaluate_candidate, _, DecisionReason, DecisionStatus, RejectionRule = _selection_api()

    decision = evaluate_candidate(
        42,
        _candidate(title="Реклама инструмента"),
        _developer_tools_profile(rules=(RejectionRule.HIRING,)),
        now=NOW,
    )

    assert decision.status is DecisionStatus.SELECTED
    assert decision.reason is DecisionReason.ELIGIBLE_FOR_AI


def test_first_matching_rule_in_profile_order_wins() -> None:
    # Поломка: при нескольких сигналах используется жёсткий, а не настроенный приоритет.
    _, evaluate_candidate, _, DecisionReason, _, RejectionRule = _selection_api()
    candidate = _candidate(title="Реклама: мы нанимаем инженера")

    hiring_first = evaluate_candidate(
        43,
        candidate,
        _developer_tools_profile(
            rules=(RejectionRule.HIRING, RejectionRule.ADVERTISING)
        ),
        now=NOW,
    )
    advertising_first = evaluate_candidate(
        43,
        candidate,
        _developer_tools_profile(
            rules=(RejectionRule.ADVERTISING, RejectionRule.HIRING)
        ),
        now=NOW,
    )

    assert hiring_first.reason is DecisionReason.HIRING
    assert advertising_first.reason is DecisionReason.ADVERTISING
    assert hiring_first.explanation != advertising_first.explanation


def test_profile_changes_niche_without_code_changes() -> None:
    # Поломка: политика зашивает developer-tools и игнорирует профиль другой ниши.
    _, evaluate_candidate, _, DecisionReason, DecisionStatus, _ = _selection_api()
    recipe = _candidate(title="Рецепт хлеба с практическими шагами")

    developer_decision = evaluate_candidate(44, recipe, _developer_tools_profile(), now=NOW)
    cooking_decision = evaluate_candidate(44, recipe, _cooking_profile(), now=NOW)

    assert developer_decision.reason is DecisionReason.OUT_OF_SCOPE
    assert cooking_decision.status is DecisionStatus.SELECTED
    assert cooking_decision.reason is DecisionReason.ELIGIBLE_FOR_AI


def test_matching_normalizes_unicode_case_and_repeated_whitespace() -> None:
    # Поломка: совпадение зависит от регистра либо количества пробелов в заголовке.
    _, evaluate_candidate, _, DecisionReason, _, _ = _selection_api()

    decision = evaluate_candidate(
        45,
        _candidate(title="Разбор: ПАРТНЁРСКИЙ    МАТЕРИАЛ о PostgreSQL"),
        _developer_tools_profile(),
        now=NOW,
    )

    assert decision.reason is DecisionReason.ADVERTISING


def test_matching_uses_url() -> None:
    # Поломка: политика проверяет только заголовок и игнорирует URL.
    _, evaluate_candidate, _, DecisionReason, _, _ = _selection_api()
    url_match = evaluate_candidate(
        46,
        _candidate(title="Обзор базы данных", url="https://example.test/partner/offer"),
        _developer_tools_profile(),
        now=NOW,
    )

    assert url_match.reason is DecisionReason.ADVERTISING


def test_matching_respects_unicode_word_boundaries() -> None:
    # Поломка: Unicode marker совпадает внутри более длинного слова.
    _, evaluate_candidate, _, _, DecisionStatus, _ = _selection_api()
    inside_word = evaluate_candidate(
        47,
        _candidate(title="Микреклама как культурный феномен"),
        _developer_tools_profile(),
        now=NOW,
    )

    assert inside_word.status is DecisionStatus.SELECTED


def test_title_only_candidate_is_selected_conservatively() -> None:
    # Поломка (mutation 1): недостаток данных превращается в fallback-rejected.
    _, evaluate_candidate, _, DecisionReason, DecisionStatus, _ = _selection_api()

    decision = evaluate_candidate(
        48,
        _candidate(title="Наблюдения без дополнительных метаданных", raw_payload={}),
        _developer_tools_profile(),
        now=NOW,
    )

    assert decision.status is DecisionStatus.SELECTED
    assert decision.reason is DecisionReason.ELIGIBLE_FOR_AI
    assert decision.decided_at == NOW
    assert "fresh" in _signal_scalars(decision.signals)


def test_old_candidate_is_selected_and_records_stale_signal() -> None:
    # Поломка (mutation 2): возраст становится самостоятельной причиной отказа.
    _, evaluate_candidate, _, DecisionReason, DecisionStatus, _ = _selection_api()

    decision = evaluate_candidate(
        49,
        _candidate(discovered_at=NOW - timedelta(days=365)),
        _developer_tools_profile(),
        now=NOW,
    )

    assert decision.status is DecisionStatus.SELECTED
    assert decision.reason is DecisionReason.ELIGIBLE_FOR_AI
    assert "stale" in _signal_scalars(decision.signals)


def test_absent_positive_topic_term_does_not_prove_rejection() -> None:
    # Поломка: отсутствие topic_terms ошибочно трактуется как OUT_OF_SCOPE.
    _, evaluate_candidate, _, DecisionReason, DecisionStatus, _ = _selection_api()

    decision = evaluate_candidate(
        50,
        _candidate(title="Как организовать исследовательские заметки"),
        _developer_tools_profile(),
        now=NOW,
    )

    assert decision.status is DecisionStatus.SELECTED
    assert decision.reason is DecisionReason.ELIGIBLE_FOR_AI


def test_technical_release_is_rejected_only_without_practical_use() -> None:
    # Поломка: любой технический релиз отклоняется даже при практическом сценарии.
    _, evaluate_candidate, _, DecisionReason, DecisionStatus, _ = _selection_api()

    with_use = evaluate_candidate(
        51,
        _candidate(title="Релиз 4.0: практическое руководство и пример"),
        _developer_tools_profile(),
        now=NOW,
    )
    without_use = evaluate_candidate(
        52,
        _candidate(title="Релиз 4.0 и список изменений"),
        _developer_tools_profile(),
        now=NOW,
    )

    assert with_use.status is DecisionStatus.SELECTED
    assert with_use.reason is DecisionReason.ELIGIBLE_FOR_AI
    assert without_use.reason is DecisionReason.TECHNICAL_WITHOUT_USE


def test_evaluation_requires_timezone_aware_now() -> None:
    # Поломка: naive now делает freshness зависимой от локальной timezone процесса.
    _, evaluate_candidate, _, _, _, _ = _selection_api()

    with pytest.raises(ValueError, match="timezone-aware"):
        evaluate_candidate(
            53,
            _candidate(),
            _developer_tools_profile(),
            now=datetime(2026, 8, 2, 12, 0),
        )


def test_hn_raw_metrics_cannot_change_domain_decision() -> None:
    # Поломка (mutation 6): points/num_comments начинают влиять на чистую политику.
    _, evaluate_candidate, _, _, _, _ = _selection_api()
    low_metrics = _candidate(
        source_name="hacker_news",
        raw_payload={"points": 0, "num_comments": 0},
    )
    high_metrics = _candidate(
        source_name="hacker_news",
        raw_payload={"points": 50_000, "num_comments": 10_000},
    )

    low_decision = evaluate_candidate(54, low_metrics, _developer_tools_profile(), now=NOW)
    high_decision = evaluate_candidate(54, high_metrics, _developer_tools_profile(), now=NOW)

    assert low_decision.status is high_decision.status
    assert low_decision.reason is high_decision.reason
    assert low_decision.explanation == high_decision.explanation
    assert low_decision.signals == high_decision.signals


def test_candidate_decision_keeps_independent_deep_copy_of_signals() -> None:
    # Поломка: журнал решения сохраняет ссылку на изменяемые сигналы вызывающего кода.
    _, _, CandidateDecision, DecisionReason, DecisionStatus, _ = _selection_api()
    source_signals = {"matched_terms": ["релиз"], "freshness": {"state": "fresh"}}

    decision = CandidateDecision(
        candidate_id=55,
        status=DecisionStatus.REJECTED,
        reason=DecisionReason.TECHNICAL_WITHOUT_USE,
        explanation="Технический релиз без практического применения",
        signals=source_signals,
        policy_version="developer-tools-v1",
        decided_at=NOW,
    )
    source_signals["matched_terms"].append("подмена")
    source_signals["freshness"]["state"] = "stale"

    assert tuple(decision.signals["matched_terms"]) == ("релиз",)
    assert decision.signals["freshness"]["state"] == "fresh"


def _decision_with_nested_signals():
    CandidateDecision, DecisionReason, DecisionStatus = _decision_api()
    return CandidateDecision(
        candidate_id=56,
        status=DecisionStatus.REJECTED,
        reason=DecisionReason.TECHNICAL_WITHOUT_USE,
        explanation="Технический релиз без практического применения",
        signals={
            "matched_terms": ["релиз"],
            "freshness": {"state": "fresh", "age_days": 1},
        },
        policy_version="developer-tools-v1",
        decided_at=NOW,
    )


@pytest.mark.parametrize(
    ("key", "replacement"),
    [
        ("freshness", {"state": "stale"}),
        ("injected", "yes"),
    ],
)
def test_candidate_decision_signals_reject_top_level_mutation(
    key: str,
    replacement: object,
) -> None:
    # Поломка Important: после создания можно заменить либо добавить верхнеуровневый сигнал.
    decision = _decision_with_nested_signals()

    with pytest.raises((TypeError, AttributeError)):
        decision.signals[key] = replacement  # type: ignore[index]

    assert set(decision.signals) == {"matched_terms", "freshness"}
    assert decision.signals["freshness"]["state"] == "fresh"


def test_candidate_decision_signals_reject_nested_mapping_assignment() -> None:
    # Поломка Important: вложенный JSON-object остаётся изменяемым после создания решения.
    decision = _decision_with_nested_signals()
    freshness = decision.signals["freshness"]

    with pytest.raises((TypeError, AttributeError)):
        freshness["state"] = "stale"  # type: ignore[index]

    assert freshness["state"] == "fresh"  # type: ignore[index]
    assert freshness["age_days"] == 1  # type: ignore[index]


def test_candidate_decision_signals_reject_nested_sequence_append() -> None:
    # Поломка Important: вложенный JSON-array допускает append после создания решения.
    decision = _decision_with_nested_signals()
    matched_terms = decision.signals["matched_terms"]

    with pytest.raises((TypeError, AttributeError)):
        getattr(matched_terms, "append")("подмена")

    assert tuple(matched_terms) == ("релиз",)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("status_name", "reason_name"),
    [
        ("selected", "advertising"),
        ("rejected", "eligible_for_ai"),
    ],
)
def test_candidate_decision_rejects_inconsistent_status_and_reason(
    status_name: str,
    reason_name: str,
) -> None:
    # Поломка: бинарный статус и машинная причина противоречат друг другу.
    CandidateDecision, DecisionReason, DecisionStatus = _decision_api()

    with pytest.raises(ValueError):
        CandidateDecision(
            candidate_id=61,
            status=DecisionStatus(status_name),
            reason=DecisionReason(reason_name),
            explanation="Проверяемое решение",
            signals={},
            policy_version="generic-v1",
            decided_at=NOW,
        )


@pytest.mark.parametrize(
    ("status_name", "reason_name"),
    [
        ("selected", "eligible_for_ai"),
        ("rejected", "advertising"),
    ],
)
def test_candidate_decision_accepts_consistent_status_and_reason(
    status_name: str,
    reason_name: str,
) -> None:
    # Поломка: согласованная пара status/reason ошибочно отвергается общей проверкой.
    CandidateDecision, DecisionReason, DecisionStatus = _decision_api()

    decision = CandidateDecision(
        candidate_id=62,
        status=DecisionStatus(status_name),
        reason=DecisionReason(reason_name),
        explanation="Проверяемое решение",
        signals={},
        policy_version="generic-v1",
        decided_at=NOW,
    )

    assert decision.status.value == status_name
    assert decision.reason.value == reason_name


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("candidate_id", 0),
        ("candidate_id", -1),
        ("explanation", " \t "),
        ("policy_version", " \n "),
        ("decided_at", datetime(2026, 8, 2, 12, 0)),
    ],
)
def test_candidate_decision_rejects_invalid_required_invariant(
    field_name: str,
    invalid_value: object,
) -> None:
    # Поломка: журнал принимает неидентифицируемое или необъяснимое решение.
    CandidateDecision, DecisionReason, DecisionStatus = _decision_api()
    values: dict[str, object] = {
        "candidate_id": 63,
        "status": DecisionStatus.SELECTED,
        "reason": DecisionReason.ELIGIBLE_FOR_AI,
        "explanation": "Допущен к будущему AI-анализу",
        "signals": {},
        "policy_version": "generic-v1",
        "decided_at": NOW,
    }
    values[field_name] = invalid_value

    with pytest.raises(ValueError):
        CandidateDecision(**values)


@pytest.mark.parametrize("field_name", ["version", "language", "audience"])
def test_selection_profile_rejects_blank_identity_field(field_name: str) -> None:
    # Поломка: доменный профиль невозможно идентифицировать без Pydantic Settings.
    with pytest.raises(ValueError):
        _developer_tools_profile(**{field_name: " \t "})


@pytest.mark.parametrize("freshness_window", [timedelta(0), timedelta(days=-1)])
def test_selection_profile_requires_positive_freshness_window(
    freshness_window: timedelta,
) -> None:
    # Поломка: доменный профиль принимает бессмысленное окно свежести.
    with pytest.raises(ValueError):
        _developer_tools_profile(freshness_window=freshness_window)


def test_selection_profile_rejects_duplicate_rules() -> None:
    # Поломка: одно правило выполняется дважды и искажает настроенный порядок.
    _, _, _, _, _, RejectionRule = _selection_api()

    with pytest.raises(ValueError):
        _developer_tools_profile(
            rules=(RejectionRule.HIRING, RejectionRule.HIRING),
        )


@pytest.mark.parametrize(
    "terms_field",
    [
        "topic_terms",
        "topic_exclusion_terms",
        "advertising_terms",
        "hiring_terms",
        "technical_release_terms",
        "practical_terms",
    ],
)
def test_selection_profile_rejects_normalized_duplicate_terms(
    terms_field: str,
) -> None:
    # Поломка: UI-клиент может обойти Settings и передать повторный термин.
    with pytest.raises(ValueError):
        _developer_tools_profile(**{terms_field: ("Маркер", " маркер ")})


@pytest.mark.parametrize(
    ("rule_name", "empty_dictionary"),
    [
        ("advertising", "advertising_terms"),
        ("out_of_scope", "topic_exclusion_terms"),
        ("hiring", "hiring_terms"),
        ("technical_without_use", "technical_release_terms"),
        ("technical_without_use", "practical_terms"),
    ],
)
def test_selection_profile_rejects_empty_dictionary_for_enabled_rule(
    rule_name: str,
    empty_dictionary: str,
) -> None:
    # Поломка: сам домен принимает включённое правило, которое не способно доказать отказ.
    _, _, _, _, _, RejectionRule = _selection_api()

    with pytest.raises(ValueError):
        _developer_tools_profile(
            rules=(RejectionRule(rule_name),),
            **{empty_dictionary: ()},
        )


def test_selection_profile_allows_empty_dictionaries_for_disabled_rules() -> None:
    # Поломка: профиль требует данные для правил, которые пользователь явно отключил.
    _, _, _, _, _, RejectionRule = _selection_api()

    profile = _developer_tools_profile(
        rules=(RejectionRule.HIRING,),
        topic_terms=(),
        topic_exclusion_terms=(),
        advertising_terms=(),
        technical_release_terms=(),
        practical_terms=(),
    )

    assert profile.rules == (RejectionRule.HIRING,)
