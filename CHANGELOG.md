# V6.6 — Prix récursifs dans les crafts

- Modification du prix de vente de l’objet final.
- Modification des prix de tous les composants directs.
- Modification des prix des composants des composants, jusqu’à 8 niveaux.
- Affichage indenté de la hiérarchie des sous-recettes.
- Sauvegarde groupée sans doublons.

# V6.6 — Atelier & liste de courses

- Fusion de la Liste de courses et de l’Atelier.
- Tout objet ajouté depuis une fiche craft rejoint automatiquement « Objets à fabriquer ».
- La liste de courses est recalculée après déduction du stock.
- Recalcul automatique après ajout, retrait, changement de quantité ou modification du stock.
- Migration automatique de l’ancienne liste locale vers l’Atelier.

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

## V6.4 — Qualité de vie
- Ajout d’un filtre par type de ressource dans « Prix prioritaires ».
- Ajout de la modification des prix x1, x10 et x100 de l’objet crafté directement dans sa fiche.
- Enregistrement groupé du prix de vente et des ingrédients.
- Navigation au clavier avec Entrée entre les champs de prix.
