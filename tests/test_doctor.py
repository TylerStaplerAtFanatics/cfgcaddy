"""Tests for cfgcaddy doctor command (Epic 6)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner
from ruamel.yaml import YAML

from cfgcaddy.__main__ import main
from cfgcaddy.alternate import AlternateContext
from cfgcaddy.commands.doctor import (
    AmbiguousAlternatesCheck,
    BrokenSymlinksCheck,
    CheckLevel,
    MissingLocalTomlCheck,
    MissingVariablesCheck,
    NoUnmatchedAlternatesCheck,
    OpCliCheck,
    SymlinkDriftCheck,
    run_all_checks,
)

yaml = YAML(typ="safe")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def write_config(cfg_path: Path, src_dir: Path, dest_dir: Path, links: list | None = None):
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


def make_linker_config(tmp_path: Path, links: list | None = None, local_data: dict | None = None):
    """Return a LinkerConfig pointing at tmp dirs, with optional local_data override."""
    from unittest.mock import MagicMock
    from unittest.mock import patch as _patch

    src_dir = tmp_path / "src"
    dest_dir = tmp_path / "dest"
    src_dir.mkdir(exist_ok=True)
    dest_dir.mkdir(exist_ok=True)

    cfg_path = tmp_path / ".cfgcaddy.yml"
    write_config(cfg_path, src_dir, dest_dir, links=links)

    mock_loader = MagicMock()
    mock_loader.return_value.load.return_value = local_data if local_data is not None else {}

    with _patch("cfgcaddy.config.LocalDataLoader", mock_loader):
        from cfgcaddy.config import LinkerConfig
        lc = LinkerConfig(config_file_path=str(cfg_path))

    return lc, src_dir, dest_dir


# ---------------------------------------------------------------------------
# 1. BrokenSymlinksCheck
# ---------------------------------------------------------------------------


def test_broken_symlinks_check_pass(tmp_path):
    lc, src_dir, dest_dir = make_linker_config(tmp_path)
    # Create a valid symlink
    target = src_dir / "foo"
    target.write_text("hi")
    link = dest_dir / "foo"
    link.symlink_to(target)

    check = BrokenSymlinksCheck(lc)
    result = check.run()
    assert result.level == CheckLevel.PASS


def test_broken_symlinks_check_fail(tmp_path):
    lc, src_dir, dest_dir = make_linker_config(tmp_path)
    # Create a broken symlink
    gone = tmp_path / "gone"
    link = dest_dir / "broken"
    link.symlink_to(gone)

    check = BrokenSymlinksCheck(lc)
    result = check.run()
    assert result.level == CheckLevel.FAIL
    assert "broken" in result.message.lower() or str(link) in result.message


# ---------------------------------------------------------------------------
# 2. BrokenSymlinksCheck with --fix
# ---------------------------------------------------------------------------


def test_broken_symlinks_fix_removes_link_and_warns(tmp_path):
    lc, src_dir, dest_dir = make_linker_config(tmp_path)
    gone = tmp_path / "gone"
    link = dest_dir / "broken"
    link.symlink_to(gone)

    check = BrokenSymlinksCheck(lc)
    result = check.run(fix=True)
    assert result.level == CheckLevel.WARN
    assert not link.exists()
    assert not link.is_symlink()


# ---------------------------------------------------------------------------
# 3. SymlinkDriftCheck
# ---------------------------------------------------------------------------


def test_symlink_drift_check_pass(tmp_path):
    """All symlinks point to the correct source."""
    from unittest.mock import MagicMock
    from unittest.mock import patch as _patch

    src_dir = tmp_path / "src"
    dest_dir = tmp_path / "dest"
    src_dir.mkdir()
    dest_dir.mkdir()

    src_file = src_dir / ".gitconfig"
    src_file.write_text("[user]")

    dest_link = dest_dir / ".gitconfig"
    dest_link.symlink_to(src_file)

    cfg_path = tmp_path / ".cfgcaddy.yml"
    write_config(cfg_path, src_dir, dest_dir, links=[{"src": ".gitconfig"}])

    mock_loader = MagicMock()
    mock_loader.return_value.load.return_value = {}
    with _patch("cfgcaddy.config.LocalDataLoader", mock_loader):
        from cfgcaddy.config import LinkerConfig
        lc = LinkerConfig(config_file_path=str(cfg_path))

    check = SymlinkDriftCheck(lc)
    result = check.run()
    assert result.level == CheckLevel.PASS


def test_symlink_drift_check_warn(tmp_path):
    """Symlink pointing to the wrong source produces WARN."""
    from unittest.mock import MagicMock
    from unittest.mock import patch as _patch

    src_dir = tmp_path / "src"
    dest_dir = tmp_path / "dest"
    src_dir.mkdir()
    dest_dir.mkdir()

    correct_src = src_dir / ".gitconfig"
    correct_src.write_text("[user] correct")

    wrong_src = tmp_path / ".gitconfig_wrong"
    wrong_src.write_text("[user] wrong")

    # Symlink points at wrong_src, not correct_src
    dest_link = dest_dir / ".gitconfig"
    dest_link.symlink_to(wrong_src)

    cfg_path = tmp_path / ".cfgcaddy.yml"
    write_config(cfg_path, src_dir, dest_dir, links=[{"src": ".gitconfig"}])

    mock_loader = MagicMock()
    mock_loader.return_value.load.return_value = {}
    with _patch("cfgcaddy.config.LocalDataLoader", mock_loader):
        from cfgcaddy.config import LinkerConfig
        lc = LinkerConfig(config_file_path=str(cfg_path))

    check = SymlinkDriftCheck(lc)
    result = check.run()
    assert result.level == CheckLevel.WARN


# ---------------------------------------------------------------------------
# 4. MissingVariablesCheck
# ---------------------------------------------------------------------------


def test_missing_variables_check_pass(tmp_path):
    lc, src_dir, dest_dir = make_linker_config(
        tmp_path, local_data={"username": "alice"}
    )
    tmpl = src_dir / "profile.tmpl"
    tmpl.write_text("Hello {{ username }}")

    check = MissingVariablesCheck(lc)
    result = check.run()
    assert result.level == CheckLevel.PASS


def test_missing_variables_check_fail_names_var_and_file(tmp_path):
    lc, src_dir, dest_dir = make_linker_config(tmp_path, local_data={})
    tmpl = src_dir / "profile.tmpl"
    tmpl.write_text("Hello {{ missing_var }}")

    check = MissingVariablesCheck(lc)
    result = check.run()
    assert result.level == CheckLevel.FAIL
    assert "missing_var" in result.message
    assert "profile.tmpl" in result.message


# ---------------------------------------------------------------------------
# 5. MissingLocalTomlCheck
# ---------------------------------------------------------------------------


def test_missing_local_toml_pass_no_tmpl_files(tmp_path):
    """No .tmpl files → PASS regardless of local.toml presence."""
    lc, src_dir, dest_dir = make_linker_config(tmp_path)
    fake_local = tmp_path / "nonexistent_local.toml"

    with patch("cfgcaddy.commands.doctor.LOCAL_DATA_PATH", fake_local):
        check = MissingLocalTomlCheck(lc)
        result = check.run()

    assert result.level == CheckLevel.PASS


def test_missing_local_toml_warn_when_tmpl_exists(tmp_path):
    """.tmpl files present + no local.toml → WARN pointing to secrets init."""
    lc, src_dir, dest_dir = make_linker_config(tmp_path)
    (src_dir / "something.tmpl").write_text("{{ var }}")
    fake_local = tmp_path / "nonexistent_local.toml"

    with patch("cfgcaddy.commands.doctor.LOCAL_DATA_PATH", fake_local):
        check = MissingLocalTomlCheck(lc)
        result = check.run()

    assert result.level == CheckLevel.WARN
    assert "secrets init" in result.message


# ---------------------------------------------------------------------------
# 6. AmbiguousAlternatesCheck
# ---------------------------------------------------------------------------


def test_ambiguous_alternates_pass(tmp_path):
    """Two candidates with different scores — no tie."""
    lc, src_dir, dest_dir = make_linker_config(tmp_path)
    (src_dir / "gitconfig##os.darwin").write_text("[user]")
    (src_dir / "gitconfig##hostname.mybox").write_text("[user] host")

    # Override alternate_context to darwin
    lc.alternate_context = AlternateContext(os="darwin", hostname="other", profile=None)

    check = AmbiguousAlternatesCheck(lc)
    result = check.run()
    # "gitconfig##os.darwin" scores 1002, "gitconfig##hostname.mybox" scores None (hostname mismatch)
    # So only one candidate matches → no tie
    assert result.level == CheckLevel.PASS


def test_ambiguous_alternates_warn_on_tie(tmp_path):
    """Two candidates with equal scores → WARN."""
    lc, src_dir, dest_dir = make_linker_config(tmp_path)
    (src_dir / "gitconfig##os.darwin").write_text("[user] a")
    (src_dir / "gitconfig##os.darwin.2").write_text("[user] b")

    # Both have os=darwin so both match with same weight
    lc.alternate_context = AlternateContext(os="darwin", hostname="box", profile=None)

    # Manually set up: identical condition key+value gives same score
    # Actually "gitconfig##os.darwin.2" → key=os, value=darwin.2 which won't match "darwin"
    # We need to create a true tie: two files with same conditions but different names
    # The only way is identical condition strings. Let's use a subdirectory to avoid
    # duplicate filename collisions on the filesystem.
    subdir = src_dir / "sub"
    subdir.mkdir()
    (subdir / "vimrc##os.darwin").write_text("set nu")
    (src_dir / "vimrc##os.darwin").write_text("set nu 2")

    check = AmbiguousAlternatesCheck(lc)
    result = check.run()
    # vimrc##os.darwin appears in both src_dir and sub/ — both match with same score
    assert result.level == CheckLevel.WARN


# ---------------------------------------------------------------------------
# 7. OpCliCheck
# ---------------------------------------------------------------------------


def test_op_cli_check_pass_no_op_refs(tmp_path):
    lc, _, _ = make_linker_config(tmp_path, local_data={"key": "plain_value"})
    check = OpCliCheck(lc)
    result = check.run()
    assert result.level == CheckLevel.PASS


def test_op_cli_check_warn_op_ref_no_cli(tmp_path):
    lc, _, _ = make_linker_config(tmp_path, local_data={"secret": "op://vault/item/field"})
    with patch("shutil.which", return_value=None):
        check = OpCliCheck(lc)
        result = check.run()
    assert result.level == CheckLevel.WARN
    assert "op" in result.message.lower()


def test_op_cli_check_pass_op_ref_with_cli(tmp_path):
    lc, _, _ = make_linker_config(tmp_path, local_data={"secret": "op://vault/item/field"})
    with patch("shutil.which", return_value="/usr/local/bin/op"):
        check = OpCliCheck(lc)
        result = check.run()
    assert result.level == CheckLevel.PASS


def test_op_cli_check_nested_dict(tmp_path):
    """op:// in a nested dict is detected."""
    lc, _, _ = make_linker_config(
        tmp_path,
        local_data={"db": {"password": "op://Private/db/password"}},
    )
    with patch("shutil.which", return_value=None):
        check = OpCliCheck(lc)
        result = check.run()
    assert result.level == CheckLevel.WARN


