#!/usr/bin/env python3
# Regression : les profils "HD-1080p VF" (Radarr et Sonarr) n'acceptent que les
# releases a audio francais. VOSTFR (sous-titres) et les releases sans tag FR
# restent sous le seuil.
# Usage : tests/french-audio.py   (cles API lues dans CONFIG_DIR/<app>/config.xml ;
# STACK_HOST pour viser une autre machine que localhost)
import os, sys, urllib.parse
sys.path.insert(0, os.path.dirname(__file__))
from _stack import api

PROFILE = 'HD-1080p VF'
CF = 'VF'
APPS = {
    'radarr': dict(port=7878, stem='Nosferatu.1922',
                   cam_cf='Pre-release/CAM'),
    'sonarr': dict(port=8989, stem='Show.Name.S01E01'),
}
GOOD = ['{s}.MULTi.1080p.BluRay.x264-GRP', '{s}.TRUEFRENCH.1080p.WEB-DL.x264-GRP',
        '{s}.FRENCH.1080p.WEB-DL.x264-GRP', '{s}.VFF.1080p.WEB-DL.x264-GRP',
        '{s}.MULTi.VF2.1080p.WEB-DL.x264-GRP']
BAD = ['{s}.1080p.BluRay.x264-GRP', '{s}.VOSTFR.1080p.WEB-DL.x264-GRP',
       '{s}.MULTi.SUBFRENCH.1080p.WEB-DL.x264-GRP', '{s}.1080p.WEB-DL.x264-GRP.German']
# Une release FR de mauvaise qualite ne doit pas passer non plus (Radarr).
CAM_FR = '{s}.TRUEFRENCH.HDCAM.x264-GRP'

fail = 0


def check(ok, msg):
    global fail
    fail |= not ok
    print(('  ok   ' if ok else '  FAIL ') + msg)


for app, c in APPS.items():
    print(f'== {app}')
    get = api(app, c['port'])

    prof = next((p for p in get('/qualityprofile') if p['name'] == PROFILE), None)
    check(prof is not None, f'profil "{PROFILE}" existe')
    if prof is None:
        continue
    scores = {i['name']: i['score'] for i in prof['formatItems']}
    check(scores.get(CF) == 10000 and prof['minFormatScore'] == 10000,
          f'{CF} = {scores.get(CF)}, seuil du profil = {prof["minFormatScore"]} (attendu 10000)')
    if 'cam_cf' in c:
        check(scores.get(c['cam_cf']) == -10000, f'{c["cam_cf"]} garde -10000 dans le profil VF')
        # Avec "Original", Radarr peut ecarter un TRUEFRENCH sur un film non francais :
        # le profil VF filtre deja par le format VF, pas par la langue.
        check(prof['language']['name'] == 'Any', f'langue du profil = {prof["language"]["name"]} (attendu Any)')

    def accepted(title):
        r = get('/parse?title=' + urllib.parse.quote(title))
        total = sum(scores.get(f['name'], 0) for f in r['customFormats'])
        return total >= prof['minFormatScore'], total

    for t in GOOD:
        ok, s = accepted(t.format(s=c['stem']))
        check(ok, f'accepte {s:6} {t.format(s=c["stem"])}')
    for t in BAD:
        ok, s = accepted(t.format(s=c['stem']))
        check(not ok, f'rejette {s:6} {t.format(s=c["stem"])}')
    if 'cam_cf' in c:
        ok, s = accepted(CAM_FR.format(s=c['stem']))
        check(not ok, f'rejette {s:6} {CAM_FR.format(s=c["stem"])}')

print('TOUT VERT' if not fail else 'ECHECS')
sys.exit(fail)
