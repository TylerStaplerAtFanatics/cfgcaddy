from __future__ import annotations

import sys
from pathlib import Path

import click
import jinja2
import jinja2.meta
import questionary
import tomli_w

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from cfgcaddy import LOCAL_DATA_PATH


@click.group()
def secrets():
    """Manage local secrets and template variables"""
    pass


@secrets.command()
@click.option(
    "-c",
    "--config",
    default=None,
    help="The path to your cfgcaddy.yml",
)
def init(config):
    """Scan .tmpl files and interactively populate local.toml"""
    import cfgcaddy
    from cfgcaddy.config import LinkerConfig

    config_path = config or cfgcaddy.DEFAULT_CONFIG_PATH
    linker_config = LinkerConfig(config_file_path=config_path)
    linker_src = Path(linker_config.linker_src)

    # Collect all template variables from *.tmpl files
    env = jinja2.Environment(undefined=jinja2.Undefined, autoescape=False)
    all_vars: set[str] = set()
    for tmpl_file in linker_src.rglob("*.tmpl"):
        try:
            source = tmpl_file.read_text()
            ast = env.parse(source)
            all_vars.update(jinja2.meta.find_undeclared_variables(ast))
        except jinja2.TemplateSyntaxError:
            click.echo(
                f"Warning: could not parse {tmpl_file} for variable discovery.",
                err=True,
            )

    # Load existing local.toml
    existing: dict = {}
    if LOCAL_DATA_PATH.exists():
        with LOCAL_DATA_PATH.open("rb") as fh:
            existing = tomllib.load(fh)

    # Prompt for any variable not already set
    new_values: dict = {}
    for var in sorted(all_vars):
        if var in existing:
            continue
        value = questionary.text(f"Enter value for '{var}':").ask()
        if value is not None:
            new_values[var] = value

    if not new_values and not all_vars:
        click.echo("No template variables found in .tmpl files.")
        return

    # Merge and write
    merged = {**existing, **new_values}
    LOCAL_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_DATA_PATH.write_bytes(tomli_w.dumps(merged).encode())

    if new_values:
        click.echo(
            f"\nWrote {len(new_values)} variable(s) to {LOCAL_DATA_PATH}:"
        )
        for var in sorted(new_values):
            click.echo(f"  {var}")
    else:
        click.echo(f"No new variables written ({LOCAL_DATA_PATH} already up to date).")

    if all_vars:
        click.echo(
            "\nTip: use {{% raw %}}...{{% endraw %}} to escape literal {{{{ }}}} "
            "sequences in your templates that should not be treated as variables."
        )
