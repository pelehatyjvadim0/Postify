#!/usr/bin/env -S uv run
# /// script
# dependencies = ["pydantic", "python-dotenv", "pyyaml", "rich"]
# ///
"""ADW Build Review — реализовать, затем убедиться, что результат соответствует запросу.

Использование:
    uv run adws/adw_build_review.py "<prompt or path/to/prompt.md>" [--config adws/adw_sssf_config/sssf.config.yaml] [--adw-id a1b2c3d4]

Этапы: engineer(request) -> builder -> reviewer [-> builder(revise) -> reviewer ... ограниченное число раз]

Ревью — не тестирование. Тесты отвечают на вопрос «запускается ли это», а
ревьюер — «это именно то, что было запрошено». Он читает спецификацию (`plan.md`
из предыдущего этапа планирования, если она есть в сессии; иначе — исходный
промпт), читает написанный код и выносит решение по каждому требованию.

Как и у тестировщика, этап ревьюера считается успешным, когда он ВЫПОЛНЕН и
ВЫДАЛ ОТЧЁТ. Отклонение не проваливает этап, а проваливает запуск: это
проверяется в конце после всех попыток ограниченного цикла доработки.
"""

import argparse
import sys

from adw_modules import agents, gates, session, utils
from adw_modules.data_types import (AgentCall, BuildOutput, PhaseParams,
                                    ReviewOutput)

REQUIRED_AGENTS = ["builder", "reviewer"]
MAX_REVISION_LOOPS = 3


def main(prompt: str, config: str = "adws/adw_sssf_config/sssf.config.yaml", adw_id: str | None = None) -> int:
    cfg = agents.load_config(config)
    agents.validate(cfg, REQUIRED_AGENTS)
    run = session.ensure(cfg, adw_id)

    with run.phase(PhaseParams(name="request", kind="engineer", owner=run.engineer,
                               description="Capture the incoming ask")) as ph:
        ph.log(input=prompt)

    with run.phase(PhaseParams(name="build", kind="agent", owner="builder",
                               description="Implement the request")) as ph:
        previous = ph.call(AgentCall(output_type=BuildOutput, prompt=prompt,
                                     gates=[gates.diff_matches_claims]))

    review = None
    for i in range(1, MAX_REVISION_LOOPS + 1):
        with run.phase(PhaseParams(name=f"review_{i}", kind="agent", owner="reviewer",
                                   description="Rule on every requirement in the spec, against the code on disk")) as ph:
            review = ph.call(AgentCall(output_type=ReviewOutput, prompt=prompt,
                                       previous=previous,
                                       gates=[gates.artifacts_exist,
                                              gates.verdict_consistent]))

        if review.approved:
            break
        if i == MAX_REVISION_LOOPS:
            break

        with run.phase(PhaseParams(name=f"revise_{i}", kind="agent", owner="builder", retries=1,
                                   description="Close every blocking finding the reviewer named")) as ph:
            previous = ph.call(AgentCall(output_type=BuildOutput, prompt=prompt, previous=review,
                                         gates=[gates.diff_matches_claims]))

    return run.finish(accepted=review is not None and review.approved,
                      reason=f"the reviewer never approved after {MAX_REVISION_LOOPS} revision(s)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt", help="inline text or a path to a prompt file")
    parser.add_argument("--config", default="adws/adw_sssf_config/sssf.config.yaml")
    parser.add_argument("--adw-id", default=None, help="join or pin an existing session")
    args = parser.parse_args()
    sys.exit(main(utils.resolve_prompt(args.prompt), args.config, args.adw_id))
