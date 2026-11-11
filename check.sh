#!/usr/bin/env bash
# Vérifie que la stack media est saine. À lancer depuis le dossier du projet.
# Usage : ./check.sh [--killswitch]
#   --killswitch coupe le tunnel ~15 s pour vérifier qu'aucun trafic ne sort.
set -uo pipefail
cd "$(dirname "$0")"

set -a; [ -f .env ] && . ./.env; set +a
: "${DATA_DIR:?DATA_DIR absent de .env}"
PUID=${PUID:-1000}; PGID=${PGID:-1000}
QBIT_PORT=${QBIT_PORT:-8081}

fail=0
ok()  { printf '  ok    %s\n' "$1"; }
ko()  { printf '  FAIL  %s\n' "$1"; fail=1; }
check() { local name=$1; shift; if "$@" >/dev/null 2>&1; then ok "$name"; else ko "$name"; fi; }
# Commande dans le conteneur qBittorrent (= réseau de gluetun).
inq() { docker exec qbittorrent "$@"; }
# Premier résultat non vide, sinon vide.
qbit_pref() { inq curl -s --max-time 5 http://127.0.0.1:8081/api/v2/app/preferences | grep -o "\"$1\":[0-9]*" | cut -d: -f2; }

for c in gluetun qbittorrent; do
  [ "$(docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null)" = true ] || { echo "Conteneur $c arrêté : lancez « docker compose up -d »."; exit 1; }
done

echo "== vpn"
home4=$(curl -4 -s --max-time 10 https://ifconfig.me)
home6=$(curl -6 -s --max-time 10 https://ifconfig.me)
vpn4=$(inq curl -4 -s --max-time 10 https://ifconfig.me)
vpn6=$(inq curl -6 -s --max-time 10 https://ifconfig.me)
# IP annoncée par gluetun après connexion (mesurée à travers le tunnel Proton).
glue_ip=$(docker logs gluetun 2>&1 | grep -o 'Public IP address is [0-9.]*' | tail -1 | awk '{print $NF}')
[ -n "$vpn4" ] && [ "$vpn4" != "$home4" ] && ok "IP de sortie de qBittorrent = $vpn4 (hôte : $home4)" \
  || ko "IP de sortie de qBittorrent '$vpn4' vs hôte '$home4'"
[ -n "$glue_ip" ] && [ "$vpn4" = "$glue_ip" ] && ok "= IP Proton annoncée par gluetun ($glue_ip)" \
  || ko "IP qBittorrent '$vpn4' ≠ IP Proton de gluetun '${glue_ip:-inconnue}'"
{ [ -z "$vpn6" ] || [ "$vpn6" != "$home6" ]; } && ok "IPv6 de qBittorrent = '${vpn6:-aucune}' (hôte : ${home6:-aucune})" \
  || ko "IPv6 de qBittorrent fuit l'IP de l'hôte"

# DNS : qBittorrent doit n'utiliser que le résolveur de gluetun (DNS over TLS dans le tunnel).
check "DNS de qBittorrent = résolveur de gluetun (127.0.0.1), pas celui de l'hôte" \
  inq sh -c 'grep -q "^nameserver 127.0.0.1" /etc/resolv.conf && [ "$(grep -c ^nameserver /etc/resolv.conf)" = 1 ]'
check "DNS résout depuis qBittorrent" inq nslookup example.com
# Témoin négatif : un résolveur local (passerelle docker) injoignable = pas de fuite hors tunnel.
gw=$(docker exec gluetun ip route | awk '/default/ {print $3; exit}')
check "DNS vers le réseau local (${gw:-?}) bloqué depuis qBittorrent" \
  inq sh -c "! nslookup -timeout=3 example.com ${gw:-192.0.2.1}"

echo "== port forwarding"
port=$(docker exec gluetun cat /tmp/gluetun/forwarded_port 2>/dev/null || true)
# Le port est poussé à qBittorrent après la connexion : laisse ~30 s.
qport=""
for _ in $(seq 1 15); do
  port=$(docker exec gluetun cat /tmp/gluetun/forwarded_port 2>/dev/null || true)
  qport=$(qbit_pref listen_port)
  [ -n "$port" ] && [ "$port" = "$qport" ] && break
  sleep 2
done
[ -n "$port" ] && ok "port forwardé = $port" || ko "aucun port forwardé (NAT-PMP coché sur la clé ? serveur P2P ?)"
[ -n "$port" ] && [ "$qport" = "$port" ] && ok "qBittorrent écoute sur $qport" \
  || ko "qBittorrent écoute sur '${qport:-?}', attendu '$port'"

echo "== stockage"
dir="$DATA_DIR"
if [ -d "$dir/torrents" ] && [ -d "$dir/library" ]; then
  t="/data/torrents/.check$$"; l="/data/library/.check$$"
  check "hardlink torrents/ → library/ (même inode)" \
    docker exec -u "$PUID:$PGID" sonarr sh -c "set -e; touch $t; ln $t $l; [ \"\$(stat -c %i $t)\" = \"\$(stat -c %i $l)\" ]; rm -f $t $l"
  docker exec sonarr rm -f "$t" "$l" 2>/dev/null
else
  ko "$dir/torrents ou $dir/library absent : lancez ./setup.sh"
fi

echo "== interfaces"
ui() { check "$1 répond ($2)" curl -s -o /dev/null --max-time 10 --retry 5 --retry-delay 3 --retry-connrefused "$2"; }
ui qBittorrent "http://localhost:$QBIT_PORT/"
ui Prowlarr    http://localhost:9696/
ui Sonarr      http://localhost:8989/
ui Radarr      http://localhost:7878/
ui Jellyfin    http://localhost:8096/
ui Jellyseerr  http://localhost:5055/
check "FlareSolverr répond (depuis Prowlarr)" docker exec prowlarr curl -sf --max-time 10 http://flaresolverr:8191/
check "Sonarr joint qBittorrent via gluetun" docker exec sonarr curl -s -o /dev/null --max-time 10 http://gluetun:8081/
check "Radarr joint qBittorrent via gluetun" docker exec radarr curl -s -o /dev/null --max-time 10 http://gluetun:8081/

if [ "${1:-}" = "--killswitch" ]; then
  echo "== kill-switch (tunnel coupé ~15 s)"
  docker exec gluetun ip link set tun0 down
  check "IPv4 bloqué tunnel coupé" inq sh -c '! curl -4 -s --max-time 5 https://ifconfig.me'
  check "IPv6 bloqué tunnel coupé" inq sh -c '! curl -6 -s --max-time 5 https://ifconfig.me'
  check "DNS bloqué tunnel coupé"  inq sh -c '! nslookup -timeout=3 example.com'
  check "IP de l'hôte jamais exposée (connexion directe par IP bloquée)" inq sh -c '! curl -s --max-time 5 http://1.1.1.1/'
  echo "  ... rétablissement du tunnel"
  # tun0 coupé ne revient pas seul : on relance gluetun puis qBittorrent (qui doit rejoindre son nouveau réseau).
  docker restart gluetun >/dev/null
  for _ in $(seq 1 30); do
    [ "$(docker inspect -f '{{.State.Health.Status}}' gluetun)" = healthy ] && break; sleep 3
  done
  docker restart qbittorrent >/dev/null
  for _ in $(seq 1 30); do
    inq curl -4 -s --max-time 5 https://ifconfig.me >/dev/null 2>&1 && break; sleep 3
  done
  check "tunnel rétabli (qBittorrent ressort par Proton)" \
    sh -c "[ \"\$(docker exec qbittorrent curl -4 -s --max-time 10 https://ifconfig.me)\" != '$home4' ]"
fi

[ $fail -eq 0 ] && echo "TOUT VERT" || echo "ÉCHECS"
exit $fail
