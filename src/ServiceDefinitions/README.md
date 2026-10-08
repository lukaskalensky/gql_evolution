# ServiceDefinitions

Adresář `ServiceDefinitions` obsahuje aplikační service vrstvu backendu.

Service vrstva je prostřední vrstva mezi GraphQL resolvery a datovou vrstvou. Resolver by neměl přímo pracovat se SQLAlchemy session ani s databázovými modely mimo jasně definovaný aplikační tok. Veškerá aplikační logika má být umístěna do service tříd.

Typický tok aplikace je:

```text
GraphQL resolver
  ↓
Service
  ↓
Dataloader / LoaderMap
  ↓
DBDefinitions / SQLAlchemy model
```

---

## Účel adresáře

`ServiceDefinitions` slouží k definici aplikačních služeb.

Obsahuje:

* společnou základní service třídu,
* service context,
* service registry,
* doménové service třídy,
* sjednocené zpracování chyb,
* testovací/seedovací CLI nástroj nad service vrstvou.

Service vrstva je místo, kde má být:

* aplikační logika,
* validační logika,
* doménová pravidla,
* jednotné zpracování chyb,
* práce s dataloadery,
* zapouzdření operací `Create`, `Read`, `Update`, `Delete`.

---

## Struktura

Příklad struktury:

```text
ServiceDefinitions/
  __init__.py
  BaseService.py
  ServiceContext.py
  main.py

  Domain_Events/
    __init__.py
    EventService.py
    EventInvitationService.py
```

### `BaseService.py`

Obsahuje společný základ pro service třídy.

Typicky obsahuje:

```python
class BaseService:
    ...
```

a společné metody jako:

```python
Create
ReadById
ReadPage
Update
Delete
ExecuteServiceMethod
CreateError
CreateErrorCallback
```

`BaseService` sjednocuje způsob, jakým service vrstva komunikuje s loaderem a jak se zpracovávají výsledky i chyby.

---

## ServiceContext

`ServiceContext` je objekt předávaný do service metod.

Typicky obsahuje:

```text
loaders
Services
user
request
```

Příklad použití:

```python
result = await EventService.Create(
    ctx=info.ServiceCtx,
    entity=event
)
```

V GraphQL resolverech se service context obvykle získává z `ApplicationInfo`:

```python
info.ServiceCtx
```

V testovacím CLI se `ServiceContext` vytváří ručně nad databázovou session a `LoaderMap`.

---

## ServiceRegistry

Service registry poskytuje explicitní přístup k dostupným service třídám.

Příklad:

```python
EventService = info.ServiceCtx.Services.EventService
```

nebo:

```python
EventInvitationService = info.ServiceCtx.Services.EventInvitationService
```

Registry má být explicitní.

Novou service je potřeba přidat do service registry, aby ji bylo možné používat z resolverů i z testovacího CLI.

---

## Doménové service

Doménové service jsou seskupené podle domén.

Například:

```text
Domain_Events/
  EventService.py
  EventInvitationService.py
```

### `EventService`

Service pro hlavní entitu události.

Typické operace:

```python
EventService.Create(...)
EventService.ReadById(...)
EventService.ReadPage(...)
EventService.Update(...)
EventService.Delete(...)
```

### `EventInvitationService`

Service pro vazební entitu mezi událostí a uživatelem.

Typické operace:

```python
EventInvitationService.Create(...)
EventInvitationService.ReadById(...)
EventInvitationService.ReadPage(...)
EventInvitationService.Update(...)
EventInvitationService.Delete(...)
```

Může obsahovat také doménové metody, například:

```python
AcceptOrDeclineByInvitedUser
```

nebo jiné metody, které vyjadřují aplikační chování nad pozvánkou.

---

## Vazba na LoaderMap

Každá service explicitně určuje, který loader používá.

Příklad:

```python
class EventService(BaseService):

    @classmethod
    async def getLoader(cls, ctx: ServiceContext):
        return ctx.loaders.EventModel
```

nebo podle konkrétního tvaru projektu:

```python
class EventInvitationService(BaseService):

    @classmethod
    async def getLoader(cls, ctx: ServiceContext):
        return ctx.loaders.EventInvitationModel
```

Service vrstva tedy nepracuje přímo se session. Přístup k datům má jít přes loader.

---

## Proč service vrstva nesmí být obcházena

