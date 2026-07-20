
## V7.0 Alpha — correctif interface Craft

- Remplacement des défilements indépendants par une seule barre de défilement pour toute la fiche Craft.
- Conservation de l'en-tête de l'éditeur de recette en position fixe pendant le défilement.
- Correction de `start_server.bat` pour détecter automatiquement `py -3` ou `python`.

# V7.0 Alpha — Fondation serveur privé et Craft interactif

- Fenêtre Craft presque plein écran.
- Sections centrales défilantes sans perdre les actions principales.
- Sous-composants repliables/dépliables individuellement.
- Commandes Tout déplier / Tout replier.
- Serveur accessible sur le réseau local.
- Affichage automatique de l’adresse réseau.
- Sauvegarde automatique au démarrage avec rotation sur 30 fichiers.
- Aucune prise en charge du x1000, conformément au choix produit.

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

## V7.1.1 — Collaboration stable
- Correction du démarrage sur un nouvel appareil : la fenêtre d'identité est maintenant chargée avant le JavaScript.
- Ajout de la présence des utilisateurs connectés.
- Ajout des statistiques de fraîcheur et de l'activité quotidienne.
- Conservation et migration automatique de la base V7.0.
