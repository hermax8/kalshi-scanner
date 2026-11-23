# kalshi-scanner

Scanner d'opportunités entre **Kalshi** et les bookmakers (bet365 Malte, Unibet FR, Winamax FR, PokerStars FR).
**Phase 1 : aucune mise.** Le scanner lit les prix, compare, enregistre dans `data/` et alerte sur Telegram.

## Ce qu'il cherche
- **Arbitrage** : couvrir toutes les issues d'un match (Kalshi OUI/NON + cotes bookmakers) pour moins de 100 % → gain garanti, frais Kalshi et change inclus.
- **Arbitrage interne Kalshi** : même calcul, Kalshi seul (fonctionne même sans OddsPapi).
- **Value** : cote bookmaker au-dessus de la cote « juste » déduite des prix Kalshi (milieu de fourchette normalisé). Avantage statistique, pas un gain garanti.

Sports v1 : foot (1N2, temps réglementaire), tennis, basket. Filtre de liquidité Kalshi : écart ≤ 5 ¢ et ≥ 50 contrats.

## Fichiers
- `config.yaml` : bookmakers, seuils, compétitions, séries Kalshi.
- `scan.py` : le scanner (workflow `scan`, toutes les 4 h). `python scan.py --dry-run` pour tester sans rien écrire.
- `discover.py` : catalogue Kalshi + OddsPapi (workflow `discover`, à lancer à la main).
- `data/opportunities.csv` : historique des opportunités ; `data/last_scan.json` : bilan du dernier passage.

## Secrets GitHub
`ODDSPAPI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (les clés Kalshi ne servent pas en phase 1).

## Tests
`pip install -r requirements.txt pytest && python -m pytest -q`
