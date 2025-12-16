from __future__ import annotations

import logging
import os
import shutil
from os import path
from pathlib import Path
from typing import List, Optional, Union

from questionary import prompt

logger = logging.getLogger()

Pathlike = Union[str, Path]


def is_termux() -> bool:
    """Detect if running in Termux environment

    Returns:
        bool: True if running in Termux, False otherwise
    """
    return os.environ.get("TERMUX_VERSION") is not None or os.environ.get(
        "PREFIX", ""
    ).startswith("/data/data/com.termux")


def get_termux_shared_storage() -> Optional[Path]:
    """Get Termux shared storage path if available

    Returns:
        Path: Path to shared storage if available, None otherwise
    """
    if not is_termux():
        return None

    # Check for termux-setup-storage symlinks
    storage_path = Path.home() / "storage" / "shared"
    if storage_path.exists():
        return storage_path

    # Fallback to direct path
    direct_path = Path("/storage/emulated/0")
    if direct_path.exists():
        return direct_path

    return None


def can_symlink(target_path: Pathlike) -> bool:
    """Check if symlinks are supported at the target path

    Args:
        target_path: Path where symlink would be created

    Returns:
        bool: True if symlinks are supported, False otherwise
    """
    target = convert_to_path(target_path)
    parent = target.parent if target.exists() else target

    # Make sure parent directory exists
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        return False

    # Try creating a test symlink
    test_link = parent / f".cfgcaddy_symlink_test_{os.getpid()}"
    test_target = parent / f".cfgcaddy_target_test_{os.getpid()}"

    try:
        test_target.touch()
        test_link.symlink_to(test_target)
        test_link.unlink()
        test_target.unlink()
        return True
    except (OSError, NotImplementedError):
        # Clean up if anything was created
        try:
            if test_link.exists() or test_link.is_symlink():
                test_link.unlink()
        except Exception:
            pass
        try:
            if test_target.exists():
                test_target.unlink()
        except Exception:
            pass
        return False


def user_confirm(question: str, default: bool = True) -> bool:
    """Ask the user to confirm a choice

    Args:
        question (string): a string that is presented to the user.
        default (string): the answer if the user just hits <Enter>.
            It must be True, False or None (meaning
            an answer is required of the user).

    Returns "answer" return value is True for "yes" or False for "no".
    """
    return prompt(
        [{"type": "confirm", "name": "ok", "message": question, "default": default}]
    ).get("ok", False)


def make_parent_dirs(file_path: Pathlike) -> None:
    try:
        os.makedirs(path.dirname(file_path))
    except OSError:  # Python >2.5
        pass


def expand_path(file_path: Pathlike) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(file_path)))


def create_dirs(dirs: Optional[List[str]] = None) -> None:
    """Creates all folders in dirs

    Args:
        dirs ([string]): A list of paths to be linked

    Returns:
        None: Does not return anything
    """
    if dirs:
        for dir_name in dirs:
            try:
                os.makedirs(dir_name)
            except OSError:
                logger.error("Unable to create directory: {}", dir_name)


def convert_to_path(f: Union[str, Path]) -> Path:
    if isinstance(f, str):
        f = Path(f)
    return f


def copy_file_or_dir(src: Pathlike, dest: Pathlike) -> None:
    """Copy a file or directory from src to dest

    Args:
        src: Source path
        dest: Destination path
    """
    src_path = convert_to_path(src)
    dest_path = convert_to_path(dest)

    # Create parent directories if needed
    make_parent_dirs(dest_path)

    if src_path.is_dir():
        if dest_path.exists():
            shutil.rmtree(dest_path)
        shutil.copytree(src_path, dest_path, symlinks=True)
        logger.info(f"Copied directory {src_path} to {dest_path}")
    else:
        shutil.copy2(src_path, dest_path)
        logger.info(f"Copied file {src_path} to {dest_path}")
