from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_uoishelpers_is_declared_as_direct_github_zip_dependency():
    pyproject = (ROOT / 'pyproject.toml').read_text()
    assert 'uoishelpers @ https://github.com/hrbolek/uoishelpers/archive/4e41615436d6effbe248d8503e4df373549bcec3.zip' in pyproject


def test_project_does_not_vendor_uoishelpers():
    assert not (ROOT / 'uoishelpers').exists()
    assert not (ROOT / 'src' / 'uoishelpers').exists()


def test_production_schema_registers_real_identity_and_role_extensions():
    from uoishelpers.gqlpermissions.RolePermissionSchemaExtension import (
        RolePermissionSchemaExtension,
    )
    from uoishelpers.schema import WhoAmIExtension

    from src.GraphTypeDefinitions.schema_factory import get_production_extensions

    extensions = get_production_extensions()

    assert WhoAmIExtension in extensions
    assert RolePermissionSchemaExtension in extensions
