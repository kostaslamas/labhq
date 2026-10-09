"""How a report's status and an A2A task state stand for each other. Data, not branches."""

from a2a.types import TaskState

from labhq.db.enums import ReportKind

# A report's status becomes the task's state. `blocked` is input-required, not failed: the
# order is stuck waiting on its giver, and the CEO may still report ready later.
STATE_OF_REPORT: dict[ReportKind, TaskState] = {
    ReportKind.PROGRESS: TaskState.TASK_STATE_WORKING,
    ReportKind.READY: TaskState.TASK_STATE_COMPLETED,
    ReportKind.BLOCKED: TaskState.TASK_STATE_INPUT_REQUIRED,
}
# Accepted but not reported on yet.
INITIAL_STATE = TaskState.TASK_STATE_SUBMITTED

# States after which the node will say nothing more about the order.
TERMINAL_STATES = frozenset(
    {
        TaskState.TASK_STATE_COMPLETED,
        TaskState.TASK_STATE_FAILED,
        TaskState.TASK_STATE_CANCELED,
        TaskState.TASK_STATE_REJECTED,
    }
)

# Metadata keys labhq adds to A2A messages and artifacts, under one vendor prefix.
ORDER_ID = "labhq.orderId"
SPEND_CAP = "labhq.spendCapMicros"
REPORT_SEQ = "labhq.seq"
REPORT_STATUS = "labhq.status"
REPORT_REF = "labhq.ref"

REPORT_ARTIFACT_PREFIX = "report-"
