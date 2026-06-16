from __future__ import annotations

import sys
from unittest.mock import patch

from click.testing import CliRunner

from cfgcaddy.commands.profiles import profiles
from cfgcaddy.data import LocalDataLoader

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


# ---------------------------------------------------------------------------
# profiles list
# ---------------------------------------------------------------------------


class TestProfilesList:
    def test_no_profiles_dir(self, tmp_path):
        """profiles list with no profiles dir prints 'No profiles found.' and exits 0."""
        runner = CliRunner(mix_stderr=False)
        profiles_dir = tmp_path / "profiles"
        # Directory intentionally NOT created
        with patch("cfgcaddy.commands.profiles.PROFILES_DIR", profiles_dir):
            result = runner.invoke(profiles, ["list"])
        assert result.exit_code == 0
        assert "No profiles found." in result.output

    def test_empty_profiles_dir(self, tmp_path):
        """profiles list with an empty directory also prints 'No profiles found.'"""
        runner = CliRunner(mix_stderr=False)
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        with patch("cfgcaddy.commands.profiles.PROFILES_DIR", profiles_dir):
            result = runner.invoke(profiles, ["list"])
        assert result.exit_code == 0
        assert "No profiles found." in result.output

    def test_two_profile_files(self, tmp_path):
        """profiles list with work.toml and home.toml prints their stems."""
        runner = CliRunner(mix_stderr=False)
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        (profiles_dir / "work.toml").write_bytes(b"")
        (profiles_dir / "home.toml").write_bytes(b"")
        with patch("cfgcaddy.commands.profiles.PROFILES_DIR", profiles_dir):
            result = runner.invoke(profiles, ["list"])
        assert result.exit_code == 0
        lines = result.output.strip().splitlines()
        assert set(lines) == {"home", "work"}


# ---------------------------------------------------------------------------
# profiles init
# ---------------------------------------------------------------------------


class TestProfilesInit:
    def test_path_traversal_rejected(self, tmp_path):
        """profiles init with a path-traversal name is rejected before any file I/O."""
        runner = CliRunner(mix_stderr=False)
        profiles_dir = tmp_path / "profiles"
        with patch("cfgcaddy.commands.profiles.PROFILES_DIR", profiles_dir):
            result = runner.invoke(profiles, ["init", "../evil"])
        assert result.exit_code != 0
        # No directory should have been created
        assert not profiles_dir.exists()

    def test_invalid_name_with_slash(self, tmp_path):
        """Names containing slashes are rejected (regex check)."""
        runner = CliRunner(mix_stderr=False)
        profiles_dir = tmp_path / "profiles"
        with patch("cfgcaddy.commands.profiles.PROFILES_DIR", profiles_dir):
            result = runner.invoke(profiles, ["init", "bad/name"])
        assert result.exit_code != 0
        assert not profiles_dir.exists()

    def _make_text_mock(self, responses: list[str]):
        """Return a mock for questionary.text that yields canned responses in order."""
        responses_iter = iter(responses)

        class FakeText:
            def __init__(self, *args, **kwargs):
                pass

            def ask(self):
                return next(responses_iter)

        def text_factory(*args, **kwargs):
            return FakeText()

        return text_factory

    def test_init_creates_toml_file(self, tmp_path):
        """profiles init writes key-value pairs into the profile TOML file."""
        runner = CliRunner(mix_stderr=False)
        profiles_dir = tmp_path / "profiles"

        text_mock = self._make_text_mock(["email", "work@example.com", ""])
        with patch("cfgcaddy.commands.profiles.PROFILES_DIR", profiles_dir), \
             patch("cfgcaddy.commands.profiles.questionary.text", side_effect=text_mock):
            result = runner.invoke(profiles, ["init", "work"])
        assert result.exit_code == 0, result.output
        profile_file = profiles_dir / "work.toml"
        assert profile_file.exists()
        with profile_file.open("rb") as fh:
            data = tomllib.load(fh)
        assert data["email"] == "work@example.com"

    def test_profile_data_loads_via_local_data_loader(self, tmp_path):
        """Data written by profiles init is readable via LocalDataLoader."""
        runner = CliRunner(mix_stderr=False)
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        actual_profiles_dir = config_dir / "profiles"

        text_mock = self._make_text_mock(["env", "staging", ""])
        with patch("cfgcaddy.commands.profiles.PROFILES_DIR", actual_profiles_dir), \
             patch("cfgcaddy.commands.profiles.questionary.text", side_effect=text_mock):
            result = runner.invoke(profiles, ["init", "staging"])
        assert result.exit_code == 0, result.output

        loader = LocalDataLoader(config_dir=config_dir, profile="staging")
        data = loader.load()
        assert data["env"] == "staging"
