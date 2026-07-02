"""Light, free, keyword-based enrichment.

This is intentionally crude. In Phase 2 you replace `tag()` with an LLM call
that does real classification + summarization. Keeping the seam here means the
rest of the pipeline doesn't change when you upgrade it.
"""
from __future__ import annotations

# topic -> trigger keywords (lowercased substring match)
TOPIC_KEYWORDS = {
    "maritime": ["strait", "shipping", "vessel", "tanker", "naval", "port",
                 "blockade", "ais", "convoy", "frigate", "destroyer"],
    "conflict": ["airstrike", "offensive", "ceasefire", "shelling", "drone",
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
    t = text.lower()
    return [label for label, kws in table.items() if any(k in t for k in kws)]


def tag(title: str, summary: str = "") -> tuple[str, str]:
    """Return (region, topics_csv). Coarse and free; upgrade in Phase 2."""
    text = f"{title} {summary}"
    topics = _match(text, TOPIC_KEYWORDS)
    regions = _match(text, REGION_KEYWORDS)
    return (", ".join(regions), ", ".join(topics))
