"""
Explicitní GraphQL testy domény Tags (TagType, Tag, TagEntity).

Běží nad skutečným schématem se SessionCommitExtension a lokálními fake
WhoAmI/permission extensions, stejně jako testy Event domény.
"""

from __future__ import annotations

import uuid

import pytest

from src.GraphTypeDefinitions.Domain_Tags.permissions import TAG_ADMIN_ROLES
from src.ServiceDefinitions.Domain_Tags import ErrorCodes
from tests.support.asserts import assert_delete, assert_insert, assert_read, assert_typename_with_error, assert_update


def make_user(role_name: str | None, user_id: uuid.UUID | None = None) -> dict:
    roles = [] if role_name is None else [{"name": role_name, "roletype": {"name": role_name}, "valid": True}]
    return {"id": str(user_id or uuid.uuid4()), "name": "pytest tag user", "email": "pytest@example.test", "roles": roles}


ADMIN = make_user(TAG_ADMIN_ROLES[0])


@pytest.fixture
def AsUser(WhoAmIExtensionOverride):
    """Přepne uživatele, za kterého se provádějí další GraphQL operace."""

    def as_user(user: dict) -> None:
        WhoAmIExtensionOverride.set_user(user)

    yield as_user
    WhoAmIExtensionOverride.reset()


TAG_TYPE_INSERT = """
mutation TagTypeInsert($tagType: TagTypeInsertGQLModel!) {
  tagTypeInsert(tagType: $tagType) {
    __typename
    ... on TagTypeGQLModel { id name nameEn parentId lastchange parent { id name } }
    ... on TagTypeGQLModelInsertError { msg code location }
  }
}
"""

TAG_TYPE_UPDATE = """
mutation TagTypeUpdate($tagType: TagTypeUpdateGQLModel!) {
  tagTypeUpdate(tagType: $tagType) {
    __typename
    ... on TagTypeGQLModel { id name nameEn parentId lastchange }
    ... on TagTypeGQLModelUpdateError { msg code location Entity { id name } }
  }
}
"""

TAG_TYPE_DELETE = """
mutation TagTypeDelete($tagType: TagTypeDeleteGQLModel!) {
  tagTypeDelete(tagType: $tagType) {
    __typename
    ... on TagTypeGQLModelDeleteError { msg code location }
  }
}
"""

TAG_INSERT = """
mutation TagInsert($tag: TagInsertGQLModel!) {
  tagInsert(tag: $tag) {
    __typename
    ... on TagGQLModel { id name label color description typeId lastchange type { id name } }
    ... on TagGQLModelInsertError { msg code location }
  }
}
"""

TAG_UPDATE = """
mutation TagUpdate($tag: TagUpdateGQLModel!) {
  tagUpdate(tag: $tag) {
    __typename
    ... on TagGQLModel { id name label color description lastchange }
    ... on TagGQLModelUpdateError { msg code location }
  }
}
"""

TAG_DELETE = """
mutation TagDelete($tag: TagDeleteGQLModel!) {
  tagDelete(tag: $tag) {
    __typename
    ... on TagGQLModelDeleteError { msg code location }
  }
}
"""

TAG_ENTITY_ASSIGN = """
mutation TagEntityAssign($tagEntity: TagEntityInsertGQLModel!) {
  tagEntityAssign(tagEntity: $tagEntity) {
    __typename
    ... on TagEntityGQLModel { id entityId entityTypeId tagId ownerId lastchange tag { id label } }
    ... on TagEntityGQLModelInsertError { msg code location }
  }
}
"""

TAG_ENTITY_UNASSIGN = """
mutation TagEntityUnassign($tagEntity: TagEntityDeleteGQLModel!) {
  tagEntityUnassign(tagEntity: $tagEntity) {
    __typename
    ... on TagEntityGQLModelDeleteError { msg code location }
  }
}
"""


async def insert_tag_type(execute, **values):
    return assert_insert(await execute(TAG_TYPE_INSERT, {"tagType": {"id": str(uuid.uuid4()), **values}}))


async def insert_tag(execute, **values):
    return assert_insert(await execute(TAG_INSERT, {"tag": {"id": str(uuid.uuid4()), **values}}))


