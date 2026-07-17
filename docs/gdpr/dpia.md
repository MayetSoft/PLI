# Analyse d'impact relative à la protection des données (AIPD / DPIA)

Une AIPD est indiquée : traitement à grande échelle potentiel de données
de l'art. 9 (vie affective) concernant des personnes potentiellement
vulnérables (étudiants), par un dispositif « innovant ». Trame :

## 1. Description du traitement

Voir `registre_traitements.md` T1 et HANDOFF.md. La donnée dangereuse
n'est pas l'adresse e-mail : c'est **le graphe des déclarations** (« A
espère que B partage ses sentiments »).

## 2. Nécessité et proportionnalité

- Finalité unique et explicite ; aucune réutilisation.
- Minimisation maximale : pas de comptes participants, pas d'historique,
  pas d'horodatage des déclarations, pseudonymisation à clé + chiffrement,
  destruction à la révélation.
- Durée : bornée par la manche (jours, voire heures).

## 3. Risques et mesures

| Risque | Gravité | Mesures |
|---|---|---|
| Divulgation d'un sentiment non réciproque | Maximale — c'est le préjudice que le produit existe pour empêcher | Silence structurel : aucune notification hors paire réciproque ; annulation = silence ; suspension = silence ; réponses HTTP identiques (tests I1–I8) |
| Accès illégitime à la base (dump) | Élevée | Empreintes HMAC poivrées + AES-GCM ; poivre hors base ; graphe détruit à la révélation ; pas de sauvegardes |
| Opérateur malveillant / réquisition pendant une manche | Élevée | Fenêtre réduite à la durée de la manche ; code public ; v2 envisagée : OPRF à deux opérateurs (Callisto) supprimant la capacité unilatérale |
| Coercition d'un participant (« montre-moi ta liste ») | Élevée | Les déclarations sont irrécupérables, y compris par leur auteur |
| Harcèlement via événements | Moyenne | Cohortes bornées (domaines/codes), plafond de 3, signalements anonymes, suspension automatique, listes noires |
| Corrélation par journaux | Moyenne | Pas de journaux de requêtes applicatifs ; journaux d'accès désactivés ; e-mail sans archivage |

## 4. Conclusion (à faire valider)

Les risques résiduels sont ramenés à un niveau acceptable par la
conception ; le risque le plus grave (révélation d'un sentiment non
réciproque) est traité par des invariants testés plutôt que par des
procédures. Consultation CNIL préalable non requise si cette analyse est
confirmée par le conseil.
