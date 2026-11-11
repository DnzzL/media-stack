#!/usr/bin/env python3
"""Configure la stack media via les API. Lancé par setup.sh dans un conteneur
python (stdlib seule), sur le réseau docker de la stack. Idempotent : chaque
réglage est « créé s'il manque, remis à la valeur voulue sinon ».

Entrée (variables d'environnement) :
  QBIT_PASSWORD       mot de passe voulu pour qBittorrent (obligatoire)
  QBIT_TEMP_PASSWORD  mot de passe temporaire des logs (première fois seulement)
  JELLYFIN_API_KEY    clé API Jellyfin (facultatif : active Connect Jellyfin)
Les clés API des *arr sont lues dans /config/<app>/config.xml.
"""
import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

QBIT = "http://gluetun:8081"
QBIT_USER = "admin"
CONFIG = "/config"

# Regex des formats personnalisés (pièges documentés dans le README du setup NixOS de référence).
RE_CAM = r"\b(HQ[ ._-]?Pre|PreDVD|HD-?CAM|CAM(Rip)?|HD-?TS|TS|TELESYNC|TC|TELECINE|HC)\b"
RE_VF = r"\b(MULTi|VFF|VF2|VFi|VFQ|TRUEFRENCH|FRENCH)\b"
RE_SUBS = r"VOSTFR|SUBFRENCH"

PUBLIC_INDEXERS = ["1337x", "The Pirate Bay", "YTS", "EZTV", "LimeTorrents"]
CLOUDFLARE_INDEXERS = {"1337x", "LimeTorrents"}  # tag flaresolverr

ANY_LANGUAGE = {"id": -1, "name": "Any"}


class Fatal(Exception):
    pass


def say(msg):
    print(f"  {msg}", flush=True)


# --------------------------------------------------------------------- HTTP --
class Api:
    def __init__(self, name, base, key):
        self.name, self.base, self.key = name, base, key

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.base + path, data=data, method=method,
            headers={"X-Api-Key": self.key, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:400]
            raise Fatal(f"{self.name} {method} {path} → {e.code} {detail}") from None
        except urllib.error.URLError as e:
            raise Fatal(f"{self.name} {method} {path} → {e.reason}") from None
        return json.loads(raw) if raw else None

    def get(self, path):
        return self.call("GET", path)

    def post(self, path, body):
        return self.call("POST", path, body)

    def put(self, path, body):
        return self.call("PUT", path, body)


def api_key(app):
    path = f"{CONFIG}/{app}/config.xml"
    for _ in range(60):
        try:
            m = re.search(r"<ApiKey>([^<]+)</ApiKey>", open(path).read())
            if m:
                return m.group(1)
        except OSError:
            pass
        time.sleep(2)
    raise Fatal(f"{path} introuvable : {app} a-t-il démarré (docker compose up -d) ?")


def connect(app, port, version="v3"):
    api = Api(app, f"http://{app}:{port}/api/{version}", api_key(app))
    for _ in range(90):
        try:
            api.get("/system/status")
            return api
        except Fatal:
            time.sleep(2)
    raise Fatal(f"{app} ne répond pas sur le port {port}")


def by_name(items, name):
    return next((i for i in items if i.get("name") == name), None)


def set_fields(item, values):
    """Renseigne les champs (liste name/value) d'une ressource *arr."""
    for f in item["fields"]:
        if f["name"] in values:
            f["value"] = values[f["name"]]


def upsert(api, path, name, build, label):
    """Crée la ressource `name` ou met à jour l'existante. build(item) la prépare."""
    existing = by_name(api.get(path), name)
    if existing:
        build(existing)
        api.put(f"{path}/{existing['id']}", existing)
        say(f"{label} : à jour")
        return existing
    item = build(None)
    created = api.post(path, item)
    say(f"{label} : créé")
    return created


