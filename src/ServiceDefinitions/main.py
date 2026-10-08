"""
Testovací / seedovací CLI nástroj nad service vrstvou.

Použití z rootu projektu:

    python -m src.ServiceDefinitions.main Event create @event_create.json

    python -m src.ServiceDefinitions.main Event get '{"id": "..."}'

    python -m src.ServiceDefinitions.main Event list @event_filter.json

    python -m src.ServiceDefinitions.main Event update @event_update.json

    python -m src.ServiceDefinitions.main Event delete '{"id": "..."}'

Payload lze načíst i ze souboru:

    python -m src.ServiceDefinitions.main Event create @payload.json

Tento nástroj je určen pro testování service vrstvy.
Není to aplikační API.
"""

from __future__ import annotations

import traceback
import argparse
import asyncio
import datetime
import decimal
import inspect as pyinspect
import json
import typing
import uuid

import sqlalchemy
from sqlalchemy import inspect
from sqlalchemy.orm.properties import ColumnProperty, RelationshipProperty

from src.DBDefinitions import ComposeConnectionString, startEngine
from src.Dataloaders import LoaderMap
from src.ServiceDefinitions.BaseService import (
    BaseService,
    ServiceExceptionWithCode,
    filter_kwargs_for_callable,
    maybe_await,
)
from src.ServiceDefinitions.ServiceContext import ServiceContext, SERVICES


JsonDict = dict[str, typing.Any]


class CliError(Exception):
    pass


def parse_payload(raw: str | None) -> JsonDict:
    if raw is None:
        return {}

    if raw.startswith("@"):
        path = raw[1:]
        with open(path, "r", encoding="utf-8") as f:
            result = json.load(f)
    else:
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


def iter_service_classes() -> typing.Iterator[tuple[str, type[BaseService]]]:
    """
    Vrátí service třídy registrované v ServiceRegistry.

    Zdrojem pravdy je ServiceContext.SERVICES, nikoliv DB registry.
    Tím se testovací CLI chová stejně jako resolver vrstva:

        info.ServiceCtx.Services.EventService
    """
    for name in dir(SERVICES):
        if name.startswith("_"):
            continue

        if not name.endswith("Service"):
            continue

        value = getattr(SERVICES, name)

        if pyinspect.isclass(value) and issubclass(value, BaseService):
            yield name, value


def build_service_index() -> dict[str, type[BaseService]]:
    """
    Vytvoří index service tříd bez ručního výčtu.

    Podporované aliasy:

      EventService
      Event
      eventservice
      event

      EventInvitationService
      EventInvitation
      eventinvitationservice
      eventinvitation
    """
    result: dict[str, type[BaseService]] = {}

    for service_name, service_cls in iter_service_classes():
        aliases = {
            service_name,
        }

        if service_name.endswith("Service"):
            aliases.add(service_name[: -len("Service")])

        for alias in aliases:
            result[alias] = service_cls
            result[normalize_name(alias)] = service_cls

    return result


def resolve_service(service_name: str) -> type[BaseService]:
    service_index = build_service_index()

    result = service_index.get(service_name)
    if result is not None:
        return result

    result = service_index.get(normalize_name(service_name))
    if result is not None:
        return result

    available = sorted(
        {
            name
            for name, _service_cls in iter_service_classes()
        }
    )

    raise CliError(
        f"Unknown service/entity '{service_name}'. "
        f"Available services: {', '.join(available)}"
    )


async def get_service_model(ctx: ServiceContext, service_cls: type[BaseService]) -> type:
    """
    Získá DB model nepřímo přes service -> loader.

    Service CLI nesahá do DB registry podle názvu entity.
    Model se odvozuje ze service kontraktu:

        service.getLoader(ctx).getModel()
    """
    loader = await service_cls.getLoader(ctx)
    return loader.getModel()


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

    ignored_keys = {
        "include",
        "where",
        "limit",
        "offset",
        "skip",
        "orderby",
        "order_by",
        "desc",
        "extendedfilter",
        "user",
        "kwargs",
        "entity",
    }

    for key, value in payload.items():
        if key in ignored_keys:
            continue

        if key in column_names:
            column_values[key] = value
        elif key in relationships:
            relationship_values[key] = value
        else:
            raise CliError(
                f"Unknown attribute '{key}' for model {model_cls.__name__}"
            )

    return column_values, relationship_values


