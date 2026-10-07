# PokeRestock

Surveillance **personnelle** des restocks de cartes Pokémon (produits scellés en français).
L'appli te prévient sur ton téléphone dès qu'un produit passe en stock à un prix raisonnable,
ou qu'une nouvelle fiche produit apparaît. **Elle n'achète jamais rien** : tu achètes toi-même.

- Alertes push via **ntfy** (priorité maximale pour les produits « chauds », lien cliquable vers la fiche),
  e-mail et Telegram en option.
- **Résumé quotidien à 8 h** : ce qui a bougé, ce qui est disponible, les sources illisibles.
- **Tableau de bord** sur GitHub Pages : état de chaque produit par enseigne, historique sur 7 jours.
- Fonctionne **sans PC** : GitHub Actions lance un passage toutes les 10 minutes.

## Règles respectées (non négociables)

- Au moins **5 minutes entre deux visites d'un même site**, plus un délai aléatoire de 0 à 2 min.
  Une seule page par site et par visite. Le moteur refuse un réglage plus agressif.
- **User-Agent honnête** (`PokeRestockPerso/0.1 (usage personnel non commercial; +lien du dépôt)`), **robots.txt respecté**.
- **Aucun contournement** : pas de résolution de captcha, pas de proxys, pas d'usurpation d'empreinte,
  pas de navigateur « furtif », pas de connexion à tes comptes. Si un site bloque, la source est marquée
  **illisible**, tu es prévenu **une seule fois**, et elle n'est re-testée qu'une fois par jour.
  Les sources de secours prennent alors le relais.
- **Aucun achat automatique.**

## Ce qui est lisible (audit du 7 octobre 2026)

| Enseigne | Verdict | Comment |
|---|---|---|
| JouéClub | ✅ lisible | JSON-LD schema.org (prix + disponibilité) |
| La Grande Récré | ✅ lisible | même plateforme que JouéClub |
| E.Leclerc | ✅ lisible | fiche `https://www.e.leclerc/fp/<EAN>`, JSON-LD. Les produits 30 ans n'y sont pas encore (404 = surveillé comme « rupture », alerte dès l'apparition). Recherche interdite par robots.txt, donc non utilisée. Marketplace : vendeur « non vérifié » |
| Auchan | ✅ lisible | microdata schema.org + « Vendu par Auchan ». Découverte par recherche de mots-clés |
| Amazon.fr | ⚠️ partiel | lisible depuis une connexion domestique (y compris « Disponible sur invitation »). Depuis GitHub Actions (IP de datacenter), Amazon affiche souvent un captcha : la source passe alors illisible |
| Smyths Toys | ❌ illisible | Imperva (403). Stock du magasin de Villetaneuse inaccessible |
| Micromania | ❌ illisible | Imperva |
| King Jouet | ❌ illisible | DataDome |
| Cultura | ❌ illisible | DataDome, y compris avec un vrai navigateur |
| Fnac | ❌ illisible | 403 (et vente en ligne 30 ans réservée aux adhérents) |
| Cdiscount | ❌ illisible | challenge Cloudflare |
| Carrefour | ❌ illisible | challenge Cloudflare |
| Boutique Asmodée | — | aucune boutique Pokémon en ligne trouvée |

**Sources de secours** (couvrent indirectement les enseignes illisibles, avec quelques minutes de retard) :
recherche **Dealabs**, flux RSS **Le CrocoDeal** et **Alerte&Go**, fiches produit Alerte&Go.
Une alerte de secours dit toujours « source indirecte : vérifie sur le site ». Si une fiche est déjà lue
directement (ex. Amazon), elle fait foi et l'agrégateur est ignoré.

## États possibles

`en_stock`, `precommande`, `invitation` (Amazon), `rupture`, `trop_cher` (au-dessus de plafond + marge),
`marketplace` (vendeur tiers), `illisible`.

Une alerte part quand une fiche **devient** achetable (`en_stock`, `precommande`, `invitation`) à un prix
≤ **plafond + marge** (marge par défaut : 10 €), ou quand son prix baisse. Jamais deux fois la même.

---

## Installation pas à pas (faisable depuis un téléphone)

### 1. Recevoir les notifications

