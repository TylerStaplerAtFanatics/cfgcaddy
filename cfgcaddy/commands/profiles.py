from __future__ import annotations

import click
import questionary
import tomli_w

from cfgcaddy import PROFILES_DIR
from cfgcaddy.data import CfgcaddyError, validate_profile_name


@click.group(name="profiles")
def profiles():
    """Manage cfgcaddy profiles"""
    pass


@profiles.command(name="list")
def list_profiles():
    """List available profiles"""
    if not PROFILES_DIR.exists():
        click.echo("No profiles found.")
        return

    toml_files = sorted(PROFILES_DIR.glob("*.toml"))
    if not toml_files:
        click.echo("No profiles found.")
        return

    for f in toml_files:
        click.echo(f.stem)


@profiles.command()
@click.argument("name")
def init(name: str):
    """Create a new profile interactively"""
    try:
        validate_profile_name(name)
    except CfgcaddyError as exc:
        raise click.ClickException(str(exc)) from exc

    PROFILES_DIR.mkdir(parents=True, exist_ok=True)

    data: dict = {}
    click.echo("Enter key-value pairs for the profile (empty key to finish).")
    while True:
        key = questionary.text("Key:").ask()
        if key is None or key.strip() == "":
            break
        value = questionary.text(f"Value for {key!r}:").ask()
        if value is None:
            break
        data[key.strip()] = value

    profile_path = PROFILES_DIR / f"{name}.toml"
    with profile_path.open("wb") as fh:
        tomli_w.dump(data, fh)

    click.echo(f"Profile {name!r} written to {profile_path}")
