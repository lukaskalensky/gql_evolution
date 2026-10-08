"""
Automatické CRUD testy nad DBDefinitions/main.py.

Tyto testy jsou záměrně integrační.

Předpoklady:
- existuje dostupná testovací databáze,
- connection string je dostupný přes ComposeConnectionString(),
- tabulky už obsahují alespoň některá seed data,
- primární klíč entit je UUID,
- operace se provádí přes funkce z DBDefinitions/main.py.

Testy nevytvářejí nová data od nuly.
Vezmou existující řádek, vytvoří jeho kopii s novým UUID,
kopii aktualizují, smažou a ověří základní čtení.

Spuštění:

    pytest tests/test_dbdefinitions_crud.py -q

Volitelně:

    pytest tests/test_dbdefinitions_crud.py -q -s
"""

from __future__ import annotations

import datetime
import decimal
import typing
import uuid

import pytest
import pytest_asyncio
import sqlalchemy
from sqlalchemy import inspect
from sqlalchemy.orm.properties import ColumnProperty, RelationshipProperty

from src.DBDefinitions import ComposeConnectionString, startEngine
from src.DBDefinitions.main import (
    CliError,
    iter_mapped_classes,
    get_primary_key_name,
    op_create,
    op_get,
    op_list,
    op_update,
    op_delete,
    serialize_instance,
)


JsonDict = dict[str, typing.Any]


@pytest.fixture#(scope="session")
def mapped_classes() -> list[type]:
    """
    Vrátí všechny SQLAlchemy mapované třídy.

    Modely musí být importované v DBDefinitions/__init__.py,
    jinak nebudou dostupné v BaseDBModel.registry.mappers.
    """
    result = list(iter_mapped_classes())

    assert result, "No mapped SQLAlchemy classes found"

    return result


@pytest_asyncio.fixture
async def db_session():
    """
    Vytvoří async session pro DB test.

    makeDrop=False:
      Testy nesmí mazat databázi.

    makeUp=True:
      Lokálně pomůže vytvořit tabulky, pokud ještě neexistují.
      V CI lze podle potřeby změnit na False.
    """
    session_maker = await startEngine(
        ComposeConnectionString(),
        makeDrop=False,
        makeUp=True,
    )

    assert session_maker is not None, "Unable to create async session maker"

    async with session_maker() as session:
        yield session

    remove = getattr(session_maker, "remove", None)
    if remove is not None:
        result = remove()
        if hasattr(result, "__await__"):
            await result


def is_json_like_scalar(value: typing.Any) -> bool:
    """
    Pomocná kontrola pro hodnoty, které lze bezpečně přenést
    do payloadu pro build_instance().
    """
    return (
        value is None
        or isinstance(value, str)
        or isinstance(value, bool)
        or isinstance(value, int)
        or isinstance(value, float)
        or isinstance(value, uuid.UUID)
        or isinstance(value, datetime.date)
        or isinstance(value, datetime.datetime)
        or isinstance(value, decimal.Decimal)
    )


def column_names(model_cls: type) -> set[str]:
    mapper = inspect(model_cls)

    return {
        prop.key
        for prop in mapper.attrs
        if isinstance(prop, ColumnProperty)
    }


def relationship_names(model_cls: type) -> set[str]:
    mapper = inspect(model_cls)

    return {
        prop.key
        for prop in mapper.attrs
        if isinstance(prop, RelationshipProperty)
    }


def make_copy_payload(model_cls: type, source: JsonDict) -> JsonDict:
    """
    Vytvoří payload pro create operaci jako kopii existující entity.

    Záměrně kopírujeme pouze sloupcové atributy, ne relationship atributy.
    Relationship testy je vhodné dělat samostatně, protože obecná kopie
    vnořených entit může narážet na unique constrainty, viewonly vztahy
    nebo specifickou doménovou logiku.
    """
    pk_name = get_primary_key_name(model_cls)
    allowed_columns = column_names(model_cls)

    payload: JsonDict = {}

    for key, value in source.items():
        if key not in allowed_columns:
            continue

        if not is_json_like_scalar(value):
            continue

        payload[key] = value

    payload[pk_name] = uuid.uuid4()

    return payload


def find_update_payload(model_cls: type, entity_payload: JsonDict) -> JsonDict | None:
    pk_name = get_primary_key_name(model_cls)

    base_payload = {
        pk_name: entity_payload[pk_name],
    }

    if "lastchange" in entity_payload:
        base_payload["lastchange"] = entity_payload["lastchange"]

    preferred_names = [
        "name",
        "name_en",
        "description",
        "place",
        "path",
    ]

    for name in preferred_names:
        if name in entity_payload:
            return {
                **base_payload,
                name: f"pytest-update-{uuid.uuid4()}",
            }

    mapper = inspect(model_cls)

    for prop in mapper.attrs:
        if not isinstance(prop, ColumnProperty):
            continue

        if prop.key in {pk_name, "lastchange"}:
            continue

        column = prop.columns[0]

        if isinstance(column.type, sqlalchemy.String):
            return {
                **base_payload,
                prop.key: f"pytest-update-{uuid.uuid4()}",
            }

    return None


