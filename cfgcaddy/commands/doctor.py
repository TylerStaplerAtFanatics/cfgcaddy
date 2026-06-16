"""cfgcaddy doctor command – audit dotfile state across 7 checks."""
from __future__ import annotations

import enum
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import click
import jinja2
import jinja2.meta
from rich.console import Console

import cfgcaddy
import cfgcaddy.config
from cfgcaddy import LOCAL_DATA_PATH
from cfgcaddy.alternate import parse_alternate_name, score_candidate, select_candidate
from cfgcaddy.config import LinkerConfig

# ---------------------------------------------------------------------------
# Core types
# ---------------------------------------------------------------------------


class CheckLevel(enum.IntEnum):
    PASS = 0
    WARN = 1
    FAIL = 2


@dataclass
class CheckResult:
    level: CheckLevel
    name: str
    message: str


class Check(Protocol):
    def name(self) -> str: ...
    def run(self) -> CheckResult: ...


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_all_checks(checks: list[Check], console: Console, fix: bool = False) -> int:
    """Run all checks, print results, return worst CheckLevel value as exit code."""
    worst = CheckLevel.PASS

    for check in checks:
        import inspect

        run_fn = check.run
        sig = inspect.signature(run_fn)
        if "fix" in sig.parameters:
            result = run_fn(fix=fix)
        else:
            result = run_fn()

        if result.level == CheckLevel.PASS:
            icon = "[green]✓[/]"
        elif result.level == CheckLevel.WARN:
            icon = "[yellow]![/]"
        else:
            icon = "[red]✗[/]"

        console.print(f"{icon} {result.name}: {result.message}")

        if result.level > worst:
            worst = result.level

    return int(worst)


# ---------------------------------------------------------------------------
# Check implementations
# ---------------------------------------------------------------------------


class BrokenSymlinksCheck:
    def __init__(self, linker_config: LinkerConfig) -> None:
        self._cfg = linker_config

    def name(self) -> str:
        return "BrokenSymlinks"

    def run(self, fix: bool = False) -> CheckResult:
        broken: list[Path] = []
        dest = Path(self._cfg.linker_dest)
        if not dest.exists():
            return CheckResult(CheckLevel.PASS, self.name(), "No broken symlinks found")

        for item in dest.rglob("*"):
            if item.is_symlink() and not item.resolve().exists():
                broken.append(item)

        if not broken:
            return CheckResult(CheckLevel.PASS, self.name(), "No broken symlinks found")

        if fix:
            for path in broken:
                path.unlink()
            names = ", ".join(str(p) for p in broken[:3])
            return CheckResult(
                CheckLevel.WARN,
                self.name(),
                f"Removed {len(broken)} broken symlink(s): {names}",
            )

        names = ", ".join(str(p) for p in broken[:3])
        extra = f" (and {len(broken) - 3} more)" if len(broken) > 3 else ""
        return CheckResult(
            CheckLevel.FAIL,
            self.name(),
            f"Found {len(broken)} broken symlink(s): {names}{extra}",
        )


class SymlinkDriftCheck:
    def __init__(self, linker_config: LinkerConfig) -> None:
        self._cfg = linker_config

    def name(self) -> str:
        return "SymlinkDrift"

    def run(self) -> CheckResult:
        drifted: list[str] = []

        for link in self._cfg.links:
            dest = Path(link.dest)
            src = Path(link.src)
            if not dest.exists() and not dest.is_symlink():
                # Not yet linked — not drift
                continue
            if dest.is_symlink():
                current_target = os.readlink(str(dest))
                if current_target != str(src):
                    drifted.append(f"{dest} -> {current_target} (expected {src})")

        if not drifted:
            return CheckResult(CheckLevel.PASS, self.name(), "All symlinks point to correct sources")

        return CheckResult(
            CheckLevel.WARN,
            self.name(),
            f"{len(drifted)} symlink(s) point to wrong source: {drifted[0]}",
        )


class MissingVariablesCheck:
    def __init__(self, linker_config: LinkerConfig) -> None:
        self._cfg = linker_config

    def name(self) -> str:
        return "MissingVariables"

    def run(self) -> CheckResult:
        linker_src = Path(self._cfg.linker_src)
        env = jinja2.Environment()
        missing: list[str] = []

        for tmpl_file in linker_src.rglob("*.tmpl"):
            try:
                source = tmpl_file.read_text()
                ast = env.parse(source)
                undeclared = jinja2.meta.find_undeclared_variables(ast)
                for var in sorted(undeclared):
                    if var not in self._cfg.local_data:
                        missing.append(f"{var} (in {tmpl_file})")
            except Exception:
                pass

        if not missing:
            return CheckResult(CheckLevel.PASS, self.name(), "All template variables are defined")

        return CheckResult(
            CheckLevel.FAIL,
            self.name(),
            f"Missing variable(s): {'; '.join(missing[:5])}",
        )


class MissingLocalTomlCheck:
    def __init__(self, linker_config: LinkerConfig) -> None:
        self._cfg = linker_config

    def name(self) -> str:
        return "MissingLocalToml"

    def run(self) -> CheckResult:
        linker_src = Path(self._cfg.linker_src)
        tmpl_files = list(linker_src.rglob("*.tmpl"))

        if not tmpl_files:
            return CheckResult(CheckLevel.PASS, self.name(), "No template files — local.toml not required")

        if LOCAL_DATA_PATH.exists():
            return CheckResult(CheckLevel.PASS, self.name(), "local.toml found")

        return CheckResult(
            CheckLevel.WARN,
            self.name(),
            f"Template files found but local.toml is missing at {LOCAL_DATA_PATH}. "
            "Run `cfgcaddy secrets init` to create it.",
        )


