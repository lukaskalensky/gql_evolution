
# DBDefinitions

Adresář `DBDefinitions` obsahuje databázovou vrstvu aplikace.

Tato vrstva definuje SQLAlchemy modely, společný základ databázových entit, vytvoření databázového spojení a testovací/seedovací příkazovou řádku pro práci s databázovými entitami.

DB vrstva nesmí záviset na GraphQL vrstvě ani na service vrstvě.

---

## Účel adresáře

`DBDefinitions` slouží k definici databázových struktur aplikace.

Obsahuje:

* společný základ všech DB modelů,
* doménové SQLAlchemy modely,
* pomocné typy pro UUID sloupce a foreign keys,
* funkci pro vytvoření async databázového engine,
* funkci pro sestavení connection stringu z environment proměnných,
* testovací/seedovací CLI nástroj nad DB entitami.

Typický tok aplikace je:

```text
GraphQL resolver
  ↓
Service
  ↓
Dataloader
  ↓
DBDefinitions / SQLAlchemy model
```

Adresář `DBDefinitions` je tedy nejnižší vrstva backendu.

---

## Struktura

Příklad struktury:

```text
DBDefinitions/
  __init__.py
  BaseModel.py
  main.py

  Domain_Events/
    __init__.py
    EventModel.py
    EventInvitationModel.py
```

### `BaseModel.py`

Obsahuje společný SQLAlchemy základ.

Typicky exportuje:

```python
BaseModel
BaseDBModel
IDType
UUIDColumn
UUIDFKey
```

`BaseDBModel` je základní třída pro všechny databázové entity.

Obsahuje společné atributy, například:

```text
id
created
lastchange
createdby_id
changedby_id
rbacobject_id
```

Přesné atributy se řídí implementací v `BaseModel.py`.

---

## Doménové modely

Doménové modely jsou seskupené do doménových adresářů.

Například:

```text
Domain_Events/
  EventModel.py
  EventInvitationModel.py
```

### `EventModel`

Reprezentuje událost.

Příklad významu entity:

```text
Event
  id
  name
  name_en
  description
  place
  start_datetime
  end_datetime
```

Událost může mít více pozvánek.

### `EventInvitationModel`

Reprezentuje vazbu mezi událostí a uživatelem.

```text
EventInvitation
  id
  event_id
  user_id
  state_id
```

`user_id` odkazuje na uživatele, ale `User` není DB entita této domény. Z hlediska Apollo Federation je `UserGQLModel` externí entita.

DB vrstva tedy obsahuje pouze `user_id`, nikoliv SQLAlchemy relationship na uživatelskou tabulku.

---

## Relationship mezi DB modely

Pokud mají DB modely vztahy uvnitř stejné domény, měly by být deklarované pomocí SQLAlchemy `relationship()`.

Například:

```python
class EventModel(BaseDBModel):
    __tablename__ = "events"

    invitations: Mapped[list["EventInvitationModel"]] = relationship(
        "EventInvitationModel",
        back_populates="event",
        cascade="all, delete-orphan",
    )
```

a:

```python
class EventInvitationModel(BaseDBModel):
    __tablename__ = "event_invitations"

    event: Mapped["EventModel"] = relationship(
        "EventModel",
        back_populates="invitations",
    )
```

Relationship je důležitý i pro testovací/seedovací CLI, protože umožňuje vytvářet vnořené entity.

---

## `__init__.py`

Soubor `DBDefinitions/__init__.py` exportuje základní prvky DB vrstvy a importuje doménové modely.

Příklad:

```python
import sqlalchemy

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine

from .BaseModel import BaseModel, BaseDBModel, IDType, UUIDColumn, UUIDFKey
from .Domain_Events import EventModel, EventInvitationModel
```

Import doménových modelů je důležitý.

SQLAlchemy registry zná pouze ty modely, které byly importované. Testovací CLI používá implicitní introspekci přes:

```python
BaseModel.registry.mappers
```

Nový model tedy není potřeba ručně registrovat v CLI, ale musí být importovaný v `DBDefinitions/__init__.py`.

---

## Vytvoření databázového spojení

Funkce:

```python
ComposeConnectionString()
```

sestaví connection string z environment proměnných.

Používané proměnné:

```text
POSTGRES_USER
POSTGRES_PASSWORD
POSTGRES_DB
POSTGRES_HOST
CONNECTION_STRING
```

Výchozí hodnoty:

