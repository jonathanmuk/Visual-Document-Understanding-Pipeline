"""Which local files the server is allowed to read.

The MCP Roots feature was the protocol's way for a host to scope a server to
certain folders. It is deprecated as of the 2026-07-28 specification (SEP-2577),
and it was never a security boundary: the specification itself called it a
convention. This module is the enforcement, and it does not depend on the host.

Allowed directories come from VDU_ALLOWED_DIRS (path-separator delimited, so
";" on Windows and ":" elsewhere). If unset, only the current working directory
is allowed. A path is accepted only if, after resolving symlinks and "..", it is
inside one of those directories.
"""
import os
from pathlib import Path


class PathNotAllowed(Exception):
    pass


def allowed_dirs() -> list[Path]:
    raw = os.getenv("VDU_ALLOWED_DIRS", "")
    parts = [p for p in raw.split(os.pathsep) if p.strip()] if raw else [os.getcwd()]
    return [Path(p).expanduser().resolve() for p in parts]


def resolve_allowed(path_str: str, roots: list[Path] | None = None) -> Path:
    roots = roots if roots is not None else allowed_dirs()
    try:
        candidate = Path(path_str).expanduser().resolve(strict=True)
    except FileNotFoundError:
        raise PathNotAllowed(f"file not found: {path_str}")
    except OSError as e:
        raise PathNotAllowed(f"cannot resolve {path_str}: {e}")
    if not candidate.is_file():
        raise PathNotAllowed(f"not a file: {path_str}")
    for root in roots:
        try:
            candidate.relative_to(root)
            return candidate
        except ValueError:
            continue
    listed = ", ".join(str(r) for r in roots)
    raise PathNotAllowed(
        f"{path_str} is outside the allowed directories ({listed}). "
        f"Set VDU_ALLOWED_DIRS to permit more."
    )
