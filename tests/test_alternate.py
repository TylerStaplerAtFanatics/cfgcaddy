from __future__ import annotations

import logging
from pathlib import Path

import pytest

from cfgcaddy.alternate import (
    CONDITION_WEIGHTS,
    AlternateContext,
    parse_alternate_name,
    score_candidate,
    select_candidate,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ctx_darwin():
    return AlternateContext(os="darwin", hostname="workmac", profile=None)


@pytest.fixture
def ctx_darwin_work():
    return AlternateContext(os="darwin", hostname="workmac", profile="work")


@pytest.fixture
def ctx_linux():
    return AlternateContext(os="linux", hostname="server1", profile=None)


# ---------------------------------------------------------------------------
# parse_alternate_name
# ---------------------------------------------------------------------------


class TestParseAlternateName:
    def test_multiple_conditions(self):
        assert parse_alternate_name("gitconfig##os.darwin##hostname.workmac") == (
            "gitconfig",
            [("os", "darwin"), ("hostname", "workmac")],
        )

    def test_single_condition(self):
        assert parse_alternate_name("gitconfig##os.darwin") == (
            "gitconfig",
            [("os", "darwin")],
        )

    def test_tmpl_suffix_stripped(self):
        """The .tmpl suffix must be removed before parsing conditions."""
        assert parse_alternate_name("gitconfig.tmpl##os.linux") == (
            "gitconfig",
            [("os", "linux")],
        )

    def test_bare_filename(self):
        assert parse_alternate_name("gitconfig") == ("gitconfig", [])

    def test_default_condition(self):
        assert parse_alternate_name("gitconfig##default") == (
            "gitconfig",
            [("default", "")],
        )


# ---------------------------------------------------------------------------
# score_candidate
# ---------------------------------------------------------------------------


class TestScoreCandidate:
    def test_bare_filename_scores_zero(self, ctx_darwin):
        assert score_candidate("gitconfig", ctx_darwin) == 0

    def test_default_only_scores_zero(self, ctx_darwin):
        assert score_candidate("gitconfig##default", ctx_darwin) == 0

    def test_os_match(self, ctx_darwin):
        # os weight=2 → 2+1000 = 1002
        assert score_candidate("gitconfig##os.darwin", ctx_darwin) == 1002

    def test_os_no_match_returns_none(self, ctx_darwin):
        assert score_candidate("gitconfig##os.linux", ctx_darwin) is None

    def test_os_and_hostname_match(self, ctx_darwin_work):
        # (2+1000) + (32+1000) = 2034
        assert (
            score_candidate(
                "gitconfig##os.darwin##hostname.workmac", ctx_darwin_work
            )
            == 2034
        )

    def test_hostname_mismatch_returns_none(self, ctx_darwin):
        assert (
            score_candidate("gitconfig##os.darwin##hostname.server1", ctx_darwin)
            is None
        )

    def test_profile_match(self, ctx_darwin_work):
        # profile weight=16 → 16+1000 = 1016
        assert score_candidate("gitconfig##profile.work", ctx_darwin_work) == 1016

    def test_profile_missing_in_context_returns_none(self, ctx_darwin):
        """If context has no profile, a ##profile condition must not match."""
        assert score_candidate("gitconfig##profile.work", ctx_darwin) is None

    def test_unrecognized_key_returns_none_and_warns(self, ctx_darwin, caplog):
        with caplog.at_level(logging.WARNING, logger="cfgcaddy.alternate"):
            result = score_candidate("gitconfig##distro.arch", ctx_darwin)
        assert result is None
        assert any("distro" in msg for msg in caplog.messages)

    def test_tmpl_suffix_stripped_before_scoring(self, ctx_darwin):
        """Score of foo.tmpl##os.darwin should equal score of foo##os.darwin."""
        assert score_candidate("gitconfig.tmpl##os.darwin", ctx_darwin) == 1002


# ---------------------------------------------------------------------------
# select_candidate
# ---------------------------------------------------------------------------


class TestSelectCandidate:
    def _paths(self, tmp_path: Path, names: list[str]) -> list[Path]:
        """Create empty files in tmp_path and return their Paths."""
        paths = []
        for name in names:
            p = tmp_path / name
            p.touch()
            paths.append(p)
        return paths

    def test_highest_score_wins(self, tmp_path, ctx_darwin_work):
        """os+hostname candidate beats os-only candidate on darwin/workmac."""
        paths = self._paths(
            tmp_path,
            [
                "gitconfig##os.darwin",
                "gitconfig##os.darwin##hostname.workmac",
                "gitconfig##default",
            ],
        )
        winner = select_candidate(paths, ctx_darwin_work)
        assert winner is not None
        assert winner.name == "gitconfig##os.darwin##hostname.workmac"

    def test_non_matching_excluded(self, tmp_path, ctx_darwin):
        """Linux candidate is excluded on a darwin machine."""
        paths = self._paths(
            tmp_path,
            ["gitconfig##os.linux", "gitconfig##os.darwin"],
        )
        winner = select_candidate(paths, ctx_darwin)
        assert winner is not None
        assert winner.name == "gitconfig##os.darwin"

    def test_no_match_returns_none(self, tmp_path, ctx_linux):
        """No candidate matches → None returned."""
        paths = self._paths(
            tmp_path,
            ["gitconfig##os.darwin", "gitconfig##os.darwin##hostname.workmac"],
        )
        assert select_candidate(paths, ctx_linux) is None

    def test_tie_picks_lexicographically_last_and_warns(
        self, tmp_path, ctx_darwin, caplog
    ):
        """Two equal-score candidates: lexicographically last path wins + warning."""
        paths = self._paths(
            tmp_path,
            ["aaa_gitconfig##os.darwin", "zzz_gitconfig##os.darwin"],
        )
        with caplog.at_level(logging.WARNING, logger="cfgcaddy.alternate"):
            winner = select_candidate(paths, ctx_darwin)
        assert winner is not None
        # zzz sorts after aaa
        assert winner.name == "zzz_gitconfig##os.darwin"
        assert any("Tie" in msg or "tie" in msg.lower() for msg in caplog.messages)

    def test_bare_filename_scores_zero_and_is_selectable(self, tmp_path, ctx_darwin):
        """A plain filename (no ##) is a valid candidate scoring 0."""
        paths = self._paths(tmp_path, ["gitconfig"])
        winner = select_candidate(paths, ctx_darwin)
        assert winner is not None
        assert winner.name == "gitconfig"

    def test_default_candidate_selected_when_only_option(
        self, tmp_path, ctx_darwin
    ):
        paths = self._paths(tmp_path, ["gitconfig##default"])
        winner = select_candidate(paths, ctx_darwin)
        assert winner is not None
        assert winner.name == "gitconfig##default"