# ---------------------------------------------------------------------------
# 8. NoUnmatchedAlternatesCheck
# ---------------------------------------------------------------------------


def test_no_unmatched_alternates_pass(tmp_path):
    """A candidate matching current context → PASS."""
    lc, src_dir, dest_dir = make_linker_config(tmp_path)
    (src_dir / "gitconfig##os.darwin").write_text("[user]")
    lc.alternate_context = AlternateContext(os="darwin", hostname="box", profile=None)

    check = NoUnmatchedAlternatesCheck(lc)
    result = check.run()
    assert result.level == CheckLevel.PASS


def test_no_unmatched_alternates_warn(tmp_path):
    """Only linux candidate on a darwin machine → WARN."""
    lc, src_dir, dest_dir = make_linker_config(tmp_path)
    (src_dir / "gitconfig##os.linux").write_text("[user]")
    lc.alternate_context = AlternateContext(os="darwin", hostname="box", profile=None)

    check = NoUnmatchedAlternatesCheck(lc)
    result = check.run()
    assert result.level == CheckLevel.WARN
    assert "gitconfig" in result.message


def test_no_unmatched_alternates_bare_file_passes(tmp_path):
    """A bare filename (no ##) always matches → PASS."""
    lc, src_dir, dest_dir = make_linker_config(tmp_path)
    (src_dir / "gitconfig").write_text("[user]")
    lc.alternate_context = AlternateContext(os="darwin", hostname="box", profile=None)

    check = NoUnmatchedAlternatesCheck(lc)
    result = check.run()
    assert result.level == CheckLevel.PASS


