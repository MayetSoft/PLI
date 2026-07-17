# Registre des activités de traitement (art. 30 RGPD)

Exploitant : [COMPANY NAME] SASU — [ADRESSE] — SIREN [SIREN]
Contact : [CONTACT EMAIL] — Pas de DPO désigné à ce stade (à réévaluer
si le volume ou la nature des traitements change).

## T1 — Manches de déclarations réciproques (cœur du service)

| Champ | Contenu |
|---|---|
| Finalité | Mettre en relation deux personnes uniquement en cas de déclaration réciproque |
| Qualité | Responsable (communauté par défaut) ; sous-traitant (événements d'organisateurs) |
| Personnes | Participants majeurs de 15 ans et plus |
| Données | Adresse e-mail (empreinte HMAC + bloc AES-256-GCM) ; déclarations (paires d'empreintes) |
| Catégories particulières | Oui — le graphe peut révéler la vie affective/orientation (art. 9.2.a, consentement explicite) |
| Base légale | Consentement (6.1.a) + consentement explicite (9.2.a) |
| Destinataires | Aucun, sauf : chaque membre d'une paire réciproque reçoit l'adresse de l'autre |
| Durée | Jusqu'à la révélation ou l'annulation de la manche (≤ 5 jours pour l'hebdomadaire) ; effacement + VACUUM |
| Transferts hors UE | Aucun (hébergement et e-mail : UE — voir sous_traitants.md) |
| Sécurité | HMAC poivré, AES-GCM par manche, clés détruites, pas de journaux, pas de sauvegardes |

## T2 — Comptes organisateurs

| Champ | Contenu |
|---|---|
| Finalité | Création et gestion d'événements ; facturation |
| Qualité | Responsable |
| Données | E-mail, offre, configuration d'événements, identifiant client Stripe |
| Base légale | Contrat (6.1.b) |
| Durée | Vie du compte + obligations comptables (10 ans, pièces facturation chez le prestataire de paiement) |

## T3 — Sécurité de la plateforme (signalements, listes)

| Champ | Contenu |
|---|---|
| Finalité | Traiter les abus ; ne plus écrire aux adresses en erreur/plainte |
| Qualité | Responsable |
| Données | Signalements (motif, texte, empreinte IP) ; liste de suppression (empreintes) ; liste noire (adresses/domaines d'organisateurs) |
| Base légale | Intérêt légitime (6.1.f) |
| Durée | Signalements : 12 mois après clôture de l'événement ; suppression : sans limite (c'est sa fonction) ; liste noire : sans limite, revue annuelle |

## T4 — E-mails transactionnels

Liens de connexion et notifications de réciprocité, via prestataire
transactionnel configuré **sans archivage des messages**. Aucune
newsletter, aucune prospection.
