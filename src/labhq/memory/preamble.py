"""The memory section at the head of a long-lived agent's prompt.

A preamble rather than the system prompt: every adapter takes a prompt, the tmux adapter
included, while only some can change the system prompt.
"""

from labhq.memory.settings import MemorySettings

MEMORY_HEADING = "## Your memory"

INSTRUCTION = (
    "You keep memory across runs in .labhq/memory.md; it is shown below and starts every "
    "run, also in a fresh session, another task or another worktree. Use it for what you "
    "need next time: decisions, open threads, where things are, who does what. Keep it "
    "brief, newest at the bottom; it holds at most {limit} characters and the oldest lines "
    "go first. Update the file before your turn ends."
)

TRUNCATED_NOTICE = (
    "Your memory went over the limit last time: its oldest {dropped} line(s) were dropped. "
    "Condense it."
)

EMPTY = "(empty)"


def memory_preamble(memory: str, dropped: int, settings: MemorySettings) -> str:
    parts = [MEMORY_HEADING, INSTRUCTION.format(limit=settings.memory_max_chars)]
    if dropped:
        parts.append(TRUNCATED_NOTICE.format(dropped=dropped))
    parts.append(f"<memory>\n{memory.rstrip() or EMPTY}\n</memory>")
    return "\n\n".join(parts)
