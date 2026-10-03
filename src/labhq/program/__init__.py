"""The always-on program: the MCP server and the background loops in one process."""

from labhq.program.loops import LoopRegistry, LoopSpec, Step, run_loop
from labhq.program.runner import Program, ProgramError, ProgramServer
from labhq.program.services import Services, default_loops
from labhq.program.settings import ProgramSettings, get_program_settings

__all__ = [
    "LoopRegistry",
    "LoopSpec",
    "Program",
    "ProgramError",
    "ProgramServer",
    "ProgramSettings",
    "Services",
    "Step",
    "default_loops",
    "get_program_settings",
    "run_loop",
]
