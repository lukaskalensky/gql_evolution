"""
Automatické CRUD testy nad ServiceDefinitions.

Tyto testy jsou integrační.

Cíl:
- otestovat service vrstvu,
- otestovat napojení service -> LoaderMap -> dataloadery -> DB,
- pokrýt standardní CRUD metody:
  Create
  ReadById
  ReadPage
  Update
  Delete,
- ověřit, že Update používá aktuální lastchange token.

Testovací princip:
- najdeme service třídy přes ServiceRegistry,
- přes service.getLoader(ctx) zjistíme DB model,
- přes service.ReadPage najdeme existující řádek,
- vytvoříme jeho kopii s novým UUID,
- přes service.Create kopii uložíme,
- přes service.ReadById ověříme čtení,
- přes service.ReadPage ověříme filtrování,
- před Update znovu načteme aktuální entitu a použijeme její lastchange,
- přes service.Update upravíme bezpečný textový atribut,
- přes service.Delete kopii smažeme.

Spuštění:

    pytest tests/test_servicedefinitions_crud.py -q
"""

from __future__ import annotations

import datetime
import decimal
import inspect as pyinspect
import typing
import uuid

import pytest
import sqlalchemy
from sqlalchemy import inspect
from sqlalchemy.orm.properties import ColumnProperty

from src.DBDefinitions import ComposeConnectionString, startEngine
from src.Dataloaders import LoaderMap
from src.ServiceDefinitions.BaseService import BaseService
from src.ServiceDefinitions.ServiceContext import ServiceContext, SERVICES


JsonDict = dict[str, typing.Any]


def iter_service_classes() -> typing.Iterator[tuple[str, type[BaseService]]]:
    """
    Vrátí service třídy registrované v ServiceRegistry.

    Zdrojem pravdy je SERVICES ze ServiceContext.py.
    """
    for name in dir(SERVICES):
        if name.startswith("_"):
            continue

        if not name.endswith("Service"):
            continue

        value = getattr(SERVICES, name)

        if pyinspect.isclass(value) and issubclass(value, BaseService):
            yield name, value


def service_has_standard_crud(service_cls: type[BaseService]) -> bool:
    required_methods = [
        "getLoader",
        "Create",
        "ReadById",
        "ReadPage",
        "Update",
        "Delete",
    ]

    return all(
        callable(getattr(service_cls, method_name, None))
        for method_name in required_methods
    )


@pytest.fixture#(scope="session")
def service_classes() -> list[tuple[str, type[BaseService]]]:
    result = [
        (name, service_cls)
        for name, service_cls in iter_service_classes()
        if service_has_standard_crud(service_cls)
    ]

    assert result, "No standard CRUD services found"

    return result


@pytest.fixture
async def service_context():
    """
    Vytvoří ServiceContext nad skutečnou DB session.

    makeDrop=False:
      Test nesmí mazat databázi.

    makeUp=True:
      Lokálně pomůže vytvořit tabulky, pokud ještě neexistují.
    """
    session_maker = await startEngine(
        ComposeConnectionString(),
        makeDrop=False,
        makeUp=True,
    )

    assert session_maker is not None, "Unable to create async session maker"

    async with session_maker() as session:
        loaders = LoaderMap(session)

        ctx = ServiceContext(
            loaders=loaders,
            user=None,
            request=None,
        )

        yield ctx

    remove = getattr(session_maker, "remove", None)
    if remove is not None:
        result = remove()
        if hasattr(result, "__await__"):
            await result


async def get_service_model(
    ctx: ServiceContext,
    service_cls: type[BaseService],
) -> type:
    """
    Získá DB model nepřímo přes service -> loader.

    Test service vrstvy by neměl vyhledávat model přes DB registry.
    """
    loader = await service_cls.getLoader(ctx)

    get_model = getattr(loader, "getModel", None)
    if callable(get_model):
        return get_model()

    model = getattr(loader, "DBModel", None)
    if model is not None:
        return model

    model = getattr(loader, "model", None)
    if model is not None:
        return model

    raise AssertionError(
        f"Unable to determine DB model from loader for {service_cls.__name__}"
    )


def get_primary_key_name(model_cls: type) -> str:
    mapper = inspect(model_cls)
    primary_key = mapper.primary_key

    assert len(primary_key) == 1, (
        f"Model {model_cls.__name__} must have exactly one primary key"
    )

    return primary_key[0].key


def get_column_names(model_cls: type) -> set[str]:
    mapper = inspect(model_cls)

    return {
        prop.key
        for prop in mapper.attrs
        if isinstance(prop, ColumnProperty)
    }


def is_scalar_copy_value(value: typing.Any) -> bool:
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


def serialize_instance(instance: typing.Any) -> JsonDict:
    """
    Převede SQLAlchemy instanci na dict sloupcových atributů.

    Relationship atributy se zde záměrně nekopírují.
    """
    mapper = inspect(instance.__class__)
    result: JsonDict = {}

    for prop in mapper.attrs:
        if not isinstance(prop, ColumnProperty):
            continue

        value = getattr(instance, prop.key)

        if is_scalar_copy_value(value):
            result[prop.key] = value

    return result


