"""Light, free, keyword-based enrichment.

This is intentionally crude. In Phase 2 you replace `tag()` with an LLM call
that does real classification + summarization. Keeping the seam here means the
rest of the pipeline doesn't change when you upgrade it.
"""
from __future__ import annotations

import re

# topic -> trigger keywords, matched as whole words/phrases (see _match below)
TOPIC_KEYWORDS = {
    "maritime": ["strait", "shipping", "vessel", "tanker", "naval", "port",
                 "blockade", "convoy", "frigate", "destroyer"],
    # NOTE: "offensive" and bare "drone" were removed — both are extremely
    # common in sports coverage ("offensive line", "offensive coordinator",
    # drone-camera shots) and were the main source of sports articles
    # bleeding into the conflict tab. Phrased instead so they only fire on
    # genuine military-conflict usage.
    "conflict": ["airstrike", "military offensive", "ground offensive",
                 "counteroffensive", "ceasefire", "shelling", "drone strike",
                 "missile", "frontline", "casualties", "militant", "insurgent"],
    "policy": ["sanction", "tariff", "treaty", "legislation", "regulation",
               "parliament", "congress", "central bank", "election"],
    "geopolitics": ["summit", "alliance", "diplomat", "border", "annex",
                    "sovereignty", "nato", "un security council"],
}

# very rough region hints
REGION_KEYWORDS = {
    "Middle East": ["iran", "israel", "gaza", "yemen", "hormuz", "red sea",
                    "syria", "iraq", "saudi", "lebanon"],
    "Europe": ["ukraine", "russia", "nato", "eu", "germany", "france", "baltic"],
    "Indo-Pacific": ["china", "taiwan", "south china sea", "philippines",
                     "japan", "korea", "india"],
    "Africa": ["sudan", "sahel", "ethiopia", "nigeria", "congo", "somalia"],
    "Americas": ["venezuela", "mexico", "haiti", "colombia", "brazil"],
}


def _match(text: str, table: dict[str, list[str]]) -> list[str]:
    """Whole-word/phrase matching, not bare substring search.

    Bare substring matching was a bug in its own right: "port" (maritime)
    matched inside "sport"/"support"/"import", "eu" (Europe) matched inside
    "museum"/"beautiful", "ais" (maritime, since removed) matched inside
    "raise"/"praise". Word boundaries (\\b) fix all of that for free —
    "sport" never satisfies \\bport\\b because there's no boundary between
    the "s" and the "p".
    """
    t = text.lower()
    matched = []
    for label, kws in table.items():
        if any(re.search(r"\b" + re.escape(kw) + r"\b", t) for kw in kws):
            matched.append(label)
    return matched


def tag(title: str, summary: str = "") -> tuple[str, str]:
    """Return (region, topics_csv). Coarse and free; upgrade in Phase 2."""
    text = f"{title} {summary}"
    topics = _match(text, TOPIC_KEYWORDS)
    regions = _match(text, REGION_KEYWORDS)
    return (", ".join(regions), ", ".join(topics))


# --------------------------------------------------------------------------- #
# story clustering — collapse near-duplicate titles from different sources
# --------------------------------------------------------------------------- #
_STOPWORDS = {
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "is", "are",
    "at", "by", "with", "after", "over", "amid", "as", "from", "its", "his",
    "her", "their", "new", "into", "this", "that", "will", "says", "say",
}


def _title_tokens(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", (title or "").lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


def cluster_titles(items: list[dict], similarity: float = 0.5) -> list[list[dict]]:
    """Group near-duplicate stories by Jaccard similarity of title tokens.

    Crude and free, same tradeoff as tag() above — good enough to collapse
    "BBC: X strikes Y" / "Reuters: X launches strike on Y" into one card
    instead of three near-identical ones, without an LLM call. Preserves
    input order; each item ends up in exactly one cluster.
    """
    clusters: list[list[dict]] = []
    cluster_tokens: list[set[str]] = []
    for item in items:
        toks = _title_tokens(item.get("title"))
        placed = False
        if toks:
            for i, ctoks in enumerate(cluster_tokens):
                if not ctoks:
                    continue
                overlap = len(toks & ctoks) / len(toks | ctoks)
                if overlap >= similarity:
                    clusters[i].append(item)
                    cluster_tokens[i] = ctoks | toks
                    placed = True
                    break
        if not placed:
            clusters.append([item])
            cluster_tokens.append(toks)
    return clusters
