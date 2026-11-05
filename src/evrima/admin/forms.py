"""Small helpers for reading admin forms, shared by every module.

Modules parse their forms by hand (docs/modules.md, "Forms"); these helpers
cover the parts that are easy to get subtly wrong and are copied from module
to module.
"""

# Ids are database integers. Anything outside this range cannot be a real id,
# and a huge number would make some databases raise instead of finding nothing.
MAX_ID = 2**31 - 1


def parse_id(value: str | None) -> int | None:
    """An id typed or sent by the browser, or None when it is not a valid one.

    `str.isdigit()` is not enough: it accepts characters such as "²" that
    `int()` refuses, which would turn a crafted request into an error 500.
    """
    value = (value or "").strip()
    if not value.isascii() or not value.isdecimal():
        return None
    number = int(value)
    return number if 0 < number <= MAX_ID else None


def parse_ids(value: str | None) -> list[int]:
    """A comma-separated list of ids (e.g. a new order), invalid parts left out."""
    ids = (parse_id(part) for part in (value or "").split(","))
    return [i for i in ids if i is not None]
