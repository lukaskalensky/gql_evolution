# AGENTS.md

## Purpose of this file

This file is an operational knowledge base for the **Coder agent** working on this repository.

Its purpose is not merely to describe the codebase. It must enable the agent to correctly transform a user's implementation request into a complete, repository-consistent change.

The agent is expected to:

1. understand the user's requested capability,
2. inspect the existing implementation patterns,
3. determine which architecture layers are affected,
4. implement all required pieces,
5. integrate them into the running application and GraphQL schema,
6. preserve repository conventions and security rules,
7. add or update tests,
8. run relevant checks,
9. report what was changed and any assumptions or unresolved domain decisions.

A request such as:

> "Add a new entity X with CRUD"

must **not** be interpreted as:

> "Create one Strawberry class."

It normally means implementing the complete vertical slice required by this architecture.

---

# 0. Coder agent operating contract

## 0.1 The user's requested capability is the source of truth

Always begin from the behavior requested by the user.

Translate the request into concrete repository changes.

Do not mechanically create every possible artifact. Create every artifact that is necessary for the requested behavior to work in this repository.

Examples:

### User asks for a new persistent GraphQL entity with CRUD

Expected impact normally includes:

```text
DBDefinitions
    -> Dataloaders
    -> ServiceDefinitions
    -> GraphTypeDefinitions
    -> domain Query/Mutation composition
    -> root schema reachability
    -> tests
```

### User asks only for a new read-only field on an existing GQL type

Expected impact may be only:

```text
GraphTypeDefinitions
    -> resolver / relationship
    -> tests
```

unless the new field requires service or persistence changes.

### User asks for a business operation

Expected impact normally includes:

```text
ServiceDefinitions
    -> GraphQL mutation/query orchestration
    -> permissions/RBAC
    -> tests
```

Do not force business logic into a generic CRUD method if the operation has domain semantics.

### User asks for a new database attribute

Expected impact normally includes:

```text
DB model
    -> loader/service compatibility
    -> GraphQL input/output exposure if requested
    -> tests
```

If schema migration infrastructure exists, use it. If this repository relies on `metadata.create_all()` and no migration framework is present, do not invent an Alembic workflow without a user request or repository precedent.

---

## 0.2 Inspect before editing

Before implementing a feature, inspect:

1. the closest existing entity in the same domain,
2. the equivalent entity in another domain if useful,
3. the relevant base classes and helpers,
4. domain `__init__.py` composition,
5. loader registration,
6. service registration,
7. schema composition,
8. existing tests for the same kind of behavior.

Prefer an existing repository pattern over a newly invented abstraction.

Important reference areas include:

```text
src/DBDefinitions/
src/Dataloaders/
src/ServiceDefinitions/
src/GraphTypeDefinitions/
tests/db/
tests/services/
tests/graphql/
tests/support/
```

For this repository, particularly useful canonical examples are:

```text
src/DBDefinitions/Domain_Events/EventModel.py
src/DBDefinitions/Domain_Events/EventInvitationModel.py

src/Dataloaders/__init__.py

src/ServiceDefinitions/BaseService.py
src/ServiceDefinitions/Domain_Events/EventService.py
src/ServiceDefinitions/Domain_Events/EventInvitationService.py
src/ServiceDefinitions/ServiceContext.py

src/GraphTypeDefinitions/BaseGQLModel.py
src/GraphTypeDefinitions/Domain_Events/EventGQLModel.py
src/GraphTypeDefinitions/Domain_Events/EventInvitationGQLModel.py
src/GraphTypeDefinitions/Domain_Events/__init__.py
src/GraphTypeDefinitions/query.py
src/GraphTypeDefinitions/mutation.py
src/GraphTypeDefinitions/schema_factory.py

tests/db/
tests/services/
tests/graphql/
```

---

## 0.3 Determine the required vertical slice

Use this decision table.

| Requested capability | DB model | Loader | Service | GQL type | Query | Mutation | Schema/domain composition | Tests |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| New persistent entity with full CRUD | yes | yes | yes | yes | yes | yes | yes | yes |
| New persistent entity, read-only | yes | yes | usually yes | yes | yes | no | yes | yes |
| New field stored in DB | yes | existing loader usually sufficient | possibly | yes if exposed | maybe | maybe | usually no root change | yes |
| New relationship | maybe | existing/new related loader | maybe | yes | via field resolver | no unless requested | normally no | yes |
| New business command | maybe | maybe | yes | input/output types as needed | maybe | yes | yes if new interface/domain | yes |
| External federation reference | no local table | usually no local loader | maybe remote/client support | `extend=True` type | relationship/reference use | usually no CRUD | `types=[...]` when required | yes |
| New domain containing entities | yes as needed | yes as needed | yes as needed | yes | domain interface | domain interface | root Query/Mutation composition | yes |

This table is guidance, not a substitute for understanding the user's requirement.

---

## 0.4 Do not stop at the first compilable change

A task is not complete merely because:

- a Python file parses,
- a class exists,
- a resolver exists,
- a unit test for one method passes.

A feature is complete only when the requested capability is reachable through the intended architecture boundary.

For a GraphQL capability this normally means:

```text
model/service/resolver implementation
    +
domain registration
    +
root schema reachability
    +
schema construction succeeds
    +
requested operation can be exercised
    +
relevant tests pass
```

---

## 0.5 Respect existing architecture boundaries

The intended dependency direction is:

```text
DBDefinitions
    ↓
Dataloaders
    ↓
ServiceDefinitions
    ↓
GraphTypeDefinitions
    ↓
Schema / API
```

The GraphQL layer should orchestrate API behavior, not become the business or persistence layer.

Do not:

- write direct SQLAlchemy queries in ordinary GraphQL CRUD resolvers,
- duplicate `BaseService` CRUD logic,
- create an ad-hoc loader when `LoaderMap` should provide it,
- instantiate services manually when `ServiceRegistry` provides them,
- bypass `lastchange` optimistic concurrency,
- silently remove RBAC/permission extensions,
- add a local type to federation `types=[...]` merely to make schema discovery work,
- modify unrelated files just because they are nearby.

---

## 0.6 Preserve user intent when details are underspecified