def build_instance(model_cls: type, payload: JsonDict) -> typing.Any:
    """
    Vytvoří DB entitu z payloadu.

    Pro obecný CRUD test kopírujeme pouze sloupcové atributy.
    Relationship testy patří do explicitních doménových testů.
    """
    column_names = get_column_names(model_cls)

    constructor_payload = {
        key: value
        for key, value in payload.items()
        if key in column_names
    }

    return model_cls(**constructor_payload)


def make_copy_payload(model_cls: type, source_entity: typing.Any) -> JsonDict:
    """
    Vytvoří payload pro Create jako kopii existující entity s novým UUID.

    Pozor:
    lastchange z původní entity se kopírovat může, ale pro následný Update
    se nesmí použít tato původní hodnota. Po Create je nutné entitu znovu
    načíst a použít aktuální lastchange uložený v DB.
    """
    pk_name = get_primary_key_name(model_cls)

    payload = serialize_instance(source_entity)
    payload[pk_name] = uuid.uuid4()

    return payload


def find_update_payload(model_cls: type, fresh_entity_payload: JsonDict) -> JsonDict | None:
    """
    Najde bezpečný atribut pro Update.

    Důležité:
    Pokud model obsahuje lastchange, musí být do update payloadu vložen
    aktuální lastchange z čerstvě načtené entity.

    Service.Update používá lastchange jako optimistic concurrency token.
    Pokud token nesouhlasí s DB, update má selhat.
    """
    pk_name = get_primary_key_name(model_cls)

    base_payload: JsonDict = {
        pk_name: fresh_entity_payload[pk_name],
    }

    if "lastchange" in fresh_entity_payload:
        base_payload["lastchange"] = fresh_entity_payload["lastchange"]

    preferred_names = [
        "name",
        "name_en",
        "description",
        "place",
        "path",
    ]

    for name in preferred_names:
        if name in fresh_entity_payload:
            return {
                **base_payload,
                name: f"pytest-service-update-{uuid.uuid4()}",
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
                prop.key: f"pytest-service-update-{uuid.uuid4()}",
            }

    return None


async def get_first_existing_entity(
    ctx: ServiceContext,
    service_cls: type[BaseService],
) -> typing.Any | None:
    """
    Najde první existující entitu přes service.ReadPage.

    where=None má projít do service vrstvy jako nefiltrující dotaz.
    """
    result = await service_cls.ReadPage(
        ctx=ctx,
        skip=0,
        limit=1,
        where=None,
    )

    if not result:
        return None

    return result[0]


@pytest.mark.asyncio
async def test_servicedefinitions_crud_copy_existing_entities(
    service_context: ServiceContext,
    service_classes: list[tuple[str, type[BaseService]]],
):
    """
    Integrační CRUD smoke test pro všechny standardní service.

    Entity bez seed dat se přeskočí.
    """
    tested_services: list[str] = []
    skipped_services: list[str] = []

    for service_name, service_cls in service_classes:
        model_cls = await get_service_model(service_context, service_cls)
        pk_name = get_primary_key_name(model_cls)

        source_entity = await get_first_existing_entity(
            service_context,
            service_cls,
        )

        if source_entity is None:
            skipped_services.append(f"{service_name}: no source row")
            continue

        create_payload = make_copy_payload(model_cls, source_entity)
        copied_id = create_payload[pk_name]
        copied_entity = build_instance(model_cls, create_payload)

        created = None
        deleted = False

        try:
            created = await service_cls.Create(
                ctx=service_context,
                entity=copied_entity,
            )

            assert created is not None
            assert getattr(created, pk_name) == copied_id

            loaded = await service_cls.ReadById(
                ctx=service_context,
                id=copied_id,
            )

            assert loaded is not None
            assert getattr(loaded, pk_name) == copied_id

            listed = await service_cls.ReadPage(
                ctx=service_context,
                skip=0,
                limit=10,
                where={
                    pk_name: {
                        "_eq": copied_id,
                    }
                },
            )

            assert len(listed) == 1
            assert getattr(listed[0], pk_name) == copied_id

            fresh_loaded_before_update = await service_cls.ReadById(
                ctx=service_context,
                id=copied_id,
            )

            assert fresh_loaded_before_update is not None

            fresh_loaded_payload = serialize_instance(
                fresh_loaded_before_update,
            )

            update_payload = find_update_payload(
                model_cls,
                fresh_loaded_payload,
            )

            if update_payload is not None:
                update_entity = build_instance(model_cls, update_payload)

                updated = await service_cls.Update(
                    ctx=service_context,
                    entity=update_entity,
                )

                assert updated is not None
                assert getattr(updated, pk_name) == copied_id

                for field_name, expected_value in update_payload.items():
                    if field_name in {pk_name, "lastchange"}:
                        continue

                    assert getattr(updated, field_name) == expected_value

            delete_entity = build_instance(
                model_cls,
                {
                    pk_name: copied_id,
                },
            )

            deleted_result = await service_cls.Delete(
                ctx=service_context,
                entity=delete_entity,
            )

            assert deleted_result is None # lepe osetrit
            deleted = True

            loaded_after_delete = await service_cls.ReadById(
                ctx=service_context,
                id=copied_id,
            )

            assert loaded_after_delete is None

            tested_services.append(service_name)

        finally:
            if created is not None and not deleted:
                try:
                    cleanup_entity = build_instance(
                        model_cls,
                        {
                            pk_name: copied_id,
                        },
                    )

                    await service_cls.Delete(
                        ctx=service_context,
                        entity=cleanup_entity,
                    )
                except Exception:
                    pass

    if not tested_services:
        pytest.skip(
            "No service had existing seed rows. "
            f"Skipped services: {skipped_services}"
        )

    assert tested_services


