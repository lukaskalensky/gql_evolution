
import logging


def assert_same(major, minor):
    for key in major:
        assert key in minor, f"Expected key '{key}' not found in minor result"
        assert major[key] == minor[key], f"Expected value for key '{key}' to be the same, but got {major[key]} and {minor[key]}"
    
def assert_read(result):
    errors = result.get("errors", None)
    assert errors is None, f"Unexpected errors: {errors}"
    data = result.get("data", None)
    assert data is not None, "Data must be present in the result"
    
    for key, value in data.items():
        assert value is not None, f"{key} must not be null"
        break

    assert "__typename" in value, f"Expected __typename field not found: {value}"
    if "Error" in value["__typename"]:
        logging.error(f"Insert failed with error: {result}")
        assert "msg" in value, f"Expected msg field not found in error: {value}"
        assert "code" in value, f"Expected code field not found in error: {value}"
        assert False, f"Insert failed with error: {value['msg']} (code: {value['code']})"

    assert "lastchange" in value, f"Expected lastchange field not found: {value}"
    assert "id" in value, f"Expected id field not found: {value}"
    return value


def assert_insert(result):

    errors = result.get("errors", None)
    assert errors is None, f"Unexpected errors: {errors}"
    data = result.get("data", None)
    assert data is not None, "Data must be present in the result"
    
    for key, value in data.items():
        assert value is not None, f"{key} must not be null"
        break

    if "__typename" not in value:
        logging.error(f"Insert failed, __typename field not found in result: {result}")
        assert False, f"Insert failed, __typename field not found in result: {result}"
    
    if "Error" in value["__typename"]:
        logging.error(f"Insert failed with error: {result}")
        assert "msg" in value, f"Expected msg field not found in error: {value}"
        assert "code" in value, f"Expected code field not found in error: {value}"
        assert False, f"Insert failed with error: {value['msg']} (code: {value['code']})"

    assert "lastchange" in value, f"Expected lastchange field not found: {value}"
    assert "id" in value, f"Expected id field not found: {value}"
    return value

def assert_update(result):

    errors = result.get("errors", None)
    assert errors is None, f"Unexpected errors: {errors}"
    data = result.get("data", None)
    assert data is not None, "Data must be present in the result"
    for key, value in data.items():
        assert value is not None, f"{key} must not be null"
        break

    assert "__typename" in value, f"Expected __typename field not found: {value}"
    if "Error" in value["__typename"]:
        if "Entity" in value:
            entity = value["Entity"]
            logging.error(f"Update failed with error: {result}, Entity: {entity}")
        assert "msg" in value, f"Expected msg field not found in error: {value}"
        assert "code" in value, f"Expected code field not found in error: {value}"
        assert False, f"Update failed with error: {value['msg']} (code: {value['code']})"
    assert "lastchange" in value, f"Expected lastchange field not found: {value}"
    assert "id" in value, f"Expected id field not found: {value}"

    return value

def assert_delete(result):

    errors = result.get("errors", None)
    assert errors is None, f"Unexpected errors: {errors}"
    
    assert "data" in result, "Data must be present in the result"
    data = result.get("data", None)
    for key, value in data.items():
        break

    if value is None:
        return None
    assert "__typename" in value, f"Expected __typename field not found: {value}"
    if "Error" in value["__typename"]:
        assert "msg" in value, f"Expected msg field not found in error: {value}"
        assert "code" in value, f"Expected code field not found in error: {value}"
        if "Entity" in value:
            entity = value["Entity"]
            logging.error(f"Update failed with error: {result}, Entity: {entity}")
        assert False, f"Update failed with error: {value['msg']} (code: {value['code']})"

    assert value is None, f"Delete failed: {value}"

def assert_typename_with_error(result, code=None):

    errors = result.get("errors", None)
    assert errors is None, f"Unexpected errors: {errors}"
    data = result.get("data", None)
    assert data is not None, "Data must be present in the result"
    for key, value in data.items():
        assert value is not None, f"{key} must not be null"
        break

    assert "__typename" in value, f"Expected __typename field not found: {value}"
    if "Error" in value["__typename"]:
        assert "msg" in value, f"Expected msg field not found in error: {value}"
        assert "code" in value, f"Expected code field not found in error: {value}"
        if code:
            return_code = value["code"]
            assert return_code == code, f"Expected error code '{code}', but got '{return_code}'"
    else:
        assert False, "result of operation must be an error, but got: {value}"
    return value

