#!/usr/bin/env -S uv run
# /// script
# dependencies = ["pydantic", "python-dotenv", "pyyaml", "rich"]
# ///
"""ADW Build Test — реализовать, затем проверить; сбои возвращаются разработчику.

Использование:
    uv run adws/adw_build_test.py "<prompt or path/to/prompt.md>" [--config adws/adw_sssf_config/sssf.config.yaml] [--adw-id a1b2c3d4]

Этапы: engineer(request) -> builder -> code(test) [-> builder(fix) -> code(test) ... ограниченное число раз]

Тестирование — это КОД. Команда набора тестов задана в
adw_modules/quality.py, поэтому для её запуска не требуется суждение — оно
нужно только для исправления. Сбои поступают разработчику в конверте через
`quality.as_envelope`, тем же путём, что и отчёт агента, поэтому цикл
исправления не меняется.

Падающий набор тестов НЕ проваливает свой этап: исполнитель сделал свою работу,
а не прошёл код. Он проваливает запуск, что проверяется в конце после всех
попыток ограниченного цикла исправления.
"""

import argparse
import sys

from adw_modules import agents, gates, quality, session, utils
from adw_modules.data_types import AgentCall, BuildOutput, PhaseParams

REQUIRED_AGENTS = ["builder"]
MAX_FIX_LOOPS = 3


def main(prompt: str, config: str = "adws/adw_sssf_config/sssf.config.yaml", adw_id: str | None = None) -> int:
    cfg = agents.load_config(config)
    agents.validate(cfg, REQUIRED_AGENTS)
    run = session.ensure(cfg, adw_id)

    def record(ph, result) -> None:
        passed = sum(1 for check in result.checks if check.passed)
        ph.log(passed=result.passed, checks=f"{passed}/{len(result.checks)}",
               artifacts=", ".join(result.artifacts))

    with run.phase(PhaseParams(name="request", kind="engineer", owner=run.engineer,
                               description="Capture the incoming ask")) as ph:
        ph.log(input=prompt)

    with run.phase(PhaseParams(name="build", kind="agent", owner="builder",
                               description="Implement the request")) as ph:
        previous = ph.call(AgentCall(output_type=BuildOutput, prompt=prompt,
                                     gates=[gates.diff_matches_claims]))

    test = None
    for i in range(1, MAX_FIX_LOOPS + 1):
        with run.phase(PhaseParams(name=f"test_{i}", kind="code", owner="quality",
                                   description="Run the suite — a known command, so code runs "
                                               "it and no agent has to rediscover it")) as ph:
            test = quality.run_tests(run)
            record(ph, test)

        if test.passed:
            break

        with run.phase(PhaseParams(name=f"fix_{i}", kind="agent", owner="builder", retries=1,
                                   description="Repair what the suite reported, from its "
                                               "verbatim output")) as ph:
            previous = ph.call(AgentCall(output_type=BuildOutput, prompt=prompt,
                                         previous=quality.as_envelope(test, "tests"),
                                         gates=[gates.diff_matches_claims]))

    return run.finish(accepted=test is not None and test.passed,
                      reason=f"the suite still failed after {MAX_FIX_LOOPS} fix attempt(s)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt", help="inline text or a path to a prompt file")
    parser.add_argument("--config", default="adws/adw_sssf_config/sssf.config.yaml")
    parser.add_argument("--adw-id", default=None, help="join or pin an existing session")
    args = parser.parse_args()
    sys.exit(main(utils.resolve_prompt(args.prompt), args.config, args.adw_id))
