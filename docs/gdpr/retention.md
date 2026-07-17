# Registre des durées de conservation

| Donnée | Durée | Sort |
|---|---|---|
| Participants d'une manche (empreintes + blocs chiffrés) | Jusqu'à révélation/annulation | DELETE + VACUUM, clé de manche détruite |
| Déclarations | Jusqu'à révélation/annulation | Idem — le graphe ne survit jamais |
| Liens magiques | Jusqu'à révélation/annulation (30 min de validité) | Idem |
| Clés de manche (fichiers) | Vie de la manche | Écrasées puis supprimées |
| Comptes organisateurs | Vie du compte | Suppression sur demande (hors obligations comptables) |
| Signalements d'abus | 12 mois après clôture de l'événement | Purge manuelle (CLI) |
| Liste de suppression e-mail | Permanente (empreintes seulement) | — |
| Liste noire organisateurs | Permanente, revue annuelle | — |
| Journaux applicatifs | Codes de statut et durées uniquement, 7 jours | Rotation |
| Journaux d'accès (Traefik) | **Désactivés** pour ce service | — |
| Sauvegardes de la base de participation | **Interdites** | — |

La ligne « sauvegardes interdites » est une décision de conception,
documentée dans HANDOFF.md : une sauvegarde est un graphe qui a survécu
à la révélation. La perte du fichier en cours de manche annule la
manche ; c'est le mode de défaillance choisi.