GraphQL resolver by neměl obsahovat aplikační logiku ani přímé databázové operace.

Nevhodné:

```python
session.add(entity)
await session.commit()
```

v resolveru.

Správně:

```python
EventService = info.ServiceCtx.Services.EventService

result = await EventService.ExecuteServiceMethod(
    EventService.Create(
        ctx=info.ServiceCtx,
        entity=event
    ),
    OK=EventGQLModel.from_dataclass,
    Error=EventService.CreateErrorCallback(
        ErrorClass=InsertError[EventGQLModel],
        code="...",
        location="EventMutation.event_insert",
        _input=event
    )
)
```

Resolver má pouze:

1. převzít GraphQL vstup,
2. zavolat service,
3. převést výsledek na GraphQL typ nebo error typ.

---

# ExecuteServiceMethod

`ExecuteServiceMethod` je důležitá metoda `BaseService`.

Slouží k zapouzdření spouštění service operací a sjednocení zpracování výsledků i chyb.

Typický tvar:

```python
result = await EventService.ExecuteServiceMethod(
    EventService.Update(
        ctx=info.ServiceCtx,
        entity=event
    ),
    OK=EventGQLModel.from_dataclass,
    Error=EventService.CreateErrorCallback(
        ErrorClass=UpdateError[EventGQLModel],
        code="...",
        location="EventMutation.event_update",
        _input=event,
        _entity=EventGQLModel.load_with_loader(
            info=info,
            id=event.id
        )
    )
)
```

## Účel

`ExecuteServiceMethod` zajišťuje:

* spuštění asynchronní service operace,
* zavolání `OK` callbacku při úspěchu,
* zachycení SQLAlchemy chyb,
* zachycení doménových chyb,
* zachycení neočekávaných výjimek,
* vytvoření jednotného error objektu přes `Error` callback.

---

## Zpracování úspěchu

Při úspěchu se výsledek service metody předá do `OK` callbacku.

Příklad:

```python
OK=EventGQLModel.from_dataclass
```

nebo:

```python
OK=lambda result: EventGQLModel.from_dataclass(result)
```

V aktuální architektuře může `from_dataclass()` sloužit jako kompatibilní alias pro `from_db()`, který nepřevádí DB entitu přes `dataclasses.asdict()`, ale uloží ji do interního atributu GraphQL typu.

---

## Zpracování chyby

Chybový callback je možné vytvořit přes:

```python
EventService.CreateErrorCallback(...)
```

Příklad:

```python
Error=EventService.CreateErrorCallback(
    ErrorClass=InsertError[EventGQLModel],
    code="3a9b8eb5-88c9-4432-9c0c-a48c53a43179",
    location="EventMutation.event_insert",
    _input=event
)
```

`CreateErrorCallback` vytvoří callback, který při chybě zavolá `CreateError`.

---

# Testovací / seedovací CLI

Soubor:

```text
ServiceDefinitions/main.py
```

obsahuje testovací příkazovou řádku nad service vrstvou.

CLI je určeno pro:

* lokální testování service vrstvy,
* ověření, že service správně používají loadery,
* seedování dat přes aplikační service,
* testování doménových service metod,
* kontrolu chování `Create`, `ReadById`, `ReadPage`, `Update`, `Delete`.

Není to aplikační API.

---

## Rozdíl proti DBDefinitions CLI

`DBDefinitions/main.py` pracuje přímo nad SQLAlchemy modelem a databázovou session.

```text
DBDefinitions/main.py
  ↓
SQLAlchemy model
  ↓
session
  ↓
database
```

`ServiceDefinitions/main.py` pracuje přes service vrstvu.

```text
ServiceDefinitions/main.py
  ↓
ServiceContext
  ↓
Service
  ↓
LoaderMap / Dataloader
  ↓
database
```

To znamená, že service CLI lépe ověřuje skutečný aplikační tok.

---

## Spuštění CLI

Z rootu projektu:

```bash
python -m src.ServiceDefinitions.main Event list '{}'
```

Root projektu je adresář, který obsahuje složku `src`.

Příklad:

```text
project-root/
  src/
    ServiceDefinitions/
      main.py
```

Pak:

```bash
cd project-root
python -m src.ServiceDefinitions.main Event list '{}'
```

---

## Obecný tvar příkazu

```bash
python -m src.ServiceDefinitions.main <service> <operation> <payload>
```

Kde:

