from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import jinja2

from cfgcaddy import RENDERED_CACHE_DIR
from cfgcaddy.data import CfgcaddyError


class TemplateRenderer:
    """Render .tmpl files using Jinja2 and cache the output."""

    def __init__(
        self,
        variables: dict,
        linker_src: Path,
        output_dir: Path = RENDERED_CACHE_DIR,
    ) -> None:
        self.variables = variables
        self.linker_src = Path(linker_src)
        self.output_dir = Path(output_dir)

    def _make_env(self) -> jinja2.Environment:
        return jinja2.Environment(
            undefined=jinja2.StrictUndefined,
            autoescape=False,
        )

    def _render_text(self, src: Path) -> str:
        """Render *src* (a .tmpl file) and return the rendered string."""
        env = self._make_env()
        try:
            template = env.from_string(src.read_text())
            return template.render(**self.variables)
        except jinja2.UndefinedError as exc:
            raise CfgcaddyError(
                f"Template variable not defined in '{src}': {exc}"
            ) from exc
        except jinja2.TemplateSyntaxError as exc:
            raise CfgcaddyError(
                f"Template syntax error in '{exc.filename or src}' "
                f"at line {exc.lineno}: {exc.message}. "
                "Use {{% raw %}}...{{% endraw %}} to escape literal {{{{ }}}} sequences."
            ) from exc

    def render_if_template(self, src: Path) -> Path:
        """Return *src* unchanged for non-.tmpl files.

        For .tmpl files, render to a cache path (stripping the .tmpl suffix)
        and return the cache path.  The cache file is only written when the
        rendered content differs from the existing cached content (idempotent
        write optimisation).  The write is atomic via a temp-file + os.rename
        pattern.  File permissions are copied from the source.
        """
        if src.suffix != ".tmpl":
            return src

        rendered = self._render_text(src)
        rendered_bytes = rendered.encode()

        cache_path = self.output_dir / src.relative_to(self.linker_src).with_suffix("")
        cache_path.parent.mkdir(parents=True, exist_ok=True)

        # Only write if content differs from what is already cached.
        if cache_path.exists():
            if cache_path.read_bytes() == rendered_bytes:
                return cache_path

        # Atomic write: write to a sibling tempfile then rename.
        tmp_fd, tmp_path = tempfile.mkstemp(dir=cache_path.parent)
        try:
            with os.fdopen(tmp_fd, "wb") as fh:
                fh.write(rendered_bytes)
            os.rename(tmp_path, cache_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        shutil.copymode(src, cache_path)
        return cache_path

    def render_to_string(self, src: Path) -> str | None:
        """Return rendered content for .tmpl files without writing to cache.

        Returns *None* for non-.tmpl files.
        Used by the diff command for side-effect-free preview.
        """
        if src.suffix != ".tmpl":
            return None
        return self._render_text(src)
