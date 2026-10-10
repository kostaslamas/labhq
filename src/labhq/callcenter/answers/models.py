"""`models`: which model each role and task kind uses, and a request to change one.

A change is only requested here. It is a heavy `change_models` approval that the owner
confirms with the passkey, so a voice call can never change what the agents cost.
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.approvals import ApprovalService
from labhq.callcenter.answers.refs import approval_ref
from labhq.clock import Clock
from labhq.modelpolicy import PolicyError, info, load_policy
from labhq.modelpolicy.apply import CHANGE_ACTION
from labhq.modelpolicy.policy import build
from labhq.speech import join_sentences, speakable

SPOKEN_KEYS = {"project_analysis": "project analysis", "it": "I T"}


def _name(key: str) -> str:
    return SPOKEN_KEYS.get(key, key)


def _model_name(model_id: str) -> str:
    known = info(model_id)
    return known.display_name if known is not None else model_id


async def models_answer(db: AsyncSession) -> str:
    policy = await load_policy(db)
    groups: dict[tuple[str, str], list[str]] = {}
    for key, row in policy.rows.items():
        groups.setdefault((row.model, row.effort), []).append(_name(key))
    sentences = [
        f"{_model_name(model)} at {effort} effort for {', '.join(keys)}"
        for (model, effort), keys in groups.items()
    ]
    return speakable(join_sentences([f"{sentence}." for sentence in sentences]))


async def request_model_change(
    db: AsyncSession, clock: Clock, *, key: str, model: str, effort: str
) -> str:
    try:
        rows = {key: {"model": model, "effort": effort}}
        build(rows)
    except PolicyError as error:
        return speakable(f"I could not request that change. {error}.")
    if db.bind is None:
        raise RuntimeError("request_model_change needs a session bound to an engine")
    service = ApprovalService(async_sessionmaker(db.bind, expire_on_commit=False), clock=clock)
    approval = await service.request(CHANGE_ACTION, {"rows": rows})
    return speakable(
        f"Changing {_name(key)} to {_model_name(model)} at {effort} effort needs your approval, "
        f"so confirm {approval_ref(approval.id)} with your passkey."
    )