```text
service
  název service nebo entity

operation
  create, get, list, update, delete
  případně název veřejné doménové service metody

payload
  JSON objekt nebo odkaz na JSON soubor pomocí @soubor.json
```

Příklady názvu service:

```text
Event
EventService
EventInvitation
EventInvitationService
```

Service se dohledávají podle service registry.

---

## Doporučený způsob předávání payloadu

Pro jednoduché payloady lze JSON předat přímo:

```bash
python -m src.ServiceDefinitions.main Event list '{}'
```

Pro složitější payloady je doporučené použít JSON soubor:

```bash
python -m src.ServiceDefinitions.main Event list @event_filter.json
```

To je bezpečnější zejména na Windows, kde shell často rozbije JSON na více argumentů.

---

## Create

Vytvoření entity přes service vrstvu:

```bash
python -m src.ServiceDefinitions.main Event create @event_create.json
```

`event_create.json`:

```json
{
  "name": "GraphQL workshop",
  "name_en": "GraphQL workshop",
  "description": "Seed přes service vrstvu",
  "place": "Praha"
}
```

Pokud CLI podporuje obal `entity`, lze použít také:

```json
{
  "entity": {
    "name": "GraphQL workshop",
    "name_en": "GraphQL workshop",
    "description": "Seed přes service vrstvu",
    "place": "Praha"
  }
}
```

---

## Create s vnořenými entitami

Pokud DB model obsahuje SQLAlchemy relationship, lze vytvářet vnořené entity i přes service CLI.

Příklad:

```bash
python -m src.ServiceDefinitions.main Event create @event_with_invitations.json
```

`event_with_invitations.json`:

```json
{
  "name": "GraphQL workshop",
  "description": "Událost s pozvánkami",
  "place": "Praha",
  "user_invitations": [
    {
      "user_id": "11111111-1111-1111-1111-111111111111",
      "state_id": "01b96c1d-8389-4267-a859-d8116e1c32f3"
    }
  ]
}
```

Přesný název relationship atributu musí odpovídat názvu v DB modelu.

---

## Get / Read single

Načtení jedné entity podle primárního klíče:

```bash
python -m src.ServiceDefinitions.main Event get @event_get.json
```

`event_get.json`:

```json
{
  "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
}
```

Načtení včetně relationship:

```json
{
  "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
  "include": ["user_invitations"]
}
```

---

## List / ReadPage

Načtení více entit přes `ReadPage`:

```bash
python -m src.ServiceDefinitions.main Event list '{}'
```

S limitem a offsetem:

```bash
python -m src.ServiceDefinitions.main Event list @event_list.json
```

`event_list.json`:

```json
{
  "limit": 10,
  "offset": 0
}
```

Service CLI předává `offset` jako `skip`, pokud service metoda používá název `skip`.

---

## List s filtrem

Filtrování probíhá přes service metodu `ReadPage`.

Typicky:

```python
result = await EventService.ReadPage(
    ctx=ctx,
    skip=skip,
    limit=limit,
    where=where,
    orderby=orderby,
    desc=desc,
    extendedfilter=extendedfilter
)
```

Pokud `where` není uvedené nebo je `null`, service by měla vrátit běžnou stránku bez filtru.

Pokud `where` uvedené je, mělo by odpovídat rigidní struktuře filtru používané funkcí `prepareSelect` z `uoishelpers`.

Správný příklad:

```json
{
  "where": {
    "name": {
      "_ilike": "%workshop%"
    }
  },
  "limit": 10,
  "offset": 0
}
```

Spuštění:

```bash
python -m src.ServiceDefinitions.main Event list @event_filter.json
```

---

## Logické operátory ve filtru

Filtr může používat `_and` a `_or`.

Příklad:

```json
{
  "where": {
    "_and": [
      {
        "name": {
          "_ilike": "%workshop%"
        }
      },
      {
        "place": {
          "_eq": "Praha"
        }
      }
    ]
  }
}
```

Každý uzel filtru má mít právě jeden klíč.

---

## Podporované operátory filtru

Podle implementace `prepareSelect` jsou podporované například:

```text
_eq
_lt
_le
_gt
_ge
_in
_like
_ilike
_startswith
_endswith
```

Příklad:

```json
{
  "where": {
    "name": {
      "_startswith": "GraphQL"
    }
  }
}
```

---

## Update

Aktualizace entity přes service vrstvu:

