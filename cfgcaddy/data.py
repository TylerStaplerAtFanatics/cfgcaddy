from __future__ import annotations

import re
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

import tomli_w  # noqa: F401 — imported so dependency is exercised; used by future writers

from cfgcaddy import LOCAL_DATA_PATH, PROFILES_DIR


class CfgcaddyError(Exception):
    pass


_PROFILE_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def validate_profile_name(name: str) -> None:
    """Raise CfgcaddyError if *name* is not a safe profile identifier."""
    if not _PROFILE_NAME_RE.match(name):
        raise CfgcaddyError(
            f"Invalid profile name {name!r}: only letters, digits, underscores, "
            "and hyphens are allowed."
        )
    # Path-traversal guard: resolved path must stay inside PROFILES_DIR
    candidate = (PROFILES_DIR / f"{name}.toml").resolve()
    try:
        candidate.relative_to(PROFILES_DIR.resolve())
    except ValueError as exc:
        raise CfgcaddyError(
            f"Profile name {name!r} resolves outside the profiles directory."
        ) from exc


class LocalDataLoader:
    """Load local TOML variables, optionally merged with a profile overlay."""

    def __init__(
        self,
        config_dir: Path = LOCAL_DATA_PATH.parent,
        profile: str | None = None,
    ) -> None:
        self.config_dir = config_dir
        self.profile = profile
        if profile is not None:
            validate_profile_name(profile)

    def load(self) -> dict:
        """Return the merged variable dict (base local.toml + optional profile)."""
        base_path = self.config_dir / "local.toml"
        try:
            with base_path.open("rb") as fh:
                data: dict = tomllib.load(fh)
        except FileNotFoundError:
            data = {}

        if self.profile is not None:
            profile_path = self.config_dir / "profiles" / f"{self.profile}.toml"
            try:
                with profile_path.open("rb") as fh:
                    profile_data: dict = tomllib.load(fh)
            except FileNotFoundError as exc:
                raise CfgcaddyError(
                    f"Profile file not found: {profile_path}"
                ) from exc
            # Shallow-merge: profile keys override base keys
            data = {**data, **profile_data}

        return data
