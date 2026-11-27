"""Calculs d'arbitrage et de value.

Convention : chaque "option" coûte `cost` pour recevoir 1 unité si l'une des
issues de `covers` se produit.
  - Bookmaker, cote décimale o sur l'issue k : cost = 1/o, covers = {k}
  - Kalshi OUI à p sur k : cost = p + frais, covers = {k}
  - Kalshi NON à q sur k : cost = q + frais, covers = toutes les issues sauf k
Si on peut couvrir toutes les issues pour un coût total < 1, c'est un arbitrage.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations


@dataclass(frozen=True)
class Option:
    covers: frozenset
    cost: float
    source: str        # "kalshi" ou slug bookmaker
    label: str         # ex. "OUI Everton à 0.42 $" / "Everton @ 2.40"
    price: float       # cote décimale (bookmaker) ou prix du contrat (Kalshi)
    changed: str = ""  # bookmaker : date ISO du dernier changement de la cote (OddsPapi changedAt)


@dataclass
class Arb:
    total_cost: float
    margin: float                       # profit garanti en fraction de la mise totale
    legs: list = field(default_factory=list)
    mixed: bool = False                 # mélange Kalshi + bookmaker (change USD/EUR)


def kalshi_fee(price: float, fee_rate: float) -> float:
    """Frais taker Kalshi par contrat (approximation sans l'arrondi au centime)."""
    return fee_rate * price * (1.0 - price)


def _partitions(items: list):
    """Toutes les partitions d'un petit ensemble (2 ou 3 issues)."""
    if not items:
        yield []
        return
    first, rest = items[0], items[1:]
    for k in range(len(rest) + 1):
        for others in combinations(rest, k):
            block = frozenset((first,) + others)
            remaining = [x for x in rest if x not in others]
            for p in _partitions(remaining):
                yield [block] + p


def best_cover(outcomes: list, options: list[Option]) -> Arb | None:
    """Couverture la moins chère de toutes les issues (une option par bloc)."""
    cheapest: dict[frozenset, Option] = {}
    for opt in options:
        cur = cheapest.get(opt.covers)
        if cur is None or opt.cost < cur.cost:
            cheapest[opt.covers] = opt

    best = None
    for part in _partitions(list(outcomes)):
        if not all(b in cheapest for b in part):
            continue
        legs = [cheapest[b] for b in part]
        total = sum(l.cost for l in legs)
        if best is None or total < best.total_cost:
            sources = {l.source == "kalshi" for l in legs}
            best = Arb(total_cost=total, margin=1.0 / total - 1.0, legs=legs,
                       mixed=len(sources) > 1)
    return best


def stakes_for(arb: Arb, payout: float = 100.0) -> list[tuple[Option, float]]:
    """Mise par jambe pour encaisser `payout` quel que soit le résultat.
    Bookmaker : mise en € ; Kalshi : nombre de contrats (1 $ chacun à l'échéance)."""
    out = []
    for leg in arb.legs:
        if leg.source == "kalshi":
            out.append((leg, payout))                # contrats
        else:
            out.append((leg, payout / leg.price))     # mise €
    return out


def fair_probs(mids: dict) -> dict | None:
    """Probabilités 'justes' Kalshi : milieux de fourchette normalisés à 100 %."""
    total = sum(mids.values())
    if total <= 0:
        return None
    return {k: v / total for k, v in mids.items()}


def value_bets(fair: dict, book_odds: dict[str, dict], min_ev: float) -> list[dict]:
    """book_odds = {slug: {issue: cote}}. Renvoie les paris à espérance >= min_ev."""
    found = []
    for slug, odds in book_odds.items():
        for outcome, o in odds.items():
            p = fair.get(outcome)
            if p is None or o <= 1.0:
                continue
            ev = o * p - 1.0
            if ev >= min_ev:
                found.append({"bookmaker": slug, "outcome": outcome, "odds": o,
                              "fair_prob": p, "fair_odds": 1.0 / p, "ev": ev})
    return sorted(found, key=lambda x: -x["ev"])