1. Installe l'appli **ntfy** ([Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy) /
   [iPhone](https://apps.apple.com/app/ntfy/id1625396347)).
2. Appuie sur **+**, puis abonne-toi au topic indiqué dans le secret `NTFY_TOPIC` (un nom long et aléatoire :
   un topic ntfy est public pour qui connaît son nom, donc ne le partage pas).
3. Dans les réglages de l'abonnement, autorise la **priorité maximale** à sonner même en mode silencieux.

### 2. Le dépôt GitHub

Le dépôt est **public** : les minutes d'Actions et GitHub Pages sont alors gratuits et illimités.
Ta liste de produits et l'historique sont visibles, mais **les secrets (topic ntfy, e-mail) ne le sont pas**.

Depuis l'appli GitHub ou github.com dans le navigateur du téléphone :

1. **Settings → Secrets and variables → Actions → New repository secret** :
   - `NTFY_TOPIC` (obligatoire) : le nom de ton topic ntfy.
   - Optionnel, e-mail : `SMTP_HOST`, `SMTP_PORT` (587 ou 465), `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_TO`.
     Pour Gmail : `smtp.gmail.com`, port 587, et un **mot de passe d'application** (pas ton mot de passe habituel).
   - Optionnel, Telegram : `TELEGRAM_TOKEN` (créé avec @BotFather) et `TELEGRAM_CHAT_ID`.
2. **Settings → Pages → Source : GitHub Actions**.
3. **Actions → Surveillance → Run workflow** pour un premier passage manuel.
   Coche « Simulation » pour un essai sans envoi.

Ensuite, le passage tourne tout seul **toutes les 10 minutes**. GitHub retarde parfois les tâches planifiées
de 5 à 30 minutes aux heures chargées : c'est une limite de GitHub. Pour être plus réactif, utilise un Raspberry Pi (plus bas).

Le tableau de bord est à l'adresse `https://<ton-compte>.github.io/pokerestock/`.

### 3. Où est stocké l'état ?

Sur la branche **`donnees`** du dépôt (`data/state.json` et `data/historique.jsonl`), réécrite à chaque passage
en un seul commit, pour ne pas polluer l'historique du code.

---

## Ajouter ou modifier un produit

Édite [`config/produits.yaml`](config/produits.yaml). Depuis le téléphone : ouvre le fichier sur github.com,
puis l'icône crayon, puis « Commit changes ».

```yaml
  - id: delta-etb                  # identifiant unique, sans espace
    nom: Règne Delta (ME06) — ETB
    ean: "0196214143913"           # facultatif mais très utile (Leclerc /fp/<EAN>, découverte Amazon)
    plafond: 59.99
    marge: 5                       # facultatif : remplace la marge globale de 10 €
    priorite: chaud                # chaud = notification priorité max + vérifié plus souvent
    mots_cles: ["etb regne delta", "dresseur d elite regne delta"]
    exclure: [display]             # écarte les annonces qui contiennent ces mots
    urls:                          # fiches connues (facultatif)
      joueclub: [https://www.joueclub.fr/...]
      amazon: [https://www.amazon.fr/dp/XXXXXXXXXX]
    secours:
      alertetgo: [https://alertetgo.com/...]
```

- `mots_cles` : chaque phrase est un ensemble de mots qui doivent **tous** apparaître (accents et majuscules ignorés).
  Ils servent à rattacher une annonce Dealabs, un article CrocoDeal ou une fiche découverte à ce produit.
- Une fiche trouvée par la **découverte** (recherche Amazon ou Auchan) est ajoutée à la surveillance
  automatiquement, et tu reçois une alerte « NOUVELLE FICHE » si son prix est sous ton plafond + marge.

## Ajouter une enseigne

1. Teste une fiche : `python -m pokerestock lire jsonld https://www.exemple.fr/produit`.
   - Si l'état et le prix sont bons, l'adaptateur générique `jsonld` suffit (JSON-LD ou microdata schema.org).
   - « page sans données » : le site est rendu en JavaScript. Le moteur le relit automatiquement avec
     Chromium (Playwright) ; tu peux aussi forcer `adaptateur: navigateur`.
   - « illisible » avec 403, captcha, DataDome, Cloudflare ou Imperva : le site bloque, on n'insiste pas.
2. Déclare-la dans [`config/enseignes.yaml`](config/enseignes.yaml) :
   ```yaml
   monenseigne:
     nom: Mon Enseigne
     adaptateur: jsonld            # jsonld | proximis | amazon | auchan | navigateur
     vendeurs_officiels: [Mon Enseigne]   # facultatif : sinon « marketplace »
     recherche: "https://www.exemple.fr/search?q={q}"   # facultatif, pour la découverte
     fiche_ean: "https://www.exemple.fr/p/{ean}"         # facultatif, si l'URL se déduit de l'EAN
   ```
3. Ajoute ses URLs dans `produits.yaml`.
4. Si le site a une structure particulière, crée un adaptateur dans `pokerestock/adapters/`
   (copie `auchan.py` : une classe avec `analyser(html, url) -> Lecture`), enregistre-le dans
   `pokerestock/adapters/__init__.py`, puis ajoute une page d'exemple dans `tests/fixtures/` et un test.

---

## Sur un ordinateur

```bash
git clone https://github.com/<ton-compte>/pokerestock && cd pokerestock
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt playwright
.venv/bin/python -m playwright install chromium
cp .env.exemple .env      # puis renseigne NTFY_TOPIC
```

| Commande | Effet |
|---|---|
| `python -m pokerestock run` | un passage |
| `python -m pokerestock run --dry-run` | simulation : lit les sites, n'envoie rien, n'enregistre que les délais de politesse |
| `python -m pokerestock boucle` | passages en continu (un par minute, les délais par site restent ≥ 5 min) |
| `python -m pokerestock etat` | tableau de l'état connu |
| `python -m pokerestock lire ENSEIGNE URL` | tester un adaptateur sur une fiche |
| `python -m pokerestock test-notif` | envoyer une notification de test |
| `python -m pokerestock resume` | envoyer le résumé quotidien tout de suite |
| `python -m pokerestock tableau` | régénérer `docs/index.html` |
| `python -m pytest` | lancer les tests |

Ajoute `-v` pour des journaux détaillés.

⚠️ N'exécute pas la surveillance **à la fois** sur GitHub et sur une autre machine : chacune a son propre état,
et les sites seraient visités deux fois plus souvent. Désactive le workflow (Actions → Surveillance → « … » → Disable) si tu passes au Raspberry Pi.

## Alternative : Raspberry Pi (ou petit serveur)

C'est plus réactif que GitHub (pas de retard de cron), et l'IP domestique est mieux acceptée (Amazon lisible).

```bash
sudo apt install -y python3-venv git
git clone https://github.com/<ton-compte>/pokerestock /home/pi/pokerestock && cd /home/pi/pokerestock
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt playwright
.venv/bin/python -m playwright install --with-deps chromium
echo "NTFY_TOPIC=ton-topic" > .env && chmod 600 .env
sudo cp deploy/pokerestock.service /etc/systemd/system/
sudo systemctl enable --now pokerestock
journalctl -u pokerestock -f        # suivre les journaux
```

Pour publier le tableau de bord depuis le Pi, ouvre `docs/index.html` localement ou sers le dossier `docs/`.

## Organisation du code

```
config/            produits.yaml, enseignes.yaml
pokerestock/
  adapters/        un module par plateforme : jsonld (générique + microdata), proximis, amazon, auchan, navigateur
  secours/         Dealabs, flux RSS, fiches Alerte&Go
  http.py          User-Agent, robots.txt, détection des blocages
  navigateur.py    Chromium headless (Playwright), sans technique furtive
  moteur.py        planification polie par domaine, décisions, alertes, découverte
  regles.py        plafond + marge, vendeur officiel, dédoublonnage
  etat.py          state.json + historique.jsonl
  notif/           console, ntfy, e-mail, Telegram (+ file d'attente si un envoi échoue)
  resume.py        résumé de 8 h
  tableau.py       tableau de bord statique
tests/             pytest, avec de vraies pages capturées pendant l'audit (fixtures/)
```

## Limites, honnêtement

- Six enseignes sur treize bloquent les robots : elles ne sont suivies qu'**indirectement**, via les agrégateurs.
- Le stock **par magasin** n'est consultable sur aucune enseigne lisible sans compte ni contournement.
- GitHub Actions : retards de cron possibles, et Amazon souvent en captcha depuis leurs serveurs.
- Les agrégateurs peuvent être en retard ou se tromper (Alerte&Go affichait « en stock » une fiche Amazon
  « sur invitation ») : vérifie toujours sur le site avant d'acheter.
