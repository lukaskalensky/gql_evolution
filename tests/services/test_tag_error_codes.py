import uuid

from src.ServiceDefinitions.Domain_Tags import ErrorCodes


def test_every_error_code_is_unique_uuid_with_description():
    constants = {
        name: value
        for name, value in vars(ErrorCodes).items()
        if name.startswith('TAG_')
    }

    assert constants
    assert len(set(constants.values())) == len(constants)
    assert set(constants.values()) == set(ErrorCodes.ERROR_CODES)
    for code, description in ErrorCodes.ERROR_CODES.items():
        assert str(uuid.UUID(code)) == code
        assert description.strip()