# ------------------------------------------------------------------ qBittorrent
def qbittorrent(password, temp):
    print("== qBittorrent")
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def post(path, form):
        req = urllib.request.Request(QBIT + path, data=urllib.parse.urlencode(form).encode(),
                                     headers={"Referer": QBIT})
        try:
            return opener.open(req, timeout=30).read().decode()
        except urllib.error.HTTPError as e:
            return f"HTTP {e.code}"

    logged = None
    for _ in range(60):  # qBittorrent peut démarrer après gluetun
        try:
            for candidate in (temp, password):  # temp d'abord : évite un échec de login (5 = ban 1 h)
                if candidate and post("/api/v2/auth/login", {"username": QBIT_USER, "password": candidate}) in ("Ok.", ""):  # qBittorrent 5 : 204 sans corps
                    logged = candidate
                    break
            break
        except (urllib.error.URLError, OSError):
            time.sleep(2)
    if not logged:
        raise Fatal("connexion à qBittorrent impossible : ni le mot de passe de .env ni le mot de passe "
                    "temporaire des logs ne passent (5 échecs = IP bannie 1 h : redémarrez le conteneur qbittorrent).")
    prefs = {
        "save_path": "/data/torrents",
        "max_ratio_enabled": True, "max_ratio": 1.0,
        "max_seeding_time_enabled": True, "max_seeding_time": 10080,  # 7 jours
        "max_ratio_act": 0,       # 0 = Stop torrent (pas Remove : Sonarr/Radarr s'en chargent)
        "upnp": False,            # le port est géré par gluetun
        "web_ui_password": password,
    }
    r = post("/api/v2/app/setPreferences", {"json": json.dumps(prefs)})
    if r.startswith("HTTP"):
        raise Fatal(f"qBittorrent setPreferences → {r}")
    say("réglages appliqués (dossier, limites de seed puis Stop, UPnP off, mot de passe)")


# --------------------------------------------------------------------- Prowlarr
def wait_flaresolverr():
    for _ in range(60):
        try:
            urllib.request.urlopen("http://flaresolverr:8191/", timeout=5).read()
            return
        except (urllib.error.URLError, OSError):
            time.sleep(2)
    raise Fatal("FlareSolverr ne répond pas sur http://flaresolverr:8191/")


def prowlarr(sonarr_key, radarr_key):
    print("== Prowlarr")
    api = connect("prowlarr", 9696, "v1")
    wait_flaresolverr()

    tag = next((t for t in api.get("/tag") if t["label"] == "flaresolverr"), None) \
        or api.post("/tag", {"label": "flaresolverr"})

    def proxy(existing):
        item = existing or next(s for s in api.get("/indexerProxy/schema") if s["implementation"] == "FlareSolverr")
        item.update(name="FlareSolverr", tags=[tag["id"]])
        set_fields(item, {"host": "http://flaresolverr:8191/", "requestTimeout": 60})
        return item
    upsert(api, "/indexerProxy", "FlareSolverr", proxy, "proxy FlareSolverr (tag flaresolverr)")

    profiles = api.get("/appprofile")
    profile = (by_name(profiles, "Standard") or profiles[0])["id"]
    missing = []
    have = {i["name"] for i in api.get("/indexer")}
    schemas = {s["name"]: s for s in api.get("/indexer/schema")}
    for name in PUBLIC_INDEXERS:
        if name in have:
            say(f"indexeur {name} : déjà présent")
            continue
        if name not in schemas:
            say(f"indexeur {name} : absent de cette version de Prowlarr, ignoré")
            missing.append(name)
            continue
        item = dict(schemas[name], enable=True, appProfileId=profile,
                    tags=[tag["id"]] if name in CLOUDFLARE_INDEXERS else [])
        try:
            api.post("/indexer", item)
            say(f"indexeur {name} : ajouté")
        except Fatal as e:  # un indexeur public peut être en panne : pas bloquant
            say(f"indexeur {name} : test refusé, non ajouté (relancez plus tard) : {str(e)[:120]}")
            missing.append(name)

    for app, port, key in (("Sonarr", 8989, sonarr_key), ("Radarr", 7878, radarr_key)):
        def application(existing, app=app, port=port, key=key):
            item = existing or next(s for s in api.get("/applications/schema") if s["implementation"] == app)
            item.update(name=app, syncLevel="fullSync")
            set_fields(item, {"prowlarrUrl": "http://prowlarr:9696", "baseUrl": f"http://{app.lower()}:{port}", "apiKey": key})
            return item
        upsert(api, "/applications", app, application, f"application {app}")
    return missing