When the requested behavior is clear but implementation details are not explicitly stated:

1. infer them from the nearest existing repository pattern,
2. use the least surprising domain-consistent choice,
3. avoid inventing new roles, ownership rules, table semantics, or external contracts,
4. keep assumptions minimal and visible.

Examples:

- If an existing domain uses `<parent>_id` to derive RBAC for child creation, follow that pattern when the new entity clearly has the same ownership semantics.
- If the correct authorization role cannot be inferred from repository precedent, do not fabricate a role name. Preserve a clearly marked placeholder or report the unresolved domain decision.
- If the user asked for CRUD, implement CRUD unless repository constraints make an operation intentionally unsupported.

Do not ask the user to repeat information already available in the repository or the task.

---

## 0.7 Make the smallest complete change

Prefer the smallest set of changes that fully satisfies the user's requested behavior.

Avoid speculative refactoring.

Do not rewrite base classes merely because a new entity can be implemented with the existing abstractions.

Refactor shared infrastructure only when:

- the user explicitly requests it,
- the current architecture cannot support the requested capability correctly,
- or multiple concrete implementations would otherwise duplicate substantial logic.

---

## 0.8 Verification is part of implementation

After changes, verify at the narrowest useful levels first:

```text
syntax/imports
-> DB/service unit tests
-> GraphQL unit tests
-> schema construction
-> explicit GraphQL operation tests
-> broader relevant test suite
```

If a test fails because of the change, fix the implementation rather than weakening the test unless the user explicitly requested changed behavior.

Do not delete or skip security/concurrency tests merely to get a green suite.

---

# 1. Repository architecture

This repository implements a Strawberry GraphQL federation subgraph with the following main vertical architecture:

```text
DBDefinitions
    ↓
Dataloaders
    ↓
ServiceDefinitions
    ↓
GraphTypeDefinitions
    ↓
Domain Query / Mutation composition
    ↓
Root Query / Mutation
    ↓
Federation Schema
```

Supporting runtime concerns include:

```text
DBDefinitions/runtime.py
DBDefinitions/seed.py
GraphTypeDefinitions/GraphQLContext.py
GraphTypeDefinitions/SessionCommitExtension.py
GraphTypeDefinitions/schema_factory.py
```

The Coder agent must understand both the vertical feature path and these runtime integration points.


# 2. Translating a user request into architecture changes

Before writing code, produce an internal implementation map.

For each requested capability, determine:

```text
Persistence?
Dataloader?
Service?
GraphQL output type?
GraphQL input types?
Query?
Mutation?
Relationship resolver?
RBAC / ownership?
Federation reference?
Domain composition?
Root schema composition?
Seed/demo data?
Runtime/config?
Tests?
```

Then inspect the repository for each applicable integration point.

For a standard new persistent entity `<Entity>`, the expected implementation map is usually:

```text
src/DBDefinitions/Domain_<Domain>/<Entity>Model.py
src/DBDefinitions/Domain_<Domain>/__init__.py
src/DBDefinitions/__init__.py

src/Dataloaders/__init__.py

src/ServiceDefinitions/Domain_<Domain>/<Entity>Service.py
src/ServiceDefinitions/Domain_<Domain>/__init__.py
src/ServiceDefinitions/ServiceContext.py

src/GraphTypeDefinitions/Domain_<Domain>/<Entity>GQLModel.py
src/GraphTypeDefinitions/Domain_<Domain>/__init__.py

src/GraphTypeDefinitions/query.py          # only if a new domain must be composed
src/GraphTypeDefinitions/mutation.py       # only if a new domain must be composed
src/GraphTypeDefinitions/schema_factory.py # only when schema-level registration is actually required

tests/db/...
tests/services/...
tests/graphql/...
```

Potentially also:

```text
src/DBDefinitions/seed.py
```

when the entity is a type/catalog model that must exist at runtime or the user explicitly requests demo/seed data.

Do not edit `runtime.py`, context code, or schema extensions for an ordinary entity unless the requested capability requires infrastructure behavior that those files control.

---

# 3. DB model integration

The GraphQL layer expects every locally stored entity to be available through a dataloader.

A local model should normally inherit from `BaseDBModel`.

Example conceptual structure:

```python
class ExampleModel(BaseDBModel):
    __tablename__ = "examples"

    name: Mapped[str] = mapped_column(default=None, nullable=True)
    parent_id: Mapped[IDType] = mapped_column(
        ForeignKey("parents.id"),
        nullable=True,
        default=None,
        index=True,
    )
```

Export the model from its domain package, for example:

```python
# src/DBDefinitions/Domain_X/__init__.py
from .ExampleModel import ExampleModel

__all__ = ["ExampleModel"]
```

Then export it from:

```python
src/DBDefinitions/__init__.py
```

The model must be importable as:

```python
from src.DBDefinitions import ExampleModel
```

---

# 4. Register the dataloader

Edit:

```text
src/Dataloaders/__init__.py
```

Import the DB model:

```python
from src.DBDefinitions import ExampleModel
```

Add a typed loader attribute:

```python
class LoaderMap(LoaderMapBase[BaseDBModel]):
    ExampleModel: IDLoader[src.DBDefinitions.ExampleModel] = None
```

Initialize it in `LoaderMap.__init__`:

```python
self.ExampleModel = self.get(ExampleModel)
```

The loader attribute name is important because the GraphQL type references it through `LoaderName`.

The following values must match exactly:

```python
ExampleGQLModel.LoaderName == "ExampleModel"
ctx.loaders.ExampleModel
```

Do not instantiate ad-hoc loaders in GraphQL resolvers.

---

# 5. Add the service

Create a service such as:

```text
src/ServiceDefinitions/Domain_X/ExampleService.py
```

For ordinary CRUD, inherit from `BaseService`.

Minimal pattern:

```python
from uoishelpers.dataloaders.IDLoader import IDLoader

from src.DBDefinitions import ExampleModel
from src.ServiceDefinitions.BaseService import BaseService
from src.ServiceDefinitions.ServiceContext import ServiceContext


class ExampleService(BaseService[IDLoader[ExampleModel]]):

    @classmethod
    async def getLoader(cls, ctx: ServiceContext) -> IDLoader[ExampleModel]:
        return ctx.loaders.ExampleModel
```

