# PROJECT_STATUS

## 23/11/2026 — v1 du scanner
**Fait**
- Scanner (scan.py) : arbitrage Kalshi ↔ bookmakers, arbitrage interne Kalshi, value bets ; alertes Telegram dédupliquées ; historique CSV.
- Découverte (discover.py) pour récupérer les IDs OddsPapi et les séries Kalshi.
- Garde-fou quota OddsPapi : budget mensuel dans config.yaml (200), une seule requête OddsPapi par passage.
- 9 tests unitaires et bout en bout (données factices) : OK.

**À faire**
1. Ajouter les secrets TELEGRAM_BOT_TOKEN et TELEGRAM_CHAT_ID au dépôt.
2. Lancer le workflow `discover` (Actions → discover → Run workflow).
3. Remplir config.yaml : tournament_ids, marchés tennis/basket, slugs bookmakers, séries Kalshi confirmées, vrai quota.
4. Laisser tourner ~2 semaines, puis analyser data/opportunities.csv (fréquence, taille, durée des écarts).

**Points d'attention**
- Tennis : Kalshi paie le vainqueur « dès qu'une balle est jouée » ; règles d'abandon différentes chez les bookmakers.
- Prix OddsPapi possiblement en léger retard sur les sites : toujours revérifier avant de miser.
- Les cotes affichées sont celles des versions FR (Unibet, Winamax, PokerStars) et bet365 (version de référence OddsPapi).
