"""Editorial gates: what has to be true before a post can be approved.

Pure functions, no I/O.

Splay gated on a hardcoded list of private-equity jargon, which is exactly the
kind of thing that shouldn't be compiled into a multi-tenant product. The
equivalent here is the brand kit's own ``avoid`` list — already per-business,
already owner-editable, and already the thing they told us not to say.

Errors block approval; warnings are advice and never block. An owner can still
approve over a blocking error, but only by writing a note explaining why
(see ``app/social/review.py``), so the override leaves a trail.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# LinkedIn's own guidance, and what the hashtag repair aims for.
LINKEDIN_HASHTAG_MIN, LINKEDIN_HASHTAG_MAX = 3, 4
LINKEDIN_BODY_MIN, LINKEDIN_BODY_MAX = 500, 2200
X_MAX_CHARS = 280

_STOPWORDS = {
    "about", "after", "again", "because", "before", "could", "every", "first",
    "from", "have", "into", "more", "should", "their", "there", "these", "thing",
    "those", "using", "what", "when", "where", "which", "with", "would", "your",
}
_WORD = re.compile(r"[a-z][a-z0-9]{3,}")


@dataclass(frozen=True)
class GateResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.errors

    @property
    def verdict(self) -> str:
        return "reject" if self.errors else "publish"

    def as_dict(self) -> dict:
        return {
            "passed": self.passed,
            "verdict": self.verdict,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


def _avoid_pattern(phrase: str) -> re.Pattern[str]:
    """Match an avoid-phrase whole-word, treating spaces and hyphens as equal.

    Split first, then escape each word: escaping the whole phrase up front would
    backslash the hyphens and separators we are about to rewrite.
    """
    words = [re.escape(part) for part in re.split(r"[-\s]+", phrase.strip()) if part]
    if not words:
        return re.compile(r"(?!)")  # matches nothing
    return re.compile(rf"\b{r'[\s-]+'.join(words)}\b", re.I)


def normalized_hashtags(hashtags: list[str]) -> list[str]:
    """Strip leading '#', drop blanks, lowercase, de-duplicate, keep order."""
    seen: dict[str, None] = {}
    for tag in hashtags:
        cleaned = tag.strip().lstrip("#").strip().lower()
        if cleaned:
            seen.setdefault(cleaned, None)
    return list(seen)


def formatted_length(text: str, hashtags: list[str]) -> int:
    """Published length in code points — what the platform actually counts."""
    tags = " ".join(f"#{t}" for t in hashtags if t.strip())
    published = f"{text.strip()}\n\n{tags}" if tags else text.strip()
    return len(published)


def check_draft(
    *, platform: str, topic: str, text: str, hashtags: list[str], avoid: list[str]
) -> GateResult:
    errors: list[str] = []
    warnings: list[str] = []

    corpus = f"{topic} {text}"
    for phrase in avoid:
        if phrase.strip() and _avoid_pattern(phrase).search(corpus):
            errors.append(f'Post uses "{phrase.strip()}", which your brand kit avoids.')

    unique = normalized_hashtags(hashtags)

    if platform == "linkedin":
        if not LINKEDIN_HASHTAG_MIN <= len(unique) <= LINKEDIN_HASHTAG_MAX:
            errors.append(
                f"LinkedIn posts need {LINKEDIN_HASHTAG_MIN}–{LINKEDIN_HASHTAG_MAX} "
                f"unique hashtags; this one has {len(unique)}."
            )
        body = len(text.strip())
        if body < LINKEDIN_BODY_MIN:
            warnings.append(
                f"Short for LinkedIn ({body} characters); posts around "
                f"{LINKEDIN_BODY_MIN}+ tend to land better."
            )
        elif body > LINKEDIN_BODY_MAX:
            warnings.append(f"Over LinkedIn's {LINKEDIN_BODY_MAX}-character limit ({body}).")
    elif platform == "x":
        published = formatted_length(text, unique)
        if published > X_MAX_CHARS:
            errors.append(
                f"Too long for X: {published} characters including hashtags, "
                f"limit is {X_MAX_CHARS}."
            )
        if len(unique) > 1:
            warnings.append("More than one hashtag reads as spammy on X.")

    return GateResult(errors=errors, warnings=warnings)


def only_hashtag_errors(errors: list[str]) -> bool:
    return bool(errors) and all("hashtag" in e.lower() for e in errors)


def repair_hashtags(*, platform: str, topic: str, text: str) -> list[str]:
    """Derive usable hashtags from the post's own words.

    X gets none — a bare post outperforms a tagged one there.
    """
    if platform != "linkedin":
        return []
    seen: dict[str, None] = {}
    for word in _WORD.findall(f"{topic} {text}".lower()):
        if word not in _STOPWORDS:
            seen.setdefault(word, None)
        if len(seen) >= LINKEDIN_HASHTAG_MAX:
            break
    return [w.title() for w in seen]