`BaseService` already provides the standard operations:

```python
Create(...)
ReadById(...)
ReadPage(...)
Update(...)
Delete(...)
ExecuteServiceMethod(...)
CreateErrorCallback(...)
```

Put business rules into the service, not into GraphQL resolver bodies.

Examples of business-specific service methods in the repository are:

```python
EventService.EnsureInvitations(...)
EventInvitationService.AcceptOrDeclineByInvitedUser(...)
EventInvitationService.UpdateByOrganizer(...)
EventInvitationService.DeleteByOrganizer(...)
```

---

# 6. Register the service

Edit:

```text
src/ServiceDefinitions/ServiceContext.py
```

Add a `TYPE_CHECKING` import:

```python
if typing.TYPE_CHECKING:
    from src.ServiceDefinitions.Domain_X.ExampleService import ExampleService as _ExampleService
```

Add a property to `ServiceRegistry`:

```python
@property
def ExampleService(self) -> type["_ExampleService"]:
    from src.ServiceDefinitions.Domain_X.ExampleService import ExampleService
    return ExampleService
```

Resolvers must obtain services through:

```python
service = info.ServiceCtx.Services.ExampleService
```

Do not instantiate service classes manually.

---

# 7. Create the GraphQL model file

Create:

```text
src/GraphTypeDefinitions/Domain_X/ExampleGQLModel.py
```

For a locally owned federated entity use:

```python
@strawberry.federation.type(
    description="Entity representing an Example",
    keys=["id"],
)
class ExampleGQLModel(BaseGQLModel):
    LoaderName = "ExampleModel"
```

Always inherit local persistent entities from:

```python
BaseGQLModel
```

`BaseGQLModel` already supplies:

```text
id
lastchange
created
createdby_id
changedby_id
rbacobject_id
getLoader(...)
from_dataclass(...)
from_db(...)
load_with_loader(...)
resolve_reference(...)
get_db_value(...)
```

Do not duplicate these fields unless there is a concrete reason.

---

# 8. Declare scalar fields

Use explicit Strawberry fields with descriptions and permissions.

Pattern:

```python
name: typing.Optional[str] = strawberry.field(
    default=None,
    description="Example name",
    permission_classes=[OnlyForAuthentized],
)
```

The default resolver in this project can resolve values from the attached DB object stored in `_dbdata`, so a GraphQL object created by:

```python
ExampleGQLModel.from_dataclass(db_row)
```

does not need every scalar copied manually.

Use repository naming conventions:

```text
Python:       parent_id
GraphQL SDL:  parentId
```

Do not manually convert field names to camelCase unless there is a special API requirement. Strawberry performs the normal field-name conversion.

---

# 9. Relationships and foreign keys

Expose the FK scalar when it is part of the API:

```python
parent_id: typing.Optional[IDType] = strawberry.field(...)
```

For a many-to-one relationship use `ScalarResolver`:

```python
parent: typing.Optional[ParentGQLModel] = strawberry.field(
    description="Parent entity",
    permission_classes=[OnlyForAuthentized],
    resolver=ScalarResolver[ParentGQLModel](
        fkey_field_name="parent_id"
    ),
)
```

For a one-to-many relationship use `VectorResolver`:

```python
children: typing.List[ChildGQLModel] = strawberry.field(
    description="Children",
    permission_classes=[OnlyForAuthentized],
    resolver=VectorResolver[ChildGQLModel](
        fkey_field_name="parent_id",
        whereType=ChildInputFilter,
    ),
)
```

Use lazy Strawberry references to break circular imports.

Same package:

```python
ChildGQLModel = typing.Annotated[
    "ChildGQLModel",
    strawberry.lazy(".ChildGQLModel"),
]
```

Different package:

```python
UserGQLModel = typing.Annotated[
    "UserGQLModel",
    strawberry.lazy(
        "src.GraphTypeDefinitions.Domain_UG.UserGQLModel"
    ),
]
```

Prefer resolvers/dataloaders over direct SQLAlchemy relationship traversal inside GraphQL fields.

---

# 10. Filter input for page queries

The repository uses `createInputs2` for generated filtering inputs.

Pattern:

```python
@createInputs2
class ExampleInputFilter:
    id: IDType
    name: str
    parent_id: IDType
```

Include fields that should be filterable.

This type is then passed to `PageResolver`.

---

# 11. Add read/query endpoints

Define a Strawberry interface in the same GraphQL model file:

```python
@strawberry.interface(description="Example queries")
class ExampleQuery:

    example_by_id: typing.Optional[ExampleGQLModel] = strawberry.field(
        description="Get an example by id",
        permission_classes=[OnlyForAuthentized],
        resolver=ExampleGQLModel.load_with_loader,
    )

    example_page: typing.List[ExampleGQLModel] = strawberry.field(
        description="Get a page of examples",
        permission_classes=[OnlyForAuthentized],
        resolver=PageResolver[ExampleGQLModel](
            whereType=ExampleInputFilter
        ),
    )
```

The public GraphQL names become approximately:

```graphql
exampleById
examplePage
```

Do not implement manual DB queries for standard `by_id` or `page` operations when the existing loader resolvers are sufficient.

---

# 12. Create mutation input models

## Insert

Use `InputModelMixin` for standard inserts:

```python
@strawberry.input(description="Input type for creating an Example")
class ExampleInsertGQLModel(InputModelMixin):
    getLoader = ExampleGQLModel.getLoader

    id: typing.Optional[IDType] = strawberry.field(
        description="Client generated id",
        default=None,
    )

    name: typing.Optional[str] = strawberry.field(
        description="Example name",
        default=None,
    )

    parent_id: typing.Optional[IDType] = strawberry.field(
        description="Parent id",
        default=None,
    )

    createdby_id: strawberry.Private[IDType] = None
    rbacobject_id: strawberry.Private[IDType] = None
```

`createdby_id` and `rbacobject_id` are internal values and should normally remain `strawberry.Private`.

## Update

Updates must include optimistic concurrency information:

