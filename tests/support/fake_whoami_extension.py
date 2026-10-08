from __future__ import annotations

import os
import typing
import uuid

try:
    from uoishelpers.schema import WhoAmIExtension as _BaseWhoAmIExtension
except Exception:  # pragma: no cover - fallback for local linting without uoishelpers
    from strawberry.extensions import SchemaExtension as _BaseWhoAmIExtension


def default_fake_user() -> dict[str, typing.Any]:
    role_name = os.getenv("EXPLICIT_TEST_ROLE", "plánovací administrátor")
    return {
        "id": os.getenv("EXPLICIT_TEST_USER_ID", str(uuid.uuid4())),
        "name": os.getenv("EXPLICIT_TEST_USER_NAME", "pytest explicit user"),
        "email": os.getenv("EXPLICIT_TEST_USER_EMAIL", "pytest@example.test"),
        "roles": [
            {
                "name": role_name,
                "roletype": {"name": role_name},
                "valid": True,
            }
        ],
    }


class FakeWhoAmIExtension(_BaseWhoAmIExtension):
    """Local replacement for production WhoAmIExtension used in GraphQL tests.

    Pytest tries to collect classes whose names start with ``Test``.  Keep this
    class named ``FakeWhoAmIExtension`` intentionally.

    The production extension talks to the external UG/WhoAmI microservice and
    writes the resolved user into ``context["user"]``.  This fake preserves the
    same context contract without network communication.
    """

    user: dict[str, typing.Any] | None = None

    async def on_execute(self):
        context = self.execution_context.context
        user = self.__class__.user or context.get("test_user") or context.get("user") or default_fake_user()
        context["user"] = user
        yield

    @classmethod
    def set_user(cls, user: dict[str, typing.Any] | None) -> None:
        cls.user = user

    @classmethod
    def reset(cls) -> None:
        cls.user = None
