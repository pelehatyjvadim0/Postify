from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from postify.domain.candidates.models import Candidate
from postify.domain.candidates.statuses import (
    CandidateDecision,
    DecisionReason,
    DecisionStatus,
    RejectionRule,
)


def _normalise(value: str) -> str:
    return " ".join(value.casefold().split())


def _normalise_terms(terms: tuple[str, ...]) -> tuple[str, ...]:
    normalised = tuple(_normalise(term) for term in terms)
    if any(not term for term in normalised) or len(set(normalised)) != len(normalised):
        raise ValueError("terms must be non-blank and unique")
    return normalised


@dataclass(frozen=True, slots=True)
class SelectionProfile:
    version: str
    language: str
    audience: str
    rules: tuple[RejectionRule, ...]
    topic_terms: tuple[str, ...]
    topic_exclusion_terms: tuple[str, ...]
    advertising_terms: tuple[str, ...]
    hiring_terms: tuple[str, ...]
    technical_release_terms: tuple[str, ...]
    practical_terms: tuple[str, ...]
    freshness_window: timedelta

    def __post_init__(self) -> None:
        if any(not value.strip() for value in (self.version, self.language, self.audience)):
            raise ValueError("profile identity fields must not be blank")
        if self.freshness_window <= timedelta():
            raise ValueError("freshness_window must be positive")
        if len(set(self.rules)) != len(self.rules):
            raise ValueError("rules must be unique")
        for name in (
            "topic_terms", "topic_exclusion_terms", "advertising_terms", "hiring_terms",
            "technical_release_terms", "practical_terms",
        ):
            object.__setattr__(self, name, _normalise_terms(getattr(self, name)))
        required = {
            RejectionRule.ADVERTISING: (self.advertising_terms,),
            RejectionRule.OUT_OF_SCOPE: (self.topic_exclusion_terms,),
            RejectionRule.HIRING: (self.hiring_terms,),
            RejectionRule.TECHNICAL_WITHOUT_USE: (
                self.technical_release_terms,
                self.practical_terms,
            ),
        }
        if any(not terms for rule in self.rules for terms in required[rule]):
            raise ValueError("enabled rules require terms")


def _matching_terms(text: str, terms: tuple[str, ...]) -> list[str]:
    return [term for term in terms if re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text)]


def evaluate_candidate(
    candidate_id: int, candidate: Candidate, profile: SelectionProfile, *, now: datetime
) -> CandidateDecision:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    text = _normalise(f"{candidate.title} {candidate.url}")
    freshness = "fresh" if now - candidate.discovered_at <= profile.freshness_window else "stale"
    signals: dict[str, object] = {"freshness": freshness}
    for rule in profile.rules:
        if rule is RejectionRule.ADVERTISING:
            matched = _matching_terms(text, profile.advertising_terms)
            reason = DecisionReason.ADVERTISING
            explanation = "Обнаружен маркер рекламы или партнёрского материала"
        elif rule is RejectionRule.OUT_OF_SCOPE:
            matched = _matching_terms(text, profile.topic_exclusion_terms)
            reason = DecisionReason.OUT_OF_SCOPE
            explanation = "Обнаружен явный маркер материала вне настроенной ниши"
        elif rule is RejectionRule.HIRING:
            matched = _matching_terms(text, profile.hiring_terms)
            reason = DecisionReason.HIRING
            explanation = "Обнаружен маркер вакансии, найма или объявления"
        else:
            matched = _matching_terms(text, profile.technical_release_terms)
            practical = _matching_terms(text, profile.practical_terms)
            if practical:
                matched = []
            reason = DecisionReason.TECHNICAL_WITHOUT_USE
            explanation = "Технический релиз без понятного практического применения"
        if matched:
            signals.update({"matched_rule": rule.value, "matched_terms": matched})
            return CandidateDecision(candidate_id, DecisionStatus.REJECTED, reason, explanation, signals, profile.version, now)
    return CandidateDecision(
        candidate_id, DecisionStatus.SELECTED, DecisionReason.ELIGIBLE_FOR_AI,
        "Допущен к будущему анализу", signals, profile.version, now,
    )