```python
@strawberry.input(description="Input type for updating an Example")
class ExampleUpdateGQLModel:
    id: IDType = strawberry.field(description="Example id")
    lastchange: datetime.datetime = strawberry.field(
        description="Timestamp"
    )

    name: typing.Optional[str] = strawberry.field(
        description="Example name",
        default=strawberry.UNSET,
    )

    changedby_id: strawberry.Private[IDType] = None
```

IMPORTANT:

Use:

```python
default=strawberry.UNSET
```

for optional update fields when omission must mean "do not change this field".

Do not replace `UNSET` with `None`, because `None` can be a legitimate explicit value and would change update semantics.

## Delete

Deletes must also include `lastchange`:

```python
@strawberry.input(description="Input type for deleting an Example")
class ExampleDeleteGQLModel:
    id: IDType = strawberry.field(description="Example id")
    lastchange: datetime.datetime = strawberry.field(
        description="Last change"
    )
```

---

# 13. Implement CRUD mutations

Create a mutation interface:

```python
@strawberry.interface(description="Example mutations")
class ExampleMutation:
    ...
```

The standard resolver flow is:

```text
GraphQL mutation
-> permission/extensions
-> service from info.ServiceCtx.Services
-> BaseService / domain service
-> ExecuteServiceMethod
-> GraphQL model or typed error
```

Do not bypass this sequence.

---

## Insert mutation

Canonical shape:

```python
@strawberry.mutation(
    description="Insert an Example",
    permission_classes=[OnlyForAuthentized],
    extensions=[
        UserAccessControlExtension[
            InsertError,
            ExampleGQLModel
        ](roles=["appropriate role"]),

        UserRoleProviderExtension[
            InsertError,
            ExampleGQLModel
        ](),

        RbacProviderExtension[
            InsertError,
            ExampleGQLModel
        ](),

        LoadDataExtension[
            InsertError,
            ExampleGQLModel
        ](
            getLoader=ParentGQLModel.getLoader,
            primary_key_name="parent_id",
        ),
    ],
)
async def example_insert(
    self,
    info: ApplicationInfo,
    example: ExampleInsertGQLModel,
    db_row: typing.Any,
    rbacobject_id: IDType,
    user_roles: typing.List[dict],
) -> typing.Union[
    ExampleGQLModel,
    InsertError[ExampleGQLModel],
]:
    example.rbacobject_id = rbacobject_id

    service = info.ServiceCtx.Services.ExampleService

    return await service.ExecuteServiceMethod(
        service.Create(
            ctx=info.ServiceCtx,
            entity=example,
        ),
        Error=service.CreateErrorCallback(
            ErrorClass=InsertError[ExampleGQLModel],
            code="<stable-unique-error-code>",
            location="example_insert",
            _input=example,
        ),
        OK=ExampleGQLModel.from_dataclass,
    )
```

### Insert parent/RBAC rule

For child entities, the insert mutation usually derives access from the parent.

Use:

```python
LoadDataExtension(
    getLoader=ParentGQLModel.getLoader,
    primary_key_name="parent_id",
)
```

This mirrors patterns such as:

```text
Event -> masterevent_id
EventInvitation -> event_id
```

Then assign the provided:

```python
rbacobject_id
```

to the insert model before calling the service.

Choose the parent field based on the actual ownership/RBAC model. Do not copy `masterevent_id` blindly.

---

## Update mutation

Canonical shape:

```python
@strawberry.mutation(
    description="Update an Example",
    permission_classes=[OnlyForAuthentized],
    extensions=[
        UserAccessControlExtension[
            UpdateError,
            ExampleGQLModel
        ](roles=["appropriate role"]),

        UserRoleProviderExtension[
            UpdateError,
            ExampleGQLModel
        ](),

        RbacProviderExtension[
            UpdateError,
            ExampleGQLModel
        ](),

        LoadDataExtension[
            UpdateError,
            ExampleGQLModel
        ](),
    ],
)
async def example_update(
    self,
    info: ApplicationInfo,
    example: ExampleUpdateGQLModel,
    db_row: typing.Any,
    rbacobject_id: IDType,
    user_roles: typing.List[dict],
) -> typing.Union[
    ExampleGQLModel,
    UpdateError[ExampleGQLModel],
]:
    service = info.ServiceCtx.Services.ExampleService

    return await service.ExecuteServiceMethod(
        service.Update(
            ctx=info.ServiceCtx,
            entity=example,
        ),
        Error=service.CreateErrorCallback(
            ErrorClass=UpdateError[ExampleGQLModel],
            code="<stable-unique-error-code>",
            location="example_update",
            _input=example,
            _entity=ExampleGQLModel.from_dataclass(db_row),
        ),
        OK=ExampleGQLModel.from_dataclass,
    )
```

The `LoadDataExtension` supplies the current DB row and RBAC context.

Do not reload the row manually in the resolver unless the business use case requires it.

---

## Delete mutation

Canonical shape:

```python
@strawberry.mutation(
    description="Delete an Example",
    permission_classes=[OnlyForAuthentized],
    extensions=[
        UserAccessControlExtension[
            DeleteError,
            ExampleGQLModel
        ](roles=["appropriate role"]),

        UserRoleProviderExtension[
            DeleteError,
            ExampleGQLModel
        ](),

        RbacProviderExtension[
            DeleteError,
            ExampleGQLModel
        ](),

        LoadDataExtension[
            DeleteError,
            ExampleGQLModel
        ](),
    ],
)
async def example_delete(
    self,
    info: ApplicationInfo,
    example: ExampleDeleteGQLModel,
    db_row: typing.Any,
    rbacobject_id: IDType,
    user_roles: typing.List[dict],
) -> typing.Optional[
    DeleteError[ExampleGQLModel]
]:
    service = info.ServiceCtx.Services.ExampleService

    return await service.ExecuteServiceMethod(
        service.Delete(
            ctx=info.ServiceCtx,
            entity=example,
        ),
        Error=service.CreateErrorCallback(
            ErrorClass=DeleteError[ExampleGQLModel],
            code="<stable-unique-error-code>",
            location="example_delete",
            _input=example,
            _entity=ExampleGQLModel.from_dataclass(db_row),
        ),
        OK=lambda result: None,
    )
```

Successful delete returns `None`.

---

# 14. Authorization and extensions

Do not remove the security extensions merely to make a resolver simpler.

