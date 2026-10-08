import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src'


def py_files():
    return [p for p in SRC.rglob('*.py') if '__pycache__' not in p.parts]


def test_all_python_files_are_parseable():
    for path in py_files():
        ast.parse(path.read_text(encoding='utf-8'), filename=str(path))



# def test_gql_layer_does_not_import_db_layer():
#     gql_root = SRC / 'GraphTypeDefinitions'
#     violations = []

#     for path in gql_root.rglob('*.py'):
#         source = path.read_text(encoding='utf-8')
#         tree = ast.parse(source, filename=str(path))

#         for node in ast.walk(tree):
#             if isinstance(node, ast.ImportFrom) and node.module and 'DBDefinitions' in node.module:
#                 violations.append(f"{path}:{node.lineno} -> from {node.module} import ...")

#             if isinstance(node, ast.Import):
#                 for alias in node.names:
#                     if 'DBDefinitions' in alias.name:
#                         violations.append(f"{path}:{node.lineno} -> import {alias.name}")

#     assert not violations, "Found forbidden imports:\n" + "\n".join(violations)



def test_gql_uses_loader_name_contract_not_db_model_contract():
    text = (SRC / 'GraphTypeDefinitions' / 'Domain_Events' / 'EventGQLModel.py').read_text(encoding='utf-8')
    assert "LoaderName = 'EventModel'" in text
    assert 'DBModel' not in text


def test_page_filters_are_createinputs2():
    event_text = (SRC / 'GraphTypeDefinitions' / 'Domain_Events' / 'EventGQLModel.py').read_text(encoding='utf-8')
    invitation_text = (SRC / 'GraphTypeDefinitions' / 'Domain_Events' / 'EventInvitationGQLModel.py').read_text(encoding='utf-8')
    assert '@createInputs2\nclass EventInputFilter' in event_text
    assert '@createInputs2\nclass EventInvitationInputFilter' in invitation_text
    assert 'PageResolver[EventGQLModel](whereType=EventInputFilter)' in event_text
    assert 'PageResolver[EventInvitationGQLModel](whereType=EventInvitationInputFilter)' in invitation_text


def test_base_gql_keeps_original_data_reference():
    text = (SRC / 'GraphTypeDefinitions' / 'BaseGQLModel.py').read_text(encoding='utf-8')
    assert '_dbdata' in text
    assert 'dataclasses.asdict' not in text
    assert 'EntityProtocol' in text
