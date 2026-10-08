"""Backward-compatible import location for older tests.

Prefer importing from ``tests.support.explicit_schema``.  This file intentionally
contains no classes named ``Test*`` because pytest would try to collect them.
"""

from tests.support.explicit_schema import create_explicit_test_schema, explicit_test_schema

__all__ = ["create_explicit_test_schema", "explicit_test_schema"]