Common extensions in this project are:

```text
OnlyForAuthentized
UserAccessControlExtension
UserRoleProviderExtension
RbacProviderExtension
LoadDataExtension
```

Typical order for protected CRUD is:

```python
extensions=[
    UserAccessControlExtension(...),
    UserRoleProviderExtension(...),
    RbacProviderExtension(...),
    LoadDataExtension(...),
]
```

Some domain-specific mutations intentionally use only a subset. Preserve or adapt the authorization behavior based on the use case.

Never invent a role name when the required role is not known. Reuse an established domain role or explicitly mark the authorization decision as needing domain confirmation.

---

# 15. Error handling

CRUD mutations return typed errors from `uoishelpers.resolvers`:

```python
InsertError[ExampleGQLModel]
UpdateError[ExampleGQLModel]
DeleteError[ExampleGQLModel]
```

Always execute service operations through:

```python
service.ExecuteServiceMethod(...)
```

and construct failures with:

```python
service.CreateErrorCallback(...)
```

Use a stable unique error identifier for each resolver location.

Example:

```python
code="c2980f1a-eb73-4cd7-960b-94bf16dfa993"
location="example_insert"
```

For new code, generate a new UUID-like identifier unless the repository/task specifies another error-code convention.

Do not expose raw uncaught database exceptions directly as the resolver result.

---

# 16. Add the type to its GraphQL domain

Edit the domain package:

```text
src/GraphTypeDefinitions/Domain_X/__init__.py
```

Import the model and interfaces:

```python
from .ExampleGQLModel import (
    ExampleGQLModel,
    ExampleInputFilter,
    ExampleQuery,
    ExampleMutation,
)
```

Compose the domain root interfaces.

Example:

```python
@strawberry.interface(description="Domain X queries")
class Query_Domain_X(
    ExistingQuery,
    ExampleQuery,
):
    pass


@strawberry.interface(description="Domain X mutations")
class Mutation_Domain_X(
    ExistingMutation,
    ExampleMutation,
):
    pass
```

Update `__all__`.

This is the normal place where a locally owned GraphQL entity becomes part of the domain API.

---

# 17. Integrate the domain into root Query and Mutation

Current repository root pattern:

```python
# src/GraphTypeDefinitions/query.py

@strawberry.type(description="Root query")
class Query(Query_Domain_Events):
    pass
```

and:

```python
# src/GraphTypeDefinitions/mutation.py

@strawberry.type(description="Root mutation")
class Mutation(Mutation_Domain_Events):
    pass
```

If adding a new domain, compose it into these roots:

```python
class Query(
    Query_Domain_Events,
    Query_Domain_X,
):
    pass
```

```python
class Mutation(
    Mutation_Domain_Events,
    Mutation_Domain_X,
):
    pass
```

If adding a new entity to an existing domain, normally only update that domain's `__init__.py`; root `query.py` and `mutation.py` should not need an entity-specific import.

Avoid placing every entity directly into root `Query` or `Mutation`.

---

# 18. Schema integration rules

The schema is created in:

```text
src/GraphTypeDefinitions/schema_factory.py
```

through:

```python
strawberry.federation.Schema(
    query=Query,
    mutation=Mutation,
    ...
)
```

## Locally owned GraphQL entities

A normal local entity such as `EventGQLModel` becomes reachable through the query/mutation interfaces and relationships.

Do NOT automatically add every local entity to:

```python
types=[...]
```

just because it is new.

## External federation entities

External entities owned by another subgraph use a different pattern.

Example:

```python
@strawberry.federation.type(
    extend=True,
    keys=["id"],
)
class UserGQLModel:
    id: IDType = strawberry.federation.field(
        external=True
    )
```

External types such as `UserGQLModel` and `StateGQLModel` are explicitly supplied to the schema:

```python
types=[
    UserGQLModel,
    StateGQLModel,
]
```

Therefore:

- local owned entity -> normally integrate through Query/Mutation/domain relationships
- external federation stub -> use `extend=True`, `external=True`, and add to schema `types=[...]` when required

Do not mark a locally owned entity as `extend=True`.

---

# 19. Federation references

Locally owned entities use:

```python
@strawberry.federation.type(keys=["id"])
```

and inherit `resolve_reference` behavior from `BaseGQLModel`.

`BaseGQLModel.resolve_reference(...)` loads the entity by ID using its dataloader.

Therefore a new local entity must have a valid:

```python
LoaderName
```

and registered loader, otherwise federation entity resolution will fail.

---

# 20. Custom computed fields

Computed GraphQL fields may be implemented as methods.

Example pattern:

```python
@strawberry.field(
    description="Computed value",
    permission_classes=[OnlyForAuthentized],
)
def computed_value(self) -> typing.Optional[float]:
    ...
```

Prefer values available from:

```python
self._dbdata
```

or existing exposed fields.

Do not open database sessions from computed field resolvers.

If additional entities must be loaded, use dataloaders/resolvers.

---

# 21. Testing requirements

For every new CRUD GraphQL entity, add GraphQL-level tests.

Use the existing tests as patterns:

```text
tests/graphql/test_EventGQLModel.py
tests/graphql/test_event_gql_explicit.py
tests/graphql/test_event_gql_model_unit.py
tests/graphql/test_event_invitation_gql_model_unit.py
```

At minimum test:

1. page query
2. by-id query
3. insert
4. update
5. delete
6. error path for at least one mutation when practical
7. relationships/resolvers when the entity exposes them
8. federation/schema construction when relevant

Prefer testing through the public GraphQL schema for contract/integration behavior.

Example expected GraphQL API for `ExampleGQLModel`:

```graphql
query {
  examplePage(limit: 10) {
    id
    name
    lastchange
  }
}
```

```graphql
query ExampleById($id: UUID!) {
  exampleById(id: $id) {
    id
    name
    lastchange
  }
}
```

```graphql
mutation ExampleInsert($example: ExampleInsertGQLModel!) {
  exampleInsert(example: $example) {
    __typename

    ... on ExampleGQLModel {
      id
      name
      lastchange
    }

    ... on ExampleGQLModelInsertError {
      msg
      code
      location
    }
  }
}
```

Update must use the `lastchange` returned by insert/read.