```text
POSTGRES_USER=postgres
POSTGRES_PASSWORD=example
POSTGRES_DB=data
POSTGRES_HOST=localhost:5432
```

Výsledný výchozí connection string:

```text
postgresql+asyncpg://postgres:example@localhost:5432/data
```

Proměnná `CONNECTION_STRING` má přednost před jednotlivými proměnnými.

Příklad:

```bash
export CONNECTION_STRING='postgresql+asyncpg://postgres:example@localhost:5432/data'
```

Na Windows PowerShell:

```powershell
$env:CONNECTION_STRING = "postgresql+asyncpg://postgres:example@localhost:5432/data"
```

---

## Inicializace engine

Funkce:

```python
async def startEngine(connectionstring, makeDrop=False, makeUp=True):
    ...
```

vytvoří asynchronní SQLAlchemy engine a vrátí async session maker.

Parametry:

```text
connectionstring
  databázový connection string

makeDrop
  pokud je True, provede BaseModel.metadata.drop_all

makeUp
  pokud je True, provede BaseModel.metadata.create_all
```

Funkce je určena hlavně pro lokální vývoj, testování a seedování.

V produkčním prostředí je vhodnější používat migrace, například Alembic.

---

# Testovací / seedovací CLI

Soubor:

```text
DBDefinitions/main.py
```

obsahuje testovací příkazovou řádku nad DB entitami.

CLI je určeno pro:

* lokální testování DB modelů,
* ruční vytvoření seed dat,
* ověření relationship vazeb,
* rychlou kontrolu obsahu databáze.

Není to aplikační API.

Aplikační přístup k datům má stále probíhat přes:

```text
GraphQL resolver → Service → Dataloader → DB
```

---

## Spuštění CLI

Z rootu projektu:

```bash
python -m src.DBDefinitions.main Event list '{}'
```

Root projektu je adresář, který obsahuje složku `src`.

Příklad:

```text
project-root/
  src/
    DBDefinitions/
      main.py
```

Pak:

```bash
cd project-root
python -m src.DBDefinitions.main Event list '{}'
```

---

## Obecný tvar příkazu

```bash
python -m src.DBDefinitions.main <entity> <operation> <payload>
```

Kde:

```text
entity
  název entity, název modelu nebo název tabulky

operation
  create, get, list, update, delete

payload
  JSON objekt nebo odkaz na JSON soubor pomocí @soubor.json
```

Příklady názvu entity:

```text
Event
EventModel
events
EventInvitation
EventInvitationModel
event_invitations
```

Entity se dohledávají implicitně přes SQLAlchemy registry.

CLI tedy nepotřebuje ruční výčet entit.

---

## Doporučený způsob předávání payloadu

Pro jednoduché payloady lze JSON předat přímo:

```bash
python -m src.DBDefinitions.main Event list '{}'
```

Pro složitější payloady je doporučené použít JSON soubor:

```bash
python -m src.DBDefinitions.main Event list @filter.json
```

To je bezpečnější zejména na Windows, kde shell jinak často rozbije JSON na více argumentů.

---

## Create

Vytvoření jednoduché entity:

```bash
python -m src.DBDefinitions.main Event create @event_create.json
```

`event_create.json`:

```json
{
  "name": "GraphQL workshop",
  "name_en": "GraphQL workshop",
  "description": "Testovací událost",
  "place": "Praha"
}
```

---

## Create s vnořenými entitami

Pokud je v DB modelu deklarovaný SQLAlchemy relationship, lze vytvářet i vnořené entity.

Příklad:

```bash
python -m src.DBDefinitions.main Event create @event_with_invitations.json
```

`event_with_invitations.json`:

```json
{
  "name": "GraphQL workshop",
  "name_en": "GraphQL workshop",
  "description": "Událost s pozvánkami",
  "place": "Praha",
  "invitations": [
    {
      "user_id": "11111111-1111-1111-1111-111111111111",
      "state_id": "22222222-2222-2222-2222-222222222222"
    },
    {
      "user_id": "33333333-3333-3333-3333-333333333333",
      "state_id": "22222222-2222-2222-2222-222222222222"
    }
  ]
}
```

V tomto případě CLI vytvoří jeden `EventModel` a k němu dvě entity `EventInvitationModel`.

---

## Get / Read single

Načtení jedné entity podle primárního klíče:

```bash
python -m src.DBDefinitions.main Event get @event_get.json
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
  "include": ["invitations"]
}
```

---

## List / Read multi

Načtení více entit bez filtru:

