"""Tableau de bord statique (docs/index.html), publié par GitHub Pages."""

from __future__ import annotations

import html
import json
from datetime import datetime, timedelta
from pathlib import Path

from pokerestock.config import Config
from pokerestock.etat import Memoire
from pokerestock.models import PARIS
from pokerestock.notif import LIBELLES, euros
from pokerestock.resume import lire_historique

CLASSES = {
    "en_stock": "ok",
    "precommande": "ok",
    "invitation": "info",
    "trop_cher": "warn",
    "marketplace": "warn",
    "rupture": "off",
    "illisible": "err",
}

STYLE = """
:root{--bg:#f6f7f9;--carte:#fff;--texte:#1b1f24;--doux:#5b6470;--bord:#e2e5ea;
--ok:#0f7b3f;--ok-bg:#dcf5e6;--info:#1c5fb8;--info-bg:#e0ecfb;--warn:#8a5a00;--warn-bg:#fdf0d5;
--off:#5b6470;--off-bg:#eceef1;--err:#b42318;--err-bg:#fde4e1;--lien:#1c5fb8}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#111418;--carte:#1a1e24;--texte:#e8eaed;
--doux:#9aa3ae;--bord:#2c323a;--ok:#6fdc9c;--ok-bg:#12351f;--info:#8db8f5;--info-bg:#132a47;--warn:#f2c36b;
--warn-bg:#3a2c0f;--off:#9aa3ae;--off-bg:#252a31;--err:#ff9b8f;--err-bg:#3d1712;--lien:#8db8f5}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--texte);
font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:980px;margin:0 auto;padding:16px}h1{font-size:1.4rem;margin:.2rem 0}
h2{font-size:1.05rem;margin:1.6rem 0 .6rem}.meta{color:var(--doux);font-size:.9rem}
.grille{display:grid;gap:12px;grid-template-columns:repeat(auto-fill,minmax(290px,1fr))}
.carte{background:var(--carte);border:1px solid var(--bord);border-radius:10px;padding:12px 14px}
.carte h3{font-size:1rem;margin:0 0 2px}.carte .sous{color:var(--doux);font-size:.85rem;margin-bottom:8px}
.ligne{display:flex;justify-content:space-between;align-items:center;gap:8px;padding:6px 0;border-top:1px solid var(--bord)}
.ligne a{color:var(--lien);text-decoration:none}.ligne small{color:var(--doux);display:block}
.badge{font-size:.78rem;font-weight:600;padding:2px 8px;border-radius:99px;white-space:nowrap}
.ok{color:var(--ok);background:var(--ok-bg)}.info{color:var(--info);background:var(--info-bg)}
.warn{color:var(--warn);background:var(--warn-bg)}.off{color:var(--off);background:var(--off-bg)}
.err{color:var(--err);background:var(--err-bg)}.chaud{color:var(--err);font-size:.8rem;font-weight:600}
table{width:100%;border-collapse:collapse;background:var(--carte);border:1px solid var(--bord);border-radius:10px;overflow:hidden}
td,th{padding:7px 10px;border-bottom:1px solid var(--bord);text-align:left;font-size:.88rem;vertical-align:top}
th{color:var(--doux);font-weight:600}.defile{overflow-x:auto}
.vide{color:var(--doux);font-style:italic}
"""


def _e(x) -> str:
    return html.escape(str(x if x is not None else ""))