# ------------------------------------------------------------------ Sonarr/Radarr
def custom_format(api, name, specs):
    """specs : [(nom, regex, négation)] ; toutes obligatoires (ET)."""
    def build(existing):
        item = existing or {"name": name}
        item["includeCustomFormatWhenRenaming"] = False
        item["specifications"] = [
            {"name": n, "implementation": "ReleaseTitleSpecification", "negate": neg, "required": True,
             "fields": [{"name": "value", "value": rx}]} for n, rx, neg in specs]
        return item
    return upsert(api, "/customformat", name, build, f"format personnalisé {name}")


def set_allowed(items, allowed_names, denied_names):
    for it in items:
        name = it.get("name") or it["quality"]["name"]
        if name in allowed_names or name in denied_names:
            it["allowed"] = name in allowed_names
            for sub in it.get("items", []):
                sub["allowed"] = it["allowed"]


def profiles(api, is_radarr):
    cams = custom_format(api, "Pre-release/CAM", [("Pre-release/CAM", RE_CAM, False)]) if is_radarr else None
    vf = custom_format(api, "VF", [("Audio français", RE_VF, False), ("Pas de sous-titres seuls", RE_SUBS, True)])

    def scores(profile, wanted):
        by_id = {f["format"]: f for f in profile["formatItems"]}
        for cf, score in wanted:
            by_id[cf["id"]]["score"] = score

    base_name = "HD-1080p"
    base = by_name(api.get("/qualityprofile"), base_name)
    if not base:
        raise Fatal(f"profil {base_name} absent : version inattendue ?")
    set_allowed(base["items"], {"WEB 1080p", "Bluray-1080p"}, {"HDTV-1080p"})
    base["cutoff"] = 7  # Bluray-1080p (le défaut de Sonarr pointait HDTV-1080p, désormais décoché)
    base["minFormatScore"] = 0
    if is_radarr:
        scores(base, [(cams, -10000)])
    api.put(f"/qualityprofile/{base['id']}", base)
    say(f"profil {base_name} : à jour")

    # Clone : même qualités, VF obligatoire (+10000, seuil 10000).
    vf_profile = by_name(api.get("/qualityprofile"), "HD-1080p VF")
    if not vf_profile:
        vf_profile = json.loads(json.dumps(base))
        vf_profile.pop("id", None)
        vf_profile["name"] = "HD-1080p VF"
    else:
        vf_profile["items"] = json.loads(json.dumps(base["items"]))
        vf_profile["cutoff"] = base["cutoff"]
    vf_profile["minFormatScore"] = 10000
    vf_profile["cutoffFormatScore"] = 10000
    if is_radarr:
        # Radarr lit MULTi comme « Unknown » : Language=French le rejetterait. Le filtre, c'est VF.
        vf_profile["language"] = ANY_LANGUAGE
    for f in vf_profile["formatItems"]:
        f["score"] = 0
    scores(vf_profile, [(vf, 10000)] + ([(cams, -10000)] if is_radarr else []))
    if "id" in vf_profile:
        api.put(f"/qualityprofile/{vf_profile['id']}", vf_profile)
    else:
        api.post("/qualityprofile", vf_profile)
    say("profil HD-1080p VF : à jour")


def quality_sizes(api, names, lo, hi):
    defs = api.get("/qualitydefinition")
    changed = []
    for d in defs:
        if d["title"] in names:
            d.update(minSize=lo, maxSize=hi, preferredSize=min(d.get("preferredSize") or hi, hi))
            changed.append(d)
    api.put("/qualitydefinition/update", changed)
    # Radarr met parfois quelques secondes à servir les nouvelles valeurs : on attend de les relire.
    for _ in range(30):
        now = {d["title"]: (d.get("minSize"), d.get("maxSize")) for d in api.get("/qualitydefinition")}
        if all(now[d["title"]] == (lo, hi) for d in changed):
            break
        time.sleep(2)
    else:
        raise Fatal(f"{api.name} : tailles de qualité non relues après modification")
    say(f"tailles 1080p : {lo} à {hi} Mo/min")


