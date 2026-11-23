"""Scanner Kalshi <-> bookmakers. Aucune mise : lit, compare, enregistre, alerte.

Lancement : python scan.py            (alertes Telegram si secrets présents)
            python scan.py --dry-run  (rien n'est envoyé ni écrit dans data/)
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

from scanner.arb import Option, best_cover, fair_probs, kalshi_fee, stakes_for, value_bets
from scanner.clients import Kalshi, OddsPapi, QuotaExceeded, send_telegram
from scanner.matching import kalshi_event_date, match_fixture, norm

ROOT = Path(__file__).parent
DATA = ROOT / "data"
STATE_FILE = DATA / "state.json"
CSV_FILE = DATA / "opportunities.csv"
SPORT_FR = {"soccer": "foot", "tennis": "tennis", "basketball": "basket"}
LABEL_FR = {"home": "dom.", "draw": "Nul", "away": "ext."}


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def eur_usd(default=1.08) -> float:
    try:
        r = requests.get("https://api.frankfurter.app/latest?from=EUR&to=USD", timeout=10)
        return float(r.json()["rates"]["USD"])
    except Exception:
        return default


# ------------------------------------------------------------------ Kalshi
def kalshi_events(k: Kalshi, sport: str, cfg: dict, log: dict) -> list[dict]:
    """Normalise les matchs Kalshi : {names: [A, B], quotes: {issue: quote}, ...}."""
    out = []
    for series in cfg.get("kalshi_series", []):
        try:
            events = k.open_events(series)
        except Exception as e:
            log["errors"].append(f"Kalshi {series}: {e}")
            continue
        log["kalshi_series"][series] = len(events)
        for ev in events:
            markets = ev.get("markets") or []
            tie = [m for m in markets if m["ticker"].endswith("-TIE")
                   or (m.get("yes_sub_title") or "").lower() in ("tie", "draw")]
            teams = [m for m in markets if m not in tie]
            if len(teams) != 2 or (sport == "soccer" and len(tie) != 1) or (sport != "soccer" and tie):
                continue
            out.append({
                "sport": sport, "series": series, "ticker": ev["event_ticker"],
                "title": ev.get("title", ""), "date": kalshi_event_date(ev["event_ticker"]),
                "names": [m.get("yes_sub_title") or m.get("title", "") for m in teams],
                "markets": {"A": teams[0], "B": teams[1], **({"draw": tie[0]} if tie else {})},
            })
    return out


def kalshi_options(ev: dict, role_of: dict, outcomes: list, kcfg: dict):
    """Options Kalshi (OUI/NON) qui passent le filtre de liquidité, + milieux de fourchette."""
    opts, mids = [], {}
    for key, m in ev["markets"].items():
        role = role_of[key]
        q = Kalshi.quote(m)
        if q["yes_bid"] is None or q["yes_ask"] is None:
            continue
        if q["yes_ask"] - q["yes_bid"] > kcfg["max_spread"]:
            continue
        mids[role] = (q["yes_bid"] + q["yes_ask"]) / 2
        name = m.get("yes_sub_title") or role
        if q["yes_ask_size"] >= kcfg["min_ask_size"] and 0 < q["yes_ask"] < 1:
            p = q["yes_ask"]
            opts.append(Option(frozenset([role]), p + kalshi_fee(p, kcfg["fee_rate"]), "kalshi",
                               f"Kalshi OUI « {name} » à {p:.2f} $", p))
        if q["no_ask"] and q["no_ask_size"] >= kcfg["min_ask_size"] and 0 < q["no_ask"] < 1:
            p = q["no_ask"]
            opts.append(Option(frozenset(set(outcomes) - {role}), p + kalshi_fee(p, kcfg["fee_rate"]),
                               "kalshi", f"Kalshi NON « {name} » à {p:.2f} $", p))
    if set(mids) != set(outcomes):
        mids = {}
    return opts, mids


# ------------------------------------------------------------------ OddsPapi
def parse_fixtures(raw: list[dict]) -> list[dict]:
    for fx in raw:
        ts = fx.get("startTime") or fx.get("trueStartTime")
        try:
            fx["_date"] = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).date()
        except (TypeError, ValueError):
            fx["_date"] = None
    return raw


def add_participant_names(op, raw: list[dict], log: dict, max_age_days: int = 7):
    """OddsPapi ne renvoie que des IDs d'équipes : on complète avec /participants (cache local)."""
    for sid in {fx.get("sportId") for fx in raw if fx.get("sportId") is not None}:
        path = DATA / f"participants_{sid}.json"
        cache = load_json(path, {})
        ids = {str(fx.get(k)) for fx in raw if fx.get("sportId") == sid
               for k in ("participant1Id", "participant2Id")}
        stale = time.time() - cache.get("_fetched", 0) > max_age_days * 86400
        if stale or not ids <= set(cache):
            try:
                data = op.get("/participants", sportId=sid)
                if isinstance(data, list):   # format v5 éventuel
                    data = {str(d.get("participantId")): d.get("name") for d in data}
                cache = {str(k): v for k, v in data.items()}
                cache["_fetched"] = time.time()
                DATA.mkdir(exist_ok=True)
                path.write_text(json.dumps(cache, ensure_ascii=False))
                log.setdefault("participants_refreshed", []).append(sid)
            except Exception as e:
                log["errors"].append(f"participants {sid}: {e}")
        for fx in raw:
            if fx.get("sportId") == sid:
                fx["participant1Name"] = cache.get(str(fx.get("participant1Id")), "")
                fx["participant2Name"] = cache.get(str(fx.get("participant2Id")), "")


