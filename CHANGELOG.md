# Changelog

## V6.3 — Stable & Fluide
- Sauvegarde groupée des prix depuis une fiche craft (une seule requête).
- Cache réel du Dashboard et des Opportunités.
- Suppression du N+1 SQL dans Opportunités.
- Vérification stricte du budget limitée aux meilleurs candidats accessibles.
- Index SQLite complémentaires.
- Tests fonctionnels renforcés.

# Dofus Craft Manager — V6.1 Performance

## Modifications
- Suppression réelle du Scan HDV.
- Chargement différé des pages lourdes.
- Désactivation de l’actualisation automatique par défaut.
- Cache mémoire du moteur de recettes et des prix.
- Un seul moteur partagé pour tout l’arbre de craft.
- Fin des recalculs globaux après chaque saisie de prix.
- Atelier : sélection clavier, double-clic, suppression explicite du stock.
- Atelier : investissement, vente brute/nette, taxe, bénéfice net, ROI et bénéfice moyen.
- Ajout d’un `.gitignore` pour protéger la base locale.


## V6.2 — Architecture & performance
- Backend découpé en modules `dcm/` (base, moteur, économie, atelier, synchronisation).
- Cache des réponses analytiques invalidé lors des changements de prix, paramètres ou stock.
- SQLite configuré avec cache mémoire, mmap et tables temporaires en mémoire.
- Synchronisation API regroupée en opérations batch.
- Comportement et interface V6.1 conservés.
