# Sous-traitants ultérieurs

À compléter avec les choix définitifs avant lancement. Exigences non
négociables pour chacun :

1. Hébergement des données en Union européenne.
2. DPA art. 28 signé.
3. Pour l'e-mail : archivage des messages **désactivé**, rétention des
   journaux minimale, webhooks bounce/plainte activés (alimentent la
   liste de suppression).

| Rôle | Prestataire pressenti | Localisation | Notes |
|---|---|---|---|
| Hébergement | [Scaleway / OVHcloud / Hetzner] | UE | VPS + Docker/Traefik |
| E-mail transactionnel | [Scaleway TEM / OVH / Postmark*] | UE / *US-EU DPF | Domaine dédié, SPF+DKIM+DMARC |
| Paiement | Stripe Payments Europe Ltd | Irlande | Organisateurs uniquement ; aucune donnée participant |

\* Postmark est opérationnellement excellent mais implique un transfert
encadré (DPF/CCT) ; un prestataire UE est préférable pour la cohérence
de la posture.
