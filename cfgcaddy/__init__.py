import os
from enum import Enum
from logging import getLogger
from pathlib import Path

__version__ = "0.1.8"

logging = getLogger()
logging.propagate = True


class LinkMode(Enum):
    SKIP = "SKIP"
    OVERRIDE = "OVERRIDE"


DEFAULT_CONFIG_NAME = ".cfgcaddy.yml"

DEFAULT_DOTFILES_DIR = os.path.join(os.path.expanduser("~"), "dotfiles")

HOME_DIR = os.path.expanduser("~")
DEFAULT_CONFIG_PATH = os.path.join(HOME_DIR, DEFAULT_CONFIG_NAME)

LOCAL_DATA_PATH = Path.home() / ".config" / "cfgcaddy" / "local.toml"
PROFILES_DIR = Path.home() / ".config" / "cfgcaddy" / "profiles"
RENDERED_CACHE_DIR = Path.home() / ".local" / "share" / "cfgcaddy" / "rendered"
