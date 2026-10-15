# gql_metadata / Tags

Subgraf pro systém uživatelských tagů, které lze přiřazovat k libovolným entitám informačního systému
(např. `Project A` → „Důležité“, „K projednání“).

Autoři: Lukáš Kalenský, Jan Jasanský. Vychází ze vzorového projektu `gql_evolution`, větev `2026`.

## Datový model (1. PD – databázová vrstva)

| Tabulka | Model | Popis |
|---|---|---|
| `tagtypes` | `TagTypeModel` | Číselník typů tagů jako strom (`parent_id`), např. Tagy → Priorita / Stav / Projekt / Kategorie |
| `tags` | `TagModel` | Definice tagu: `name`, `label`, `color`, `description`, `type_id` → `tagtypes` |
| `tag_entities` | `TagEntityModel` | Přiřazení tagu k entitě: `entity_id`, `entity_type_id`, `tag_id` → `tags`, `owner_id` |

Modely jsou v `src/DBDefinitions/Domain_Tags/`, demo data v `systemdata.json`
(`tagtypes` se importují vždy jako číselník, `tags` a `tag_entities` jen s `DEMODATA=True`).
Testy DB vrstvy: `tests/db/test_TagTypeModel.py`, `tests/db/test_TagModel.py`, `tests/db/test_TagEntityModel.py`.

## Deníček

### 2026-10-05
- Nastavení repozitáře a prostředí (commity `hesla`, `zkouska siren`).

### 2026-10-08
- Zprovoznění dev containeru a nástroje Coder (`Pridani do dev Container a zprovozneni Codera`, `Coder`).

### 2026-10-12
- Přidány DB modely `TagModel` a `TagEntityModel` v doméně `Domain_Tags`, export přes `src/DBDefinitions`.
- Demo data: 10 tagů a 10 přiřazení (včetně scénáře Project A → Důležité, K projednání) v `systemdata.json`.
- Testy modelů nad in-memory SQLite a nad CLI `src/DBDefinitions/main.py`.
- Úprava importu dat do databáze (`pro import databaze`).

### 2026-10-15
- Doplněn číselník typů tagů `TagTypeModel` jako strom (požadavek „typy implementujte jako stromy“), `TagModel.type_id`.
- Seed: odstraněna výjimka, která importovala tagy i bez `DEMODATA`; číselník `tagtypes` se importuje automaticky díky sufixu `TypeModel`.
- Testy stromu typů a seedu s/bez demo dat.

### Otevřené problémy
- Testy ze šablony, které vyžadují běžící PostgreSQL (`postgres_gql`), lokálně bez docker compose nejdou spustit.
- 2 unit testy `BaseService.ExecuteServiceMethod` ze šablony selhávají i bez našich změn.
- `entity_type_id` a `owner_id` jsou zatím jen UUID bez vazby (entity a uživatelé patří jiným subgrafům).

---

# Event boilerplate project

Demonstrační boilerplate pro doménu `Event / EventInvitation` podle funkčního vzoru ze `src.zip`.

## Zásady

- GQL vrstva nesmí importovat DB vrstvu ani typově odkazovat na DB modely.
- Pro decoupling mezi vrstvami se používají `Protocol` kontrakty v `src/common/protocols.py`.
- `LoaderMap`, services a GQL typy jsou explicitně definované.
- `EventInvitation` je vazba `Event - User` se stavem pozvánky/účasti.
- `UserGQLModel` je externí federovaná entita pro Apollo Federation.
- `StateGQLModel` je také externí federovaná entita, protože stav pozvánky typicky patří do UG / state-machine subgrafu.
- Page resolvery vždy používají `whereType` definovaný přes `@createInputs2`.
- Mutace používají `BaseService.ExecuteServiceMethod` a `CreateErrorCallback`, aby resolver neobsahoval lokální zpracování výjimek.
- `BaseGQLModel.from_dataclass()` zůstává kompatibilní název, ale interně volá `from_db()` a ukládá původní entitu do `_dbdata` bez `dataclasses.asdict()`.


## Závislost na `uoishelpers`

Projekt pracuje s balíkem `uoishelpers` z repozitáře:

```text
https://github.com/hrbolek/uoishelpers/archive/4e41615436d6effbe248d8503e4df373549bcec3.zip
```

Závislost je uvedená přímo v `pyproject.toml`:

```toml
'uoishelpers @ https://github.com/hrbolek/uoishelpers/archive/4e41615436d6effbe248d8503e4df373549bcec3.zip'
```

Boilerplate proto nepřidává lokální náhražky pro `uoishelpers`. Používá importy ve stejném stylu jako funkční vzor, například:

```python
from uoishelpers.dataloaders.LoaderMapBase import LoaderMapBase
from uoishelpers.dataloaders.IDLoader import IDLoader
from uoishelpers.gqlpermissions import OnlyForAuthentized
from uoishelpers.resolvers import PageResolver, createInputs2
```

Závislost je připnutá na konkrétní commit, aby instalace i CI používaly stejnou verzi.

## Vrstvy

```text
DBDefinitions/
  Domain_Events/
    EventModel.py
    EventInvitationModel.py

Dataloaders/
  __init__.py        # explicitní LoaderMap

ServiceDefinitions/
  Domain_Events/
    EventService.py
    EventInvitationService.py

GraphTypeDefinitions/
  BaseGQLModel.py    # _dbdata + LoaderName kontrakt
  Domain_Events/
    EventGQLModel.py
    EventInvitationGQLModel.py
  Domain_UG/
    UserGQLModel.py  # externí federovaná entita
    StateGQLModel.py # externí federovaná entita
```

## Studenti typicky doplní

1. DB model do `DBDefinitions/Domain_X`.
2. Explicitní položku v `LoaderMap`.
3. Service třídu do `ServiceDefinitions/Domain_X`.
4. GQL typ bez importu DB vrstvy.
5. `InputFilter` přes `@createInputs2`.
6. Query přes `PageResolver(... whereType=...)`.
7. Mutace přes `ExecuteServiceMethod`.

## Spuštění Coder

```bash
python .CoderDefinitions/main.py
```