# Tahák – prezentace 1. PD (databázová vrstva)

## Před začátkem
- Docker Desktop zapnutý (stack `uois`)
- pgAdmin: http://localhost:31122 (server `db` → Databases → `data`)
- VS Code terminál v kořeni projektu:

```bash
export POSTGRES_HOST=localhost:5432
```

## pgAdmin – Query Tool (pravým na `data` → Query Tool, spustit F5)

Tagy podle typů (hlavní dotaz, ten nech otevřený):
```sql
SELECT tt.name AS typ, t.label AS tag, t.color
FROM tags t JOIN tagtypes tt ON tt.id = t.type_id
ORDER BY 1, 2;
```

Strom typů:
```sql
SELECT p.name AS nadrazeny, t.name AS typ
FROM tagtypes t LEFT JOIN tagtypes p ON p.id = t.parent_id
ORDER BY 1 NULLS FIRST, 2;
```

Scénář Projekt A (jaké tagy má entita):
```sql
SELECT te.entity_id, t.label
FROM tag_entities te JOIN tags t ON t.id = te.tag_id
WHERE te.entity_id = '11111111-aaaa-aaaa-aaaa-aaaaaaaaaaaa';
```

## Terminál – živá ukázka

1. Vytvořit tag (pak v pgAdminu F5 → přibude „Kategorie | Prezentace“):
```bash
.venv/bin/python -m src.DBDefinitions.main Tag create '{"id":"d0000000-0000-0000-0000-000000000001","name":"demo","label":"Prezentace","color":"#13c2c2","type_id":"a0000000-0000-0000-0000-000000000005"}'
```

2. Upravit tag:
```bash
.venv/bin/python -m src.DBDefinitions.main Tag update '{"id":"d0000000-0000-0000-0000-000000000001","label":"Prezentace 1. PD"}'
```

3. Databáze hlídá vazby (neexistující typ → ForeignKeyViolationError):
```bash
.venv/bin/python -m src.DBDefinitions.main Tag create '{"name":"spatny","type_id":"a0000000-0000-0000-0000-000000000099"}'
```

4. Úklid – NEVYNECHAT:
```bash
.venv/bin/python -m src.DBDefinitions.main Tag delete '{"id":"d0000000-0000-0000-0000-000000000001"}'
```

5. Testy (výsledek: 21 passed):
```bash
DEMODATA=True .venv/bin/python -m pytest tests/db -q --no-cov
```