def book_options(fx: dict, scfg: dict, books: dict, swapped_names: list):
    """Options bookmakers + dict {slug: {issue: cote}} pour la value."""
    opts, odds = [], {}
    for nick, slug in books.items():
        for oid, role in scfg["oddspapi_outcomes"].items():
            o = OddsPapi.price(fx, slug, scfg["oddspapi_market"], oid)
            if o is None:
                continue
            odds.setdefault(slug, {})[role] = o
            opts.append(Option(frozenset([role]), 1.0 / o, slug,
                               f"{nick} « {swapped_names[role]} » @ {o:.2f}", o))
    return opts, odds


# ------------------------------------------------------------------ Alertes
def should_alert(state: dict, key: str, value: float, hours: float) -> bool:
    prev = state.setdefault("alerts", {}).get(key)
    t = time.time()
    if prev and t - prev[0] < hours * 3600 and value < prev[1] + 0.005:
        return False
    state["alerts"][key] = [t, value]
    return True


def fmt_arb(ev, arb, margin, names_by_role, eurusd):
    lines = [f"🟢 <b>ARBITRAGE +{margin*100:.1f} %</b> ({SPORT_FR[ev['sport']]})",
             f"{ev['title']} · {ev['date']:%d/%m}" if ev["date"] else ev["title"]]
    for leg, stake in stakes_for(arb, 100.0):
        if leg.source == "kalshi":
            lines.append(f"• {leg.label} → {stake*eurusd:.0f} contrats")
        else:
            lines.append(f"• {leg.label} → {stake:.2f} €")
    lines.append(f"Pour encaisser 100 € quel que soit le résultat (change {'inclus' if arb.mixed else 'sans objet'}).")
    if ev["sport"] == "tennis":
        lines.append("⚠️ Règles d'abandon différentes selon les sites : vérifie avant.")
    lines.append("⚠️ Revérifie les cotes en direct avant de miser.")
    return "\n".join(lines)


def fmt_value(ev, vb, names_by_role):
    return (f"💡 <b>VALUE +{vb['ev']*100:.1f} %</b> ({SPORT_FR[ev['sport']]})\n"
            f"{ev['title']}\n"
            f"• {vb['bookmaker']} « {names_by_role[vb['outcome']]} » @ {vb['odds']:.2f}\n"
            f"Cote juste selon Kalshi : {vb['fair_odds']:.2f} (proba {vb['fair_prob']*100:.0f} %)\n"
            f"Pas un gain garanti : avantage statistique seulement.")


