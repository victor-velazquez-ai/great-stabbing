"""Pre-LLM filter — language detection + keyword regex.

Goal: cut raw GDELT volume by ~95% before any LLM sees an article. Run as part
of the GitHub Actions monthly fetch job (no Anthropic API needed for this step).
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
KEYWORDS_DIR = REPO_ROOT / "extraction" / "keywords"


def _load_keywords(lang: str) -> tuple[list[str], list[str]]:
    path = KEYWORDS_DIR / f"{lang}.yaml"
    if not path.exists():
        return [], []
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("positive", []), data.get("negative", [])


def _compile(words: list[str]) -> re.Pattern[str]:
    if not words:
        return re.compile(r"$^")  # never matches
    return re.compile(r"|".join(re.escape(w) for w in words), re.IGNORECASE)


def matches_keywords(text: str, lang: str) -> bool:
    pos_words, neg_words = _load_keywords(lang)
    pos = _compile(pos_words)
    neg = _compile(neg_words)
    if neg.search(text):
        return False
    return bool(pos.search(text))


def filter_articles(articles_in_path: Path, articles_out_path: Path) -> int:
    """Read JSONL of articles, write JSONL of candidates. Return count kept."""
    kept = 0
    with articles_in_path.open(encoding="utf-8") as fin, articles_out_path.open(
        "w", encoding="utf-8"
    ) as fout:
        for line in fin:
            art = json.loads(line)
            text = " ".join(filter(None, [art.get("title", ""), art.get("lead", "")]))
            lang = art.get("language", "en")
            if matches_keywords(text, lang):
                fout.write(json.dumps(art, ensure_ascii=False) + "\n")
                kept += 1
    log.info("filter: kept %d articles → %s", kept, articles_out_path)
    return kept
