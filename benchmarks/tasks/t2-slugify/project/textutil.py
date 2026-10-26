"""Small text helpers."""
import re


def slugify(text):
    """Lowercase URL slug: letters and digits separated by single hyphens, no leading or trailing hyphen."""
    return re.sub(r'[^a-z0-9]', '-', text.lower())


def truncate(text, limit):
    """Cut text to at most `limit` characters, adding '...' when it was cut."""
    if len(text) <= limit:
        return text
    return text[:limit] + '...'
