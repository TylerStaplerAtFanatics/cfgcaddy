"""Tests for cfgcaddy diff command and --dry-run alias (Epic 5)."""
from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner
from ruamel.yaml import YAML

from cfgcaddy.__main__ import main

yaml = YAML(typ="safe")


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def write_config(cfg_path: Path, src_dir: Path, dest_dir: Path, links: list | None = None):
    """Write a minimal .cfgcaddy.yml pointing at src_dir / dest_dir."""
    config = {
        "preferences": {
            "linker_src": str(src_dir),
            "linker_dest": str(dest_dir),
        },
        "links": links or [],
        "ignore": [],
    }
    with open(cfg_path, "w") as fh:
        yaml.dump(config, fh)
    return cfg_path


def invoke_diff(runner: CliRunner, cfg_path: Path, extra_args: list | None = None):
    args = ["diff", "-c", str(cfg_path)] + (extra_args or [])
    return runner.invoke(main, args, catch_exceptions=False)


def invoke_link_dry_run(runner: CliRunner, cfg_path: Path):
    return runner.invoke(
        main, ["link", "-c", str(cfg_path), "--dry-run"], catch_exceptions=False
    )


# ---------------------------------------------------------------------------
# Test: exit 0 — no pending changes (all links already correct)
# ---------------------------------------------------------------------------


def test_no_changes_exit_0(tmp_path):
    src_dir = tmp_path / "src"
    dest_dir = tmp_path / "dest"
    src_dir.mkdir()
    dest_dir.mkdir()

    # Create a source file and a correct symlink pointing to it
    src_file = src_dir / ".foo"
    src_file.write_text("content")
    dest_link = dest_dir / ".foo"
    dest_link.symlink_to(src_file)

    cfg_path = tmp_path / ".cfgcaddy.yml"
    write_config(cfg_path, src_dir, dest_dir, links=[])

    runner = CliRunner()
    result = invoke_diff(runner, cfg_path)
    assert result.exit_code == 0
    assert "No changes" in result.output


# ---------------------------------------------------------------------------
# Test: exit 1 — new link pending (link.dest doesn't exist)
# ---------------------------------------------------------------------------


def test_new_link_exit_1(tmp_path):
    src_dir = tmp_path / "src"
    dest_dir = tmp_path / "dest"
    src_dir.mkdir()
    dest_dir.mkdir()

    src_file = src_dir / ".bar"
    src_file.write_text("hello")
    # Do NOT create the dest symlink

    cfg_path = tmp_path / ".cfgcaddy.yml"
    write_config(cfg_path, src_dir, dest_dir, links=[])

    runner = CliRunner()
    result = invoke_diff(runner, cfg_path)
    assert result.exit_code == 1
    assert "[+]" in result.output or "bar" in result.output


# ---------------------------------------------------------------------------
# Test: exit 1 — changed link (symlink points to wrong src)
# ---------------------------------------------------------------------------


def test_changed_link_exit_1(tmp_path):
    src_dir = tmp_path / "src"
    dest_dir = tmp_path / "dest"
    src_dir.mkdir()
    dest_dir.mkdir()

    src_file = src_dir / ".baz"
    src_file.write_text("correct content")

    # Dest points to a different (wrong) file
    wrong_target = tmp_path / "wrong"
    wrong_target.write_text("wrong")
    dest_link = dest_dir / ".baz"
    dest_link.symlink_to(wrong_target)

    cfg_path = tmp_path / ".cfgcaddy.yml"
    write_config(cfg_path, src_dir, dest_dir, links=[])

    runner = CliRunner()
    result = invoke_diff(runner, cfg_path)
    assert result.exit_code == 1
    assert "CHANGED" in result.output or "[~]" in result.output


# ---------------------------------------------------------------------------
# Test: exit 1 — broken symlink
# ---------------------------------------------------------------------------


