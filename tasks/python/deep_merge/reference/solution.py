import copy


def deep_merge(a: dict, b: dict) -> dict:
    result = copy.deepcopy(a)
    for key, value in b.items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result
