"""Projects, agents, tasks and comments: who works on what."""

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from labhq.db.base import Base, enum_column, micros_column
from labhq.db.enums import AgentStatus, DepartmentStatus, ProjectStatus, TaskStatus


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    repo_path: Mapped[str] = mapped_column(Text)
    budget_micros: Mapped[int | None] = micros_column(nullable=True)
    status: Mapped[ProjectStatus] = mapped_column(
        enum_column(ProjectStatus, "project_status"), default=ProjectStatus.ACTIVE
    )
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class Department(Base):
    """A non-code unit under the CEO: a head, its members and a working folder (issue #171)."""

    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    # A key of the department kind registry (`labhq.departments.default_kinds`).
    kind: Mapped[str] = mapped_column(String(64))
    head_agent_id: Mapped[int | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL", use_alter=True)
    )
    budget_micros: Mapped[int | None] = micros_column(nullable=True)
    # Under the data directory; not required to be a git repository.
    folder: Mapped[str] = mapped_column(Text)
    status: Mapped[DepartmentStatus] = mapped_column(
        enum_column(DepartmentStatus, "department_status"), default=DepartmentStatus.ACTIVE
    )
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (
        Index("ix_agents_project_id_status", "project_id", "status"),
        Index("ix_agents_reports_to", "reports_to"),
        Index("ix_agents_department_id", "department_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("departments.id", ondelete="SET NULL")
    )
    role: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(200))
    reports_to: Mapped[int | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    adapter: Mapped[str] = mapped_column(String(64))
    config: Mapped[dict[str, Any]] = mapped_column(default=dict)
    budget_micros: Mapped[int | None] = micros_column(nullable=True)
    status: Mapped[AgentStatus] = mapped_column(
        enum_column(AgentStatus, "agent_status"), default=AgentStatus.PENDING_APPROVAL
    )
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_project_id_status", "project_id", "status"),
        Index("ix_tasks_assignee_id_status", "assignee_id", "status"),
        Index("ix_tasks_parent_id", "parent_id"),
        Index("ix_tasks_checkout_run_id", "checkout_run_id"),
        Index("ix_tasks_department_id_status", "department_id", "status"),
        CheckConstraint(
            "(project_id IS NOT NULL AND department_id IS NULL) "
            "OR (project_id IS NULL AND department_id IS NOT NULL)",
            name="task_scope",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Exactly one of `project_id` and `department_id` is set (the `task_scope` check).
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("departments.id", ondelete="CASCADE")
    )
    # A key of the deliverable registry (`labhq.departments.deliverables`).
    deliverable: Mapped[str] = mapped_column(String(32), default="branch")
    # What a `document` deliverable points at: its path inside the department folder.
    deliverable_ref: Mapped[str | None] = mapped_column(Text)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[TaskStatus] = mapped_column(
        enum_column(TaskStatus, "task_status"), default=TaskStatus.TODO
    )
    # Higher runs first.
    priority: Mapped[int] = mapped_column(default=0)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    # The lock for atomic checkout: set only by a conditional UPDATE ... WHERE IS NULL.
    checkout_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL", use_alter=True)
    )
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class Comment(Base):
    __tablename__ = "comments"
    __table_args__ = (Index("ix_comments_task_id_created_at", "task_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    # NULL author means the human operator.
    author_agent_id: Mapped[int | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL")
    )
    body: Mapped[str] = mapped_column(Text)
    # Ids of mentioned agents; each mention is a wakeup source.
    mentions: Mapped[list[Any]] = mapped_column(default=list)
    created_at: Mapped[datetime]
