from __future__ import annotations

from src.GraphTypeDefinitions.SessionCommitExtension import SessionCommitExtension
from src.GraphTypeDefinitions.schema_factory import create_schema
from tests.support.fake_permissions_extension import FakeRolePermissionSchemaExtension
from tests.support.fake_whoami_extension import FakeWhoAmIExtension


def create_explicit_test_schema():
    """Create schema for explicit GraphQL tests.

    The schema keeps the real Query/Mutation definitions and real
    SessionCommitExtension, but replaces external WhoAmI and permissions loading
    with local fakes.
    """

    return create_schema(
        extensions=[
            SessionCommitExtension,
            FakeWhoAmIExtension,
            FakeRolePermissionSchemaExtension,
        ],
        include_cache_extensions=True,
    )


explicit_test_schema = create_explicit_test_schema()
