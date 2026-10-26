from .lexer import tokenize

MISSING = object()


def lookup(path, context):
    """Resolve a dotted path against nested dicts and objects. Returns MISSING if any part is absent."""
    value = context
    for part in path.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif hasattr(value, part):
            value = getattr(value, part)
        else:
            return MISSING
    return value


def render(template, context=None):
    context = context or {}
    out = []
    for kind, body in tokenize(template):
        if kind == "text":
            out.append(body)
        else:
            value = lookup(body, context)
            out.append("" if value is MISSING or value is None else str(value))
    return "".join(out)
