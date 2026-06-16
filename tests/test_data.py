"""Tests for cfgcaddy.data — LocalDataLoader and validate_profile_name."""

import pytest

from cfgcaddy.data import CfgcaddyError, LocalDataLoader, validate_profile_name


# ---------------------------------------------------------------------------
# LocalDataLoader.load()
# ---------------------------------------------------------------------------


def test_absent_local_toml_returns_empty_dict(tmp_path):
    """When local.toml does not exist, load() returns {}."""
    loader = LocalDataLoader(config_dir=tmp_path)
    assert loader.load() == {}


def test_variables_load_from_local_toml(tmp_path):
    """Variables defined in local.toml are returned by load()."""
    (tmp_path / "local.toml").write_bytes(b'name = "alice"\ncolor = "blue"\n')
    loader = LocalDataLoader(config_dir=tmp_path)
    result = loader.load()
    assert result == {"name": "alice", "color": "blue"}


def test_profile_merge_overrides_base_value(tmp_path):
    """Profile values take precedence over the same key in local.toml."""
    (tmp_path / "local.toml").write_bytes(b'name = "alice"\nenv = "dev"\n')
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    (profiles_dir / "work.toml").write_bytes(b'env = "prod"\n')

    loader = LocalDataLoader(config_dir=tmp_path, profile="work")
    result = loader.load()
    assert result["env"] == "prod"   # overridden by profile
    assert result["name"] == "alice"  # preserved from base


def test_missing_profile_file_raises_cfgcaddy_error(tmp_path):
    """If the profile toml does not exist, load() raises CfgcaddyError."""
    (tmp_path / "local.toml").write_bytes(b'key = "value"\n')
    (tmp_path / "profiles").mkdir()

    loader = LocalDataLoader(config_dir=tmp_path, profile="nonexistent")
    with pytest.raises(CfgcaddyError):
        loader.load()


def test_missing_profile_file_not_file_not_found_error(tmp_path):
    """The raised error must be CfgcaddyError, not a raw FileNotFoundError."""
    (tmp_path / "profiles").mkdir()
    loader = LocalDataLoader(config_dir=tmp_path, profile="ghost")
    with pytest.raises(CfgcaddyError):
        loader.load()
    # Ensure a bare FileNotFoundError is NOT raised
    try:
        loader.load()
    except CfgcaddyError:
        pass
    except FileNotFoundError:
        pytest.fail("load() raised FileNotFoundError instead of CfgcaddyError")


# ---------------------------------------------------------------------------
# validate_profile_name()
# ---------------------------------------------------------------------------


def test_validate_profile_name_path_traversal_raises():
    """../../../etc/passwd must be rejected."""
    with pytest.raises(CfgcaddyError):
        validate_profile_name("../../../etc/passwd")


def test_validate_profile_name_valid_name_passes():
    """A plain alphanumeric name should pass without raising."""
    validate_profile_name("work")  # must not raise


def test_validate_profile_name_dots_are_disallowed():
    """Dots are not in the allowed character set."""
    with pytest.raises(CfgcaddyError):
        validate_profile_name("work.v2")


def test_validate_profile_name_hyphen_and_underscore_ok():
    """Hyphens and underscores are explicitly allowed."""
    validate_profile_name("work-laptop")   # must not raise
    validate_profile_name("work_laptop")   # must not raise


def test_validate_profile_name_empty_string_raises():
    """An empty name is invalid."""
    with pytest.raises(CfgcaddyError):
        validate_profile_name("")
