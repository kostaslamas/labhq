"""A meeting mirrored to one thread of its project's channel, each agent under its persona."""

from sqlalchemy import update

from labhq.adapters import RunRequest
from labhq.db.models import Agent
from labhq.meetings import add_owner_entry, read_minutes
from tests.meetings.channels.conftest import Bridge

MANAGER = "Manager (manager)"
LEAD = "Backend lead (lead)"


async def test_a_standup_opens_one_thread_and_posts_every_entry_then_the_minutes(
    bridge: Bridge,
) -> None:
    world = bridge.world
    world.stage.minutes.append(world.minutes_json())
    meeting_id = await world.approved_meeting()

    async def mirror_live(_request: RunRequest) -> None:
        # Drained between turns, as the program's loop would while the meeting runs.
        await bridge.flush()

    world.stage.on_start.append(mirror_live)
    await world.service.start(meeting_id)
    await bridge.flush()

    assert bridge.channel_names() == ["demo"]
    assert len(bridge.service.threads) == 1
    thread = await bridge.thread_of(meeting_id)
    assert bridge.service.threads[thread.id] == f"Standup M{meeting_id}, 2026-10-02"
    async with world.sessions() as db:
        minutes = await read_minutes(db, meeting_id)
    posts = bridge.posts(thread.id)
    agenda, *entries, closing = posts
    assert agenda == ("labhq", minutes.agenda)
    assert [text for _, text in entries] == [entry.text for entry in minutes.transcript]
    # Two turns, then the facilitator's minutes reply, each under its own agent.
    assert [name for name, _ in entries] == [MANAGER, LEAD, MANAGER]
    name, text = closing
    assert name == MANAGER
    assert text.startswith(f"Minutes of standup M{meeting_id}: ended.")
    assert "1. Ship the parser first" in text
    assert "- Write parser tests -> Backend lead" in text
    assert await bridge.flush() == 0


async def test_an_agent_persona_comes_from_its_config(bridge: Bridge) -> None:
    world = bridge.world
    async with world.sessions() as db:
        await db.execute(
            update(Agent)
            .where(Agent.id == world.lead_id)
            .values(config={"persona": {"name": "Bea", "avatar_url": "https://a.example/b.png"}})
        )
        await db.commit()
    world.stage.minutes.append(world.minutes_json())
    meeting_id = await world.approved_meeting()
    await world.service.start(meeting_id)
    await bridge.flush()

    thread = await bridge.thread_of(meeting_id)
    personas = {post.persona for post in bridge.service.posts[thread.id]}
    assert {(p.name, p.avatar_url) for p in personas if p.name == "Bea"} == {
        ("Bea", "https://a.example/b.png")
    }


async def test_a_generated_avatar_is_seeded_by_the_agent_id_only(bridge: Bridge) -> None:
    from labhq.meetings.channels.personas import agent_persona
    from labhq.meetings.channels.settings import ChannelSettings

    async with bridge.world.sessions() as db:
        agent = await db.get_one(Agent, bridge.world.lead_id)
    persona = agent_persona(agent, ChannelSettings(avatar_url_template="https://x/{seed}.png"))

    assert persona.name == LEAD
    assert persona.avatar_url == f"https://x/labhq-agent-{agent.id}.png"


async def test_an_owner_entry_from_the_cli_is_posted_and_one_from_the_thread_is_not(
    bridge: Bridge,
) -> None:
    world = bridge.world
    meeting = await world.service.request(project_id=world.project_id, kind="standup")

    await add_owner_entry(
        world.sessions,
        world.clock,
        meeting_id=meeting.id,
        text="from the cli",
        listeners=world.listeners,
    )
    await add_owner_entry(
        world.sessions,
        world.clock,
        meeting_id=meeting.id,
        text="from the thread",
        external_ref="m1",
        listeners=world.listeners,
    )

    assert [(post.kind, post.persona_name, post.text) for post in await bridge.outbox()] == [
        ("entry", "Owner", "from the cli")
    ]
