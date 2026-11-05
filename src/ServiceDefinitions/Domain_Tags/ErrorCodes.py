"""Slovník chybových kódů služeb domény Tags: UUID kódu -> popis chyby."""

TAG_TYPE_NOT_FOUND = '9fcaa606-eab2-4a77-8f3e-1a237f6224dc'
TAG_TYPE_CONFLICT = '9a1e9fef-fc40-4789-823f-beba9723bb87'
TAG_TYPE_PARENT_NOT_FOUND = 'd8c49b51-2278-4b30-a1f2-11958c35cef1'
TAG_TYPE_CYCLE = '27211a6b-9d95-4d47-9052-9942f58fb170'
TAG_TYPE_HAS_CHILDREN = '39bc0107-6e99-4b48-9a9f-077ecca1d0b7'
TAG_TYPE_HAS_TAGS = 'c13c3238-f1d8-41ef-aead-b4a61215da43'
TAG_NOT_FOUND = 'd6ba9b9d-d649-4a8b-af69-85030e7fdad5'
TAG_CONFLICT = '05831589-381c-4dea-9988-fd68ddf75e3e'
TAG_TYPE_REFERENCE_NOT_FOUND = 'f2613d78-5f45-42e5-88a3-189797d81efd'
TAG_HAS_ASSIGNMENTS = '1668c263-a446-4457-afbd-88c6cebc3a83'
TAG_ENTITY_NOT_FOUND = '7f7338a5-43ca-447f-bfd0-dd6a22b1cb2e'
TAG_ENTITY_CONFLICT = '30923b3d-2ace-4088-b72d-fb38e6392a99'
TAG_ENTITY_TAG_NOT_FOUND = '7fd571ea-392d-45af-a79a-f56c33f64c81'
TAG_ENTITY_INVALID_INPUT = '75ae4be1-2a31-4e2b-be7e-7a5cf269e058'
TAG_ENTITY_USER_REQUIRED = '1c965f5e-c461-4881-81a7-ab46f158d516'
TAG_ENTITY_NOT_OWNER = '5b693bc1-5b34-4071-bb8e-f9e0f1f79932'

ERROR_CODES = {
    TAG_TYPE_NOT_FOUND: 'Typ tagu s daným id neexistuje.',
    TAG_TYPE_CONFLICT: 'Typ tagu mezitím změnil někdo jiný (zastaralý lastchange).',
    TAG_TYPE_PARENT_NOT_FOUND: 'Nadřazený typ tagu neexistuje.',
    TAG_TYPE_CYCLE: 'Změna nadřazeného typu by ve stromu typů vytvořila cyklus.',
    TAG_TYPE_HAS_CHILDREN: 'Typ tagu nelze smazat, protože má podřízené typy.',
    TAG_TYPE_HAS_TAGS: 'Typ tagu nelze smazat, protože ho používají tagy.',
    TAG_NOT_FOUND: 'Tag s daným id neexistuje.',
    TAG_CONFLICT: 'Tag mezitím změnil někdo jiný (zastaralý lastchange).',
    TAG_TYPE_REFERENCE_NOT_FOUND: 'Typ přiřazovaný k tagu neexistuje.',
    TAG_HAS_ASSIGNMENTS: 'Tag nelze smazat, protože je přiřazený k entitám.',
    TAG_ENTITY_NOT_FOUND: 'Přiřazení tagu s daným id neexistuje.',
    TAG_ENTITY_CONFLICT: 'Přiřazení tagu mezitím změnil někdo jiný (zastaralý lastchange).',
    TAG_ENTITY_TAG_NOT_FOUND: 'Přiřazovaný tag neexistuje.',
    TAG_ENTITY_INVALID_INPUT: 'Přiřazení tagu musí obsahovat entity_id, entity_type_id a tag_id.',
    TAG_ENTITY_USER_REQUIRED: 'Operace vyžaduje přihlášeného uživatele.',
    TAG_ENTITY_NOT_OWNER: 'Přiřazení tagu může odebrat pouze jeho vlastník.',
}
