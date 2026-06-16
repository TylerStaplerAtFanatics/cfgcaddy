"""Tests for cfgcaddy.commands.secrets"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner
from ruamel.yaml import YAML

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from cfgcaddy.commands.secrets import secrets

yaml = YAML(typ="safe")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_config(config_path: Path, linker_src: Path, linker_dest: Path) -> None:
    config = {
        "preferences": {
            "linker_src": str(linker_src),
            "linker_dest": str(linker_dest),
        },
        "links": [],
    }
    with config_path.open("w") as fh:
        yaml.dump(config, fh)


def _run_init(config_path: Path, local_data_path: Path, answers: list[str]):
    """Invoke `secrets init` patching LOCAL_DATA_PATH and questionary prompts."""
    runner = CliRunner(mix_stderr=False)
    answer_iter = iter(answers)

    def fake_text(prompt_msg, **kwargs):
        class _FakePrompt:
            def ask(self_inner):
                return next(answer_iter, "")

        return _FakePrompt()

    with patch("cfgcaddy.commands.secrets.LOCAL_DATA_PATH", local_data_path), \
         patch("cfgcaddy.commands.secrets.questionary.text", side_effect=fake_text):
        result = runner.invoke(secrets, ["init", "-c", str(config_path)], catch_exceptions=False)
    return result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_init_prompts_for_each_variable(tmp_path):
    """secrets init prompts once for each undeclared variable in .tmpl files."""
    linker_src = tmp_path / "src"
    linker_src.mkdir()
    linker_dest = tmp_path / "dest"
    linker_dest.mkdir()
    config_path = tmp_path / ".cfgcaddy.yml"
    local_data_path = tmp_path / "local.toml"

    (linker_src / "file.txt.tmpl").write_text("token={{ github_token }}")
    _write_config(config_path, linker_src, linker_dest)

    result = _run_init(config_path, local_data_path, answers=["secret123"])

    assert result.exit_code == 0, result.output
    assert local_data_path.exists()
    with local_data_path.open("rb") as fh:
        data = tomllib.load(fh)
    assert data["github_token"] == "secret123"


def test_existing_values_not_re_prompted(tmp_path):
    """Variables already in local.toml are skipped during init."""
    import tomli_w

    linker_src = tmp_path / "src"
    linker_src.mkdir()
    linker_dest = tmp_path / "dest"
    linker_dest.mkdir()
    config_path = tmp_path / ".cfgcaddy.yml"
    local_data_path = tmp_path / "local.toml"

    (linker_src / "file.txt.tmpl").write_text("token={{ github_token }}")
    _write_config(config_path, linker_src, linker_dest)

    # Pre-populate local.toml with the variable
    local_data_path.parent.mkdir(parents=True, exist_ok=True)
    local_data_path.write_bytes(tomli_w.dumps({"github_token": "existing_value"}).encode())

    prompted = []

    runner = CliRunner(mix_stderr=False)

    def fake_text(prompt_msg, **kwargs):
        class _FakePrompt:
            def ask(self_inner):
                prompted.append(prompt_msg)
                return "new_value"

        return _FakePrompt()

    with patch("cfgcaddy.commands.secrets.LOCAL_DATA_PATH", local_data_path), \
         patch("cfgcaddy.commands.secrets.questionary.text", side_effect=fake_text):
        result = runner.invoke(secrets, ["init", "-c", str(config_path)], catch_exceptions=False)

    assert result.exit_code == 0, result.output
    assert not prompted, "Should not prompt for already-set variables"
    # Original value preserved
    with local_data_path.open("rb") as fh:
        data = tomllib.load(fh)
    assert data["github_token"] == "existing_value"


def test_written_file_is_valid_toml(tmp_path):
    """The file written by secrets init is parseable as valid TOML."""
    linker_src = tmp_path / "src"
    linker_src.mkdir()
    linker_dest = tmp_path / "dest"
    linker_dest.mkdir()
    config_path = tmp_path / ".cfgcaddy.yml"
    local_data_path = tmp_path / "local.toml"

    (linker_src / "config.tmpl").write_text("a={{ alpha }}\nb={{ beta }}")
    _write_config(config_path, linker_src, linker_dest)

    result = _run_init(config_path, local_data_path, answers=["val_a", "val_b"])

    assert result.exit_code == 0, result.output
    with local_data_path.open("rb") as fh:
        data = tomllib.load(fh)
    assert "alpha" in data or "beta" in data  # at least one variable written


def test_init_idempotent(tmp_path):
    """Running secrets init twice with the same template produces the same result."""

    linker_src = tmp_path / "src"
    linker_src.mkdir()
    linker_dest = tmp_path / "dest"
    linker_dest.mkdir()
    config_path = tmp_path / ".cfgcaddy.yml"
    local_data_path = tmp_path / "local.toml"

    (linker_src / "file.txt.tmpl").write_text("x={{ my_var }}")
    _write_config(config_path, linker_src, linker_dest)

    # First run: answer the prompt
    result1 = _run_init(config_path, local_data_path, answers=["hello"])
    assert result1.exit_code == 0, result1.output

    with local_data_path.open("rb") as fh:
        data_after_first = tomllib.load(fh)

    # Second run: no answers needed (variable already in local.toml)
    result2 = _run_init(config_path, local_data_path, answers=[])
    assert result2.exit_code == 0, result2.output

    with local_data_path.open("rb") as fh:
        data_after_second = tomllib.load(fh)

    assert data_after_first == data_after_second
