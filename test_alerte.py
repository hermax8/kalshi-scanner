"""Envoie sur Telegram un EXEMPLE d'alerte d'arbitrage (cotes fictives), pour voir l'affichage.
Ne consomme aucune requête OddsPapi et n'écrit rien dans data/."""
from datetime import date, datetime, timedelta, timezone

import scan
from scanner.arb import Option, best_cover
from scanner.clients import send_telegram

il_y_a = (datetime.now(timezone.utc) - timedelta(minutes=95)).isoformat()
opts = [
    Option(frozenset(["away"]), 1 / 3.20, "bet365", "bet365 « Real Madrid » @ 3.20", 3.20, il_y_a),
    Option(frozenset(["home", "draw"]), 0.61 + 0.0167, "kalshi", "Kalshi NON « Real Madrid » à 0.61 $", 0.61),
]
arb = best_cover(["home", "draw", "away"], opts)
ev = {"sport": "soccer", "title": "Arsenal vs Real Madrid", "date": date.today() + timedelta(days=1)}
msg = scan.fmt_arb(ev, arb, arb.margin - 0.01, {}, scan.eur_usd())
send_telegram("🧪 <b>TEST — exemple fictif, ne pas miser</b>\n\n" + msg)
print(msg)