# ---------------------------------------------------------------------------
# 9. Exit codes
# ---------------------------------------------------------------------------


def test_exit_code_0_all_pass(tmp_path):
    from io import StringIO

    from rich.console import Console

    lc, _, _ = make_linker_config(tmp_path)
    console = Console(file=StringIO())

    checks = [
        BrokenSymlinksCheck(lc),
        MissingVariablesCheck(lc),
        MissingLocalTomlCheck(lc),
        OpCliCheck(lc),
        NoUnmatchedAlternatesCheck(lc),
    ]
    code = run_all_checks(checks, console)
    assert code == 0


def test_exit_code_1_for_warn(tmp_path):
    from io import StringIO

    from rich.console import Console

    lc, src_dir, _ = make_linker_config(tmp_path)
    # Trigger a WARN: tmpl file exists but no local.toml
    (src_dir / "something.tmpl").write_text("{{ var }}")
    fake_local = tmp_path / "nonexistent_local.toml"

    console = Console(file=StringIO())
    with patch("cfgcaddy.commands.doctor.LOCAL_DATA_PATH", fake_local):
        checks = [MissingLocalTomlCheck(lc)]
        code = run_all_checks(checks, console)
    assert code == 1


def test_exit_code_2_for_fail(tmp_path):
    from io import StringIO

    from rich.console import Console

    lc, src_dir, dest_dir = make_linker_config(tmp_path)
    # Trigger FAIL: broken symlink
    gone = tmp_path / "gone"
    link = dest_dir / "broken"
    link.symlink_to(gone)

    console = Console(file=StringIO())
    checks = [BrokenSymlinksCheck(lc)]
    code = run_all_checks(checks, console)
    assert code == 2


