# PROJECT_STATUS

## 23/11/2026 — rotation des bookmakers
- OddsPapi /odds-by-tournaments n'accepte qu'UN bookmaker par appel → un bookmaker par passage, en rotation
  (bet365 → Unibet → Winamax → PokerStars). 6 passages/jour = 1 requête chacun ; chaque bookmaker revu ~1,5 fois/jour.
- Conséquence : on compare Kalshi à un bookmaker à la fois ; les surebets entre bookmakers ne sont plus cherchées
  (rares en France de toute façon). Plan payant nécessaire pour tout scanner à chaque passage.

## 23/11/2026 — configuration après découverte
- Plan OddsPapi gratuit : 250 requêtes/mois, cotes avant-match seulement ; budget scanner = 235.
- Bookmakers confirmés : bet365, unibet.fr, winamax.fr, pokerstars.fr (tous inclus dans le plan).
- Compétitions : foot 17/7/8/23/35/34 (marché 101), basket 132/138 (marché 111, prolongations incluses).
- Tennis : marché 121 prêt, mais aucun match Kalshi ouvert (fin de saison) → tournament_ids vides jusqu'à la reprise.
- Séries Kalshi vérifiées (foot + NBA + EuroLeague : matchs ouverts). KXATPMATCH/KXWTAMATCH : 0 pour l'instant.
- account.json nettoyé (clé et e-mail retirés) ; discover.py ne les enregistre plus.

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