Delete must use the latest `lastchange` returned by insert/update/read.

---

# 22. Implementation checklist for the coding agent

When asked to add a new GraphQL entity, perform the following checklist.

## Persistence

- [ ] Find or create `<Entity>Model`.
- [ ] Export it from its DB domain.
- [ ] Export it from `src/DBDefinitions/__init__.py`.
- [ ] Verify FK names and nullable semantics.

## Loader

- [ ] Import `<Entity>Model` in `src/Dataloaders/__init__.py`.
- [ ] Add `<Entity>Model: IDLoader[...]`.
- [ ] Initialize `self.<Entity>Model = self.get(<Entity>Model)`.

## Service

- [ ] Create `<Entity>Service(BaseService[...])`.
- [ ] Implement `getLoader`.
- [ ] Put domain-specific business rules here.
- [ ] Register service in `ServiceRegistry`.

## GraphQL type

- [ ] Create `<Entity>GQLModel.py`.
- [ ] Inherit from `BaseGQLModel`.
- [ ] Set `LoaderName = "<Entity>Model"`.
- [ ] Use `@strawberry.federation.type(keys=["id"])`.
- [ ] Define exposed scalar fields.
- [ ] Define lazy relationship types.
- [ ] Use `ScalarResolver` and `VectorResolver`.
- [ ] Define `<Entity>InputFilter`.

## Queries

- [ ] Add `<entity>_by_id` using `load_with_loader`.
- [ ] Add `<entity>_page` using `PageResolver`.

## Mutations

- [ ] Add insert input.
- [ ] Add update input with `lastchange`.
- [ ] Use `strawberry.UNSET` for optional update fields.
- [ ] Add delete input with `lastchange`.
- [ ] Add insert resolver.
- [ ] Add update resolver.
- [ ] Add delete resolver.
- [ ] Use appropriate permission/RBAC extensions.
- [ ] Route all mutations through the service layer.
- [ ] Return typed `InsertError`, `UpdateError`, `DeleteError`.

## Schema

- [ ] Export query/mutation interfaces from the domain `__init__.py`.
- [ ] Add interfaces to `Query_Domain_*` / `Mutation_Domain_*`.
- [ ] If this is a new domain, compose it into root `Query` and `Mutation`.
- [ ] Do not add an ordinary local entity to `schema_factory.types` without a reason.
- [ ] For external federation entities use `extend=True`, `external=True`, and register them in `types=[...]` as needed.

## Tests

- [ ] Schema builds successfully.
- [ ] page query works.
- [ ] by-id query works.
- [ ] insert works.
- [ ] update works with optimistic concurrency.
- [ ] delete works.
- [ ] authorization/error behavior is tested.
- [ ] relationships resolve without N+1-style direct resolver queries.

---

# 23. Coding constraints

Follow these constraints when modifying this repository:

1. Preserve the existing layered architecture.
2. Do not access SQLAlchemy sessions directly from ordinary GraphQL CRUD resolvers.
3. Do not duplicate generic CRUD logic already provided by `BaseService`, `BaseGQLModel`, `PageResolver`, `ScalarResolver`, or `VectorResolver`.
4. Do not silently remove RBAC/security extensions.
5. Do not replace `lastchange` concurrency checks with unconditional updates.
6. Do not use `None` where `strawberry.UNSET` is required for patch/update semantics.
7. Avoid circular imports by using `typing.Annotated` + `strawberry.lazy`.
8. Prefer one GraphQL model file containing the entity, its filter, query interface, mutation inputs, and mutation interface, matching the current repository convention.
9. Keep GraphQL field and operation naming consistent with existing snake_case Python names; Strawberry exposes camelCase GraphQL names.
10. Before inventing a new abstraction, check whether the same behavior already exists in `uoishelpers` or the repository base classes.
11. When adding business-specific mutation behavior, implement the rule in the service and keep the GraphQL mutation mainly as authorization + orchestration + error mapping.
12. Ensure that loader names, DB model names, service registry names, and GraphQL `LoaderName` stay consistent.

---

# 24. Preferred implementation strategy

When implementing a requested entity, use this order:

```text
1. Inspect similar existing entity
2. Confirm DB model and relations
3. Add/export DB model if necessary
4. Register dataloader
5. Implement/register service
6. Implement GQL model + filter
7. Implement Query interface
8. Implement Insert/Update/Delete input models
9. Implement mutation interface
10. Export through domain __init__.py
11. Integrate new domain into root Query/Mutation if needed
12. Register external federation types only when applicable
13. Build schema
14. Run/add unit tests
15. Run/add explicit GraphQL CRUD tests
```

Do not stop after creating the Strawberry type. A task to "add a GraphQL entity" is complete only when the entity is reachable through the schema and its requested CRUD operations are tested.

---

# 25. Reference skeleton

Use this only as a structural template; adapt fields, parent/RBAC rules, service methods, roles, descriptions, and error codes to the concrete entity.

