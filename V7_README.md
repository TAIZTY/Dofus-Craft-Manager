# Dofus Craft Manager V7.0 Alpha

Première fondation V7 construite à partir de la V6.6.

## Inclus

- fenêtre Craft presque plein écran ;
- zone centrale indépendante et boutons toujours accessibles ;
- sous-recettes repliables et dépliables ;
- boutons Tout déplier / Tout replier ;
- composants directs ouverts par défaut ;
- serveur exposé sur le réseau local (`0.0.0.0:8765`) ;
- adresse locale et adresse réseau affichées au démarrage ;
- sauvegarde automatique de la base à chaque démarrage ;
- conservation des 30 dernières sauvegardes.

## Démarrage

Double-cliquer sur `start_server.bat`, puis ouvrir l’adresse affichée.

Pour un accès distant privé, installer Tailscale sur le PC serveur et les PC amis, puis utiliser l’adresse Tailscale du serveur avec le port 8765.

## Sécurité

Cette Alpha ne contient pas encore l’authentification. Ne pas exposer directement le port 8765 sur Internet. Utiliser uniquement le réseau local ou Tailscale.
