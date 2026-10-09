"""Registers the inventory's action types and executors with `labhq.approvals`.

Import this module once per process that serves approvals (the CLI and the MCP server do).
"""

from labhq.approvals import ActionType, Executor, default_actions, default_executors
from labhq.db.enums import RiskClass
from labhq.inventory.analysis import ANALYSE_PROJECT, AnalysePayload, AnalysisEngine
from labhq.inventory.close import CLOSE_SESSION, ClosePayload, SessionCloser
from labhq.inventory.folders import (
    CREATE_FOLDER_MANAGER,
    FolderManagerEngine,
    FolderManagerPayload,
)

# All light: each one is the owner's confirmation of something shown to them, and none loses
# a conversation or touches a repository.
for _key, _executor in (
    (ANALYSE_PROJECT, Executor(AnalysisEngine().run, AnalysePayload.model_validate)),
    (CLOSE_SESSION, Executor(SessionCloser().run, ClosePayload.model_validate)),
    (
        CREATE_FOLDER_MANAGER,
        Executor(FolderManagerEngine().run, FolderManagerPayload.model_validate),
    ),
):
    if _key not in default_actions:
        default_actions.register(_key, ActionType(_key, RiskClass.LIGHT))
        default_executors.register(_key, _executor)
