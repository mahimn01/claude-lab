import re


class TemplateError(ValueError):
    pass


_TOKEN = re.compile(r"(\{\{.*?\}\})", re.S)


def tokenize(source):
    """Split a template into ('text', str) and ('var', expression) tokens."""
    tokens = []
    for part in _TOKEN.split(source):
        if part.startswith("{{") and part.endswith("}}"):
            tokens.append(("var", part[2:-2].strip()))
        elif part:
            tokens.append(("text", part))
    return tokens
