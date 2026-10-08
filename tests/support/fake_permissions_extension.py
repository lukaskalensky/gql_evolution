from __future__ import annotations

import typing

from uoishelpers.gqlpermissions.RolePermissionSchemaExtension import RolePermissionSchemaExtension


class FakeRolePermissionSchemaExtension(RolePermissionSchemaExtension):
    """Local replacement for permission/role loading in GraphQL tests.

    It mimics the loader contract used by uoishelpers permission extensions:
    ``context["userRolesForRBACQuery_loader"]`` must expose async ``load`` and
    return a ``{"result": [...]}`` payload.
    """

    response_override: dict[str, typing.Any] | None = None

    async def load(self, key):
        response = self.__class__.response_override
        if response is not None:
            return response

        user = self.execution_context.context.get("user") or {}
        return {"result": user.get("roles", [])}

    async def on_execute(self):
        self.execution_context.context["userRolesForRBACQuery_loader"] = self
        yield

    @classmethod
    def set_response(cls, response: dict[str, typing.Any] | None) -> None:
        cls.response_override = response

    @classmethod
    def reset(cls) -> None:
        cls.response_override = None
