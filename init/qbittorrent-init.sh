#!/bin/sh
# Exécuté par linuxserver/qbittorrent à chaque démarrage, avant qBittorrent.
# Active « Bypass authentication for clients on localhost » : gluetun s'en sert
# pour donner à qBittorrent le port forwardé. Ne touche pas aux autres réglages.
conf=/config/qBittorrent/qBittorrent.conf
mkdir -p "$(dirname "$conf")"
[ -f "$conf" ] || printf '[Preferences]\n' > "$conf"
if grep -q '^WebUI\\LocalHostAuth=' "$conf"; then
  sed -i 's/^WebUI\\LocalHostAuth=.*/WebUI\\LocalHostAuth=false/' "$conf"
elif grep -q '^\[Preferences\]' "$conf"; then
  sed -i '/^\[Preferences\]/a WebUI\\LocalHostAuth=false' "$conf"
else
  printf '\n[Preferences]\nWebUI\\LocalHostAuth=false\n' >> "$conf"
fi
