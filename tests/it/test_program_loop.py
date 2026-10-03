"""The always-on program runs an IT pass on the health loop's interval."""

from types import SimpleNamespace

from labhq.it import ItDepartment, it_step
from labhq.program import default_loops
from tests.roles.conftest import Org


def test_the_program_registers_the_it_loop_on_the_health_interval() -> None:
    loops = {spec.name: spec for spec in default_loops}
    assert loops["it"].interval_setting == loops["health"].interval_setting


async def test_the_step_is_one_department_pass(org: Org) -> None:
    services = SimpleNamespace(context=SimpleNamespace(sessions=org.sessions, clock=org.clock))
    step = it_step(services)
    assert isinstance(getattr(step, "__self__", None), ItDepartment)
