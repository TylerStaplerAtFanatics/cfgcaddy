"""Tests for cfgcaddy.template.TemplateRenderer"""
from __future__ import annotations

import stat
from pathlib import Path

import pytest

from cfgcaddy.data import CfgcaddyError
from cfgcaddy.template import TemplateRenderer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_renderer(tmp_path, variables: dict, *, subdir: str = "src") -> tuple[TemplateRenderer, Path, Path]:
    """Return (renderer, linker_src, output_dir) rooted in tmp_path."""
    linker_src = tmp_path / subdir
    linker_src.mkdir(parents=True, exist_ok=True)
    output_dir = tmp_path / "cache"
    renderer = TemplateRenderer(
        variables=variables,
        linker_src=linker_src,
        output_dir=output_dir,
    )
    return renderer, linker_src, output_dir


# ---------------------------------------------------------------------------
# render_if_template
# ---------------------------------------------------------------------------


def test_non_tmpl_passthrough(tmp_path):
    """Non-.tmpl files are returned unchanged without touching the filesystem."""
    renderer, linker_src, _ = make_renderer(tmp_path, {})
    plain = linker_src / "plain.txt"
    plain.write_text("hello")

    result = renderer.render_if_template(plain)
    assert result == plain


def test_happy_path_variable_substitution(tmp_path):
    """A .tmpl file is rendered with the given variables."""
    renderer, linker_src, output_dir = make_renderer(tmp_path, {"name": "World"})
    tmpl = linker_src / "greeting.txt.tmpl"
    tmpl.write_text("Hello, {{ name }}!")

    result = renderer.render_if_template(tmpl)

    assert result == output_dir / "greeting.txt"
    assert result.read_text() == "Hello, World!"


def test_rendered_file_has_no_tmpl_suffix(tmp_path):
    """The cached file name has the .tmpl suffix stripped."""
    renderer, linker_src, output_dir = make_renderer(tmp_path, {"x": "1"})
    tmpl = linker_src / "config.conf.tmpl"
    tmpl.write_text("x={{ x }}")

    result = renderer.render_if_template(tmpl)

    assert result.suffix != ".tmpl"
    assert result.name == "config.conf"


def test_missing_variable_raises_cfgcaddy_error(tmp_path):
    """An undefined Jinja2 variable raises CfgcaddyError naming both the variable and path."""
    renderer, linker_src, _ = make_renderer(tmp_path, {})
    tmpl = linker_src / "bad.txt.tmpl"
    tmpl.write_text("value={{ missing_var }}")

    with pytest.raises(CfgcaddyError) as exc_info:
        renderer.render_if_template(tmpl)

    msg = str(exc_info.value)
    assert "missing_var" in msg
    assert str(tmpl) in msg


def test_template_syntax_error_raises_cfgcaddy_error(tmp_path):
    """A Jinja2 syntax error raises CfgcaddyError with a raw-escaping hint."""
    renderer, linker_src, _ = make_renderer(tmp_path, {})
    tmpl = linker_src / "broken.txt.tmpl"
    # Invalid Jinja2 syntax
    tmpl.write_text("{% if %}")

    with pytest.raises(CfgcaddyError) as exc_info:
        renderer.render_if_template(tmpl)

    msg = str(exc_info.value)
    assert "raw" in msg.lower()


def test_rendered_output_has_same_permissions(tmp_path):
    """The cached file inherits the source file's permission bits."""
    renderer, linker_src, _ = make_renderer(tmp_path, {"v": "ok"})
    tmpl = linker_src / "exec.sh.tmpl"
    tmpl.write_text("#!/bin/sh\necho {{ v }}")
    # Make the source executable
    tmpl.chmod(0o755)

    result = renderer.render_if_template(tmpl)

    src_mode = stat.S_IMODE(tmpl.stat().st_mode)
    dst_mode = stat.S_IMODE(result.stat().st_mode)
    assert src_mode == dst_mode


def test_output_dir_is_created_if_absent(tmp_path):
    """output_dir (and any parents) are created automatically."""
    linker_src = tmp_path / "src"
    linker_src.mkdir()
    output_dir = tmp_path / "deep" / "nested" / "cache"
    renderer = TemplateRenderer(variables={"k": "v"}, linker_src=linker_src, output_dir=output_dir)

    tmpl = linker_src / "file.txt.tmpl"
    tmpl.write_text("k={{ k }}")

    result = renderer.render_if_template(tmpl)

    assert output_dir.exists()
    assert result.read_text() == "k=v"


def test_changing_variable_updates_cached_file(tmp_path):
    """Re-rendering with different variables updates the cached file."""
    linker_src = tmp_path / "src"
    linker_src.mkdir()
    output_dir = tmp_path / "cache"

    tmpl = linker_src / "file.txt.tmpl"
    tmpl.write_text("value={{ val }}")

    renderer1 = TemplateRenderer(variables={"val": "first"}, linker_src=linker_src, output_dir=output_dir)
    result1 = renderer1.render_if_template(tmpl)
    assert result1.read_text() == "value=first"

    renderer2 = TemplateRenderer(variables={"val": "second"}, linker_src=linker_src, output_dir=output_dir)
    result2 = renderer2.render_if_template(tmpl)
    assert result2.read_text() == "value=second"


# ---------------------------------------------------------------------------
# render_to_string
# ---------------------------------------------------------------------------


def test_render_to_string_returns_rendered_content(tmp_path):
    """render_to_string returns the rendered content for .tmpl files."""
    renderer, linker_src, output_dir = make_renderer(tmp_path, {"greeting": "Hi"})
    tmpl = linker_src / "msg.txt.tmpl"
    tmpl.write_text("{{ greeting }}")

    result = renderer.render_to_string(tmpl)

    assert result == "Hi"
    # Must not write anything to the cache
    assert not output_dir.exists() or not (output_dir / "msg.txt").exists()


def test_render_to_string_non_tmpl_returns_none(tmp_path):
    """render_to_string returns None for non-.tmpl files."""
    renderer, linker_src, _ = make_renderer(tmp_path, {})
    plain = linker_src / "plain.txt"
    plain.write_text("hello")

    result = renderer.render_to_string(plain)

    assert result is None