def build_instance(model_cls: type, payload: JsonDict) -> typing.Any:
    """
    Vytvoří instanci modelu z payloadu.

    Umí i vnořené relationship, pokud jsou deklarované v SQLAlchemy modelu.

    Příklad:

        {
          "name": "Workshop",
          "user_invitations": [
            {
              "user_id": "...",
              "state_id": "..."
            }
          ]
        }
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

            setattr(
                instance,
                relationship_name,
                [
                    build_instance(related_cls, item)
                    for item in value
                ],
            )

        else:
            if value is None:
                setattr(instance, relationship_name, None)
                continue

            if not isinstance(value, dict):
                raise CliError(
                    f"Relationship '{relationship_name}' expects an object"
                )

            setattr(
                instance,
                relationship_name,
                build_instance(related_cls, value),
            )

    return instance


def serialize_instance(
    instance: typing.Any,
    *,
    include: set[str] | None = None,
    visited: set[int] | None = None,
) -> JsonDict | list[JsonDict] | None:
    if instance is None:
        return None

    if isinstance(instance, list):
        return [
            serialize_instance(
                item,
                include=include,
                visited=visited,
            )
            for item in instance
        ]

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
                f"for model {instance.__class__.__name__}"
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
            f"Model {model_cls.__name__} must have exactly one primary key"
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


def parse_user(raw_user: str | None, payload: JsonDict) -> typing.Any:
    """
    Uživatele lze předat buď přes --user, nebo jako payload["user"].

    Příklad:

        --user '{"id": "11111111-1111-1111-1111-111111111111"}'

    nebo:

        {
          "user": {
            "id": "11111111-1111-1111-1111-111111111111"
          },
          ...
        }
    """
    if raw_user is not None:
        return parse_payload(raw_user)

    return payload.get("user", None)


async def op_create(
    ctx: ServiceContext,
    service_cls: type[BaseService],
    payload: JsonDict,
) -> JsonDict:
    model_cls = await get_service_model(ctx, service_cls)
    entity_payload = payload.get("entity", payload)

    if not isinstance(entity_payload, dict):
        raise CliError("'entity' must be an object")

    entity = build_instance(model_cls, entity_payload)

    result = await service_cls.Create(
        ctx=ctx,
        entity=entity,
    )

    return serialize_instance(result)


async def op_get(
    ctx: ServiceContext,
    service_cls: type[BaseService],
    payload: JsonDict,
) -> JsonDict:
    model_cls = await get_service_model(ctx, service_cls)
    primary_key_value = get_primary_key_value(model_cls, payload)
    include = parse_include(payload)

    result = await service_cls.ReadById(
        ctx=ctx,
        id=primary_key_value,
    )

    if result is None:
        return {
            "ok": False,
            "error": "not_found",
            "service": service_cls.__name__,
            "id": primary_key_value,
        }

    return serialize_instance(
        result,
        include=include,
    )


async def op_list(
    ctx: ServiceContext,
    service_cls: type[BaseService],
    payload: JsonDict,
) -> list[JsonDict]:
    where = payload.get("where", None)
    include = parse_include(payload)

    skip = int(payload.get("skip", payload.get("offset", 0)))
    limit = int(payload.get("limit", 100))

    orderby = payload.get("orderby", payload.get("order_by", None))
    desc = payload.get("desc", None)
    extendedfilter = payload.get("extendedfilter", None)

    if where is not None and not isinstance(where, dict):
        raise CliError("'where' must be an object compatible with prepareSelect")

    if extendedfilter is not None and not isinstance(extendedfilter, dict):
        raise CliError("'extendedfilter' must be an object")

    result = await service_cls.ReadPage(
        ctx=ctx,
        skip=skip,
        limit=limit,
        where=where,
        orderby=orderby,
        desc=desc,
        extendedfilter=extendedfilter,
    )

    return [
        serialize_instance(
            item,
            include=include,
        )
        for item in result
    ]


async def op_update(
    ctx: ServiceContext,
    service_cls: type[BaseService],
    payload: JsonDict,
) -> JsonDict:
    model_cls = await get_service_model(ctx, service_cls)
    entity_payload = payload.get("entity", payload)

    if not isinstance(entity_payload, dict):
        raise CliError("'entity' must be an object")

    get_primary_key_value(model_cls, entity_payload)

    entity = build_instance(model_cls, entity_payload)

    result = await service_cls.Update(
        ctx=ctx,
        entity=entity,
    )

    return serialize_instance(result)


async def op_delete(
    ctx: ServiceContext,
    service_cls: type[BaseService],
    payload: JsonDict,
) -> JsonDict:
    model_cls = await get_service_model(ctx, service_cls)
    entity_payload = payload.get("entity", payload)

    if not isinstance(entity_payload, dict):
        raise CliError("'entity' must be an object")

    get_primary_key_value(model_cls, entity_payload)

    entity = build_instance(model_cls, entity_payload)

    result = await service_cls.Delete(
        ctx=ctx,
        entity=entity,
    )

    return {
        "ok": True,
        "deleted": serialize_instance(result)
        if result is not None
        else {
            "service": service_cls.__name__,
            "id": getattr(entity, "id", None),
        },
    }


async def op_call_service_method(
    ctx: ServiceContext,
    service_cls: type[BaseService],
    operation: str,
    payload: JsonDict,
) -> typing.Any:
    """
    Volitelná možnost pro testování doménových service metod.

    Příklad:

        python -m src.ServiceDefinitions.main EventInvitation AcceptOrDeclineByInvitedUser @accept.json

    accept.json:

        {
          "user": {
            "id": "..."
          },
          "entity": {
            "id": "...",
            "state_id": "7d2ef223-b60e-4e6d-b7d5-5fdc1f8e2ec2"
          }
        }

    Metoda se volá přes introspekci signatury.
    Pokud metoda přijímá parametr `entity`, vytvoří se model instance z payload["entity"].
    """
    if operation.startswith("_"):
        raise CliError("Private service methods cannot be called from CLI")

    method = getattr(service_cls, operation, None)

    if method is None or not callable(method):
        raise CliError(
            f"Service {service_cls.__name__} has no callable method '{operation}'"
        )

    model_cls = await get_service_model(ctx, service_cls)

    kwargs: JsonDict = {
        "ctx": ctx,
    }

    explicit_kwargs = payload.get("kwargs", {})
    if explicit_kwargs is not None and not isinstance(explicit_kwargs, dict):
        raise CliError("'kwargs' must be an object")

    kwargs.update(explicit_kwargs or {})

    signature = pyinspect.signature(method)

    if "entity" in signature.parameters:
        entity_payload = payload.get("entity", payload)

        if not isinstance(entity_payload, dict):
            raise CliError("'entity' must be an object")

        kwargs["entity"] = build_instance(model_cls, entity_payload)

    # běžné id parametry pro doménové metody
    for name in signature.parameters:
        if name in {"cls", "ctx", "entity"}:
            continue

        if name in payload and name not in kwargs:
            kwargs[name] = payload[name]

    safe_kwargs = filter_kwargs_for_callable(method, kwargs)
    result = method(**safe_kwargs)
    result = await maybe_await(result)

    return serialize_instance(result)


async def run_async(args: argparse.Namespace) -> typing.Any:
    service_cls = resolve_service(args.service)
    payload = parse_payload(args.payload)

    session_maker = await startEngine(
        ComposeConnectionString(),
        makeDrop=args.drop,
        makeUp=not args.no_makeup,
    )

    if session_maker is None:
        raise CliError("Unable to create async session maker")

    async with session_maker() as session:
        loaders = LoaderMap(session)

        ctx = ServiceContext(
            loaders=loaders,
            user=parse_user(args.user, payload),
            request=None,
        )

        operation = args.operation.lower()

        if operation in {"create", "c"}:
            return await op_create(ctx, service_cls, payload)

        if operation in {"get", "read", "r", "single"}:
            return await op_get(ctx, service_cls, payload)

        if operation in {"list", "multi", "rmulti", "page"}:
            return await op_list(ctx, service_cls, payload)

        if operation in {"update", "u"}:
            return await op_update(ctx, service_cls, payload)

        if operation in {"delete", "d", "remove"}:
            return await op_delete(ctx, service_cls, payload)

        return await op_call_service_method(
            ctx=ctx,
            service_cls=service_cls,
            operation=args.operation,
            payload=payload,
        )


def create_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Service layer seed/testing CLI"
    )

    parser.add_argument(
        "service",
        help=(
            "Service/entity name. "
            "Examples: Event, EventService, EventInvitation, EventInvitationService"
        ),
    )

    parser.add_argument(
        "operation",
        help=(
            "Operation: create, get, list, update, delete, "
            "or a public service method name"
        ),
    )

    parser.add_argument(
        "payload",
        nargs="?",
        default="{}",
        help=(
            "JSON payload or @path/to/file.json. "
            "For create/update/delete it contains entity fields. "
            "For custom service methods it may contain entity, kwargs and user."
        ),
    )

    parser.add_argument(
        "--user",
        default=None,
        help="JSON user object or @user.json. Overrides payload['user'].",
    )

    parser.add_argument(
        "--drop",
        action="store_true",
        help="Drop all tables before running the operation",
    )

    parser.add_argument(
        "--no-makeup",
        action="store_true",
        help="Do not call BaseDBModel.metadata.create_all",
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
        tb = traceback.extract_tb(e.__traceback__)

        origin = tb[-1] if tb else None

        print_json(
            {
                "ok": False,
                "error": "unexpected_error",
                "exception_type": type(e).__name__,
                "msg": str(e),

                "origin": {
                    "filename": origin.filename,
                    "lineno": origin.lineno,
                    "name": origin.name,
                    "line": origin.line,
                } if origin is not None else None,

                "traceback": [
                    {
                        "filename": frame.filename,
                        "lineno": frame.lineno,
                        "name": frame.name,
                        "line": frame.line,
                    }
                    for frame in tb
                ],
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

    except ServiceExceptionWithCode as e:
        print_json(
            {
                "ok": False,
                "error": "service_error",
                "msg": str(e),
                "code": e.code,
                "location": e.location,
            }
        )
        return 4

    except Exception as e:
        tb = traceback.extract_tb(e.__traceback__)

        origin = tb[-1] if tb else None

        print_json(
            {
                "ok": False,
                "error": "unexpected_error",
                "exception_type": type(e).__name__,
                "msg": str(e),

                "origin": {
                    "filename": origin.filename,
                    "lineno": origin.lineno,
                    "name": origin.name,
                    "line": origin.line,
                } if origin is not None else None,

                "traceback": [
                    {
                        "filename": frame.filename,
                        "lineno": frame.lineno,
                        "name": frame.name,
                        "line": frame.line,
                    }
                    for frame in tb
                ],
            }
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())