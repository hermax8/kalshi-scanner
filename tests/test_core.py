import json
from datetime import date

import scan
from scanner.arb import Option, best_cover, fair_probs, kalshi_fee, stakes_for, value_bets
from scanner.matching import kalshi_event_date, match_fixture, name_score


def O(cov, cost, src="b", price=2.0):
    return Option(frozenset(cov), cost, src, "x", price)


def test_surebet_two_books():
    # 2.10 / 2.10 -> 1/2.1*2 = 0.952 -> +5 %
    arb = best_cover(["p1", "p2"], [O({"p1"}, 1/2.1, price=2.1), O({"p2"}, 1/2.1, price=2.1)])
    assert abs(arb.margin - 0.05) < 1e-9
    stakes = stakes_for(arb, 100)
    assert all(abs(s - 100/2.1) < 1e-9 for _, s in stakes)


def test_no_arb_when_overround():
    arb = best_cover(["p1", "p2"], [O({"p1"}, 1/1.9), O({"p2"}, 1/1.9)])
    assert arb.margin < 0


def test_three_way_uses_kalshi_no():
    # Kalshi NON dom. (= nul ou ext.) à 0.50 + bookmaker dom. @ 2.20
    opts = [O({"draw", "away"}, 0.50, "kalshi", 0.5), O({"home"}, 1/2.2, "unibet", 2.2),
            O({"draw"}, 1/3.0), O({"away"}, 1/3.5)]
    arb = best_cover(["home", "draw", "away"], opts)
    assert abs(arb.total_cost - (0.5 + 1/2.2)) < 1e-9
    assert arb.mixed


def test_kalshi_fee():
    assert abs(kalshi_fee(0.5, 0.07) - 0.0175) < 1e-12


def test_value():
    fair = fair_probs({"p1": 0.6, "p2": 0.4})
    vb = value_bets(fair, {"winamax": {"p1": 1.80, "p2": 2.70}}, 0.03)
    assert [v["outcome"] for v in vb] == ["p1", "p2"] or [v["outcome"] for v in vb] == ["p2", "p1"]
    assert all(v["ev"] >= 0.03 for v in vb)


def test_names():
    assert name_score("Man City", "Manchester City") > 0.7
    assert name_score("Daniil Medvedev", "Medvedev, Daniil") > 0.9
    assert name_score("Everton", "Fulham") < 0.5
    assert name_score("Atletico", "Atlético Madrid") > 0.6


def test_event_date():
    assert kalshi_event_date("KXEPLGAME-26DEC06EVEFUL") == date(2026, 12, 6)


def test_match_swapped():
    fx = [{"participant1Name": "Fulham FC", "participant2Name": "Everton FC", "_date": date(2026, 12, 6)},
          {"participant1Name": "Arsenal", "participant2Name": "Chelsea", "_date": date(2026, 12, 6)}]
    res = match_fixture(["Everton", "Fulham"], date(2026, 12, 6), fx)
    assert res and res[0] is fx[0] and res[1] is True
    assert match_fixture(["Everton", "Fulham"], date(2026, 12, 20), fx) is None


def _market(ticker, name, bid, ask, size=500):
    return {"ticker": ticker, "yes_sub_title": name, "yes_bid_dollars": str(bid),
            "yes_ask_dollars": str(ask), "no_ask_dollars": str(round(1 - bid, 2)),
            "yes_ask_size_fp": str(size), "yes_bid_size_fp": str(size)}


def test_full_scan_dry_run(monkeypatch, capsys, tmp_path):
    """Bout en bout avec des données factices : un arbitrage mixte doit sortir."""
    ev = {"event_ticker": "KXATPMATCH-26DEC06SINALC", "title": "Sinner vs Alcaraz", "markets": [
        _market("KXATPMATCH-26DEC06SINALC-SIN", "Jannik Sinner", 0.40, 0.42),
        _market("KXATPMATCH-26DEC06SINALC-ALC", "Carlos Alcaraz", 0.57, 0.59)]}
    monkeypatch.setattr(scan.Kalshi, "open_events", lambda self, s: [ev] if s == "KXATPMATCH" else [])
    fixture = {"tournamentId": 99, "participant1Name": "Alcaraz, Carlos", "participant2Name": "Sinner, Jannik",
               "startTime": "2026-12-06T14:00:00Z",
               "bookmakerOdds": {"bet365": {"markets": {"M": {"outcomes": {
                   "1": {"players": {"0": {"price": 1.60, "active": True}}},
                   "2": {"players": {"0": {"price": 2.85, "active": True}}}}}}}}}
    monkeypatch.setattr(scan.OddsPapi, "odds_by_tournaments", lambda self, t, b: [fixture])
    monkeypatch.setattr(scan, "eur_usd", lambda: 1.1)
    monkeypatch.setenv("ODDSPAPI_API_KEY", "test")
    cfg = {
        "oddspapi": {"monthly_request_budget": 10, "bookmakers": {"bet365": "bet365"}},
        "kalshi": {"base_url": "x", "fee_rate": 0.07, "max_spread": 0.05, "min_ask_size": 50},
        "thresholds": {"min_arb_margin": 0.005, "min_value_ev": 0.03, "fx_cost": 0.01, "realert_hours": 12},
        "sports": {"tennis": {"outcomes": ["p1", "p2"], "oddspapi_market": "M",
                              "oddspapi_outcomes": {"1": "p1", "2": "p2"}, "tournament_ids": [99],
                              "kalshi_series": ["KXATPMATCH"]}},
        "aliases": {},
    }
    import yaml
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(cfg))
    monkeypatch.setattr(scan, "ROOT", tmp_path)
    monkeypatch.setattr(scan, "STATE_FILE", tmp_path / "state.json")
    scan.main(dry_run=True)
    out = capsys.readouterr().out
    # Sinner : bet365 @ 2.85 (coût 0.351) + Kalshi OUI Alcaraz 0.59+frais (0.607) = 0.958 -> ~+4,4 % -1 % change
    assert "ARBITRAGE" in out and "bet365" in out and "Kalshi OUI « Carlos Alcaraz »" in out
    assert '"matched": 1' in out


def test_name_substring_and_no_false_match():
    assert name_score("FC Köln", "1. FC Koln") >= 0.85
    assert name_score("Bremen", "Werder Bremen") >= 0.85
    assert name_score("Leeds United", "Leicester City") < 0.6
    fx = [{"participant1Name": "Manchester United", "participant2Name": "Everton", "_date": date(2026, 11, 28)},
          {"participant1Name": "Newcastle United", "participant2Name": "Sunderland", "_date": date(2026, 11, 28)}]
    best = match_fixture(["Newcastle", "Sunderland"], date(2026, 11, 28), fx)
    assert best and best[0]["participant1Name"] == "Newcastle United"