# ---------------------------------------------------------------------------
# 10. CLI integration
# ---------------------------------------------------------------------------


def test_doctor_cli_exit_0_clean(tmp_path, monkeypatch):
    """doctor exits 0 when linker_dest has no broken symlinks and src has no templates."""
    from unittest.mock import MagicMock
    from unittest.mock import patch as _patch

    src_dir = tmp_path / "src"
    dest_dir = tmp_path / "dest"
    src_dir.mkdir()
    dest_dir.mkdir()

    cfg_path = tmp_path / ".cfgcaddy.yml"
    write_config(cfg_path, src_dir, dest_dir)

    mock_loader = MagicMock()
    mock_loader.return_value.load.return_value = {}

    runner = CliRunner()
    with _patch("cfgcaddy.config.LocalDataLoader", mock_loader):
        with patch("cfgcaddy.commands.doctor.LOCAL_DATA_PATH", tmp_path / "nonexistent.toml"):
            result = runner.invoke(
                main, ["doctor", "-c", str(cfg_path)], catch_exceptions=False
            )

    assert result.exit_code == 0


def test_doctor_cli_fix_flag(tmp_path):
    """--fix removes broken symlinks and exits with 1 (WARN)."""
    from unittest.mock import MagicMock
    from unittest.mock import patch as _patch

    src_dir = tmp_path / "src"
    dest_dir = tmp_path / "dest"
    src_dir.mkdir()
    dest_dir.mkdir()

    gone = tmp_path / "gone_target"
    link = dest_dir / "broken_link"
    link.symlink_to(gone)

    cfg_path = tmp_path / ".cfgcaddy.yml"
    write_config(cfg_path, src_dir, dest_dir)

    mock_loader = MagicMock()
    mock_loader.return_value.load.return_value = {}

    runner = CliRunner()
    with _patch("cfgcaddy.config.LocalDataLoader", mock_loader):
        with patch("cfgcaddy.commands.doctor.LOCAL_DATA_PATH", tmp_path / "nonexistent.toml"):
            result = runner.invoke(
                main, ["doctor", "-c", str(cfg_path), "--fix"], catch_exceptions=False
            )

    assert result.exit_code == 1  # WARN (fixed)
    assert not link.is_symlink()