# ------------------------------------------------------------------ Main
def main(dry_run: bool = False):
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    kcfg, th = cfg["kalshi"], cfg["thresholds"]
    aliases = {norm(k): norm(v) for k, v in (cfg.get("aliases") or {}).items()}
    state = load_json(STATE_FILE, {})
    log = {"time": now_iso(), "kalshi_series": {}, "errors": [], "unmatched": [],
           "matched": 0, "fixtures": 0, "opportunities": 0}

    k = Kalshi(kcfg["base_url"])
    kevents = []
    for sport, scfg in cfg["sports"].items():
        kevents += kalshi_events(k, sport, scfg, log)
    log["kalshi_events"] = len(kevents)

    # Cotes bookmakers : UNE requête pour toutes les compétitions configurées
    fixtures_by_sport = {s: [] for s in cfg["sports"]}
    tid_sport = {str(t): s for s, sc in cfg["sports"].items() if sc.get("oddspapi_market")
                 for t in sc.get("tournament_ids", [])}
    key = os.environ.get("ODDSPAPI_API_KEY")
    active_books = {}
    if tid_sport and key:
        op_state = state.setdefault("oddspapi", {})
        op = OddsPapi(key, op_state, cfg["oddspapi"]["monthly_request_budget"])
        # Limites OddsPapi : 1 bookmaker et 5 compétitions max par appel.
        # Une requête par passage, en tournant sur les combinaisons (bookmaker × groupe de compétitions).
        books = cfg["oddspapi"]["bookmakers"]
        tids = list(tid_sport)
        chunks = [tids[i:i + 5] for i in range(0, len(tids), 5)]
        combos = [(nick, ch) for nick in books for ch in chunks]
        idx = state.get("rotation", 0) % len(combos)
        nick, chunk = combos[idx]
        active_books = {nick: books[nick]}
        state["rotation"] = idx + 1
        log["bookmaker_this_run"] = nick
        log["tournaments_this_run"] = chunk
        try:
            raw = op.odds_by_tournaments(chunk, books[nick])
            if raw:
                log["fixture_sample"] = {k: v for k, v in raw[0].items() if k != "bookmakerOdds"}
                bo = raw[0].get("bookmakerOdds") or {}
                log["fixture_sample"]["_books"] = list(bo)[:5] if isinstance(bo, dict) else str(type(bo))
                b0 = next(iter(bo.values()), {}) if isinstance(bo, dict) else {}
                log["fixture_sample"]["_markets"] = list((b0.get("markets") or {}))[:10]
            add_participant_names(op, raw, log)
            for fx in parse_fixtures(raw):
                s = tid_sport.get(str(fx.get("tournamentId")))
                if s:
                    fixtures_by_sport[s].append(fx)
            log["fixtures"] = sum(len(v) for v in fixtures_by_sport.values())
        except QuotaExceeded as e:
            log["errors"].append(str(e))
        except Exception as e:
            log["errors"].append(f"OddsPapi: {e}")
        log["oddspapi_used_this_month"] = op_state.get("used")
    else:
        log["errors"].append("OddsPapi non configuré (tournament_ids vides ou clé absente) : "
                             "seuls les arbitrages internes Kalshi sont cherchés.")

    series_tid = cfg.get("series_tournament") or {}
    run_tids = {str(t) for t in log.get("tournaments_this_run", [])}
    eurusd = eur_usd()
    rows, alerts = [], []
    for ev in kevents:
        scfg = cfg["sports"][ev["sport"]]
        outcomes = scfg["outcomes"]
        fx_match = None
        ev_tid = str(series_tid.get(ev["series"], ""))
        fetched = not ev_tid or ev_tid in run_tids
        if fixtures_by_sport[ev["sport"]] and fetched:
            fx_match = match_fixture(ev["names"], ev["date"], fixtures_by_sport[ev["sport"]], aliases)
            if not fx_match:
                log["unmatched"].append(ev["title"])
        swapped = fx_match[1] if fx_match else False
        first, second = (("home", "away") if ev["sport"] == "soccer" else ("p1", "p2"))
        role_of = {"A": second if swapped else first, "B": first if swapped else second, "draw": "draw"}
        names_by_role = {role_of["A"]: ev["names"][0], role_of["B"]: ev["names"][1], "draw": "Nul"}

        opts, mids = kalshi_options(ev, role_of, outcomes, kcfg)
        book_odds = {}
        if fx_match:
            log["matched"] += 1
            b_opts, book_odds = book_options(fx_match[0], scfg, active_books, names_by_role)
            opts += b_opts

        arb = best_cover(outcomes, opts)
        if arb:
            margin = arb.margin - (th["fx_cost"] if arb.mixed else 0.0)
            if margin >= th["min_arb_margin"]:
                kind = "arb_kalshi" if all(l.source == "kalshi" for l in arb.legs) else "arb"
                legs_txt = " | ".join(l.label for l in arb.legs)
                rows.append([now_iso(), kind, ev["sport"], ev["title"], legs_txt, f"{margin:.4f}"])
                sig = f"{kind}|{ev['ticker']}|" + "|".join(sorted(f"{l.source}:{sorted(l.covers)}" for l in arb.legs))
                if should_alert(state, sig, margin, th["realert_hours"]):
                    alerts.append(fmt_arb(ev, arb, margin, names_by_role, eurusd))

        fair = fair_probs(mids) if mids else None
        if fair and book_odds:
            for vb in value_bets(fair, book_odds, th["min_value_ev"]):
                rows.append([now_iso(), "value", ev["sport"], ev["title"],
                             f"{vb['bookmaker']} {names_by_role[vb['outcome']]} @ {vb['odds']:.2f} "
                             f"(juste {vb['fair_odds']:.2f})", f"{vb['ev']:.4f}"])
                sig = f"value|{ev['ticker']}|{vb['bookmaker']}|{vb['outcome']}"
                if should_alert(state, sig, vb["ev"], th["realert_hours"]):
                    alerts.append(fmt_value(ev, vb, names_by_role))

    log["opportunities"] = len(rows)
    log["unmatched"] = log["unmatched"][:40]
    print(json.dumps(log, indent=2, ensure_ascii=False, default=str))
    for a in alerts:
        print("\n" + a)

    if dry_run:
        return
    DATA.mkdir(exist_ok=True)
    new = not CSV_FILE.exists()
    with CSV_FILE.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["time_utc", "type", "sport", "match", "details", "margin_or_ev"])
        w.writerows(rows)
    for a in alerts[:10]:            # pas plus de 10 messages par passage
        send_telegram(a)
    # ménage des vieilles alertes (> 3 jours)
    state["alerts"] = {k2: v for k2, v in state.get("alerts", {}).items() if time.time() - v[0] < 3 * 86400}
    STATE_FILE.write_text(json.dumps(state, indent=1))
    (DATA / "last_scan.json").write_text(json.dumps(log, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
