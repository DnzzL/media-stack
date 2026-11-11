"""Accès aux API de la stack locale pour les tests : clés lues dans les config.xml
de CONFIG_DIR (variable d'environnement, sinon .env à la racine du repo)."""
import json, os, re, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _config_dir():
    if os.environ.get('CONFIG_DIR'):
        return Path(os.environ['CONFIG_DIR'])
    for line in (ROOT / '.env').read_text().splitlines():
        if line.startswith('CONFIG_DIR='):
            return Path(line.split('=', 1)[1].strip().strip('"\''))
    raise SystemExit('CONFIG_DIR introuvable (variable ou .env)')


def api(app, port, host=None):
    """Retourne get(path) pour l'API v3 de Sonarr/Radarr."""
    key = re.search(r'<ApiKey>([^<]+)</ApiKey>', (_config_dir() / app / 'config.xml').read_text()).group(1)
    base = f'http://{host or os.environ.get("STACK_HOST", "localhost")}:{port}/api/v3'

    def get(path):
        req = urllib.request.Request(base + path, headers={'X-Api-Key': key})
        return json.load(urllib.request.urlopen(req, timeout=20))
    return get
