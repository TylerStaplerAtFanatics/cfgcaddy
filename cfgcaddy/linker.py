import logging
import os
from collections.abc import Collection
from pathlib import Path

import cfgcaddy.utils as utils
from cfgcaddy.link import Link, create_links, find_absences
from cfgcaddy.link_spec import LinkingResult, LinkSpec
from cfgcaddy.utils import create_dirs

logger = logging.getLogger()


class Linker:
    """Tyler Stapler's Config Linker"""

    custom_links: Collection[LinkSpec]

    def __init__(self, linker_config, interactive=True, dry_run: bool = False) -> None:
        if not linker_config:
            raise Exception("Linker requires Config!")

        self.config = linker_config
        self.interactive = interactive
        self.dry_run = dry_run

        self.custom_links = self.config.links
        self.ignored_patterns = self.config.ignore_patterns

    def _all_links(self) -> list[Link]:
        """Return all links (directory scan + custom links) without executing any writes.

        Unlike find_absences, this includes ALL source files regardless of whether
        the dest already exists - necessary for diff/dry-run to detect changed/conflict states.
        """
        from os import path

        import pathspec  # type: ignore

        import cfgcaddy as _cfgcaddy

        src = self.config.linker_src
        dest = self.config.linker_dest
        ignored_patterns = self.ignored_patterns or []
        use_copy = self.config.use_copy_mode

        default_ignore = ["!.*", _cfgcaddy.DEFAULT_CONFIG_NAME, ".git"]
        ignored = pathspec.PathSpec.from_lines(
            "gitwildmatch", default_ignore + ignored_patterns
        )

        all_files: list[Link] = []
        for root, dirs, files in os.walk(src, topdown=True):
            rel_path = path.relpath(root, src)
            if rel_path == ".":
                rel_path = ""

            dirs[:] = [
                d for d in dirs if not ignored.match_file(path.join(rel_path, d))
            ]
            files[:] = [
                f
                for f in files
                if not ignored.match_file(path.join(rel_path, f.split("##")[0]))
            ]

            for f in files:
                base_f = f.split("##")[0]
                dest_pathname = Path(path.join(dest, rel_path, base_f))
                src_pathname = Path(path.join(root, f))
                all_files.append(Link(src_pathname, dest_pathname, use_copy=use_copy))

        custom = list(self.custom_links)
        return all_files + custom  # type: ignore[operator]

    def resolve_planned_links(self) -> list[tuple[str, "Link"]]:
        """Return (action_label, link) pairs describing what create_links would do.

        Action labels:
            "new"             – link.dest does not exist at all
            "conflict"        – link.dest is a regular file (not a symlink)
            "broken"          – link.dest is a dangling symlink
            "changed"         – link.dest is a symlink pointing to wrong src
            "content_changed" – link.dest is a symlink pointing to correct src, but
                                 rendered template content differs from deployed content
            "ok"              – already correct (caller should filter these out)
        """
        renderer = self.config.renderer
        results: list[tuple[str, Link]] = []

        for link in self._all_links():
            dest = link.dest
            src = link.src

            if not dest.exists() and not dest.is_symlink():
                results.append(("new", link))
                continue

            if not dest.is_symlink():
                # Regular file (or directory) at dest — conflict
                results.append(("conflict", link))
                continue

            # dest is a symlink from here on
            if not dest.resolve().exists():
                results.append(("broken", link))
                continue

            current_target = os.readlink(dest)
            if current_target != str(src):
                results.append(("changed", link))
                continue

            # Symlink points to the right src.  For template sources, check
            # whether rendered content differs from what is currently deployed.
            orig_src = Path(str(src))
            # src may be a rendered cache path — check original .tmpl
            # The renderer knows how to render; use render_to_string (no writes)
            rendered = renderer.render_to_string(orig_src)
            if rendered is not None:
                # It's a template: compare rendered content with deployed content
                try:
                    deployed = dest.read_text()
                except OSError:
                    deployed = ""
                if rendered != deployed:
                    results.append(("content_changed", link))
                    continue

            results.append(("ok", link))

        return results

    def create_links(self) -> None:
        """Symlinks configuration files to the destination directory

        Parses the ignore file for regexes and then generates a list of files
        which need to be symlinked"""

        # TODO: Rewrite find_absences
        absent_files, absent_dirs = find_absences(
            self.config.linker_src,
            self.config.linker_dest,
            self.ignored_patterns,
            use_copy=self.config.use_copy_mode,
        )

        if not absent_files and not absent_dirs:
            logger.info("Nothing to do")
            return

        logger.info("Preparing to symlink the following files")
        logger.info("\n".join(str(link.dest) for link in absent_files))
        if not self.interactive or utils.user_confirm("Are these the correct files?"):
            create_dirs(dirs=absent_dirs)
            create_links(links=absent_files)

    def create_custom_links(self) -> None:
        """Link all the files in the customlink file

        Returns:
            None
        """
        modified = LinkingResult.SKIPPED

        for link in self.custom_links:
            modified = link.create(interactive=self.interactive)

        if not modified:
            logger.info("No folders to link")