def _heure(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        d = datetime.fromisoformat(iso)
        return d.strftime("%d/%m %H:%M")
    except ValueError:
        return iso


def generer(config: Config, memoire: Memoire, dossier: Path) -> Path:
    dossier.mkdir(parents=True, exist_ok=True)
    noms_ens = {k: v.get("nom", k) for k, v in config.enseignes.items()}
    fiches_par_produit: dict[str, list[dict]] = {}
    for f in memoire.fiches.values():
        fiches_par_produit.setdefault(f["produit"], []).append(f)

    cartes = []
    for p in config.produits:
        lignes = []
        for f in sorted(fiches_par_produit.get(p.id, []), key=lambda f: (CLASSES.get(f["etat"]) != "ok", f["enseigne"])):
            lignes.append(
                f'<div class="ligne"><div><a href="{_e(f["url"])}" rel="noopener">{_e(noms_ens.get(f["enseigne"], f["enseigne"]))}</a>'
                f'<small>{_e(euros(f.get("prix")))} · vu {_e(_heure(f.get("verifie")))}</small></div>'
                f'<span class="badge {CLASSES.get(f["etat"], "off")}" title="{_e(f.get("detail"))}">{_e(LIBELLES.get(f["etat"], f["etat"]))}</span></div>'
            )
        if not lignes:
            lignes.append('<div class="ligne vide">Pas encore de fiche lue (surveillé via découverte et sources de secours)</div>')
        marge = f" + {euros(p.marge)}" if p.marge else ""
        cartes.append(
            f'<section class="carte"><h3>{_e(p.nom)}</h3><div class="sous">plafond {_e(euros(p.plafond))}{_e(marge)}'
            f'{" · EAN " + _e(p.ean) if p.ean else ""}{" · <span class=chaud>CHAUD</span>" if p.chaud else ""}</div>{"".join(lignes)}</section>'
        )

    illisibles = "".join(
        f"<tr><td>{_e(i['enseigne'])}</td><td>{_e(i['raison'])}</td><td>{_e(_heure(i['depuis']))}</td></tr>"
        for i in memoire.illisibles.values()
    ) or '<tr><td colspan="3" class="vide">Aucune</td></tr>'

    evs = lire_historique(memoire, datetime.now(PARIS) - timedelta(days=7))
    noms_p = {p.id: p.nom for p in config.produits}
    lignes_hist = []
    for ev in reversed(evs[-150:]):
        if ev.get("evenement") == "alerte":
            quoi = f"<b>{_e(ev.get('titre'))}</b>"
        else:
            quoi = (
                f"{_e(noms_p.get(ev.get('produit'), ev.get('produit')))} @ {_e(noms_ens.get(ev.get('enseigne'), ev.get('enseigne')))} : "
                f"{_e(LIBELLES.get(ev.get('avant'), ev.get('avant') or 'nouveau'))} → {_e(LIBELLES.get(ev.get('apres'), ev.get('apres')))}"
                f" ({_e(euros(ev.get('prix')))})"
            )
        lignes_hist.append(f"<tr><td>{_e(_heure(ev.get('heure')))}</td><td>{quoi}</td></tr>")
    historique = "".join(lignes_hist) or '<tr><td colspan="2" class="vide">Rien sur les 7 derniers jours</td></tr>'

    page = f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<meta http-equiv="refresh" content="300"><title>PokeRestock</title><style>{STYLE}</style></head>
<body><main><h1>PokeRestock</h1>
<div class="meta">Dernier passage : {_e(_heure(memoire.dernier_passage))} · page générée {_e(datetime.now(PARIS).strftime("%d/%m %H:%M"))} · actualisation auto 5 min</div>
<h2>Produits</h2><div class="grille">{"".join(cartes)}</div>
<h2>Sources illisibles</h2><div class="defile"><table><tr><th>Enseigne</th><th>Raison</th><th>Depuis</th></tr>{illisibles}</table></div>
<h2>Historique (7 jours)</h2><div class="defile"><table><tr><th>Quand</th><th>Événement</th></tr>{historique}</table></div>
<p class="meta">Surveillance personnelle, sans contournement de protection ni achat automatique.</p>
</main></body></html>"""
    chemin = dossier / "index.html"
    chemin.write_text(page, encoding="utf-8")
    (dossier / "etat.json").write_text(
        json.dumps({"dernier_passage": memoire.dernier_passage, "fiches": list(memoire.fiches.values()), "illisibles": memoire.illisibles}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    (dossier / ".nojekyll").write_text("", encoding="utf-8")
    return chemin
