"""Clients HTTP : Kalshi (public, sans clé), OddsPapi (clé API), Telegram."""
from __future__ import annotations

import os
import time

import requests

TIMEOUT = 30


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- Kalshi
class Kalshi:
    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")
        self.s = requests.Session()

    def get(self, path: str, **params):
        r = self.s.get(f"{self.base}{path}", params=params, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()

    def open_events(self, series: str) -> list[dict]:
        """Événements ouverts d'une série, avec leurs marchés."""
        events, cursor = [], None
        for _ in range(10):
            params = {"series_ticker": series, "status": "open",
                      "with_nested_markets": "true", "limit": 200}
            if cursor:
                params["cursor"] = cursor
            data = self.get("/events", **params)
            events += data.get("events", [])
            cursor = data.get("cursor")
            if not cursor:
                break
        return events

    @staticmethod
    def quote(m: dict) -> dict:
        """Prix en dollars (0..1), compatibles anciens champs en cents."""
        def dollars(key):
            v = _f(m.get(f"{key}_dollars"))
            if v is None and m.get(key) is not None:
                v = _f(m.get(key))
                v = v / 100 if v is not None else None
            return v
        yes_bid, yes_ask = dollars("yes_bid"), dollars("yes_ask")
        no_ask = dollars("no_ask")
        if no_ask is None and yes_bid is not None:
            no_ask = 1 - yes_bid
        return {
            "yes_bid": yes_bid, "yes_ask": yes_ask, "no_ask": no_ask,
            "yes_ask_size": _f(m.get("yes_ask_size_fp")) or 0.0,
            "no_ask_size": _f(m.get("no_ask_size_fp")) or _f(m.get("yes_bid_size_fp")) or 0.0,
        }


# ---------------------------------------------------------------- OddsPapi
class QuotaExceeded(Exception):
    pass


class OddsPapi:
    BASE = "https://api.oddspapi.io/v4"

    def __init__(self, api_key: str, state: dict, monthly_budget: int):
        self.key = api_key
        self.state = state          # dict persisté : {"month": "2026-11", "used": 12}
        self.budget = monthly_budget
        self.s = requests.Session()
        self._last = 0.0

    def _count(self):
        month = time.strftime("%Y-%m", time.gmtime())
        if self.state.get("month") != month:
            self.state.update(month=month, used=0)
        if self.state["used"] >= self.budget:
            raise QuotaExceeded(f"budget mensuel atteint ({self.budget} requêtes)")
        self.state["used"] += 1

    def get(self, path: str, **params):
        self._count()
        wait = 1.2 - (time.time() - self._last)   # cooldown 1 s par endpoint
        if wait > 0:
            time.sleep(wait)
        params["apiKey"] = self.key
        r = self.s.get(f"{self.BASE}{path}", params=params, timeout=60)
        self._last = time.time()
        if r.status_code != 200:
            raise RuntimeError(f"OddsPapi {path} -> HTTP {r.status_code}: {r.text[:300]}")
        return r.json()

    def odds_by_tournaments(self, tournament_ids: list, bookmaker: str) -> list[dict]:
        """OddsPapi n'accepte qu'UN bookmaker par appel sur cet endpoint."""
        data = self.get("/odds-by-tournaments",
                        tournamentIds=",".join(str(t) for t in tournament_ids),
                        bookmaker=bookmaker)
        if isinstance(data, dict):
            data = data.get("data") or data.get("fixtures") or list(data.values())
        return [d for d in data if isinstance(d, dict)]

    @staticmethod
    def price(fixture: dict, slug: str, market: str, outcome: str):
        """Cote décimale active, ou None (marché suspendu = prix 1.0 à ignorer)."""
        try:
            book = fixture["bookmakerOdds"][slug]
            if book.get("suspended"):
                return None
            mk = book["markets"][str(market)]
            if mk.get("marketActive") is False:
                return None
            pl = mk["outcomes"][str(outcome)]["players"]["0"]
        except (KeyError, TypeError):
            return None
        if pl.get("active") is False:
            return None
        p = _f(pl.get("price"))
        return p if p and p > 1.0 else None


# ---------------------------------------------------------------- Telegram
def send_telegram(text: str) -> bool:
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("[telegram] secrets absents, message non envoyé")
        return False
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      json={"chat_id": chat, "text": text, "parse_mode": "HTML",
                            "disable_web_page_preview": True}, timeout=TIMEOUT)
    if r.status_code != 200:
        print(f"[telegram] erreur {r.status_code}: {r.text[:200]}")
    return r.status_code == 200
