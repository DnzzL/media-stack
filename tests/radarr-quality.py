#!/usr/bin/env python3
# Regression : Radarr doit rejeter les pre-releases (CAM/TS/HQ Pre...) quel que
# soit le libelle de qualite, et garder les releases legitimes.
# Usage : tests/radarr-quality.py   (cle API lue dans CONFIG_DIR/radarr/config.xml ;
# STACK_HOST pour viser une autre machine que localhost)
import sys, urllib.parse
sys.path.insert(0, __import__('os').path.dirname(__file__))
from _stack import api
get = api('radarr', 7878)
prof=[x for x in get('/qualityprofile') if x['name']=='HD-1080p'][0]
bad=["Spider-Man - Brand New Day 2026.1080p.HQ Pre.Multi.AAC 2.0.x264",
     "Nosferatu 1922 1080p HQ HDTS x265 AAC2.0 MULTI ESub -MAZE",
     "Nosferatu.1922.1080p.HDCAM.x264-GRP", "Nosferatu 1922 PreDVD 1080p x264",
     "Nosferatu.1922.1080p.WEBRip.x264.HC-GRP", "Nosferatu 1922 1080p TELESYNC x264-DKS"]
good=["Nosferatu.1922.1080p.BluRay.x264-HD4U [PublicHD]",
      "Project.Hail.Mary.(2026)[DUAL ESP-ENG][HDR10 HEVC][Bluray 1080p]-Mang0z4",
      "Nosferatu.1922.1080p.WEB-DL.DDP5.1.H.264-FLUX", "Nosferatu.1922.1080p.AMZN.WEB-DL.DTS-HD.MA.5.1-GRP",
      "Nosferatu.1922.The.Cameraman.Cut.1080p.BluRay.x264-GRP", "Nosferatu.1922.MULTi.1080p.BluRay.x264-TSC"]
sc={i['name']:i['score'] for i in prof['formatItems']}
fail=0
for t,want in [(t,'rejet') for t in bad]+[(t,'ok') for t in good]:
    # /parse ne note que si le titre correspond a un film de la bibliotheque :
    # on additionne nous-memes les scores du profil sur les formats reconnus.
    s=sum(sc.get(f['name'],0) for f in get('/parse?title='+urllib.parse.quote(t)).get('customFormats',[]))
    got='rejet' if s<prof['minFormatScore'] else 'ok'
    fail|= got!=want
    print(('  ok   ' if got==want else '  FAIL ')+f"{got:5} score={s:6} {t}")
for d in get('/qualitydefinition'):
    if d['title'] in ('WEBDL-1080p','WEBRip-1080p','Bluray-1080p','Remux-1080p'):
        good_size = d['minSize']==15 and d['maxSize']==50
        fail|= not good_size
        print(('  ok   ' if good_size else '  FAIL ')+f"{d['title']} {d['minSize']}-{d['maxSize']} Mo/min")
print('TOUT VERT' if not fail else 'ECHECS')
sys.exit(fail)
