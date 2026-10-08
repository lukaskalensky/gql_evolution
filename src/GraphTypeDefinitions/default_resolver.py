def gql_default_resolver(root, field_name):
    value = getattr(root, field_name, None)
    if value is not None:
        return value
    dbdata = getattr(root, '_dbdata', None)
    if dbdata is not None and hasattr(dbdata, field_name):
        return getattr(dbdata, field_name)
    return value
