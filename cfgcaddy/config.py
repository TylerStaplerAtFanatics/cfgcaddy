import glob
import logging
import os
import platform
import socket
import sys
from os import path
from pathlib import Path

import click
from ruamel.yaml import YAML

from cfgcaddy import utils
from cfgcaddy.alternate import AlternateContext, parse_alternate_name, select_candidate
from cfgcaddy.data import LocalDataLoader
from cfgcaddy.link import Link
from cfgcaddy.template import TemplateRenderer

logger = logging.getLogger()
yaml = YAML(typ="safe")  # default, if not specified, is 'rt' (round-trip)


MISSING_FILE_MESSAGE = (
    "Please create a {} file in the same directory as the linker python file."
)


class LinkerConfig:
    config: dict = {}
    links: list[Link] = []

    def __init__(self, config_file_path=None, default_config=None, profile: str | None = None) -> None:
        self.config_file_path = config_file_path

        if default_config:
            self.config = default_config
        elif self.config_file_path:
            self.read_config()

        # Don't continue if we don't have a config
        if not self.config:
            logger.error("No config has been provided or loaded")
            sys.exit(1)

        if not self.linker_src or not self.linker_dest:
            logger.error("You need to specify a src and destination")
            sys.exit(1)

        if profile is None:
            profile = self.config.get("preferences", {}).get("default_profile")
        self.profile = profile

        loader = LocalDataLoader(profile=profile)
        self.local_data = loader.load()
        self.renderer = TemplateRenderer(
            variables=self.local_data,
            linker_src=Path(self.linker_src),
        )

        self.alternate_context = AlternateContext(
            os=platform.system().lower(),
            hostname=socket.gethostname(),
            profile=self.profile,
        )

        self.generate_links(self.links_yaml)

    @property
    def preferences(self) -> dict[str, str]:
        if not self.config:
            raise
        return self.config.get("preferences", {})

    @property
    def linker_src(self) -> Path:
        src = self.preferences.get("linker_src")

        if not src:
            raise ValueError("linker_src is not set in the config")
        return utils.expand_path(src)

    @property
    def linker_dest(self) -> Path:
        dest = self.preferences.get("linker_dest")
        if not dest:
            raise ValueError("linker_dest is not set in the config")
        return utils.expand_path(dest)

    @property
    def use_copy_mode(self) -> bool:
        """Check if copy mode should be used instead of symlinks

        Returns:
            bool: True if copy mode is enabled or auto-detected for Termux
        """
        # Check explicit preference
        link_mode = self.preferences.get("link_mode", "auto")

        if link_mode == "copy":
            return True
        elif link_mode == "symlink":
            return False
        else:  # auto mode
            # Auto-detect based on platform and destination
            if utils.is_termux():
                # Check if destination supports symlinks
                return not utils.can_symlink(self.linker_dest)
            return False

    def write_config(self, prompt=True) -> None:
        if not os.path.exists(self.config_file_path) or (
            not prompt
            or utils.user_confirm(
                f"The file {self.config_file_path} exists.\n"
                "Would you like to overwrite this file?"
            )
        ):
            try:
                logger.info("Writing config file")
                with open(self.config_file_path, "w") as file:
                    logger.debug(self.config_file_path)
                    yaml.dump(self.config, file)
            except Exception as e:
                logger.error(f"Error writing config: {e}")

    def read_config(self) -> None:
        if os.path.isfile(self.config_file_path):
            with open(self.config_file_path) as file:
                self.config = yaml.load(file)

    def generate_links(self, links):
        custom_links = []

        for link in links:
            try:
                if link.get("os") and platform.system() not in link.get("os"):
                    continue

                link_src = utils.expand_path(link["src"])
                link_destinations = link.get("dest")
                src_files = glob.glob(path.join(self.linker_src, link_src))

                # Group src_files by base name (before ##) to resolve alternates
                groups: dict[str, list[Path]] = {}
                for src_path in src_files:
                    base_name, _ = parse_alternate_name(path.basename(src_path))
                    groups.setdefault(base_name, []).append(Path(src_path))

                # Select one winner per base name
                resolved_src_files: list[str] = []
                for base_name, candidates in groups.items():
                    winner = select_candidate(candidates, self.alternate_context)
                    if winner is None:
                        click.echo(
                            f"Warning: no candidate matches for '{base_name}' on this machine - skipping",
                            err=True,
                        )
                        continue
                    resolved_src_files.append(str(winner))

                # Track whether destinations were user-specified or auto-derived.
                # Only auto-derived dests may carry ## in their name (inherited
                # from link_src) and need the base-name strip.
                user_specified_dest = bool(link_destinations)

                # To account for no destination
                if not link_destinations:
                    if len(resolved_src_files) > 1:
                        link_destinations = [path.dirname(link_src)]
                    else:
                        link_destinations = [link_src]
                for src_path in resolved_src_files:
                    # Render .tmpl files; non-.tmpl files are returned unchanged.
                    effective_src = str(self.renderer.render_if_template(Path(src_path)))
                    # base_basename strips ## so dest symlinks use the clean name.
                    src_basename = path.basename(src_path)
                    base_basename = src_basename.split("##")[0]
                    for dest in map(utils.expand_path, link_destinations):
                        if len(resolved_src_files) > 1:
                            src_name = path.join(dest, base_basename)
                        else:
                            if user_specified_dest:
                                # User gave an explicit dest — use it verbatim.
                                src_name = str(dest)
                            else:
                                # Auto-derived from link_src; may carry ##.
                                dest_base, _ = parse_alternate_name(str(dest))
                                src_name = dest_base
                        if path.isabs(dest):
                            if user_specified_dest:
                                dest_path = str(dest)
                            else:
                                dest_path = path.join(path.dirname(dest), base_basename)
                        else:
                            dest_path = path.join(self.linker_dest, src_name)
                        custom_links.append(
                            Link(
                                utils.expand_path(effective_src),
                                utils.expand_path(dest_path),
                                use_copy=self.use_copy_mode,
                            )
                        )
            except KeyError:
                logger.exception("Bad custom link")

        logger.debug(f"Custom Links => {custom_links}")
        self.links = custom_links

    @property
    def links_yaml(self):
        """Parse the YAML config representation into a consistent format"""
        links = []
        for link in self.config.get("links", []):
            if type(link) is str:
                link = {"src": link, "dest": []}
            if type(link.get("dest")) is str:
                link["dest"] = [link["dest"]]
            links.append(link)
        logger.debug("Links before formatting: {}".format(self.config.get("links")))
        logger.debug(f"Links after formatting: {links}")
        return links

    @property
    def ignore_patterns(self):
        lines = self.config.get("ignore", [])
        """Parse the gitignore style file
        """
        logger.debug(f"Ignore Patterns: {lines}")
        return lines
