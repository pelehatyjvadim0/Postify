"""Четыре слоя проверки черновика поста.

Первые и третьи проверки остаются детерминированными настолько, насколько это
возможно: регулярные сущности всегда сверяются с текущей темой слота.
Соседние слоты в ``PostDraft`` отсутствуют намеренно.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from postify.application.ai.gateway import CallContext, ModelGateway
from postify.application.ports.validation import (
    PostDraft,
    PostValidator,
    ValidationReport,
    Violation,
)


_NUMBER = re.compile(
    r"(?<!\w)[+-]?\d+(?:[.,]\d+)?\s*(?:%|°\s*[CFc]|руб(?:\.|лей)?|€|\$)?"
)
_DATE = re.compile(
    r"\b\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?\b|"
    r"\b\d{1,2}\s+(?:января|февраля|марта|апреля|мая|июня|июля|"
    r"августа|сентября|октября|ноября|декабря)\b",
    re.I,
)
_TIME = re.compile(r"\b\d{1,2}:\d{2}\b")
_URL = re.compile(r"https?://[^\s)]+|www\.[^\s)]+", re.I)
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
_PHONE = re.compile(r"(?<!\w)(?:\+?\d[\d ()-]{7,}\d)(?!\w)")
_MENTION = re.compile(r"(?<!\w)@[\w_]{3,}")


class ValidationService(PostValidator):
    def __init__(self, gateway: ModelGateway | None = None, rules_repository=None) -> None:
        self.gateway = gateway
        self.rules_repository = rules_repository

    def validate(self, draft: PostDraft) -> ValidationReport:
        layers: list[dict[str, Any]] = []
        violations: list[Violation] = []
        layer, found = self._format(draft)
        layers.append(layer)
        violations.extend(found)
        layer, found = self._rules(draft)
        layers.append(layer)
        violations.extend(found)
        layer, found = self._grounding(draft, use_model=True)
        layers.append(layer)
        violations.extend(found)
        layer, found = self._image(draft)
        layers.append(layer)
        violations.extend(found)
        return ValidationReport(
            not any(v.severity == "block" for v in violations),
            tuple(violations),
            tuple(layers),
        )

    def validate_edit(self, draft: PostDraft) -> ValidationReport:
        layers: list[dict[str, Any]] = []
        violations: list[Violation] = []
        layer, found = self._format(draft)
        layers.append(layer)
        violations.extend(found)
        layer, found = self._grounding(draft, use_model=False)
        layers.append(layer)
        violations.extend(found)
        return ValidationReport(
            not any(v.severity == "block" for v in violations),
            tuple(violations),
            tuple(layers),
        )

    def _format(self, draft: PostDraft):
        text = draft.post_text
        limit = 1024 if draft.media else 4096
        items = [
            {
                "key": "length",
                "passed": bool(text.strip()) and _utf16_len(text) <= limit,
                "detail": f"{_utf16_len(text)} из {limit}",
            },
            {
                "key": "non_empty",
                "passed": bool(text.strip()),
                "detail": "Текст заполнен" if text.strip() else "Текст пуст",
            },
            {
                "key": "utf8",
                "passed": "\x00" not in text,
                "detail": "Допустимый текст" if "\x00" not in text else "Нулевой символ",
            },
        ]
        found = (
            [Violation("format", "block", "Текст поста пуст")]
            if not text.strip()
            else []
        )
        if _utf16_len(text) > limit:
            found.append(
                Violation("format", "block", f"Текст длиннее лимита {limit} символов")
            )
        if "\x00" in text:
            found.append(
                Violation("format", "block", "Текст содержит недопустимый символ")
            )
        return {
            "layer": "format",
            "passed": not found,
            "score": f"{sum(i['passed'] for i in items)}/{len(items)}",
            "items": items,
        }, found

    def _rules(self, draft: PostDraft):
        rules = ()
        if self.rules_repository is not None:
            rules = self.rules_repository.list_rules(draft.project_id, enabled_only=True)
        if not rules:
            return {"layer": "rules", "passed": True, "score": "0/0", "items": []}, []
        if self.gateway is None:
            return self._rule_items(
                rules, [False] * len(rules), "Судья правил недоступен"
            )
        prompt = (
            'Проверь пост по правилам. Верни JSON {"items":'
            '[{"rule_id":число,"passed":bool,"evidence":строка}]}\n'
        )
        prompt += (
            "Правила:\n"
            + "\n".join(f"{r.id}: {r.text}" for r in rules)
            + f"\nПост:\n{draft.post_text}"
        )
        try:
            result = self.gateway.complete(
                prompt,
                context=CallContext(
                    "judge", project_id=draft.project_id, user_id=draft.user_id
                ),
                output_schema={"type": "object"},
            )
            data = _json(result.text)
            valid = [
                item
                for item in data.get("items", [])
                if isinstance(item, dict)
                and str(item.get("rule_id", "")).isdigit()
            ]
            by_id = {int(item["rule_id"]): bool(item.get("passed")) for item in valid}
            passed = [by_id.get(r.id, False) for r in rules]
            evidence = {
                int(item["rule_id"]): item.get("evidence", "") for item in valid
            }
            return self._rule_items(rules, passed, evidence)
        except Exception:
            return self._rule_items(
                rules, [False] * len(rules), "Не удалось выполнить проверку правила"
            )

    def _rule_items(self, rules, passed, evidence):
        items = []
        violations = []
        for rule, ok in zip(rules, passed):
            ev = evidence.get(rule.id, "") if isinstance(evidence, dict) else evidence
            items.append(
                {
                    "rule_id": rule.id,
                    "text": rule.text,
                    "severity": rule.severity,
                    "passed": ok,
                    "evidence": ev,
                }
            )
            if not ok:
                violations.append(Violation("rules", rule.severity, f"Нарушено правило: {rule.text}"))
        return {"layer": "rules", "passed": not any(v.severity == "block" for v in violations), "score": f"{sum(passed)}/{len(rules)}", "items": items}, violations

    def _grounding(self, draft: PostDraft, *, use_model: bool):
        topic = " ".join(x for x in (draft.slot.topic, draft.slot.rubric_instructions) if x)
        entities: list[tuple[str, int, int]] = []
        for pattern in (_NUMBER, _DATE, _TIME, _URL, _EMAIL, _PHONE, _MENTION):
            entities.extend((m.group(), m.start(), m.end()) for m in pattern.finditer(draft.post_text))
        claims: list[str] = [e[0] for e in entities]
        model_failure = use_model and self.gateway is None
        if use_model and self.gateway is not None:
            try:
                prompt = f"Извлеки из поста проверяемые имена, компании, цитаты и источники. JSON {{claims:[{{claim:string}}]}}\nТема слота: {topic}\nПост: {draft.post_text}"
                data = _json(self.gateway.complete(prompt, context=CallContext("claims", project_id=draft.project_id, user_id=draft.user_id), output_schema={"type": "object"}).text)
                claims.extend(str(i.get("claim")) for i in data.get("claims", []) if isinstance(i, dict) and i.get("claim"))
            except Exception:
                model_failure = True
        normalized_topic = _norm(topic)
        items = []
        violations = []
        if model_failure:
            violations.append(
                Violation("grounding", "block", "Не удалось извлечь именованные факты")
            )
        for claim in dict.fromkeys(claims):
            ok = _norm(claim) in normalized_topic or _norm(claim.replace("%", "")) in normalized_topic
            span = next(([start, end] for value, start, end in entities if value == claim), None)
            item = {"claim": claim, "verdict": "supported" if ok else "unsupported", "detail": "Есть в теме слота" if ok else "Отсутствует в теме слота"}
            if span is not None:
                item["span"] = span
            items.append(item)
            if not ok:
                violations.append(Violation("grounding", "block", f"Конкретика «{claim}» отсутствует в теме слота"))
        return {"layer": "grounding", "passed": not violations, "items": items}, violations

    def _image(self, draft: PostDraft):
        if draft.media is None:
            v = Violation("image", "block", "Для поста не выбрано изображение")
            return {"layer": "image", "passed": False, "items": []}, [v]
        if self.gateway is None:
            item = {"asset_id": draft.media.asset_id, "verdict": "mismatch", "detail": "Vision-проверка недоступна"}
            return {"layer": "image", "passed": False, "items": [item]}, [Violation("image", "block", "Не удалось проверить изображение")]
        try:
            caption = self.gateway.caption_image(Path(draft.media.file_path), context=CallContext("vision", project_id=draft.project_id, user_id=draft.user_id)).text or ""
        except Exception:
            item = {"asset_id": draft.media.asset_id, "verdict": "mismatch", "detail": "Vision-проверка завершилась ошибкой"}
            return {"layer": "image", "passed": False, "items": [item]}, [Violation("image", "block", "Не удалось проверить изображение")]
        overlap = set(_norm(draft.slot.topic).split()) & set(_norm(caption).split())
        verdict = "match" if overlap else "weak"
        passed = bool(overlap)
        item = {"asset_id": draft.media.asset_id, "verdict": verdict, "detail": caption}
        return {"layer": "image", "passed": passed, "items": [item]}, ([] if passed else [Violation("image", "block", "Изображение не соответствует теме слота")])


def _utf16_len(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _norm(value: str) -> str:
    value = value.lower()
    months = {
        "января": "01", "февраля": "02", "марта": "03", "апреля": "04",
        "мая": "05", "июня": "06", "июля": "07", "августа": "08",
        "сентября": "09", "октября": "10", "ноября": "11", "декабря": "12",
    }
    value = re.sub(
        r"\b(\d{1,2})\s+(" + "|".join(months) + r")\b",
        lambda m: f"{int(m.group(1)):02d}.{months[m.group(2)]}",
        value,
    )
    value = re.sub(
        r"\b(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))?\b",
        lambda m: f"{int(m.group(1)):02d}.{int(m.group(2)):02d}" + (f".{m.group(3)}" if m.group(3) else ""),
        value,
    )
    return re.sub(r"\s+", " ", re.sub(r"[^\w%.]+", " ", value, flags=re.UNICODE)).strip()


def _json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        start, end = value.find("{"), value.rfind("}")
        parsed = json.loads(value[start:end + 1]) if start >= 0 and end > start else {}
    return parsed if isinstance(parsed, dict) else {}
