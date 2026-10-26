"""Duration helpers."""


def parse_duration(text):
    """Return the number of seconds in a duration string such as '1h30m', '45s', '2d' or '1d2h3m4s'.

    Units: d, h, m, s. Whitespace between parts is allowed. Raise ValueError for empty or invalid text.
    """
    raise NotImplementedError


def format_duration(seconds):
    """Return the shortest d/h/m/s string for a non-negative int number of seconds, e.g. 5400 -> '1h30m', 0 -> '0s'."""
    raise NotImplementedError