@pytest.mark.asyncio
async def test_servicedefinitions_readpage_all_services_does_not_crash(
    service_context: ServiceContext,
    service_classes: list[tuple[str, type[BaseService]]],
):
    """
    Coverage smoke test pro ReadPage nad všemi CRUD services.

    where=None ověří větev, kde se nemá používat rigidní prepareSelect filtr.
    """
    for service_name, service_cls in service_classes:
        result = await service_cls.ReadPage(
            ctx=service_context,
            skip=0,
            limit=5,
            where=None,
        )

        assert isinstance(result, list), service_name


@pytest.mark.asyncio
async def test_servicedefinitions_readbyid_existing_rows(
    service_context: ServiceContext,
    service_classes: list[tuple[str, type[BaseService]]],
):
    """
    Ověří ReadById pro service, které mají alespoň jeden existující řádek.
    """
    checked = 0

    for service_name, service_cls in service_classes:
        model_cls = await get_service_model(service_context, service_cls)
        pk_name = get_primary_key_name(model_cls)

        source_entity = await get_first_existing_entity(
            service_context,
            service_cls,
        )

        if source_entity is None:
            continue

        source_id = getattr(source_entity, pk_name)

        loaded = await service_cls.ReadById(
            ctx=service_context,
            id=source_id,
        )

        assert loaded is not None, service_name
        assert getattr(loaded, pk_name) == source_id

        checked += 1

    if checked == 0:
        pytest.skip("No existing rows found through any service")


# @pytest.mark.asyncio
# async def test_servicedefinitions_update_rejects_stale_lastchange(
#     service_context: ServiceContext,
#     service_classes: list[tuple[str, type[BaseService]]],
# ):
#     """
#     Ověří, že service Update odmítá zastaralý lastchange token.

#     Tento test se provede pouze pro service, jejichž model:
#     - má sloupec lastchange,
#     - má alespoň jeden existující řádek,
#     - má vhodný textový atribut pro update.
#     """
#     checked = 0

#     for service_name, service_cls in service_classes:
#         model_cls = await get_service_model(service_context, service_cls)
#         columns = get_column_names(model_cls)

#         if "lastchange" not in columns:
#             continue

#         pk_name = get_primary_key_name(model_cls)

#         source_entity = await get_first_existing_entity(
#             service_context,
#             service_cls,
#         )

#         if source_entity is None:
#             continue

#         create_payload = make_copy_payload(model_cls, source_entity)
#         copied_id = create_payload[pk_name]
#         copied_entity = build_instance(model_cls, create_payload)

#         created = None
#         deleted = False

#         try:
#             created = await service_cls.Create(
#                 ctx=service_context,
#                 entity=copied_entity,
#             )

#             assert created is not None

#             fresh = await service_cls.ReadById(
#                 ctx=service_context,
#                 id=copied_id,
#             )

#             assert fresh is not None

#             fresh_payload = serialize_instance(fresh)

#             valid_update_payload = find_update_payload(
#                 model_cls,
#                 fresh_payload,
#             )

#             if valid_update_payload is None:
#                 continue

#             stale_payload = dict(valid_update_payload)

#             current_lastchange = fresh_payload.get("lastchange")

#             if isinstance(current_lastchange, datetime.datetime):
#                 stale_payload["lastchange"] = datetime.datetime(
#                     1970,
#                     1,
#                     1,
#                     tzinfo=current_lastchange.tzinfo,
#                 )
#             else:
#                 stale_payload["lastchange"] = None

#             stale_entity = build_instance(model_cls, stale_payload)

#             with pytest.raises(Exception):
#                 await service_cls.Update(
#                     ctx=service_context,
#                     entity=stale_entity,
#                 )

#             delete_entity = build_instance(
#                 model_cls,
#                 {
#                     pk_name: copied_id,
#                 },
#             )

#             deleted_result = await service_cls.Delete(
#                 ctx=service_context,
#                 entity=delete_entity,
#             )

#             assert deleted_result is not None
#             deleted = True

#             checked += 1

#         finally:
#             if created is not None and not deleted:
#                 try:
#                     cleanup_entity = build_instance(
#                         model_cls,
#                         {
#                             pk_name: copied_id,
#                         },
#                     )

#                     await service_cls.Delete(
#                         ctx=service_context,
#                         entity=cleanup_entity,
#                     )
#                 except Exception:
#                     pass

#     if checked == 0:
#         pytest.skip(
#             "No service with lastchange and updateable text field found"
#         )