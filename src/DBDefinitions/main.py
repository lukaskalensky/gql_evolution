"""
Testovací / seedovací CLI nástroj nad DB modely.

Použití:

    python -m src.DBDefinitions.main Event create '{"name": "Workshop"}'

    python -m src.DBDefinitions.main Event get '{"id": "..."}'

    python -m src.DBDefinitions.main Event list '{"where": {"name": "Workshop"}}'

    python -m src.DBDefinitions.main Event update '{"id": "...", "name": "New name"}'

    python -m src.DBDefinitions.main Event delete '{"id": "..."}'

Payload lze načíst i ze souboru:

    python -m src.DBDefinitions.main Event create @payload.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import typing
import uuid
import datetime
import decimal

import sqlalchemy
from sqlalchemy import inspect, select
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.properties import ColumnProperty, RelationshipProperty

from uoishelpers.dataloaders import prepareSelect

from . import BaseDBModel, ComposeConnectionString, startEngine


JsonDict = dict[str, typing.Any]


class CliError(Exception):
    pass


def parse_payload(raw: str | None) -> JsonDict:
    if raw is None:
        return {}

    if raw.startswith("@"):
        path = raw[1:]
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    try:
        result = json.loads(raw)
    except json.JSONDecodeError as e:
        raise CliError(f"Invalid JSON payload: {e}") from e

    if not isinstance(result, dict):
        raise CliError("Payload must be a JSON object")

    return result


def json_default(value: typing.Any):
    if isinstance(value, uuid.UUID):
        return str(value)

    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()

    if isinstance(value, decimal.Decimal):
        return float(value)

    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def print_json(value: typing.Any) -> None:
    print(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            default=json_default,
        )
    )


def normalize_name(value: str) -> str:
    return value.replace("_", "").replace("-", "").lower()


def iter_mapped_classes() -> typing.Iterator[type]:
    """
    Vrátí všechny SQLAlchemy mapované třídy registrované pod BaseModel.

    Důležité:
    Aby zde byly doménové modely dostupné, musí být importované v
    DBDefinitions/__init__.py, např.:

        from .Domain_Events import EventModel, EventInvitationModel
    """
    for mapper in BaseDBModel.registry.mappers:
        yield mapper.class_


def build_entity_index() -> dict[str, type]:
    """
    Vytvoří vyhledávací index entit bez ručního výčtu.

    Podporované aliasy:
      - název třídy: EventModel
      - název bez suffixu Model: Event
      - název tabulky: events
      - normalizované varianty bez _, -, case insensitive
    """
    result: dict[str, type] = {}

    for cls in iter_mapped_classes():
        mapper = inspect(cls)
        class_name = cls.__name__
        table_name = mapper.local_table.name

        aliases = {
            class_name,
            table_name,
        }

        if class_name.endswith("Model"):
            aliases.add(class_name[: -len("Model")])

        for alias in aliases:
            result[alias] = cls
            result[normalize_name(alias)] = cls

    return result


def resolve_entity(entity_name: str) -> type:
    entity_index = build_entity_index()

    result = entity_index.get(entity_name)
    if result is not None:
        return result

    result = entity_index.get(normalize_name(entity_name))
    if result is not None:
        return result

    available = sorted(
        {
            cls.__name__
            for cls in iter_mapped_classes()
        }
    )

    raise CliError(
        f"Unknown entity '{entity_name}'. Available entities: {', '.join(available)}"
    )


def get_column_names(model_cls: type) -> set[str]:
    mapper = inspect(model_cls)
    return {
        prop.key
        for prop in mapper.attrs
        if isinstance(prop, ColumnProperty)
    }


def get_relationships(model_cls: type) -> dict[str, RelationshipProperty]:
    mapper = inspect(model_cls)
    return {
        prop.key: prop
        for prop in mapper.attrs
        if isinstance(prop, RelationshipProperty)
    }


def split_columns_and_relationships(
    model_cls: type,
    payload: JsonDict,
) -> tuple[JsonDict, JsonDict]:
    column_names = get_column_names(model_cls)
    relationships = get_relationships(model_cls)

    column_values: JsonDict = {}
    relationship_values: JsonDict = {}

    for key, value in payload.items():
        if key in column_names:
            column_values[key] = value
        elif key in relationships:
            relationship_values[key] = value
        else:
            raise CliError(
                f"Unknown attribute '{key}' for entity {model_cls.__name__}"
            )

    return column_values, relationship_values


def build_instance(model_cls: type, payload: JsonDict) -> typing.Any:
    """
    Vytvoří instanci SQLAlchemy modelu z payloadu.

    Umí i vnořené relationship:

        {
          "name": "Workshop",
          "invitations": [
            {"user_id": "...", "state_id": "..."}
          ]
        }

    Funguje pouze pro relationship deklarované v DB modelu pomocí relationship().
    """
    column_values, relationship_values = split_columns_and_relationships(
        model_cls,
        payload,
    )

    instance = model_cls(**column_values)

    relationships = get_relationships(model_cls)

    for relationship_name, value in relationship_values.items():
        relationship = relationships[relationship_name]
        related_cls = relationship.mapper.class_

        if relationship.uselist:
            if value is None:
                setattr(instance, relationship_name, [])
                continue

            if not isinstance(value, list):
                raise CliError(
                    f"Relationship '{relationship_name}' expects a list"
                )

            related_items = [
                build_instance(related_cls, item)
                for item in value
            ]
            setattr(instance, relationship_name, related_items)

        else:
            if value is None:
                setattr(instance, relationship_name, None)
                continue

            if not isinstance(value, dict):
                raise CliError(
                    f"Relationship '{relationship_name}' expects an object"
                )

            related_item = build_instance(related_cls, value)
            setattr(instance, relationship_name, related_item)

    return instance


def serialize_instance(
    instance: typing.Any,
    *,
    include: set[str] | None = None,
    visited: set[int] | None = None,
) -> JsonDict:
    if instance is None:
        return None

    include = include or set()
    visited = visited or set()

    object_id = id(instance)
    if object_id in visited:
        return {
            "_ref": str(getattr(instance, "id", object_id))
        }

    visited.add(object_id)

    mapper = inspect(instance.__class__)
    result: JsonDict = {}

    for prop in mapper.attrs:
        if isinstance(prop, ColumnProperty):
            result[prop.key] = getattr(instance, prop.key)

    relationships = get_relationships(instance.__class__)

    for relationship_name in include:
        relationship = relationships.get(relationship_name)

        if relationship is None:
            raise CliError(
                f"Unknown relationship '{relationship_name}' "
                f"for entity {instance.__class__.__name__}"
            )

        value = getattr(instance, relationship_name)

        if relationship.uselist:
            result[relationship_name] = [
                serialize_instance(
                    item,
                    include=set(),
                    visited=visited,
                )
                for item in value
            ]
        else:
            result[relationship_name] = serialize_instance(
                value,
                include=set(),
                visited=visited,
            )

    return result


def get_primary_key_name(model_cls: type) -> str:
    mapper = inspect(model_cls)
    primary_key = mapper.primary_key

    if len(primary_key) != 1:
        raise CliError(
            f"Entity {model_cls.__name__} must have exactly one primary key"
        )

    return primary_key[0].key


def get_primary_key_value(model_cls: type, payload: JsonDict) -> typing.Any:
    primary_key_name = get_primary_key_name(model_cls)

    if primary_key_name not in payload:
        raise CliError(
            f"Missing primary key '{primary_key_name}' in payload"
        )

    return payload[primary_key_name]


def parse_include(payload: JsonDict) -> set[str]:
    include = payload.get("include", [])

    if include is None:
        return set()

    if not isinstance(include, list):
        raise CliError("'include' must be a list of relationship names")

    return set(include)


def normalize_list_payload(payload: JsonDict) -> tuple[JsonDict, set[str], int, int, str | None]:
    """
    Normalizuje payload pro list/page operaci.

    Podporovaný tvar:

        {
          "where": {...},
          "include": ["invitations"],
          "limit": 100,
          "offset": 0,
          "order_by": "-created"
        }

    Pokud payload neobsahuje klíč "where", bere se celý payload jako where filtr.
    To je praktické pro rychlé CLI použití:

        Event list '{"name": "Workshop"}'
    """
    control_keys = {
        "where",
        "include",
        "limit",
        "offset",
        "order_by",
    }

    if "where" in payload:
        where = payload.get("where") or {}
    else:
        where = {
            key: value
            for key, value in payload.items()
            if key not in control_keys
        }

    if not isinstance(where, dict):
        raise CliError("'where' must be an object")

    include = parse_include(payload)
    limit = int(payload.get("limit", 100))
    offset = int(payload.get("offset", 0))
    order_by = payload.get("order_by")

    if order_by is not None and not isinstance(order_by, str):
        raise CliError("'order_by' must be a string column name")

    return where, include, limit, offset, order_by

async def op_create(session, model_cls: type, payload: JsonDict) -> JsonDict:
    instance = build_instance(model_cls, payload)

    session.add(instance)
    await session.commit()
    await session.refresh(instance)

    return serialize_instance(instance)


async def op_get(session, model_cls: type, payload: JsonDict) -> JsonDict:
    primary_key_value = get_primary_key_value(model_cls, payload)
    include = parse_include(payload)

    stmt = select(model_cls).where(
        getattr(model_cls, get_primary_key_name(model_cls)) == primary_key_value
    )

    for relationship_name in include:
        relationships = get_relationships(model_cls)
        if relationship_name not in relationships:
            raise CliError(
                f"Unknown relationship '{relationship_name}' "
                f"for entity {model_cls.__name__}"
            )

        stmt = stmt.options(
            selectinload(getattr(model_cls, relationship_name))
        )

    result = await session.execute(stmt)
    instance = result.scalar_one_or_none()

    if instance is None:
        return {
            "ok": False,
            "error": "not_found",
            "entity": model_cls.__name__,
            "id": primary_key_value,
        }

    return serialize_instance(
        instance,
        include=include,
    )


async def op_list(session, model_cls: type, payload: JsonDict) -> list[JsonDict]:
    where = payload.get("where", None)
    include = parse_include(payload)
    limit = int(payload.get("limit", 100))
    offset = int(payload.get("offset", 0))

    if where is not None and not isinstance(where, dict):
        raise CliError("'where' must be an object compatible with prepareSelect")

    if where is None:
        stmt = select(model_cls)
    else:
        stmt = prepareSelect(model_cls, where)

    for relationship_name in include:
        relationships = get_relationships(model_cls)

        if relationship_name not in relationships:
            raise CliError(
                f"Unknown relationship '{relationship_name}' "
                f"for entity {model_cls.__name__}"
            )

        stmt = stmt.options(
            selectinload(getattr(model_cls, relationship_name))
        )

    stmt = stmt.limit(limit).offset(offset)

    result = await session.execute(stmt)
    instances = result.scalars().all()

    return [
        serialize_instance(
            instance,
            include=include,
        )
        for instance in instances
    ]

async def op_update(session, model_cls: type, payload: JsonDict) -> JsonDict:
    primary_key_name = get_primary_key_name(model_cls)
    primary_key_value = get_primary_key_value(model_cls, payload)

    instance = await session.get(model_cls, primary_key_value)

    if instance is None:
        return {
            "ok": False,
            "error": "not_found",
            "entity": model_cls.__name__,
            "id": primary_key_value,
        }

    update_payload = {
        key: value
        for key, value in payload.items()
        if key != primary_key_name
    }

    column_values, relationship_values = split_columns_and_relationships(
        model_cls,
        update_payload,
    )

    for key, value in column_values.items():
        setattr(instance, key, value)

    relationships = get_relationships(model_cls)

    for relationship_name, value in relationship_values.items():
        relationship = relationships[relationship_name]
        related_cls = relationship.mapper.class_

        if relationship.uselist:
            if not isinstance(value, list):
                raise CliError(
                    f"Relationship '{relationship_name}' expects a list"
                )

            setattr(
                instance,
                relationship_name,
                [
                    build_instance(related_cls, item)
                    for item in value
                ],
            )
        else:
            if value is not None and not isinstance(value, dict):
                raise CliError(
                    f"Relationship '{relationship_name}' expects an object"
                )

            setattr(
                instance,
                relationship_name,
                build_instance(related_cls, value) if value is not None else None,
            )

    await session.commit()
    await session.refresh(instance)

    return serialize_instance(instance)


async def op_delete(session, model_cls: type, payload: JsonDict) -> JsonDict:
    primary_key_value = get_primary_key_value(model_cls, payload)

    instance = await session.get(model_cls, primary_key_value)

    if instance is None:
        return {
            "ok": False,
            "error": "not_found",
            "entity": model_cls.__name__,
            "id": primary_key_value,
        }

    await session.delete(instance)
    await session.commit()

    return {
        "ok": True,
        "deleted": {
            "entity": model_cls.__name__,
            "id": primary_key_value,
        },
    }


async def run_async(args: argparse.Namespace) -> typing.Any:
    model_cls = resolve_entity(args.entity)
    payload = parse_payload(args.payload)

    session_maker = await startEngine(
        ComposeConnectionString(),
        makeDrop=args.drop,
        makeUp=not args.no_makeup,
    )

    if session_maker is None:
        raise CliError("Unable to create async session maker")

    async with session_maker() as session:
        operation = args.operation.lower()

        if operation in {"create", "c"}:
            return await op_create(session, model_cls, payload)

        if operation in {"get", "read", "r", "single"}:
            return await op_get(session, model_cls, payload)

        if operation in {"list", "multi", "rmulti", "page"}:
            return await op_list(session, model_cls, payload)

        if operation in {"update", "u"}:
            return await op_update(session, model_cls, payload)

        if operation in {"delete", "d", "remove"}:
            return await op_delete(session, model_cls, payload)

        raise CliError(
            f"Unknown operation '{args.operation}'. "
            "Use create, get, list, update or delete."
        )


def create_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="DB seed/testing CLI over SQLAlchemy mapped entities"
    )

    parser.add_argument(
        "entity",
        help=(
            "Entity name, table name, or model class name. "
            "Examples: Event, EventModel, events"
        ),
    )

    parser.add_argument(
        "operation",
        help="Operation: create, get, list, update, delete",
    )

    parser.add_argument(
        "payload",
        nargs="?",
        default="{}",
        help=(
            "JSON payload or @path/to/file.json. "
            "For create/update it contains fields; for get/delete it contains id."
        ),
    )

    parser.add_argument(
        "--drop",
        action="store_true",
        help="Drop all tables before running the operation",
    )

    parser.add_argument(
        "--no-makeup",
        action="store_true",
        help="Do not call BaseModel.metadata.create_all",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = create_arg_parser()
    args = parser.parse_args(argv)

    try:
        result = asyncio.run(run_async(args))
        print_json(result)
        return 0

    except CliError as e:
        print_json(
            {
                "ok": False,
                "error": str(e),
            }
        )
        return 2

    except sqlalchemy.exc.SQLAlchemyError as e:
        print_json(
            {
                "ok": False,
                "error": "sqlalchemy_error",
                "msg": str(e),
                "code": getattr(e, "code", "unknown"),
            }
        )
        return 3

    except Exception as e:
        print_json(
            {
                "ok": False,
                "error": "unexpected_error",
                "exception_type": type(e).__name__,
                "msg": str(e),
            }
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())