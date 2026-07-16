# Dofus Craft Manager — Salar

Application locale de calcul de rentabilité des crafts pour Dofus 3.

## Lancement

1. Installer Python 3.
2. Double-cliquer sur `start.bat`.
3. Ouvrir `http://127.0.0.1:8765` si le navigateur ne s'ouvre pas.

## V6.1 Performance

- Scan HDV supprimé.
- Conseiller fusionné dans Opportunités.
- Pages lourdes chargées uniquement à l'ouverture.
- Actualisation et synchronisation automatiques désactivées par défaut.
- Cache mémoire du moteur de recettes.
- Budget Opportunités strict, basé sur la dépense réelle des lots HDV.
- Atelier amélioré avec inventaire au clavier et bilan financier complet.

## Données privées

`data/dofus_salar.sqlite` contient les prix et l'inventaire personnels. Le fichier est ignoré par Git grâce à `.gitignore`.


### Architecture V6.2
Le backend est désormais réparti dans `dcm/` :
- `database.py` : SQLite et migrations
- `engine.py` : calcul récursif acheter/fabriquer
- `economics.py` : lots et prix unitaires
- `workshop.py` : atelier et budget strict
- `sync.py` : synchronisation Dofus
