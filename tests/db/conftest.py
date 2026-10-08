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
from src.DBDefinitions.seed import init_database_data
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
async def PostgreSQL():
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


async def SQLLite(tmp_path):
    db_file = tmp_path / "test.sqlite3"
    connection_string = f"sqlite+aiosqlite:///{db_file}"

    session_maker = await startEngine(
        connection_string,
        makeDrop=True,
        makeUp=True,
    )

    assert session_maker is not None, "Unable to create async session maker"

    async with session_maker() as session:
        await init_database_data(session)
        yield session

    remove = getattr(session_maker, "remove", None)
    if remove is not None:
        result = remove()
        if hasattr(result, "__await__"):
            await result

@pytest_asyncio.fixture
async def db_session(PostgreSQL):
    return PostgreSQL

# @pytest_asyncio.fixture
# async def db_session(SQLite):
#     return SQLite