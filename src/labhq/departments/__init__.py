"""Departments: non-code units under the CEO, as data (issue #171).

Importing this package registers the built-in kinds (`labhq.departments.builtin`).
"""

from labhq.departments import builtin
from labhq.departments.builtin import GENERIC_TOOLS, IT_CONFIG, IT_INSTRUCTION
from labhq.departments.kinds import DepartmentKind, default_kinds
from labhq.departments.service import (
    add_department_task,
    create_department,
    department_of,
    find_department,
    folder_for,
    kind_named,
)

__all__ = [
    "GENERIC_TOOLS",
    "IT_CONFIG",
    "IT_INSTRUCTION",
    "DepartmentKind",
    "add_department_task",
    "builtin",
    "create_department",
    "default_kinds",
    "department_of",
    "find_department",
    "folder_for",
    "kind_named",
]