```python
import datetime
import typing

import strawberry

from uoishelpers.gqlpermissions import OnlyForAuthentized
from uoishelpers.gqlpermissions.LoadDataExtension import LoadDataExtension
from uoishelpers.gqlpermissions.RbacProviderExtension import RbacProviderExtension
from uoishelpers.gqlpermissions.UserAccessControlExtension import UserAccessControlExtension
from uoishelpers.gqlpermissions.UserRoleProviderExtension import UserRoleProviderExtension
from uoishelpers.resolvers import (
    DeleteError,
    InsertError,
    InputModelMixin,
    PageResolver,
    UpdateError,
    createInputs2,
)

from src.GraphTypeDefinitions.ApplicationInfo import ApplicationInfo
from src.GraphTypeDefinitions.BaseGQLModel import BaseGQLModel, IDType


@createInputs2
class ExampleInputFilter:
    id: IDType
    name: str


@strawberry.federation.type(
    description="Entity representing an Example",
    keys=["id"],
)
class ExampleGQLModel(BaseGQLModel):
    LoaderName = "ExampleModel"

    name: typing.Optional[str] = strawberry.field(
        default=None,
        description="Example name",
        permission_classes=[OnlyForAuthentized],
    )


@strawberry.interface(description="Example queries")
class ExampleQuery:
    example_by_id: typing.Optional[ExampleGQLModel] = strawberry.field(
        description="Get an Example by id",
        permission_classes=[OnlyForAuthentized],
        resolver=ExampleGQLModel.load_with_loader,
    )

    example_page: typing.List[ExampleGQLModel] = strawberry.field(
        description="Get a page of Examples",
        permission_classes=[OnlyForAuthentized],
        resolver=PageResolver[ExampleGQLModel](
            whereType=ExampleInputFilter
        ),
    )


@strawberry.input(description="Input type for creating an Example")
class ExampleInsertGQLModel(InputModelMixin):
    getLoader = ExampleGQLModel.getLoader

    id: typing.Optional[IDType] = strawberry.field(
        description="Example id",
        default=None,
    )

    name: typing.Optional[str] = strawberry.field(
        description="Example name",
        default=None,
    )

    createdby_id: strawberry.Private[IDType] = None
    rbacobject_id: strawberry.Private[IDType] = None


@strawberry.input(description="Input type for updating an Example")
class ExampleUpdateGQLModel:
    id: IDType = strawberry.field(description="Example id")
    lastchange: datetime.datetime = strawberry.field(
        description="Timestamp"
    )

    name: typing.Optional[str] = strawberry.field(
        description="Example name",
        default=strawberry.UNSET,
    )

    changedby_id: strawberry.Private[IDType] = None


@strawberry.input(description="Input type for deleting an Example")
class ExampleDeleteGQLModel:
    id: IDType = strawberry.field(description="Example id")
    lastchange: datetime.datetime = strawberry.field(
        description="Last change"
    )


@strawberry.interface(description="Example mutations")
class ExampleMutation:

    @strawberry.mutation(
        description="Insert an Example",
        permission_classes=[OnlyForAuthentized],
        extensions=[
            UserAccessControlExtension[
                InsertError,
                ExampleGQLModel
            ](roles=["<role>"]),
            UserRoleProviderExtension[
                InsertError,
                ExampleGQLModel
            ](),
            RbacProviderExtension[
                InsertError,
                ExampleGQLModel
            ](),
        ],
    )
    async def example_insert(
        self,
        info: ApplicationInfo,
        example: ExampleInsertGQLModel,
        rbacobject_id: IDType,
        user_roles: typing.List[dict],
    ) -> typing.Union[
        ExampleGQLModel,
        InsertError[ExampleGQLModel],
    ]:
        example.rbacobject_id = rbacobject_id
        service = info.ServiceCtx.Services.ExampleService

        return await service.ExecuteServiceMethod(
            service.Create(
                ctx=info.ServiceCtx,
                entity=example,
            ),
            Error=service.CreateErrorCallback(
                ErrorClass=InsertError[ExampleGQLModel],
                code="<new-uuid>",
                location="example_insert",
                _input=example,
            ),
            OK=ExampleGQLModel.from_dataclass,
        )

    @strawberry.mutation(
        description="Update an Example",
        permission_classes=[OnlyForAuthentized],
        extensions=[
            UserAccessControlExtension[
                UpdateError,
                ExampleGQLModel
            ](roles=["<role>"]),
            UserRoleProviderExtension[
                UpdateError,
                ExampleGQLModel
            ](),
            RbacProviderExtension[
                UpdateError,
                ExampleGQLModel
            ](),
            LoadDataExtension[
                UpdateError,
                ExampleGQLModel
            ](),
        ],
    )
    async def example_update(
        self,
        info: ApplicationInfo,
        example: ExampleUpdateGQLModel,
        db_row: typing.Any,
        rbacobject_id: IDType,
        user_roles: typing.List[dict],
    ) -> typing.Union[
        ExampleGQLModel,
        UpdateError[ExampleGQLModel],
    ]:
        service = info.ServiceCtx.Services.ExampleService

        return await service.ExecuteServiceMethod(
            service.Update(
                ctx=info.ServiceCtx,
                entity=example,
            ),
            Error=service.CreateErrorCallback(
                ErrorClass=UpdateError[ExampleGQLModel],
                code="<new-uuid>",
                location="example_update",
                _input=example,
                _entity=ExampleGQLModel.from_dataclass(db_row),
            ),
            OK=ExampleGQLModel.from_dataclass,
        )

    @strawberry.mutation(
        description="Delete an Example",
        permission_classes=[OnlyForAuthentized],
        extensions=[
            UserAccessControlExtension[
                DeleteError,
                ExampleGQLModel
            ](roles=["<role>"]),
            UserRoleProviderExtension[
                DeleteError,
                ExampleGQLModel
            ](),
            RbacProviderExtension[
                DeleteError,
                ExampleGQLModel
            ](),
            LoadDataExtension[
                DeleteError,
                ExampleGQLModel
            ](),
        ],
    )
    async def example_delete(
        self,
        info: ApplicationInfo,
        example: ExampleDeleteGQLModel,
        db_row: typing.Any,
        rbacobject_id: IDType,
        user_roles: typing.List[dict],
    ) -> typing.Optional[
        DeleteError[ExampleGQLModel]
    ]:
        service = info.ServiceCtx.Services.ExampleService

        return await service.ExecuteServiceMethod(
            service.Delete(
                ctx=info.ServiceCtx,
                entity=example,
            ),
            Error=service.CreateErrorCallback(
                ErrorClass=DeleteError[ExampleGQLModel],
                code="<new-uuid>",
                location="example_delete",
                _input=example,
                _entity=ExampleGQLModel.from_dataclass(db_row),
            ),
            OK=lambda result: None,
        )
```

When a parent entity determines RBAC for insert, add the appropriate `LoadDataExtension` to the insert mutation and include its injected `db_row` parameter exactly as required by the extension.



---

# 26. DB runtime and seed integration

A new DB model is discovered by SQLAlchemy metadata only when its module is imported.

Therefore, for local persistent entities:

1. export the model from the domain package,
2. import/export it from `src/DBDefinitions/__init__.py`,
3. verify it is present in `BaseDBModel.registry.mappers`.

This matters for:

```python
BaseDBModel.metadata.create_all(...)
```

and for generic DB tooling in:

```text
src/DBDefinitions/main.py
src/DBDefinitions/seed.py
```

