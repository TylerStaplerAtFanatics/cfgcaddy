"""cfgcaddy diff — show pending symlink changes without applying them."""
from __future__ import annotations

import difflib
import os
import sys

import click
from rich.console import Console
from rich.syntax import Syntax

import cfgcaddy
import cfgcaddy.config
import cfgcaddy.linker
from cfgcaddy.link import Link
from cfgcaddy.template import TemplateRenderer


def show_link_diff(
    console: Console,
    action: str,
    link: Link,
    renderer: TemplateRenderer,
) -> None:
    """Print a single link diff entry to *console*."""
    if action == "new":
        console.print(f"[green][+] {link.src} → {link.dest}[/green]")
    elif action == "conflict":
        console.print(
            f"[red][!] CONFLICT: {link.dest} exists as a regular file (not a symlink)[/red]"
        )
    elif action == "broken":
        console.print(f"[red][~] BROKEN: {link.dest} is a broken symlink[/red]")
    elif action == "changed":
        was = os.readlink(link.dest)
        console.print(
            f"[yellow][~] CHANGED: {link.dest} → {link.src} (was: {was})[/yellow]"
        )
    elif action == "content_changed":
        rendered = renderer.render_to_string(link.src)
        if rendered is None:
            # Fallback: not actually a template — treat as changed
            console.print(f"[yellow][~] CONTENT_CHANGED: {link.dest}[/yellow]")
            return
        try:
            current = link.dest.read_text()
        except OSError:
            current = ""
        diff_lines = list(
            difflib.unified_diff(
                current.splitlines(keepends=True),
                rendered.splitlines(keepends=True),
                fromfile=str(link.dest),
                tofile=str(link.src),
            )
        )
        if diff_lines:
            diff_text = "".join(diff_lines)
            console.print(
                Syntax(diff_text, lexer="diff", theme="ansi_dark")
            )


@click.command()
@click.option(
    "-c",
    "--config",
    default=cfgcaddy.DEFAULT_CONFIG_PATH,
    help="Path to cfgcaddy.yml",
)
@click.option(
    "--profile",
    envvar="CFGCADDY_PROFILE",
    default=None,
    help="Active profile name",
)
@click.pass_context
def diff(ctx, config, profile):
    """Show pending symlink changes without applying them."""
    if not os.path.isfile(config):
        click.echo(
            "Cannot find cfgcaddy.yml, please specify path to config using '-c' option.",
            err=True,
        )
        sys.exit(2)

    cfg = cfgcaddy.config.LinkerConfig(config_file_path=config, profile=profile)
    linker = cfgcaddy.linker.Linker(cfg, dry_run=True)
    planned = linker.resolve_planned_links()

    # Filter out already-correct links
    pending = [(action, link) for action, link in planned if action != "ok"]

    if not pending:
        click.echo("No changes.")
        sys.exit(0)

    console = Console()
    renderer = cfg.renderer
    for action, link in pending:
        show_link_diff(console, action, link, renderer)

    sys.exit(1)