@pytest.mark.explicit
@pytest.mark.asyncio
async def test_gql_tag_type_crud_and_tree_explicit(SchemaExecutor, AsUser):
    AsUser(ADMIN)
    root = await insert_tag_type(SchemaExecutor, name="pytest root", nameEn="pytest root en")
    child = await insert_tag_type(SchemaExecutor, name="pytest child", parentId=root["id"])
    assert child["parentId"] == root["id"]
    assert child["parent"] == {"id": root["id"], "name": "pytest root"}

    by_id = await SchemaExecutor(
        """
        query TagTypeById($id: UUID!) {
          tagTypeById(id: $id) { __typename id name lastchange children { id name } }
        }
        """,
        {"id": root["id"]},
    )
    assert [c["id"] for c in assert_read(by_id)["children"]] == [child["id"]]

    page = await SchemaExecutor(
        """
        query TagTypePage($where: TagTypeInputFilter) {
          tagTypePage(limit: 100, where: $where) { id name }
        }
        """,
        {"where": {"parent_id": {"_eq": root["id"]}}},
    )
    assert page.get("errors") is None
    assert [row["id"] for row in page["data"]["tagTypePage"]] == [child["id"]]

    # Kořen nelze smazat, dokud má podřízené typy.
    blocked = await SchemaExecutor(TAG_TYPE_DELETE, {"tagType": {"id": root["id"], "lastchange": root["lastchange"]}})
    assert_typename_with_error(blocked, code=ErrorCodes.TAG_TYPE_HAS_CHILDREN)

    # Cyklus ve stromu je odmítnut.
    cycle = await SchemaExecutor(TAG_TYPE_UPDATE, {"tagType": {"id": root["id"], "lastchange": root["lastchange"], "parentId": child["id"]}})
    assert_typename_with_error(cycle, code=ErrorCodes.TAG_TYPE_CYCLE)

    # Update mění jen předané atributy (nameEn zůstává).
    updated = assert_update(await SchemaExecutor(TAG_TYPE_UPDATE, {"tagType": {"id": root["id"], "lastchange": root["lastchange"], "name": "pytest root updated"}}))
    assert updated["name"] == "pytest root updated"
    assert updated["nameEn"] == "pytest root en"

    # Zastaralý lastchange vede na konflikt.
    stale = await SchemaExecutor(TAG_TYPE_UPDATE, {"tagType": {"id": root["id"], "lastchange": root["lastchange"], "name": "stale"}})
    assert_typename_with_error(stale, code=ErrorCodes.TAG_TYPE_CONFLICT)

    assert_delete(await SchemaExecutor(TAG_TYPE_DELETE, {"tagType": {"id": child["id"], "lastchange": child["lastchange"]}}))
    assert_delete(await SchemaExecutor(TAG_TYPE_DELETE, {"tagType": {"id": root["id"], "lastchange": updated["lastchange"]}}))


@pytest.mark.explicit
@pytest.mark.asyncio
async def test_gql_tag_crud_explicit(SchemaExecutor, AsUser):
    AsUser(ADMIN)
    tag_type = await insert_tag_type(SchemaExecutor, name="pytest tag type")
    tag = await insert_tag(SchemaExecutor, name="pytest-important", label="Důležité", color="#ff0000", typeId=tag_type["id"])
    assert tag["type"] == {"id": tag_type["id"], "name": "pytest tag type"}

    by_id = assert_read(await SchemaExecutor(
        """
        query TagById($id: UUID!) {
          tagById(id: $id) { __typename id label color lastchange type { id } tagEntities { id } }
        }
        """,
        {"id": tag["id"]},
    ))
    assert by_id["label"] == "Důležité"
    assert by_id["type"]["id"] == tag_type["id"]
    assert by_id["tagEntities"] == []

    page = await SchemaExecutor(
        """
        query TagPage($where: TagInputFilter) { tagPage(limit: 100, where: $where) { id label } }
        """,
        {"where": {"type_id": {"_eq": tag_type["id"]}}},
    )
    assert page.get("errors") is None
    assert [row["id"] for row in page["data"]["tagPage"]] == [tag["id"]]

    missing_type = await SchemaExecutor(TAG_INSERT, {"tag": {"name": "pytest-bad", "typeId": str(uuid.uuid4())}})
    assert_typename_with_error(missing_type, code=ErrorCodes.TAG_TYPE_REFERENCE_NOT_FOUND)

    updated = assert_update(await SchemaExecutor(TAG_UPDATE, {"tag": {"id": tag["id"], "lastchange": tag["lastchange"], "label": "Velmi důležité"}}))
    assert updated["label"] == "Velmi důležité"
    assert updated["color"] == "#ff0000"

    assert_delete(await SchemaExecutor(TAG_DELETE, {"tag": {"id": tag["id"], "lastchange": updated["lastchange"]}}))
    assert_delete(await SchemaExecutor(TAG_TYPE_DELETE, {"tagType": {"id": tag_type["id"], "lastchange": tag_type["lastchange"]}}))