def test_broken_symlink_exit_1(tmp_path):
    src_dir = tmp_path / "src"
    dest_dir = tmp_path / "dest"
    src_dir.mkdir()
    dest_dir.mkdir()

    src_file = src_dir / ".qux"
    src_file.write_text("data")

    gone = tmp_path / "gone"
    dest_link = dest_dir / ".qux"
    dest_link.symlink_to(gone)  # points to non-existent target

    cfg_path = tmp_path / ".cfgcaddy.yml"
    write_config(cfg_path, src_dir, dest_dir, links=[])

    runner = CliRunner()
    result = invoke_diff(runner, cfg_path)
    assert result.exit_code == 1
    assert "BROKEN" in result.output or "[~]" in result.output


# ---------------------------------------------------------------------------
# Test: exit 1 — conflict (regular file at link.dest)
# ---------------------------------------------------------------------------


def test_conflict_exit_1(tmp_path):
    src_dir = tmp_path / "src"
    dest_dir = tmp_path / "dest"
    src_dir.mkdir()
    dest_dir.mkdir()

    src_file = src_dir / ".conflict"
    src_file.write_text("source")
    dest_file = dest_dir / ".conflict"
    dest_file.write_text("I am a real file, not a symlink")

    cfg_path = tmp_path / ".cfgcaddy.yml"
    write_config(cfg_path, src_dir, dest_dir, links=[])

    runner = CliRunner()
    result = invoke_diff(runner, cfg_path)
    assert result.exit_code == 1
    assert "CONFLICT" in result.output


# ---------------------------------------------------------------------------
# Test: --dry-run alias — cfgcaddy link --dry-run exits same code as cfgcaddy diff
# ---------------------------------------------------------------------------


def test_dry_run_alias_matches_diff(tmp_path):
    src_dir = tmp_path / "src"
    dest_dir = tmp_path / "dest"
    src_dir.mkdir()
    dest_dir.mkdir()

    src_file = src_dir / ".newfile"
    src_file.write_text("new")

    cfg_path = tmp_path / ".cfgcaddy.yml"
    write_config(cfg_path, src_dir, dest_dir, links=[])

    runner = CliRunner()
    diff_result = invoke_diff(runner, cfg_path)
    dry_run_result = invoke_link_dry_run(runner, cfg_path)

    assert diff_result.exit_code == dry_run_result.exit_code


# ---------------------------------------------------------------------------
# Test: template content diff — a .tmpl file whose rendered output differs
# ---------------------------------------------------------------------------


def test_template_content_diff_shown(tmp_path, monkeypatch):
    """A .tmpl source with stale deployed content triggers exit code 1."""
    src_dir = tmp_path / "src"
    dest_dir = tmp_path / "dest"
    src_dir.mkdir()
    dest_dir.mkdir()

    # Use a template with no variables so we don't need local.toml
    tmpl_src = src_dir / ".myconfig.tmpl"
    tmpl_src.write_text("version=2\n")

    # Point the rendered cache dir at a tmp location so we don't pollute real cache
    import cfgcaddy as _cfgcaddy
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    monkeypatch.setattr(_cfgcaddy, "RENDERED_CACHE_DIR", cache_dir)

    dest_link_path = dest_dir / ".myconfig"

    cfg_path = tmp_path / ".cfgcaddy.yml"
    write_config(
        cfg_path,
        src_dir,
        dest_dir,
        links=[{"src": ".myconfig.tmpl", "dest": str(dest_link_path)}],
    )

    # Build config to resolve the rendered cache path
    from cfgcaddy.config import LinkerConfig

    cfg = LinkerConfig(config_file_path=str(cfg_path))
    # Render template to cache (writes cache_dir/.myconfig)
    cache_path = cfg.renderer.render_if_template(tmpl_src)

    # Create the dest symlink pointing to the rendered cache file
    dest_link_path.symlink_to(cache_path)

    # Overwrite the cache with stale content so diff detects content_changed
    cache_path.write_text("version=1\n")

    runner = CliRunner()
    result = invoke_diff(runner, cfg_path)
    # Should detect template content change (stale cache vs freshly rendered)
    assert result.exit_code == 1