class AmbiguousAlternatesCheck:
    def __init__(self, linker_config: LinkerConfig) -> None:
        self._cfg = linker_config

    def name(self) -> str:
        return "AmbiguousAlternates"

    def run(self) -> CheckResult:
        linker_src = Path(self._cfg.linker_src)
        if not linker_src.exists():
            return CheckResult(CheckLevel.PASS, self.name(), "No ambiguous alternates")

        groups: dict[str, list[Path]] = {}
        for item in linker_src.rglob("*"):
            if item.is_file():
                base_name, _ = parse_alternate_name(item.name)
                groups.setdefault(base_name, []).append(item)

        ctx = self._cfg.alternate_context
        ambiguous: list[str] = []

        for base_name, candidates in groups.items():
            scored: list[tuple[int, Path]] = []
            for candidate in candidates:
                s = score_candidate(candidate.name, ctx)
                if s is not None:
                    scored.append((s, candidate))

            if len(scored) < 2:
                continue

            max_score = max(s for s, _ in scored)
            winners = [p for s, p in scored if s == max_score]
            if len(winners) >= 2:
                names = ", ".join(p.name for p in winners)
                ambiguous.append(f"{base_name}: {names}")

        if not ambiguous:
            return CheckResult(CheckLevel.PASS, self.name(), "No ambiguous alternates found")

        return CheckResult(
            CheckLevel.WARN,
            self.name(),
            f"Tied alternates for: {'; '.join(ambiguous)}",
        )


class OpCliCheck:
    def __init__(self, linker_config: LinkerConfig) -> None:
        self._cfg = linker_config

    def name(self) -> str:
        return "OpCli"

    def _has_op_refs(self, data: dict) -> bool:
        for value in data.values():
            if isinstance(value, dict):
                if self._has_op_refs(value):
                    return True
            elif isinstance(value, str) and "op://" in value:
                return True
        return False

    def run(self) -> CheckResult:
        if not self._has_op_refs(self._cfg.local_data):
            return CheckResult(CheckLevel.PASS, self.name(), "No 1Password references found")

        if shutil.which("op") is not None:
            return CheckResult(CheckLevel.PASS, self.name(), "1Password CLI (op) is installed")

        return CheckResult(
            CheckLevel.WARN,
            self.name(),
            "local.toml contains op:// references but `op` is not on PATH. "
            "Install the 1Password CLI: https://1password.com/downloads/command-line/",
        )


class NoUnmatchedAlternatesCheck:
    def __init__(self, linker_config: LinkerConfig) -> None:
        self._cfg = linker_config

    def name(self) -> str:
        return "NoUnmatchedAlternates"

    def run(self) -> CheckResult:
        linker_src = Path(self._cfg.linker_src)
        if not linker_src.exists():
            return CheckResult(CheckLevel.PASS, self.name(), "No unmatched alternates")

        # Group files by base name
        groups: dict[str, list[Path]] = {}
        for item in linker_src.rglob("*"):
            if item.is_file():
                base_name, conditions = parse_alternate_name(item.name)
                # Track whether this file has any ## suffix
                groups.setdefault(base_name, []).append(item)

        ctx = self._cfg.alternate_context
        unmatched: list[str] = []

        for base_name, candidates in groups.items():
            # Skip if there is a bare file (no ## suffix) or a ##default
            has_bare_or_default = False
            for candidate in candidates:
                _, conditions = parse_alternate_name(candidate.name)
                if not conditions:
                    has_bare_or_default = True
                    break
                if any(key == "default" for key, _ in conditions):
                    has_bare_or_default = True
                    break

            if has_bare_or_default:
                continue

            # All candidates have ## suffixes — check if any match
            winner = select_candidate(candidates, ctx)
            if winner is None:
                unmatched.append(base_name)

        if not unmatched:
            return CheckResult(CheckLevel.PASS, self.name(), "All alternates have a matching candidate")

        return CheckResult(
            CheckLevel.WARN,
            self.name(),
            f"No candidate matches for: {', '.join(unmatched)}",
        )


# ---------------------------------------------------------------------------
# Click command
# ---------------------------------------------------------------------------


@click.command()
@click.option(
    "-c",
    "--config",
    default=cfgcaddy.DEFAULT_CONFIG_PATH,
    help="Path to your cfgcaddy.yml",
)
@click.option(
    "--profile",
    envvar="CFGCADDY_PROFILE",
    default=None,
    help="Active profile name",
)
@click.option("--fix", is_flag=True, help="Auto-repair broken symlinks")
def doctor(config, profile, fix):
    """Audit dotfile state and report issues."""
    console = Console()
    linker_config = cfgcaddy.config.LinkerConfig(config_file_path=config, profile=profile)
    checks: list[Check] = [
        BrokenSymlinksCheck(linker_config),
        SymlinkDriftCheck(linker_config),
        MissingVariablesCheck(linker_config),
        MissingLocalTomlCheck(linker_config),
        AmbiguousAlternatesCheck(linker_config),
        OpCliCheck(linker_config),
        NoUnmatchedAlternatesCheck(linker_config),
    ]
    result = run_all_checks(checks, console, fix=fix)
    sys.exit(result)
