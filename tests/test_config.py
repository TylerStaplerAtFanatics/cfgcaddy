import os
from unittest.mock import MagicMock, patch

from ruamel.yaml import YAML

from cfgcaddy.config import LinkerConfig
from tests import FileLinkTestCase

yaml = YAML(typ="safe")  # default, if not specfied, is 'rt' (round-trip)


class TestLinkerConfig(FileLinkTestCase):
    default_config = {}

    def test_no_config(self):
        os.remove(self.config_file_path)

        self.test_empty_config()

    def test_empty_config(self):
        with self.assertRaises(SystemExit) as cm:
            LinkerConfig(self.config_file_path)

        self.assertEqual(cm.exception.code, 1)

    def test_write_section(self):
        self.default_config = {
            "preferences": {
                "linker_src": self.source_dir,
                "linker_dest": self.dest_dir,
            },
            "links": [],
            "ignore": [],
        }

        linker_config = LinkerConfig(
            self.config_file_path, default_config=self.default_config
        )

        linker_config.write_config(prompt=False)

        output = {}

        with open(self.config_file_path) as file:
            output = yaml.load(file)

        print(output)

        self.assertDictEqual(self.default_config, output)


class TestDefaultProfileFallback(FileLinkTestCase):
    """Story 4.3: default_profile resolution order tests."""

    def _make_config(self, default_profile=None):
        """Return a minimal valid config dict, optionally with default_profile."""
        cfg = {
            "preferences": {
                "linker_src": self.source_dir,
                "linker_dest": self.dest_dir,
            },
            "links": [],
            "ignore": [],
        }
        if default_profile is not None:
            cfg["preferences"]["default_profile"] = default_profile
        return cfg

    def _patched_loader(self):
        """Return a context manager that stubs out LocalDataLoader.load() → {}."""
        mock_loader = MagicMock()
        mock_loader.return_value.load.return_value = {}
        return patch("cfgcaddy.config.LocalDataLoader", mock_loader)

    def test_yaml_default_profile_activates_when_no_cli_flag(self):
        """default_profile in YAML sets self.profile when no CLI flag is given."""
        cfg = self._make_config(default_profile="work")
        with self._patched_loader():
            lc = LinkerConfig(self.config_file_path, default_config=cfg, profile=None)
        assert lc.profile == "work"

    def test_cli_profile_overrides_yaml_default(self):
        """Explicit CLI --profile overrides YAML default_profile."""
        cfg = self._make_config(default_profile="work")
        with self._patched_loader():
            lc = LinkerConfig(self.config_file_path, default_config=cfg, profile="home")
        assert lc.profile == "home"

    def test_no_default_profile_yields_none(self):
        """When neither CLI flag nor YAML default_profile is set, profile is None."""
        cfg = self._make_config()
        with self._patched_loader():
            lc = LinkerConfig(self.config_file_path, default_config=cfg, profile=None)
        assert lc.profile is None

    def test_env_var_cfgcaddy_profile_activates_profile(self):
        """CFGCADDY_PROFILE env var activates profile when no --profile flag.

        LinkerConfig itself doesn't read env vars; Click's envvar= picks it up and
        passes it as the profile argument. Simulate that here.
        """
        prev = os.environ.get("CFGCADDY_PROFILE")
        os.environ["CFGCADDY_PROFILE"] = "staging"
        try:
            cfg = self._make_config()
            profile_from_env = os.environ.get("CFGCADDY_PROFILE")
            with self._patched_loader():
                lc = LinkerConfig(
                    self.config_file_path, default_config=cfg, profile=profile_from_env
                )
            assert lc.profile == "staging"
        finally:
            if prev is None:
                os.environ.pop("CFGCADDY_PROFILE", None)
            else:
                os.environ["CFGCADDY_PROFILE"] = prev
