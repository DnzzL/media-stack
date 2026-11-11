#!/usr/bin/env bash
# Configure la stack media (qBittorrent, Prowlarr, Sonarr, Radarr) via leurs API.
# À lancer une fois après « docker compose up -d » ; rejouable sans risque.
# Usage : ./setup.sh
set -euo pipefail
cd "$(dirname "$0")"

# Image pour le script de configuration : python n'est pas garanti sur le NAS.
PY_IMAGE=python:3.13-alpine

[ -f .env ] || { echo "Pas de .env : copiez .env.example en .env et remplissez-le."; exit 1; }
set -a; . ./.env; set +a
: "${DATA_DIR:?DATA_DIR absent de .env}"
: "${CONFIG_DIR:?CONFIG_DIR absent de .env}"
PUID=${PUID:-1000}; PGID=${PGID:-1000}

command -v docker >/dev/null || { echo "docker introuvable."; exit 1; }
for c in gluetun qbittorrent prowlarr sonarr radarr; do
  [ "$(docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null)" = true ] \
    || { echo "Conteneur $c arrêté : lancez « docker compose up -d » d'abord."; exit 1; }
done

echo "== dossiers"
# En root dans un conteneur : marche sur tout NAS, quel que soit le propriétaire de DATA_DIR.
docker run --rm -v "$DATA_DIR:/data" "$PY_IMAGE" sh -c \
  "mkdir -p /data/torrents /data/library/movies /data/library/tv && chown $PUID:$PGID /data/torrents /data/library /data/library/movies /data/library/tv && chmod 775 /data/torrents /data/library /data/library/movies /data/library/tv"
echo "  $DATA_DIR/torrents et $DATA_DIR/library/{movies,tv} prêts"

# Mot de passe qBittorrent : .env, sinon demandé une fois (et gardé dans .env).
if [ -z "${QBIT_PASSWORD:-}" ]; then
  if [ -t 0 ]; then
    while :; do
      read -r -s -p "Choisissez un mot de passe pour qBittorrent (8 caractères min., lettres/chiffres/._-@%+=), vide = en générer un : " QBIT_PASSWORD; echo
      [ -z "$QBIT_PASSWORD" ] && break
      printf '%s' "$QBIT_PASSWORD" | grep -Eq '^[A-Za-z0-9._@%+=-]{8,}$' && break
      echo "Mot de passe refusé (trop court ou caractères non permis)."
    done
  fi
  [ -n "${QBIT_PASSWORD:-}" ] || QBIT_PASSWORD=$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 16 || true)
  printf '\n# Mot de passe qBittorrent (écrit par setup.sh).\nQBIT_PASSWORD=%s\n' "$QBIT_PASSWORD" >> .env
  echo "Mot de passe enregistré dans .env (QBIT_PASSWORD), identifiant « admin »."
fi

# Mot de passe temporaire de qBittorrent (première fois seulement), pris dans ses logs.
temp=$(docker logs qbittorrent 2>&1 | grep -o 'temporary password is provided for this session: .*' | tail -1 | awk '{print $NF}' | tr -d '\r' || true)

network=$(docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}' gluetun)
docker run --rm --network "$network" \
  -e QBIT_PASSWORD="$QBIT_PASSWORD" -e QBIT_TEMP_PASSWORD="${temp:-}" -e JELLYFIN_API_KEY="${JELLYFIN_API_KEY:-}" \
  -v "$PWD/setup:/setup:ro" -v "$CONFIG_DIR:/config:ro" \
  "$PY_IMAGE" python3 -I /setup/configure.py

ip=$(hostname -I 2>/dev/null | awk '{print $1}' || true); ip=${ip:-IP-DU-NAS}
cat <<MSG

== À faire à la main (une fois)
1. Jellyfin  http://$ip:8096 : assistant de démarrage. Créez le compte administrateur,
   puis les bibliothèques : Films = /data/library/movies, Séries = /data/library/tv.
   (Facultatif) Tableau de bord > Clés API : créez une clé, mettez JELLYFIN_API_KEY=... dans .env,
   relancez ./setup.sh : Sonarr/Radarr préviendront Jellyfin à chaque import.
2. Jellyseerr  http://$ip:5055 : choisissez Jellyfin, serveur http://jellyfin:8096, connectez-vous
   avec le compte Jellyfin, importez les utilisateurs, lancez le scan des bibliothèques.
   Services : Radarr http://radarr:7878 et Sonarr http://sonarr:8989 (clés API : Réglages > Général
   de chacun), profil « HD-1080p » ; « HD-1080p VF » pour un contenu en français seulement.

Interfaces : qBittorrent http://$ip:${QBIT_PORT:-8081}  Prowlarr http://$ip:9696
             Sonarr http://$ip:8989  Radarr http://$ip:7878   Contrôle : ./check.sh
MSG
