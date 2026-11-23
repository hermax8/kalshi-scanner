"""Découverte (à lancer une fois, à la main) : liste ce que Kalshi et OddsPapi proposent
pour remplir config.yaml. Coûte ~7 requêtes OddsPapi. Résultats dans data/discovery/."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import yaml

from scanner.clients import Kalshi, OddsPapi

ROOT = Path(__file__).parent
OUT = ROOT / "data" / "discovery"
SPORT_SLUGS = {"soccer": ["soccer", "football"], "tennis": ["tennis"], "basketball": ["basketball"]}


def save(name, obj):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(obj, indent=1, ensure_ascii=False, default=str))
    print(f"-> data/discovery/{name}")


def main():
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    summary = {}

    # ---- Kalshi : séries de matchs (GAME / MATCH) de la catégorie Sports
    k = Kalshi(cfg["kalshi"]["base_url"])
    series = k.get("/series", category="Sports").get("series", [])
    games = sorted(({"ticker": s["ticker"], "title": s.get("title")} for s in series
                    if s["ticker"].endswith(("GAME", "MATCH"))), key=lambda x: x["ticker"])
    save("kalshi_series.json", games)
    counts = {}
    for sc in cfg["sports"].values():
        for t in sc["kalshi_series"]:
            try:
                counts[t] = len(k.open_events(t))
            except Exception as e:
                counts[t] = f"erreur: {e}"
    summary["kalshi_configured_series_open_events"] = counts

    # ---- OddsPapi
    key = os.environ.get("ODDSPAPI_API_KEY")
    if not key:
        summary["oddspapi"] = "clé ODDSPAPI_API_KEY absente"
    else:
        op = OddsPapi(key, {}, 50)
        for path, name in (("/account", "account.json"), ("/sports", "sports.json"),
                           ("/bookmakers", "bookmakers.json"), ("/markets", "markets.json")):
            try:
                save(name, op.get(path))
            except Exception as e:
                summary[f"oddspapi{path}"] = str(e)
        sports = json.loads((OUT / "sports.json").read_text()) if (OUT / "sports.json").exists() else []
        for sport, slugs in SPORT_SLUGS.items():
            sid = next((s.get("sportId") for s in sports if s.get("slug") in slugs), None)
            summary[f"{sport}_sportId"] = sid
            if sid is None:
                continue
            try:
                save(f"tournaments_{sport}.json", op.get("/tournaments", sportId=sid))
            except Exception as e:
                summary[f"tournaments_{sport}"] = str(e)
        summary["oddspapi_requests_used"] = op.state.get("used")

    summary["time"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    save("summary.json", summary)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
