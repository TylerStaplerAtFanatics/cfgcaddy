from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

CONDITION_WEIGHTS: dict[str, int] = {
    "os": 2,
    "hostname": 32,
    "profile": 16,
    "default": 0,
}


@dataclass
class AlternateContext:
    os: str
    hostname: str
    profile: str | None


def parse_alternate_name(filename: str) -> tuple[str, list[tuple[str, str]]]:
    """Parse an alternate filename into (base_name, [(key, value), ...]).

    Strips a trailing .tmpl before splitting on ##.

    Examples:
        parse_alternate_name("gitconfig##os.darwin##hostname.work")
            -> ("gitconfig", [("os", "darwin"), ("hostname", "work")])
        parse_alternate_name("gitconfig.tmpl##os.linux")
            -> ("gitconfig", [("os", "linux")])
        parse_alternate_name("gitconfig")
            -> ("gitconfig", [])
    """
    segments = filename.split("##")
    # Strip trailing .tmpl from the base segment only (.tmpl is processed after
    # scoring, not as a condition suffix)
    base_name = segments[0]
    if base_name.endswith(".tmpl"):
        base_name = base_name[: -len(".tmpl")]

    conditions: list[tuple[str, str]] = []
    for segment in segments[1:]:
        # Split on first dot only
        dot_idx = segment.find(".")
        if dot_idx == -1:
            # No dot — treat whole segment as key with empty value
            conditions.append((segment, ""))
        else:
            key = segment[:dot_idx]
            value = segment[dot_idx + 1 :]
            conditions.append((key, value))

    return base_name, conditions


def score_candidate(filename: str, context: AlternateContext) -> int | None:
    """Score a candidate filename against the current context.

    Returns:
        int: score if ALL conditions match (0 for bare name or ##default)
        None: if ANY condition doesn't match or an unrecognized key is encountered
    """
    base_name, conditions = parse_alternate_name(filename)

    # Bare filename (no ##) scores 0
    if not conditions:
        return 0

    # ##default only → score 0
    if len(conditions) == 1 and conditions[0][0] == "default":
        return 0

    total = 0
    for key, value in conditions:
        if key == "default":
            # default always matches, contributes 0 weight — skip it in sum
            continue

        if key not in CONDITION_WEIGHTS:
            logger.warning(
                "Unknown condition key %r in filename %r — excluding candidate",
                key,
                filename,
            )
            return None

        # Check the condition against the context
        if key == "os":
            if value != context.os:
                return None
        elif key == "hostname":
            if value != context.hostname:
                return None
        elif key == "profile":
            if context.profile is None or value != context.profile:
                return None

        total += CONDITION_WEIGHTS[key] + 1000

    return total


def select_candidate(
    candidates: list[Path], context: AlternateContext
) -> Path | None:
    """Select the best-scoring candidate for the current context.

    Returns None if no candidates match. Ties are broken lexicographically
    (last path wins) with a warning emitted.
    """
    scored: list[tuple[int, Path]] = []
    for path in candidates:
        score = score_candidate(path.name, context)
        if score is not None:
            scored.append((score, path))

    if not scored:
        return None

    max_score = max(s for s, _ in scored)
    winners = [p for s, p in scored if s == max_score]

    if len(winners) > 1:
        winners.sort(key=lambda p: str(p))
        logger.warning(
            "Tie between candidates %r — picking lexicographically last: %r",
            [str(w) for w in winners],
            str(winners[-1]),
        )
        return winners[-1]

    return winners[0]
