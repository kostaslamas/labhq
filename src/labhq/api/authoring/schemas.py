"""Request and response models for adding projects and agents. Amounts are micro-USD."""

from pydantic import BaseModel, ConfigDict, Field

from labhq.db.enums import AgentStatus


class AgentKindChoice(BaseModel):
    # What commands and config call it, for example `codex`.
    name: str
    display_name: str
    # The adapter key stored on the agent row.
    adapter: str
    # The program it needs; the UI names it when it is missing.
    binary: str
    # Whether `binary` is found on the machine labhq runs on.
    available: bool


class NewProjectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    # An absolute path on the machine labhq runs on, checked to be a git repository with a commit.
    repo_path: str = Field(min_length=1, max_length=4096)
    budget_micros: int | None = Field(default=None, ge=0, le=2**62)


class RegisteredProject(BaseModel):
    id: int
    name: str
    repo_path: str
    budget_micros: int | None


class NewAgentBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=200)
    kind: str = Field(min_length=1, max_length=64)
    reports_to: int | None = None
    budget_micros: int | None = Field(default=None, ge=0, le=2**62)


class AddedAgent(BaseModel):
    id: int
    project_id: int
    role: str
    title: str
    adapter: str
    kind: str
    reports_to: int | None
    budget_micros: int | None
    status: AgentStatus
    # The approval that activates it; decide it from the approvals page.
    approval_id: int