```bash
python -m src.DBDefinitions.main Event list '{}'
```

Načtení s limitem a offsetem:

```bash
python -m src.DBDefinitions.main Event list @event_list.json
```

`event_list.json`:

```json
{
  "limit": 10,
  "offset": 0
}
```

---

## List s filtrem

Pro filtrování se používá funkce `prepareSelect` z `uoishelpers`.

Pokud `where` není uvedené nebo je `null`, CLI použije jednoduché:

```python
select(Model)
```

Pokud `where` uvedené je, CLI použije:

```python
prepareSelect(Model, where)
```

Filtr musí odpovídat rigidní struktuře `prepareSelect`.

Správný jednoduchý filtr:

```json
{
  "where": {
    "name": {
      "_ilike": "%workshop%"
    }
  }
}
```

Příklad spuštění:

```bash
python -m src.DBDefinitions.main Event list @event_filter.json
```

```bash
python -m src.DBDefinitions.main Event list "{\"where\":{\"name\":{\"_ilike\":\"%1%\"}}}"
```

`event_filter.json`:

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

---

## Logické operátory ve filtru

`prepareSelect` podporuje logické operátory `_and` a `_or`.

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

Příklad s `_or`:

```json
{
  "where": {
    "_or": [
      {
        "place": {
          "_eq": "Praha"
        }
      },
      {
        "place": {
          "_eq": "Brno"
        }
      }
    ]
  }
}
```

Každý uzel filtru musí mít právě jeden klíč.

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

Příklad `_in`:

```json
{
  "where": {
    "place": {
      "_in": ["Praha", "Brno", "Ostrava"]
    }
  }
}
```

---

## Filtrování přes relationship

Pokud má model deklarovaný SQLAlchemy relationship, lze přes něj filtrovat.

Příklad:

```json
{
  "where": {
    "invitations": {
      "user_id": {
        "_eq": "11111111-1111-1111-1111-111111111111"
      }
    }
  },
  "include": ["invitations"]
}
```

V takovém případě `prepareSelect` vytvoří potřebný join na cílový model relationship.

---

## Update

Aktualizace entity podle primárního klíče:

```bash
python -m src.DBDefinitions.main Event update @event_update.json
```

`event_update.json`:

```json
{
  "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
  "name": "Aktualizovaný název",
  "place": "Brno"
}
```

---

## Delete

Smazání entity podle primárního klíče:

```bash
python -m src.DBDefinitions.main Event delete @event_delete.json
```

`event_delete.json`:

```json
{
  "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
}
```

---

## Přepínače CLI

### `--drop`

Smaže všechny tabulky a znovu je vytvoří před provedením operace.

```bash
python -m src.DBDefinitions.main Event list '{}' --drop
```

Používat pouze proti lokální testovací databázi.

### `--no-makeup`

Nevytváří tabulky přes `BaseModel.metadata.create_all`.

```bash
python -m src.DBDefinitions.main Event list '{}' --no-makeup
```

---

## Přidání nové DB entity

Při přidání nové entity je potřeba:

1. vytvořit model v příslušné doméně,
2. zajistit, že dědí z `BaseDBModel`,
3. importovat model v doménovém `__init__.py`,
4. importovat doménový model v `DBDefinitions/__init__.py`.

Příklad:

```python
from .Domain_Events import EventModel, EventInvitationModel
```

Díky tomu se model dostane do SQLAlchemy registry a CLI jej najde automaticky.

Není potřeba přidávat entitu do žádného explicitního seznamu v `main.py`.

---

## Architektonická pravidla

DB vrstva:

* smí používat SQLAlchemy,
* smí definovat tabulky, sloupce, foreign keys a relationship,
* smí obsahovat testovací/seedovací CLI,
* nesmí importovat GraphQL typy,
* nesmí importovat resolver vrstvu,
* nesmí importovat service vrstvu.

GraphQL vrstva nesmí typově ani importně odkazovat na DB modely.

Propojení mezi DB, loader, service a GQL vrstvou se řeší přes explicitní registry, názvy loaderů a Protocol anotace ve vyšších vrstvách.

---

## Doporučené použití

Tento adresář je vhodný používat pro:

```text
definici databázového schématu
lokální vytvoření tabulek
seedování testovacích dat
rychlé ověření relationship vazeb
ladění prepareSelect filtrů
```

Není určen jako hlavní aplikační rozhraní.

Pro aplikační logiku používej service vrstvu.

Pro GraphQL API používej resolver vrstvu.
