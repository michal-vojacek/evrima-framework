"""The installed Evrima version.

The version comes from the Git tag at build time (hatch-vcs), so the package
metadata is the only source of truth and the number cannot drift from the tag.
"""

from importlib.metadata import PackageNotFoundError, version


def get_version() -> str:
    """Return the installed version, or "0+unknown" when running from a plain checkout."""
    try:
        return version("evrima")
    except PackageNotFoundError:
        return "0+unknown"