The generic DB CLI discovers entities from `BaseDBModel.registry.mappers`; it does not require a hard-coded CLI registration when the model is correctly imported.

## Seed behavior

`seed.py` distinguishes ordinary demo entities from models whose class names end in:

```text
TypeModel
```

Type models may be initialized even when demo data is disabled.

Therefore:

- if adding a catalog/type entity that must be seeded, inspect the existing seed data format and integrate it,
- if adding an ordinary transactional entity, do not automatically add demo data unless requested or required by tests,
- do not hard-code special-case seeding if generic `ImportModels` behavior already supports the entity.

---

# 27. Domain package consistency

When adding a new domain, keep all three layers consistently grouped.

Expected structure:

```text
src/DBDefinitions/Domain_X/
src/ServiceDefinitions/Domain_X/
src/GraphTypeDefinitions/Domain_X/
```

Each package should export the public domain elements through its `__init__.py`.

For example:

```python
# DBDefinitions/Domain_X/__init__.py
from .ExampleModel import ExampleModel
```

```python
# ServiceDefinitions/Domain_X/__init__.py
from .ExampleService import ExampleService
```

```python
# GraphTypeDefinitions/Domain_X/__init__.py
from .ExampleGQLModel import (
    ExampleGQLModel,
    ExampleInputFilter,
    ExampleQuery,
    ExampleMutation,
)
```

The GraphQL domain package also composes:

```python
Query_Domain_X
Mutation_Domain_X
```

Only a new **domain** needs to be added to root `query.py` and `mutation.py`.

Adding another entity to an existing domain should normally modify the domain interface composition, not introduce another root-level dependency.

---

# 28. Infrastructure versus feature code

Do not change global infrastructure for a normal feature unless necessary.

The following files are infrastructure:

```text
src/GraphTypeDefinitions/GraphQLContext.py
src/GraphTypeDefinitions/ApplicationInfo.py
src/GraphTypeDefinitions/SessionCommitExtension.py
src/GraphTypeDefinitions/default_resolver.py
src/GraphTypeDefinitions/schema_factory.py
src/DBDefinitions/runtime.py
```

Typical entity CRUD should work through existing infrastructure.

Change infrastructure only when the user's request explicitly concerns:

- request/session lifecycle,
- authentication context,
- transaction behavior,
- schema-wide extensions,
- federation-wide behavior,
- default GraphQL resolution,
- DB engine/runtime startup.

If changing infrastructure, add infrastructure-focused tests in addition to entity tests.

---

# 29. Completion criteria for Coder

Before declaring a user request complete, verify every applicable item below.

## Requirement fidelity

- [ ] The implementation matches the user's requested behavior.
- [ ] No requested CRUD/query/mutation operation was omitted.
- [ ] No unrelated feature was added.
- [ ] Domain assumptions were inferred from repository precedent where possible.
- [ ] Unresolved business decisions are clearly identified rather than fabricated.

## Persistence

- [ ] DB model exists when required.
- [ ] Base fields and FK semantics match repository conventions.
- [ ] Model is imported so SQLAlchemy metadata/registry sees it.
- [ ] Type/catalog seed integration is handled when required.

## Loader

- [ ] Loader is registered when local persistent data is loaded by ID or FK.
- [ ] `LoaderName` exactly matches the loader registry attribute.
- [ ] No resolver creates an ad-hoc replacement loader.

## Service

- [ ] Service exists when business/persistence behavior requires it.
- [ ] Generic CRUD uses `BaseService`.
- [ ] Domain-specific rules live in service methods.
- [ ] Service is reachable through `ServiceRegistry`.

## GraphQL

- [ ] Output type exists and follows federation ownership rules.
- [ ] Input/filter types use repository conventions.
- [ ] `by_id` query works when requested.
- [ ] page/filter query works when requested.
- [ ] insert/update/delete exist when requested.
- [ ] update/delete preserve `lastchange`.
- [ ] optional patch semantics use `strawberry.UNSET`.
- [ ] relationships use loaders/resolvers.
- [ ] permissions and RBAC extensions are preserved.

## Integration

- [ ] Entity interfaces are composed into the correct domain.
- [ ] New domains are composed into root Query/Mutation.
- [ ] External federation types are registered appropriately.
- [ ] Local types are not unnecessarily added to `types=[...]`.
- [ ] `create_schema()` succeeds.

## Verification

- [ ] Python files parse/import.
- [ ] relevant DB tests pass.
- [ ] relevant service tests pass.
- [ ] relevant GraphQL tests pass.
- [ ] requested operation is exercised through the GraphQL schema where applicable.
- [ ] broader affected tests pass or remaining failures are reported with cause.

A feature is not complete if any required integration step is knowingly missing.

---

# 30. Expected Coder workflow for a user request

Use the following workflow as the default behavior.

```text
A. Read the user's requested behavior.

B. Inspect the nearest analogous implementation.

C. Build an internal vertical-slice map:
   DB -> Loader -> Service -> GQL -> Domain -> Schema -> Tests.

D. Mark non-applicable layers rather than blindly editing them.

E. Implement from lower layers upward:
   persistence -> loading -> service -> GraphQL -> schema composition.

F. Preserve authorization and optimistic concurrency.

G. Add tests alongside the new behavior.

H. Build the schema and run focused tests.

I. Fix regressions caused by the change.

J. Review the final diff for:
   - missing registrations,
   - inconsistent names,
   - unused imports,
   - accidental infrastructure changes,
   - missing tests,
   - behavior not requested by the user.

K. Report the completed capability, important architectural choices,
   tests run, and any unresolved domain decision.
```

The agent should perform the work, not merely describe the files that a human could edit.

---

# 31. Final response behavior

After implementation, the Coder agent should give the user a concise engineering summary.

Include:

```text
- what capability was implemented,
- which architecture layers changed,
- important behavior/authorization/concurrency decisions,
- tests or validation performed,
- any unresolved item that genuinely requires user/domain input.
```

Do not claim success if schema construction or relevant tests are failing.

Do not present implementation instructions as though the task were completed when the user asked the agent to actually modify the repository.

If the user asked only for analysis or instructions, do not modify code unnecessarily.

