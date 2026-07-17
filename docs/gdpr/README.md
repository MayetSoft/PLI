# Documentation RGPD / GDPR documentation

Dossier de conformité de l'exploitant (SASU de droit français). Ces
documents sont des **projets sérieux mais non validés par un conseil
juridique** — les faire relire avant tout lancement. Les pages publiées
(politique de confidentialité, CGU, accord de sous-traitance) vivent dans
`pli/templates/legal_*.html` et sont servies sous `/legal/…`.

- `registre_traitements.md` — registre des activités de traitement (art. 30 RGPD)
- `retention.md` — registre des durées de conservation
- `sous_traitants.md` — liste des sous-traitants ultérieurs
- `dpia.md` — analyse d'impact (AIPD) : trame et conclusions

Points de posture à ne pas perdre :

1. **La minimisation n'est pas un chapitre, c'est l'architecture.** Le
   produit supprime le graphe des déclarations à la révélation, ne tient
   ni profils, ni historique, ni sauvegardes, ni journaux de requêtes.
2. **Deux casquettes.** Responsable de traitement pour la communauté par
   défaut ; sous-traitant des organisateurs pour leurs événements.
3. **Article 9.** Le contenu d'une déclaration peut révéler la vie
   affective ou l'orientation sexuelle : consentement explicite
   (art. 9.2.a) recueilli par l'acte volontaire de déclaration, après
   information. C'est aussi la raison du « rien au repos » : la donnée
   la plus sensible du système a une durée de vie maximale de cinq jours.