@pytest.mark.explicit
@pytest.mark.asyncio
async def test_gql_tag_mutations_require_admin_role_explicit(SchemaExecutor, AsUser):
    AsUser(make_user("student"))
    denied = await SchemaExecutor(TAG_INSERT, {"tag": {"name": "pytest-denied"}})
    error = assert_typename_with_error(denied)
    assert "not authorized" in error["msg"]

    denied_type = await SchemaExecutor(TAG_TYPE_INSERT, {"tagType": {"name": "pytest-denied"}})
    assert_typename_with_error(denied_type)


@pytest.mark.explicit
@pytest.mark.asyncio
async def test_gql_tag_entity_assign_and_unassign_explicit(SchemaExecutor, AsUser):
    """Scénář ze zadání: Project A -> Důležité, K projednání; odebrat smí jen vlastník."""
    owner = make_user(None)
    AsUser(ADMIN)
    important = await insert_tag(SchemaExecutor, name="pytest-important", label="Důležité")
    review = await insert_tag(SchemaExecutor, name="pytest-review", label="K projednání")

    project_a, project_type = str(uuid.uuid4()), str(uuid.uuid4())
    AsUser(owner)  # přiřazovat smí každý přihlášený uživatel, bez role
    first = assert_insert(await SchemaExecutor(TAG_ENTITY_ASSIGN, {"tagEntity": {"entityId": project_a, "entityTypeId": project_type, "tagId": important["id"]}}))
    second = assert_insert(await SchemaExecutor(TAG_ENTITY_ASSIGN, {"tagEntity": {"entityId": project_a, "entityTypeId": project_type, "tagId": review["id"]}}))
    assert first["ownerId"] == owner["id"]
    assert first["tag"] == {"id": important["id"], "label": "Důležité"}

    again = assert_insert(await SchemaExecutor(TAG_ENTITY_ASSIGN, {"tagEntity": {"entityId": project_a, "entityTypeId": project_type, "tagId": important["id"]}}))
    assert again["id"] == first["id"]

    page = await SchemaExecutor(
        """
        query TagsOfEntity($where: TagEntityInputFilter) {
          tagEntityPage(limit: 100, where: $where) { id tag { label } }
        }
        """,
        {"where": {"entity_id": {"_eq": project_a}}},
    )
    assert page.get("errors") is None
    assert sorted(row["tag"]["label"] for row in page["data"]["tagEntityPage"]) == ["Důležité", "K projednání"]

    missing_tag = await SchemaExecutor(TAG_ENTITY_ASSIGN, {"tagEntity": {"entityId": project_a, "entityTypeId": project_type, "tagId": str(uuid.uuid4())}})
    assert_typename_with_error(missing_tag, code=ErrorCodes.TAG_ENTITY_TAG_NOT_FOUND)

    by_id = assert_read(await SchemaExecutor(
        "query TagEntityById($id: UUID!) { tagEntityById(id: $id) { __typename id lastchange entityId owner { id } } }",
        {"id": first["id"]},
    ))
    assert by_id["owner"] == {"id": owner["id"]}

    # Přiřazený tag nelze smazat.
    AsUser(ADMIN)
    blocked = await SchemaExecutor(TAG_DELETE, {"tag": {"id": important["id"], "lastchange": important["lastchange"]}})
    assert_typename_with_error(blocked, code=ErrorCodes.TAG_HAS_ASSIGNMENTS)

    # Cizí uživatel přiřazení odebrat nesmí.
    AsUser(make_user(None))
    not_owner = await SchemaExecutor(TAG_ENTITY_UNASSIGN, {"tagEntity": {"id": first["id"], "lastchange": first["lastchange"]}})
    assert_typename_with_error(not_owner, code=ErrorCodes.TAG_ENTITY_NOT_OWNER)

    AsUser(owner)
    for assignment in (first, second):
        assert_delete(await SchemaExecutor(TAG_ENTITY_UNASSIGN, {"tagEntity": {"id": assignment["id"], "lastchange": assignment["lastchange"]}}))

    AsUser(ADMIN)
    for tag in (important, review):
        assert_delete(await SchemaExecutor(TAG_DELETE, {"tag": {"id": tag["id"], "lastchange": tag["lastchange"]}}))
