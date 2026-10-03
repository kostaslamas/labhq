"""Role instructions: `role -> instruction`. It ships empty; each role registers its own text."""


class DuplicateRoleError(ValueError):
    pass


class RoleRegistry:
    def __init__(self) -> None:
        self._instructions: dict[str, str] = {}

    def register(self, role: str, instruction: str, *, replace: bool = False) -> None:
        if not role or not instruction.strip():
            raise ValueError("a role needs a name and a non-empty instruction")
        if role in self._instructions and not replace:
            raise DuplicateRoleError(role)
        self._instructions[role] = instruction.strip()

    def instruction(self, role: str) -> str | None:
        return self._instructions.get(role)

    def roles(self) -> frozenset[str]:
        return frozenset(self._instructions)


default_roles = RoleRegistry()
