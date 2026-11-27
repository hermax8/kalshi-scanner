"""Rapprochement des matchs Kalshi avec les matchs OddsPapi (noms + date)."""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher

STOPWORDS = {"fc", "cf", "afc", "sc", "ac", "as", "ss", "sv", "fk", "bc", "club",
             "the", "de", "cd", "ud", "rc", "vfb", "vfl", "tsg", "us", "1", "kv",
             "bk", "if", "ssc", "calcio", "football"}


def norm(name: str, aliases: dict | None = None) -> str:
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if aliases and s in aliases:
        s = aliases[s]
    return s


def tokens(name: str) -> set:
    return {t for t in name.split() if t not in STOPWORDS}


def name_score(a: str, b: str, aliases: dict | None = None) -> float:
    """Similarité 0..1 tolérante : 'Man City' / 'Manchester City', 'Medvedev, Daniil' / 'Daniil Medvedev'."""
    na, nb = norm(a, aliases), norm(b, aliases)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ta, tb = tokens(na), tokens(nb)
    ratio = SequenceMatcher(None, " ".join(sorted(ta)), " ".join(sorted(tb))).ratio()
    if not ta or not tb:
        return ratio
    inter = ta & tb
    jacc = len(inter) / len(ta | tb)
    contain = len(inter) / min(len(ta), len(tb))
    # préfixes : "man" ~ "manchester", "atl" ~ "atletico"
    pref = sum(1 for x in ta if any(y.startswith(x) or x.startswith(y) for y in tb if min(len(x), len(y)) >= 3))
    pref_score = pref / max(len(ta), len(tb))
    # mot inclus dans un autre : "gladbach" ~ "monchengladbach", "koln" ~ "1fckoln"
    sub = sum(1 for x in ta if len(x) >= 5 and any(x in y or y in x for y in tb if len(y) >= 5))
    sub_score = sub / min(len(ta), len(tb))
    return max(ratio, jacc, 0.9 * contain, 0.85 * pref_score, 0.85 * sub_score)


def kalshi_event_date(event_ticker: str):
    """'KXEPLGAME-26DEC06EVEFUL' -> date(2026, 12, 6)."""
    m = re.search(r"-(\d{2})([A-Z]{3})(\d{2})", event_ticker or "")
    if not m:
        return None
    try:
        return datetime.strptime(f"{m.group(1)}{m.group(2)}{m.group(3)}", "%y%b%d").date()
    except ValueError:
        return None


def match_fixture(k_names: list[str], k_date, fixtures: list[dict], aliases: dict | None = None,
                  min_each: float = 0.6, min_avg: float = 0.72):
    """Trouve le match OddsPapi correspondant à 2 noms Kalshi.
    Renvoie (fixture, swapped, score) ; swapped=True si Kalshi[0] = participant2."""
    best = None
    for fx in fixtures:
        if k_date and fx.get("_date") and abs((fx["_date"] - k_date).days) > 1:
            continue
        p1, p2 = fx.get("participant1Name", ""), fx.get("participant2Name", "")
        straight = (name_score(k_names[0], p1, aliases), name_score(k_names[1], p2, aliases))
        crossed = (name_score(k_names[0], p2, aliases), name_score(k_names[1], p1, aliases))
        for pair, swapped in ((straight, False), (crossed, True)):
            if min(pair) < min_each:
                continue
            avg = sum(pair) / 2
            if avg >= min_avg and (best is None or avg > best[2]):
                best = (fx, swapped, avg)
    return best
