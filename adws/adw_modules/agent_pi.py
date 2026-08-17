"""Интерфейс кодирующего агента Pi — единственного в v1.

Запускает `pi -p --mode json` и построчно читает его JSONL stdout, передавая
каждое событие в callback ВО ВРЕМЯ работы агента (проблема стриминга решена
самой конструкцией). `--session-id` создаёт или продолжает сессию, поэтому
запуск и продолжение агента — один вызов: одинаковый id сессии = одинаковое окно контекста.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional

from .data_types import PiRequest, PiResult
from .utils import now_iso, operator_env

PI_PATH = os.environ.get("PI_PATH", "pi")
MODELS_JSON = os.environ.get("PI_MODELS_PATH",
                             str(Path.home() / ".pi" / "agent" / "models.json"))

RESULT_SNIPPET_CHARS = 20_000   # вывод инструмента передаётся целиком; ограничение защищает только от патологических случаев
ARG_VALUE_CHARS = 20_000        # то же для аргументов — UI прокручивается, ему не нужны обрезанные данные
LABEL_CHARS = 80                # "bash: <command>" отображается как имя события

# Аргумент, по которому вызов можно быстро опознать; порядок соответствует типичному использованию инструментов.
PRIMARY_ARGS = ("command", "path", "file_path", "pattern", "query", "url")


def _count(value: str) -> int:
    """Разобрать компактные значения количества из списка моделей pi (`272K`, `1.0M`)."""
    suffixes = {"K": 1_000, "M": 1_000_000}
    suffix = value[-1:].upper()
    if suffix in suffixes:
        return int(float(value[:-1]) * suffixes[suffix])
    return int(value)


@lru_cache(maxsize=1)
def _pi_catalog() -> list[tuple[str, str, int]]:
    """Прочитать объединённый каталог pi: встроенные провайдеры и пользовательские модели."""
    try:
        result = subprocess.run(
            [PI_PATH, "--list-models"], capture_output=True, text=True,
            timeout=30, env=operator_env(), check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    rows = []
    for line in result.stdout.splitlines()[1:]:
        columns = line.split()
        if len(columns) < 3:
            continue
        try:
            rows.append((columns[0], columns[1], _count(columns[2])))
        except ValueError:
            continue
    return rows


def resolve_model(pattern: str) -> tuple[str, str]:
    """Разрешить шаблон модели в явную пару ``(provider, model_id)``.

    Каталог Pi объединяет встроенные модели с ``~/.pi/agent/models.json``.
    Использование этого же представления позволяет SSSF обращаться к прямым
    провайдерам, например ``openai/gpt-5.6-terra``, без локальной повторной
    регистрации встроенных моделей.
    """
    catalog = [(provider, model_id) for provider, model_id, _ in _pi_catalog()]
    if "/" in pattern:
        provider, model_id = pattern.split("/", 1)
        if (provider, model_id) in catalog:
            return provider, model_id
    matches = [(provider, model_id) for provider, model_id in catalog
               if pattern == model_id or pattern in model_id]
    exact = [match for match in matches
             if match[1] == pattern or match[1].endswith("/" + pattern)]
    if len(exact) == 1:
        return exact[0]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ValueError(f"model pattern {pattern!r} not found in pi --list-models — "
                         "authenticate/register it or fix the config")
    raise ValueError(f"model pattern {pattern!r} is ambiguous: {matches}")


def _context_tokens(usage: dict) -> int:
    """Токены, занимающие окно контекста после хода.

    Повторяет собственный `calculateContextTokens` pi (coding-agent
    `core/compaction/compaction.ts`), по которому pi выполняет сжатие и
    показывает значение в нижней строке: предпочтителен `totalTokens` от
    провайдера, иначе суммируются части. Чтения из кэша учитываются —
    закэшированный prompt всё ещё остаётся prompt.
    """
    total = usage.get("totalTokens") or 0
    if total:
        return int(total)
    return int(sum(usage.get(part) or 0
                   for part in ("input", "output", "cacheRead", "cacheWrite")))


def context_window(provider: str, model_id: str) -> int:
    """Лимит контекста модели из объединённого каталога моделей pi."""
    registry = json.loads(Path(MODELS_JSON).read_text())
    for model in registry.get("providers", {}).get(provider, {}).get("models", []):
        if model.get("id") == model_id:
            return int(model.get("contextWindow") or 0)
    for listed_provider, listed_model, window in _pi_catalog():
        if listed_provider == provider and listed_model == model_id:
            return window
    return 0


def _text_of(container: dict) -> str:
    """Объединить текстовые блоки сущности pi формата {content: [...]} —
    сообщения или результата инструмента."""
    return "".join(part.get("text", "") for part in container.get("content", []) or []
                   if isinstance(part, dict) and part.get("type") == "text")


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _label(tool: str, args: dict) -> str:
    """Однострочное понятное человеку имя вызова инструмента: `bash: ls -la src`."""
    value = next((args[key] for key in PRIMARY_ARGS
                  if isinstance(args.get(key), str) and args[key].strip()), "")
    if not value:
        value = next((v for v in args.values() if isinstance(v, str) and v.strip()), "")
    value = " ".join(str(value).split())
    return f"{tool}: {_clip(value, LABEL_CHARS)}" if value else tool


class ToolCallTracker:
    """Сворачивает поток инструментов pi в ОДНУ нормализованную запись на завершённый вызов.

    Pi объявляет вызов блоком содержимого `toolCall`, затем выдаёт для него
    tool_execution_start / _update / _end. Результат содержит только последнее
    событие, поэтому запись создаётся там: одно событие трассировки на реальный
    вызов инструмента в момент его возврата, а не три бесформенных события.

    Запись содержит фактический интервал вызова (`started_at`/`ended_at`),
    который tracer помещает в столбцы, чтобы UI мог разместить вызовы на временной
    шкале без разбора каждого payload.
    """

    def __init__(self) -> None:
        self._open: dict[str, dict] = {}

    def observe(self, event: dict) -> Optional[dict]:
        """Вернуть запись для завершённого вызова инструмента или None."""
        etype = event.get("type", "")
        if etype == "message_end":
            for block in event.get("message", {}).get("content", []) or []:
                if isinstance(block, dict) and block.get("type") == "toolCall":
                    self._announce(block.get("id"), block.get("name"),
                                   block.get("arguments"))
            return None
        if etype == "tool_execution_start":
            self._announce(event.get("toolCallId"), event.get("toolName"),
                           event.get("args"))
            return None
        if etype != "tool_execution_end":
            return None

        call_id = str(event.get("toolCallId") or "")
        opened = self._open.pop(call_id, {})
        tool = str(event.get("toolName") or opened.get("tool") or "tool")
        args = event.get("args") or opened.get("args") or {}
        record = {
            "tool": tool,
            "tool_call_id": call_id,
            "args": {key: _clip(value, ARG_VALUE_CHARS) if isinstance(value, str) else value
                     for key, value in args.items()},
            "ok": not event.get("isError", False),
            "label": _label(tool, args),
        }
        result_text = _text_of(event.get("result") or {})
        if result_text:
            record["result_snippet"] = _clip(result_text, RESULT_SNIPPET_CHARS)
        record["ended_at"] = now_iso()
        if opened.get("clock"):
            record["duration_ms"] = int((time.monotonic() - opened["clock"]) * 1000)
        if opened.get("started_at"):
            record["started_at"] = opened["started_at"]
        return record

    def _announce(self, call_id, tool, args) -> None:
        """Первое наблюдение запускает таймер; последующие лишь заполняют пропуски."""
        if not call_id:
            return
        known = self._open.get(str(call_id), {})
        self._open[str(call_id)] = {
            "tool": tool or known.get("tool", ""),
            "args": args or known.get("args", {}),
            "started_at": known.get("started_at") or now_iso(),   # системное время для строки
            "clock": known.get("clock") or time.monotonic(),      # монотонное время для длительности
        }


def run(request: PiRequest, on_event: Optional[Callable[[dict], None]] = None,
        on_spawn: Optional[Callable[[int], None]] = None,
        on_exit: Optional[Callable[[int], None]] = None) -> PiResult:
    """Выполнить один неинтерактивный ход pi.

    `on_spawn(pid)` и `on_exit(pid)` ограничивают жизненный цикл дочернего
    процесса, чтобы вызывающий код мог записать его как завершаемый: иначе PID
    зависшего кодирующего агента пришлось бы искать через `ps` во время простоя запуска.
    """
    provider, model_id = resolve_model(request.model)
    cmd = [
        PI_PATH, "-p", "--mode", "json",
        "--provider", provider, "--model", model_id,
        "--thinking", request.thinking,
        "--session-id", request.session_id,
        "--session-dir", request.session_dir,
        "--system-prompt", request.system_prompt,
    ]
    if request.tools:
        cmd += ["--tools", ",".join(request.tools)]
    for extension in request.extensions:
        cmd += ["-e", extension]
    cmd.append(request.prompt)

    raw_path = Path(request.raw_output_path)
    raw_path.parent.mkdir(parents=True, exist_ok=True)

    result = PiResult(session_id=request.session_id,
                      context_window=context_window(provider, model_id))
    # stdin намеренно DEVNULL. Prompt передаётся через argv, поэтому дочернему
    # процессу stdin не нужен, но при наследовании родительского stdin pi видит
    # не-TTY и может бесконечно ждать входные данные из pipe или EOF, которые
    # никогда не придут. Сбой бесшумен и полон: запрос не уходит, байты не
    # возвращаются, а ADW блокируется в цикле чтения без данных. Это наблюдалось
    # как запуск с нулевой загрузкой CPU и пустым raw_output.jsonl.
    process = subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, bufsize=1, cwd=request.cwd,
                               env=operator_env())
    if on_spawn:
        on_spawn(process.pid)
    with raw_path.open("a") as raw:
        assert process.stdout is not None
        for line in process.stdout:
            raw.write(line)
            raw.flush()                      # события записываются на диск по мере поступления
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "message_end":
                message = event.get("message", {})
                if message.get("role") == "assistant":
                    text = _text_of(message)
                    if text:
                        result.text = text   # используется последнее сообщение ассистента
                    usage = message.get("usage", {}) or {}
                    turn = _context_tokens(usage)
                    result.tokens += turn
                    result.usage.add_turn(usage, turn)
                    # Заполнение берётся из последнего ВАЛИДНОГО хода ассистента,
                    # как это делает pi: использование в отменённом ходе или ходе
                    # с ошибкой ненадёжно и не должно заменять корректное значение.
                    if turn and message.get("stopReason") not in ("aborted", "error"):
                        result.context_tokens = turn
                    result.cost += (usage.get("cost", {}) or {}).get("total", 0.0) or 0.0
            if on_event:
                on_event(event)

    stderr = process.stderr.read() if process.stderr else ""
    result.returncode = process.wait()
    if on_exit:
        on_exit(process.pid)
    if result.returncode != 0 and not result.text:
        raise RuntimeError(f"pi exited {result.returncode}: {stderr.strip()[-800:]}")
    return result
