"""Résumé quotidien (8 h, heure de Paris) : ce qui a bougé + sources illisibles."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from pokerestock.config import Config
from pokerestock.etat import Memoire
from pokerestock.models import ACHETABLES, PARIS, Alerte
from pokerestock.notif import LIBELLES, euros

HEURE_RESUME = 8


def lire_historique(memoire: Memoire, depuis: datetime) -> list[dict]:
    evenements = []
    if memoire.fichier_historique.exists():
        for ligne in memoire.fichier_historique.read_text(encoding="utf-8").splitlines():
            try:
                ev = json.loads(ligne)
                if datetime.fromisoformat(ev["heure"]) >= depuis:
                    evenements.append(ev)
            except (ValueError, KeyError):
                continue
    return evenements


def construire(config: Config, memoire: Memoire, maintenant: datetime | None = None) -> Alerte:
    maintenant = maintenant or datetime.now(PARIS)
    evs = lire_historique(memoire, maintenant - timedelta(hours=24))
    noms = {p.id: p.nom for p in config.produits}
    lignes = []

    changements = [e for e in evs if e.get("evenement") == "changement" and e.get("avant")]
    alertes = [e for e in evs if e.get("evenement") == "alerte" and e.get("type") not in ("illisible", "de_nouveau_lisible")]
    lignes.append(f"24 h : {len(alertes)} alerte(s), {len(changements)} changement(s) d'état.")

    dispo = [f for f in memoire.fiches.values() if f["etat"] in ACHETABLES]
    if dispo:
        lignes.append("\nDisponible maintenant :")
        for f in dispo:
            lignes.append(f"• {noms.get(f['produit'], f['produit'])} — {f['enseigne']} — {LIBELLES[f['etat']]} {euros(f['prix'])}")

    if changements:
        lignes.append("\nCe qui a bougé :")
        for e in changements[-15:]:
            lignes.append(
                f"• {e['heure'][11:16]} {noms.get(e['produit'], e['produit'])} @ {e['enseigne']} : "
                f"{LIBELLES.get(e['avant'], e['avant'])} → {LIBELLES.get(e['apres'], e['apres'])} {euros(e.get('prix'))}"
            )
    for a in alertes[-10:]:
        if a.get("type") in ("nouvelle_fiche", "signal_secours"):
            lignes.append(f"• {a['heure'][11:16]} {a['titre']}")

    if memoire.illisibles:
        lignes.append("\nSources illisibles (couvertes par Dealabs / CrocoDeal / Alerte&Go) :")
        for i in memoire.illisibles.values():
            lignes.append(f"• {i['enseigne']} — {i['raison']}")
    if memoire.dernier_passage:
        lignes.append(f"\nDernier passage : {memoire.dernier_passage[11:16]}")
    return Alerte(type="resume", titre=f"Résumé du {maintenant:%d/%m}", message="\n".join(lignes))


def est_l_heure(memoire: Memoire, maintenant: datetime | None = None) -> bool:
    maintenant = maintenant or datetime.now(PARIS)
    return maintenant.hour >= HEURE_RESUME and memoire.dernier_resume != maintenant.date().isoformat()