async def get_first_existing_row(
    session,
    model_cls: type,
) -> JsonDict | None:
    """
    Vrátí první existující řádek entity přes op_list().

    Pokud tabulka nemá data, vrací None.
    """
    rows = await op_list(
        session,
        model_cls,
        {
            "limit": 1,
            "offset": 0,
        },
    )

    if not rows:
        return None

    return rows[0]


@pytest.mark.asyncio
async def test_dbdefinitions_crud_copy_existing_entities(
    db_session,
    mapped_classes: list[type],
):
    """
    Integrační CRUD smoke test pro všechny mapované entity, které mají data.

    Test nedělá seed od nuly.
    Vyžaduje alespoň jeden existující řádek v tabulce dané entity.
    Entity bez dat se přeskočí.
    """
    tested_entities: list[str] = []
    skipped_entities: list[str] = []

    for model_cls in mapped_classes:
        pk_name = get_primary_key_name(model_cls)

        source_row = await get_first_existing_row(db_session, model_cls)

        if source_row is None:
            skipped_entities.append(f"{model_cls.__name__}: no source row")
            continue

        if pk_name not in source_row:
            skipped_entities.append(
                f"{model_cls.__name__}: primary key {pk_name!r} missing in source row"
            )
            continue

        create_payload = make_copy_payload(model_cls, source_row)
        copied_id = create_payload[pk_name]

        created = None

        try:
            created = await op_create(
                db_session,
                model_cls,
                create_payload,
            )

            assert created[pk_name] == copied_id

            loaded = await op_get(
                db_session,
                model_cls,
                {
                    pk_name: copied_id,
                },
            )

            assert loaded[pk_name] == copied_id

            listed = await op_list(
                db_session,
                model_cls,
                {
                    "where": {
                        pk_name: {
                            "_eq": copied_id,
                        }
                    },
                    "limit": 10,
                    "offset": 0,
                },
            )

            assert len(listed) == 1
            assert listed[0][pk_name] == copied_id

            # update_payload = find_update_payload(model_cls, create_payload)

            fresh_loaded_before_update = await op_get(
                db_session,
                model_cls,
                {
                    pk_name: copied_id,
                },
            )

            update_payload = find_update_payload(
                model_cls,
                fresh_loaded_before_update,
            )

            if update_payload is not None:
                updated = await op_update(
                    db_session,
                    model_cls,
                    update_payload,
                )

                assert updated[pk_name] == copied_id

                updated_field_names = [
                    key
                    for key in update_payload.keys()
                    if key != pk_name
                ]

                for field_name in updated_field_names:
                    assert updated[field_name] == update_payload[field_name]

            deleted = await op_delete(
                db_session,
                model_cls,
                {
                    pk_name: copied_id,
                },
            )

            assert deleted["ok"] is True

            loaded_after_delete = await op_get(
                db_session,
                model_cls,
                {
                    pk_name: copied_id,
                },
            )

            assert loaded_after_delete["ok"] is False
            assert loaded_after_delete["error"] == "not_found"

            tested_entities.append(model_cls.__name__)

        finally:
            # Bezpečnostní cleanup.
            # Pokud test spadne po create, pokusíme se kopii smazat.
            if created is not None:
                try:
                    await op_delete(
                        db_session,
                        model_cls,
                        {
                            pk_name: copied_id,
                        },
                    )
                except Exception:
                    pass

    if not tested_entities:
        pytest.skip(
            "No DB entity had existing seed rows. "
            f"Skipped entities: {skipped_entities}"
        )

    assert tested_entities, "At least one entity should be tested"


@pytest.mark.asyncio
async def test_dbdefinitions_list_all_entities_does_not_crash(
    db_session,
    mapped_classes: list[type],
):
    """
    Coverage smoke test pro list operaci nad všemi entitami.

    where není uvedené, takže DBDefinitions/main.py má použít
    primitivní select(model), nikoliv prepareSelect().
    """
    for model_cls in mapped_classes:
        rows = await op_list(
            db_session,
            model_cls,
            {
                "limit": 5,
                "offset": 0,
            },
        )

        assert isinstance(rows, list)


@pytest.mark.asyncio
async def test_dbdefinitions_get_existing_rows(
    db_session,
    mapped_classes: list[type],
):
    """
    Ověří read single pro entity, které mají alespoň jeden řádek.
    """
    checked = 0

    for model_cls in mapped_classes:
        pk_name = get_primary_key_name(model_cls)

        source_row = await get_first_existing_row(db_session, model_cls)

        if source_row is None:
            continue

        loaded = await op_get(
            db_session,
            model_cls,
            {
                pk_name: source_row[pk_name],
            },
        )

        assert loaded[pk_name] == source_row[pk_name]
        checked += 1

    if checked == 0:
        pytest.skip("No existing rows found in any mapped entity")