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