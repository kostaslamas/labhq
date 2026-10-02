"""Run the experiments named on the command line (default: all) and print a summary."""

import asyncio
import sys
import traceback

from spike import hook_blocks_push, interrupt, resume, strict_approval_wait
from spike.common import Outcome

EXPERIMENTS = {
    "hook_blocks_push": hook_blocks_push.run,
    "interrupt": interrupt.run,
    "resume": resume.run,
    "strict_approval_wait": strict_approval_wait.run,
}


async def main(names: list[str]) -> int:
    outcomes: list[Outcome] = []
    for name in names:
        print(f"--- {name}", flush=True)
        try:
            outcome = await EXPERIMENTS[name]()
        except Exception:  # noqa: BLE001 - a crash is a result to record
            traceback.print_exc()
            outcome = Outcome(name, notes=["crashed, see traceback"])
        outcomes.append(outcome)
        print(
            f"{'PASS' if outcome.passed else 'FAIL'} {outcome.elapsed_s:.1f}s "
            f"${outcome.cost_usd:.4f}",
            *[f"\n  - {n}" for n in outcome.notes],
            flush=True,
        )
    print(f"\ntotal cost: ${sum(o.cost_usd for o in outcomes):.4f}")
    return 0 if all(o.passed for o in outcomes) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:] or list(EXPERIMENTS))))