```bash
python -m src.ServiceDefinitions.main Event update @event_update.json
```

`event_update.json`:

```json
{
  "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
  "name": "Aktualizovaný název",
  "place": "Brno"
}
```

Nebo s obalem `entity`:

```json
{
  "entity": {
    "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    "name": "Aktualizovaný název",
    "place": "Brno"
  }
}
```

---

## Delete

Smazání entity přes service vrstvu:

```bash
python -m src.ServiceDefinitions.main Event delete @event_delete.json
```

`event_delete.json`:

```json
{
  "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
}
```

Nebo:

```json
{
  "entity": {
    "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
  }
}
```

---

# Volání doménové service metody

Kromě základních CRUD operací lze přes CLI zavolat i veřejnou doménovou service metodu.

Příklad:

```bash
python -m src.ServiceDefinitions.main EventInvitation AcceptOrDeclineByInvitedUser @accept_invitation.json
```

`accept_invitation.json`:

```json
{
  "user": {
    "id": "11111111-1111-1111-1111-111111111111"
  },
  "entity": {
    "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    "state_id": "7d2ef223-b60e-4e6d-b7d5-5fdc1f8e2ec2"
  }
}
```

Service CLI podle signatury metody sestaví argumenty:

* `ctx`,
* `entity`,
* další položky z payloadu,
* položky z `kwargs`, pokud jsou uvedené.

Příklad s `kwargs`:

```json
{
  "entity": {
    "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
  },
  "kwargs": {
    "some_parameter": "some value"
  }
}
```

---

## Předání uživatele

Některé service metody potřebují aktuálního uživatele.

Uživatele lze předat v payloadu:

```json
{
  "user": {
    "id": "11111111-1111-1111-1111-111111111111"
  },
  "entity": {
    "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
  }
}
```

Nebo přes přepínač:

```bash
python -m src.ServiceDefinitions.main EventInvitation AcceptOrDeclineByInvitedUser @payload.json --user @user.json
```

`user.json`:

```json
{
  "id": "11111111-1111-1111-1111-111111111111"
}
```

---

## Přepínače CLI

### `--drop`

Smaže všechny tabulky a znovu je vytvoří před provedením operace.

```bash
python -m src.ServiceDefinitions.main Event list '{}' --drop
```

Používat pouze proti lokální testovací databázi.

### `--no-makeup`

Nevytváří tabulky přes `BaseModel.metadata.create_all`.

```bash
python -m src.ServiceDefinitions.main Event list '{}' --no-makeup
```

---

## Přidání nové service

Při přidání nové domény je potřeba:

1. vytvořit DB model v `DBDefinitions`,
2. zaregistrovat odpovídající loader v `Dataloaders`,
3. vytvořit service třídu v `ServiceDefinitions`,
4. implementovat `getLoader`,
5. přidat service do `ServiceRegistry`,
6. případně doplnit testy a CLI seedovací scénáře.

Příklad service:

```python
class EventService(BaseService):

    @classmethod
    async def getLoader(cls, ctx: ServiceContext):
        return ctx.loaders.EventModel
```

Příklad registrace:

```python
class ServiceRegistry:

    @property
    def EventService(self):
        from .Domain_Events.EventService import EventService
        return EventService
```

---

## Architektonická pravidla

Service vrstva:

* smí používat DB modely,
* smí používat dataloadery,
* smí používat `ServiceContext`,
* smí obsahovat aplikační a doménovou logiku,
* nesmí záviset na GraphQL resolverech,
* nemá vracet GraphQL typy,
* nemá vytvářet GraphQL error objekty.

GraphQL vrstva volá service vrstvu a převádí výsledek na GQL typ.

Service vrstva vrací doménové/DB entity nebo vyhazuje service výjimky.

Resolver sjednotí odpověď pomocí:

```python
ExecuteServiceMethod(
    ...,
    OK=SomeGQLModel.from_dataclass,
    Error=SomeService.CreateErrorCallback(...)
)
```

---

## Doporučené použití

Tento adresář je vhodný používat pro:

```text
aplikační CRUD logiku
doménová pravidla
validace
testování service vrstvy
seedování přes aplikační logiku
testování dataloader integrace
```

Není určen pro definici GraphQL schématu.

GraphQL typy a resolvery patří do `GraphTypeDefinitions`.

Databázové modely patří do `DBDefinitions`.