def arr(app, api, kind, qbit_password, jellyfin_key):
    print(f"== {app}")
    is_radarr = kind == "radarr"

    root = "/data/library/movies" if is_radarr else "/data/library/tv"
    if root not in [r["path"] for r in api.get("/rootfolder")]:
        api.post("/rootfolder", {"path": root})
        say(f"dossier racine {root} : créé")
    else:
        say(f"dossier racine {root} : déjà présent")

    mm = api.get("/config/mediamanagement")
    mm["copyUsingHardlinks"] = True
    mm["autoUnmonitorPreviouslyDownloadedMovies" if is_radarr else "autoUnmonitorPreviouslyDownloadedEpisodes"] = True
    api.put(f"/config/mediamanagement", mm)
    say("hardlinks activés, « unmonitor deleted » activé")

    dc_cfg = api.get("/config/downloadclient")
    dc_cfg["enableCompletedDownloadHandling"] = True
    api.put("/config/downloadclient", dc_cfg)

    def client(existing):
        item = existing or next(s for s in api.get("/downloadclient/schema") if s["implementation"] == "QBittorrent")
        item.update(name="qBittorrent", enable=True, removeCompletedDownloads=True, removeFailedDownloads=True)
        set_fields(item, {"host": "gluetun", "port": 8081, "useSsl": False, "username": QBIT_USER,
                          "password": qbit_password,
                          "movieCategory" if is_radarr else "tvCategory": "movies" if is_radarr else "tv"})
        return item
    upsert(api, "/downloadclient", "qBittorrent", client, "client qBittorrent (Remove Completed, catégorie)")

    if jellyfin_key:
        def jellyfin(existing):
            item = existing or next(s for s in api.get("/notification/schema") if s["implementation"] == "MediaBrowser")
            item["name"] = "Jellyfin"
            for k in ("onDownload", "onUpgrade", "onRename", "onSeriesDelete", "onEpisodeFileDelete",
                      "onMovieDelete", "onMovieFileDelete"):
                if k in item:
                    item[k] = True
            set_fields(item, {"host": "jellyfin", "port": 8096, "useSsl": False, "apiKey": jellyfin_key,
                              "updateLibrary": True, "notify": False})
            return item
        upsert(api, "/notification", "Jellyfin", jellyfin, "Connect Jellyfin (Update Library)")
    else:
        say("Connect Jellyfin : ignoré (pas de JELLYFIN_API_KEY, voir la fin de setup.sh)")

    profiles(api, is_radarr)
    if is_radarr:
        quality_sizes(api, {"WEBDL-1080p", "WEBRip-1080p", "Bluray-1080p", "Remux-1080p"}, 15, 50)
    else:  # ~2 Go par épisode de 45 min
        quality_sizes(api, {"HDTV-1080p", "WEBDL-1080p", "WEBRip-1080p", "Bluray-1080p"}, 15, 45)


def main():
    password = os.environ.get("QBIT_PASSWORD", "")
    if not password:
        raise Fatal("QBIT_PASSWORD manquant")
    jellyfin_key = os.environ.get("JELLYFIN_API_KEY", "")
    qbittorrent(password, os.environ.get("QBIT_TEMP_PASSWORD", ""))
    # Sonarr/Radarr d'abord prêts : Prowlarr teste leur API en les ajoutant.
    sonarr, radarr = connect("sonarr", 8989), connect("radarr", 7878)
    missing = prowlarr(sonarr.key, radarr.key)
    arr("Sonarr", sonarr, "sonarr", password, jellyfin_key)
    arr("Radarr", radarr, "radarr", password, jellyfin_key)
    if missing:
        print(f"\nATTENTION : indexeurs non ajoutés : {', '.join(missing)}. Relancez ./setup.sh plus tard "
              "(ou ajoutez-les dans Prowlarr > Indexers).")


if __name__ == "__main__":
    try:
        main()
    except Fatal as e:
        print(f"ERREUR : {e}", file=sys.stderr)
        sys.exit(1)
