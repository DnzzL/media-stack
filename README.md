# media-stack : ta médiathèque personnelle sur ton NAS

Avec ce projet, ton NAS devient un petit « Netflix » à toi :

1. Tu demandes un film ou une série sur une page web (**Jellyseerr**).
2. Le NAS le trouve et le télécharge tout seul (**Radarr** pour les films, **Sonarr** pour les séries, **Prowlarr** pour chercher, **qBittorrent** pour télécharger).
3. Tu le regardes (**Jellyfin**), sur la télé, le téléphone ou l'ordinateur.

Les **téléchargements** (qBittorrent) passent **toujours** par un VPN (**Proton VPN**). Si le VPN tombe, ils s'arrêtent : rien ne sort avec ton adresse IP de maison. C'est le « kill-switch ». Seuls les téléchargements sont protégés : les recherches de Prowlarr, Radarr et Sonarr sortent avec l'IP de ta maison.

Tout fonctionne **dans ton réseau local** (ta box, ton wifi). Rien n'est accessible depuis Internet.

Tu n'as jamais utilisé Docker ? Pas de souci. Docker est un outil qui fait tourner chaque application dans sa « boîte ». Tu n'as qu'à copier-coller quelques commandes. Chaque étape est expliquée.

> **Légal** : télécharge uniquement ce que tu as le droit de télécharger. Tu es responsable de ton usage.

## Sommaire

