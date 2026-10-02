# labhq

An open-source, self-hosted project orchestrator for individuals, hobbyists and solo developers: one person, many projects, and a team of AI agents that works on them.

**Status: pre-alpha — planning only, nothing runs yet.**

## What it will do

- **Agent hierarchy.** An orchestrator, a manager per project, team leads and workers. Workers are Claude Code agents run through the Claude Agent SDK.
- **Call Center.** Talk to your orchestrator by voice from the AI app you already use (Claude, ChatGPT, Grok) through an MCP connector. labhq contains no voice code of its own.
- **Approvals on your phone.** Heavy actions wait for a passkey or biometric confirmation from a phone notification.
- **Agent meetings.** Standups, planning and review sessions between agents, mirrored live to Discord.
- **IT/Infra department.** A built-in department that watches your machines and opens tickets when something is wrong.
- **Desktop web UI.** Projects, agents, meetings and tickets in the browser.
- **Token economy.** Terse agent-to-agent output, plus rtk and graphify to keep context small.
- **Simple onboarding.** One command, and no third-party accounts required by default.

## Planned install

Not available yet. The intended entry point is:

```
uvx labhq onboard   # planned
```

## Stack

- Backend: Python 3.12, uv, FastAPI, SQLite with Alembic migrations.
- Frontend: Vue 3, TypeScript, Pinia, Tailwind 4, shadcn-vue.

## Planning

The design and roadmap live in [`planning/plan.md`](planning/plan.md). The plan is currently written in Greek.

## License

MIT. See [LICENSE](LICENSE).