1. [Ce qu'il te faut](#1-ce-quil-te-faut)
2. [Récupérer ta clé Proton VPN](#2-récupérer-ta-clé-proton-vpn)
3. [Créer le dossier de données](#3-créer-le-dossier-de-données)
4. [Remplir `.env` et démarrer](#4-remplir-env-et-démarrer)
5. [Configurer : `./setup.sh`, Jellyfin, Jellyseerr](#5-configurer--setupsh-jellyfin-jellyseerr)
6. [Vérifier : `./check.sh`](#6-vérifier--checksh)
7. [Au quotidien](#7-au-quotidien)
8. [Dépannage](#8-dépannage)
9. [Les adresses des applications](#9-les-adresses-des-applications)

---

## 1. Ce qu'il te faut

| Il te faut | Détail |
|---|---|
| Un NAS **x86** avec **Docker** | Processeur Intel ou AMD. Les NAS d'entrée de gamme à processeur **ARM** ne conviennent **pas**. |
| **4 Go de RAM** ou plus | Huit applications tournent en même temps : en dessous, le NAS risque de ramer. |
| Docker **Compose v2** | La commande `docker compose version` doit répondre. Sur Synology : **Container Manager** (DSM 7.2 ou plus récent). |
| Un abonnement **Proton VPN payant** | Le port forwarding (nécessaire pour télécharger vite) n'existe que sur les offres payantes. |
| De l'espace disque | Un film en 1080p pèse jusqu'à environ 6 Go, un épisode jusqu'à environ 2 Go. |
| Un accès **SSH** au NAS | Une « ligne de commande » à distance. Voir ci-dessous. |

**Vérifier que ton NAS est x86.** Dans un terminal SSH (voir plus bas), tape :

```bash
uname -m
```

Si tu vois `x86_64` : c'est bon. Si tu vois `aarch64` ou `armv7l` : c'est un ARM, ce projet n'est pas pour ce NAS.

### Activer SSH et se connecter

- **Synology (DSM 7)** : *Panneau de configuration* > *Terminal et SNMP* > coche *Activer le service SSH*.
- **QNAP** : *Panneau de configuration* > *Services réseau et de fichiers* > *Telnet / SSH* > coche *Autoriser la connexion SSH*.

Ensuite, depuis ton ordinateur (Terminal sur Mac et Linux, PowerShell sur Windows) :

```bash
ssh TON-UTILISATEUR@IP-DU-NAS
```

Remplace `TON-UTILISATEUR` par ton compte administrateur du NAS et `IP-DU-NAS` par l'adresse de ton NAS (par exemple `192.168.1.20`, visible dans l'interface de ta box). Tape ton mot de passe quand on te le demande (rien ne s'affiche, c'est normal).

### Récupérer le projet sur le NAS

Copie le dossier du projet sur le NAS (par exemple avec *File Station* sur Synology), **en entier** (avec `init/` et `setup/`), puis, en SSH, place-toi dedans. Exemple Synology :

```bash
cd /volume1/docker/projet-media
```

(Adapte le chemin à l'endroit où tu as mis le dossier. Il doit contenir `docker-compose.yml`, `.env.example`, `setup.sh`, `check.sh` et les dossiers `init/` et `setup/`. Ce dossier est **différent** de `CONFIG_DIR` (étape 4) : ne mélange pas les deux.)

Si les scripts ont perdu leur droit d'exécution pendant la copie, rends-le leur :

```bash
chmod +x setup.sh check.sh
```

> **Sur Synology et QNAP, les commandes `docker` demandent les droits administrateur.** Si tu vois `permission denied`, ajoute `sudo` devant : `sudo docker compose up -d`, `sudo ./setup.sh`, `sudo ./check.sh`.

---

## 2. Récupérer ta clé Proton VPN

La « clé privée » est un long mot de passe qui permet au NAS de se connecter à ton compte Proton VPN.

1. Va sur **account.protonvpn.com** et connecte-toi.
2. Ouvre **Téléchargements** (*Downloads*), puis la partie **WireGuard**.
3. Choisis la plateforme **GNU/Linux**.
4. **Coche « NAT-PMP (redirection de port) »**. C'est ce qui permet de recevoir des connexions (donc de télécharger vite). Sans lui, le port forwarding ne marche pas.
5. Choisis un serveur **P2P** (c'est le nom des serveurs qui acceptent le téléchargement par torrent).
6. Clique sur **Créer** (ou *Create*). Une configuration s'affiche, ou un fichier se télécharge.
7. Dans cette configuration, cherche la ligne qui commence par `PrivateKey =`. **Copie seulement la valeur**, c'est-à-dire le long texte après le `=`. Garde-la de côté pour l'étape 4.

> **Cette clé est secrète.** Ne l'envoie à personne, ne la publie pas.

---

## 3. Créer le dossier de données

### Pourquoi un seul dossier ?

Un téléchargement arrive d'abord dans `torrents/`. Une fois fini, il est « rangé » dans `library/` pour que Jellyfin le trouve. Si les deux dossiers sont sur le même volume, le NAS ne copie rien : il crée un **hardlink** (un second nom pour le même fichier, sans doublon). Résultat : le film continue d'être partagé (seed) tout en étant dans ta bibliothèque, et il n'occupe la place **qu'une seule fois**.

Si les dossiers étaient sur deux disques différents, le hardlink serait impossible et chaque film prendrait **deux fois** la place.

Donc : **un seul dossier**, appelé `DATA_DIR` dans la suite. Les sous-dossiers (`torrents`, `library/movies`, `library/tv`) sont créés pour toi par `./setup.sh`.

### Créer le dossier

> **Synology (DSM 7)**
>
> 1. *Panneau de configuration* > *Dossier partagé* > *Créer* > *Créer un dossier partagé*.
> 2. Nom : `media`. Choisis ton volume (en général `volume1`).
> 3. **Décoche « Activer la corbeille »** : sinon les fichiers supprimés restent dans une corbeille et ne libèrent pas de place.
> 4. Le dossier est alors `/volume1/media`. C'est la valeur par défaut de `DATA_DIR` dans `.env.example`.
>
> Crée aussi un dossier pour les réglages des applications, par exemple `/volume1/docker/media-stack` (c'est `CONFIG_DIR`). Si le dossier partagé `docker` existe déjà (créé par Container Manager), crée simplement le sous-dossier `media-stack` dedans.

> **QNAP**
>
> 1. *Panneau de configuration* > *Privilège* > *Dossiers partagés* > *Créer* > *Dossier partagé*. Nom : `media`.
> 2. En SSH, les dossiers partagés se trouvent sous `/share/`. Ton dossier est donc `/share/media`.
> 3. Crée aussi un dossier pour les réglages, par exemple `/share/media-config`.
>
> (Vérifie le chemin avec `ls /share` en SSH.)

> **Autre NAS Linux** : n'importe quel dossier existant sur ton disque de données, par exemple `/srv/media`.

### Trouver ton PUID et ton PGID

Ce sont deux numéros : ceux de l'utilisateur du NAS qui possède le dossier `media`. Les applications s'en servent pour écrire les fichiers avec les bons droits.

En SSH, connecté avec cet utilisateur, tape :

```bash
id
```

Tu obtiens une ligne comme `uid=1026(thomas) gid=100(users) ...`. Ici, **PUID = 1026** (le `uid`) et **PGID = 100** (le `gid`). Note les tiens pour l'étape suivante.

---

## 4. Remplir `.env` et démarrer

### Créer `.env`

Dans le dossier du projet, copie le modèle :

```bash
cp .env.example .env
```

Ouvre `.env` avec un éditeur. `.env` est un fichier **caché** (son nom commence par un point) : il n'apparaît pas toujours dans l'explorateur du NAS. En SSH, `nano .env` marche s'il est installé (sauvegarde avec `Ctrl+O` puis `Entrée`, quitte avec `Ctrl+X`). Sinon, utilise `vi .env`, ou copie `.env` sur ton ordinateur, modifie-le avec un éditeur de texte, puis remets-le sur le NAS.

| Variable | Ce que c'est | Que mettre |
|---|---|---|
| `WIREGUARD_PRIVATE_KEY` | Ta clé Proton VPN (étape 2). **Obligatoire** : sans elle, Docker refuse de démarrer. | Colle la valeur après le `=`, sans espace ni guillemets. |
| `SERVER_COUNTRIES` | Pays des serveurs Proton à utiliser. Noms **en anglais**, séparés par des virgules. | Laisse `Switzerland`, ou mets par exemple `France` ou `Switzerland,Netherlands`. |
| `DATA_DIR` | Le dossier de données (étape 3). | Ex. `/volume1/media` (Synology), `/share/media` (QNAP). |
| `CONFIG_DIR` | Où chaque application garde ses réglages. Petit : à sauvegarder. | Ex. `/volume1/docker/media-stack`. |
| `PUID` | Numéro d'utilisateur (étape 3). | Ton `uid`. |
| `PGID` | Numéro de groupe (étape 3). | Ton `gid`. |
| `TZ` | Ton fuseau horaire. | Laisse `Europe/Paris` si tu es en France. |

Trois autres lignes sont **en commentaire** (elles commencent par `#`) : tu n'es pas obligé de les toucher.

| Variable | Ce que c'est |
|---|---|
| `QBIT_PORT` | Le port de la page web de qBittorrent (`8081` par défaut). À changer seulement si ce port est déjà pris sur ton NAS. |
| `QBIT_PASSWORD` | Le mot de passe de qBittorrent (identifiant `admin`). `./setup.sh` te le demande et l'écrit ici pour toi. |
| `JELLYFIN_API_KEY` | Facultatif. Voir [l'étape 5](#5-configurer--setupsh-jellyfin-jellyseerr). |

> **Ne partage jamais `.env`** : il contient ta clé VPN. Il est déjà exclu de git.

### Autoriser le VPN : `/dev/net/tun`

Le VPN a besoin d'un « périphérique » du système appelé `/dev/net/tun`. Teste s'il existe :

```bash
ls -l /dev/net/tun
```

Si tu vois une ligne qui commence par `crw`, c'est bon, passe à la suite. Si tu vois `No such file or directory` (fréquent sur **Synology**), il faut le créer **à chaque démarrage** du NAS :

> **Synology (DSM 7) : créer `/dev/net/tun` au démarrage**
>
> 1. *Panneau de configuration* > *Planificateur de tâches* > *Créer* > *Tâche déclenchée* > *Script défini par l'utilisateur*.
> 2. Onglet *Général* : nom `tun`, utilisateur **root**, événement **Démarrage**.
> 3. Onglet *Paramètres de la tâche*, dans *Script défini par l'utilisateur*, colle exactement :
>
> ```bash
> #!/bin/bash
> if [ ! -c /dev/net/tun ]; then
>   [ -d /dev/net ] || mkdir -m 755 /dev/net
>   mknod /dev/net/tun c 10 200
>   chmod 0755 /dev/net/tun
> fi
> lsmod | grep -q "^tun " || insmod /lib/modules/tun.ko
> ```
>
> 4. Valide, puis **sélectionne la tâche et clique sur *Exécuter*** (pas besoin de redémarrer le NAS). Relance `ls -l /dev/net/tun` : la ligne doit maintenant commencer par `crw`.

### Préparer le dossier de Jellyseerr

Jellyseerr tourne avec ton `PUID`/`PGID`. Si Docker crée lui-même son dossier de réglages, il le crée en `root` et Jellyseerr ne peut pas y écrire. Crée-le donc avant de démarrer (remplace `CONFIG_DIR`, `PUID` et `PGID` par tes valeurs de `.env`) :

```bash
sudo mkdir -p CONFIG_DIR/jellyseerr
sudo chown PUID:PGID CONFIG_DIR/jellyseerr
```

Exemple : `sudo mkdir -p /volume1/docker/media-stack/jellyseerr` puis `sudo chown 1026:100 /volume1/docker/media-stack/jellyseerr`.

### Démarrer

Choisis **une** méthode.

> **Ligne de commande SSH (marche partout, recommandé)**
>
> Dans le dossier du projet :
>
> ```bash
> docker compose up -d
> ```
>
> La première fois, Docker télécharge les applications : compte plusieurs minutes. Quand c'est fini, tu vois des lignes `Started` ou `Healthy`.

> **Synology : Container Manager (interface graphique)**
>
> 1. Ouvre **Container Manager** > *Projet* > *Créer*.
> 2. Nom du projet : `media-stack`. Chemin : le dossier du projet (celui qui contient `docker-compose.yml` et `.env`).
> 3. Source : *Utiliser le docker-compose.yml existant*.
> 4. Valide jusqu'à la fin et laisse le projet démarrer.
>
> Tu dois **quand même** utiliser SSH pour `./setup.sh` et `./check.sh` (étapes 5 et 6).

> **QNAP : Container Station**
>
> Le plus simple et le plus sûr : utilise la **ligne de commande SSH** ci-dessus (Container Station installe Docker). Si `docker compose` n'est pas reconnu, mets Container Station à jour : le projet exige Compose v2.
>
> Les dossiers du projet doivent être sur un volume du NAS (pas dans `/tmp`).

### Vérifier que tout tourne

```bash
docker compose ps
```

Tu dois voir 8 lignes : `gluetun`, `qbittorrent`, `prowlarr`, `flaresolverr`, `sonarr`, `radarr`, `jellyfin`, `jellyseerr`, toutes à l'état `running` ou `Up`. Le VPN (`gluetun`) doit être `healthy` après une à deux minutes.

Un souci ? Va à [Dépannage](#8-dépannage).

---

## 5. Configurer : `./setup.sh`, Jellyfin, Jellyseerr

### 5.1. `./setup.sh` : la configuration automatique

Les applications sont démarrées mais vides. Ce script les relie entre elles et les règle à ta place :

```bash
./setup.sh
```

Ce qu'il fait :

- il crée les dossiers `torrents`, `library/movies` et `library/tv` dans `DATA_DIR` ;
- il te demande un **mot de passe pour qBittorrent** (8 caractères minimum, lettres, chiffres ou `._-@%+=`). Si tu laisses vide et valides, il en génère un. Dans les deux cas, il l'écrit dans `.env` (ligne `QBIT_PASSWORD`). L'identifiant est `admin` ;
- il règle qBittorrent (dossier de téléchargement `/data/torrents`, arrêt du partage à un ratio de 1.0 ou après 7 jours) ;
- il ajoute dans Prowlarr les moteurs de recherche publics (1337x, The Pirate Bay, YTS, EZTV, LimeTorrents) et FlareSolverr (qui aide à passer certaines protections de sites) ;
- il règle Radarr et Sonarr : dossiers, hardlinks, lien avec qBittorrent, profils de qualité **HD-1080p** et **HD-1080p VF**.

Tu peux le **relancer sans risque** autant de fois que tu veux.

Si à la fin il affiche `ATTENTION : indexeurs non ajoutés`, un moteur de recherche était en panne : relance `./setup.sh` plus tard.

À la fin, il affiche les adresses des applications et les deux étapes manuelles ci-dessous. Remplace `IP-DU-NAS` par l'adresse de ton NAS.

### 5.2. Jellyfin : l'assistant de démarrage

Ouvre **http://IP-DU-NAS:8096** dans ton navigateur. Un assistant s'ouvre :

1. **Langue** : choisis *Français*, puis *Suivant*.
2. **Compte administrateur** : choisis un nom d'utilisateur et un mot de passe. **Note-les** : tu les réutiliseras dans Jellyseerr.
3. **Bibliothèques** : clique sur *Ajouter une bibliothèque*.
   - Type de contenu **Films**. Nom : `Films`. Dossier : clique sur **+** et choisis (ou tape) **`/data/library/movies`**.
   - Recommence : type **Séries**, nom `Séries`, dossier **`/data/library/tv`**.
4. **Langue des métadonnées** : *Français* et pays *France* (pour avoir les affiches et résumés en français).
5. **Accès à distance** : laisse les valeurs par défaut.
6. Clique sur *Terminer* et connecte-toi avec ton compte.

> Si les écrans de ta version de Jellyfin sont un peu différents, ce n'est pas grave : ce qui compte, ce sont les deux dossiers `/data/library/movies` et `/data/library/tv`.

#### Facultatif : une clé API Jellyfin

Avec elle, Radarr et Sonarr préviennent Jellyfin dès qu'un film arrive. Sans elle, il apparaît au prochain scan automatique de Jellyfin (plus tard).

1. Dans Jellyfin : icône de menu > *Tableau de bord* > *Clés API* > **+** > donne un nom (`media`) > valide, et copie la clé.
2. Dans `.env`, retire le `# ` (dièse et espace) devant `JELLYFIN_API_KEY=` et colle la clé après le `=`.
3. Relance `./setup.sh`.

### 5.3. Jellyseerr : la page des demandes

Ouvre **http://IP-DU-NAS:5055**.

1. Choisis **Jellyfin** comme serveur de médias.
2. **Adresse de Jellyfin** : hôte `jellyfin`, port `8096`, SSL décoché (si on te demande une URL d'un seul bloc : `http://jellyfin:8096`). Écris-la exactement comme ça : `jellyfin` est le nom de l'application *vue depuis Docker*, pas l'adresse du NAS.
3. Connecte-toi avec le **compte Jellyfin** créé juste avant.
4. **Bibliothèques** : active *Films* et *Séries*, puis lance le scan (*Start Scan*).
5. **Radarr** (films) : ajoute un serveur.
   - Nom d'hôte : `radarr`, port `7878`.
   - Clé API : dans Radarr (`http://IP-DU-NAS:7878`) > *Settings* > *General*. (Ou, en SSH : `grep ApiKey CONFIG_DIR/radarr/config.xml` en remplaçant `CONFIG_DIR` par ton chemin.)
   - Clique sur **Test** : la liste des profils de qualité et des dossiers apparaît.
   - Profil de qualité : **HD-1080p**.
   - Dossier racine : `/data/library/movies`.
   - Coche **Serveur par défaut** (sinon les demandes de films ne partent pas).
6. **Sonarr** (séries) : pareil, nom d'hôte `sonarr`, port `8989`, clé API dans Sonarr (`http://IP-DU-NAS:8989`) > *Settings* > *General*, clique sur **Test**, profil **HD-1080p**, dossier racine `/data/library/tv`, et coche **Serveur par défaut**.
7. Termine l'assistant. Dans Jellyseerr, tu peux importer les autres utilisateurs Jellyfin (famille, amis) : ils pourront eux aussi faire des demandes.

> Au premier accès à Radarr, Sonarr ou Prowlarr, la page peut te demander de **créer un identifiant et un mot de passe**. Fais-le et note-les. `./setup.sh` n'en a pas besoin pour fonctionner.

---

## 6. Vérifier : `./check.sh`

```bash
./check.sh
```

Il teste le VPN, le port forwarding, les dossiers et toutes les applications. Chaque ligne commence par `ok` (bon) ou `FAIL` (problème). Attends-toi à :

```
== vpn
  ok    IP de sortie de qBittorrent = ... (hôte : ...)
  ok    = IP Proton annoncée par gluetun (...)
  ok    IPv6 de qBittorrent = ... (hôte : ...)
  ok    DNS de qBittorrent = résolveur de gluetun (127.0.0.1), pas celui de l'hôte
  ok    DNS résout depuis qBittorrent
== port forwarding
  ok    port forwardé = ...
  ok    qBittorrent écoute sur ...
== stockage
  ok    hardlink torrents/ → library/ (même inode)
== interfaces
  ok    qBittorrent répond (...)
  ok    Prowlarr répond (...)
  ...
TOUT VERT
```

La dernière ligne doit être **`TOUT VERT`**. L'important : l'adresse IP de qBittorrent doit être **différente** de l'IP publique de ta maison (c'est celle de Proton), et le hardlink doit être `ok`.

Si tu vois `ÉCHECS` à la fin, lis les lignes `FAIL` et va à [Dépannage](#8-dépannage).

Le test peut attendre jusqu'à 90 secondes pour le port forwarding : c'est normal.

**Test du kill-switch (facultatif)** : `./check.sh --killswitch` coupe le VPN pour vérifier que rien ne sort, puis le rétablit (en redémarrant gluetun et qBittorrent : compte une à plusieurs minutes). Ne le lance pas pendant un téléchargement important.

---

## 7. Au quotidien

### Demander un film ou une série

1. Ouvre Jellyseerr : **http://IP-DU-NAS:5055**.
2. Cherche le titre.
3. Clique sur **Demander** (*Request*). Pour une série, choisis les saisons.
4. **Choisis la VF** : dans la fenêtre de demande, ouvre les **options avancées** et mets le **profil de qualité** sur **`HD-1080p VF`**.
   - `HD-1080p VF` : ne télécharge **que** des versions dont le nom de fichier contient `MULTi`, `VFF`, `VF2`, `VFi`, `VFQ`, `TRUEFRENCH` ou `FRENCH` (et pas `VOSTFR`, qui n'a que des sous-titres). S'il n'en existe aucune, **rien ne se télécharge**, et c'est voulu.
   - `HD-1080p` : sans exigence de langue française. Pour un film, c'est le plus souvent la version originale.
   - Les options avancées ne s'affichent que si ton compte a la permission. Sinon, demande à l'administrateur.
5. Attends. Selon le titre et ta connexion, de quelques minutes à quelques heures. Tu peux suivre l'avancement dans qBittorrent (`http://IP-DU-NAS:8081`, identifiant `admin`).

### Regarder

Ouvre Jellyfin (**http://IP-DU-NAS:8096**) ou installe l'application Jellyfin sur ta télé ou ton téléphone, puis entre l'adresse du NAS. Le titre apparaît dans *Films* ou *Séries*.

### Supprimer après visionnage

1. Ouvre Radarr (`http://IP-DU-NAS:7878`) pour un film, ou Sonarr (`http://IP-DU-NAS:8989`) pour une série.
2. Ouvre le titre et supprime-le (icône de poubelle, avec **l'option de supprimer les fichiers**).
3. Il ne sera **pas** retéléchargé : Radarr et Sonarr arrêtent de le surveiller quand tu le supprimes.

**L'espace n'est pas libéré tout de suite.** Le fichier existe encore dans `torrents/` tant que le partage (seed) n'est pas fini : ratio de 1.0 ou 7 jours au maximum. Ensuite, qBittorrent arrête le torrent, Radarr/Sonarr le suppriment, et la place revient.

---

## 8. Dépannage

Commence toujours par :

```bash
./check.sh
docker compose ps
```

### Le VPN est coupé / `gluetun` n'est pas `healthy`

Regarde ce que dit le VPN :

```bash
docker compose logs --tail 50 gluetun
```

- **Erreur d'authentification ou de clé** : la clé dans `.env` est fausse. Reprends l'étape 2 (la valeur seulement, sans espace).
- **`/dev/net/tun` introuvable** : voir [l'étape 4](#autoriser-le-vpn--devnettun) (cas Synology).
- **Panne passagère** : redémarre le VPN (qBittorrent redémarre avec) :

```bash
docker compose restart gluetun
```

Pendant la coupure, **rien ne télécharge** et rien ne fuit : c'est le kill-switch qui fait son travail.

### Rien ne se télécharge

- Le profil **`HD-1080p VF`** n'accepte que des versions françaises. Il n'y en a peut-être pas : essaie `HD-1080p`, ou patiente.
- `./check.sh` : le port forwarding est-il `ok` ? Sinon vérifie que **NAT-PMP** était coché à l'étape 2 (il faut refaire une clé).
- Dans Prowlarr (`http://IP-DU-NAS:9696`) > *Indexers* : les moteurs de recherche sont-ils présents ? Sinon relance `./setup.sh`.
- Pour plus de choix en français, ajoute un moteur de recherche français dans Prowlarr (*Indexers* > *Add Indexer*). Il n'est pas ajouté automatiquement.
- Dans Radarr ou Sonarr > *Activity* : la demande est-elle en file ? Une erreur est-elle affichée ?
- Page de qBittorrent : cinq mauvais mots de passe bannissent ton IP pendant 1 heure. Si c'est le cas, `docker compose restart qbittorrent`.

### Le disque est plein

1. Regarde l'espace libre : `df -h` (ou le gestionnaire de stockage de ton NAS).
2. Supprime ce que tu as vu, dans Radarr/Sonarr (voir [l'étape 7](#supprimer-après-visionnage)).
3. Rappelle-toi : l'espace est rendu **après la fin du seed** (7 jours au maximum). Si rien n'est libéré après ce délai, ouvre qBittorrent, supprime le torrent terminé en cochant **aussi les fichiers**.
4. Synology : vérifie que la **corbeille est désactivée** sur le dossier partagé `media` (étape 3).

### Mettre à jour les applications

Les versions sont **épinglées** dans `docker-compose.yml` (par exemple `radarr:6.4.4`) : rien ne change tout seul. Pour mettre à jour, récupère la nouvelle version du projet (ou demande à la personne qui te l'a donné), remplace le dossier en gardant ton `.env`, puis :

```bash
docker compose pull
docker compose up -d
```

Tes réglages sont conservés dans `CONFIG_DIR`. Après une mise à jour, relancer `./setup.sh` est sans risque.

### Redémarrer le NAS

Les applications redémarrent toutes seules. Sur Synology, la tâche `tun` de l'étape 4 recrée `/dev/net/tun`. Vérifie avec `./check.sh`. Si `gluetun` est arrêté (le VPN a démarré avant la tâche `tun`), relance `docker compose up -d`.

### Sauvegarder

Sauvegarde `CONFIG_DIR` (petit) et ton `.env`. Si tu les perds, tu devras tout refaire : mieux vaut les restaurer.

---

## 9. Les adresses des applications

Remplace `IP-DU-NAS` par l'adresse de ton NAS.

| Application | Adresse | À quoi ça sert |
|---|---|---|
| Jellyseerr | `http://IP-DU-NAS:5055` | **Demander** un film ou une série |
| Jellyfin | `http://IP-DU-NAS:8096` | **Regarder** |
| Radarr | `http://IP-DU-NAS:7878` | Gère les films (suppression) |
| Sonarr | `http://IP-DU-NAS:8989` | Gère les séries (suppression) |
| Prowlarr | `http://IP-DU-NAS:9696` | Moteurs de recherche |
| qBittorrent | `http://IP-DU-NAS:8081` | Téléchargements (identifiant `admin`) |

Le port de qBittorrent peut être différent si tu as changé `QBIT_PORT`.
