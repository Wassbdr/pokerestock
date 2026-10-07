"""Mémoire persistante : data/state.json (état courant) + data/historique.jsonl."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

VIDE = {
    "domaines": {},  # domaine -> {"prochaine_visite": ts, "derniere_visite": ts}
    "robots": {},  # domaine -> {"texte", "lu"}
    "taches": {},  # clé de tâche -> ts de dernière exécution
    "fiches": {},  # "produit|enseigne|url" -> dernier état connu
    "decouvertes": {},  # produit -> enseigne -> [urls trouvées par la recherche]
    "signaux": {},  # "source|id" -> {"qualifie": bool, "vu": ts}
    "sources_initialisees": [],  # sources de secours déjà lues une première fois
    "illisibles": {},  # domaine -> {"depuis", "raison", "enseigne"}
    "dernier_passage": None,
    "en_attente": [],  # alertes dont l'envoi a échoué, retentées au passage suivant
    "dernier_resume": None,  # date (AAAA-MM-JJ) du dernier résumé quotidien
}
# Sections que le mode --dry-run a le droit d'écrire : uniquement ce qui sert
# à respecter les délais entre visites.
SECTIONS_POLITESSE = ("domaines", "robots")
MAX_SIGNAUX = 2000
MAX_LIGNES_HISTORIQUE = 20000


class Memoire:
    def __init__(self, dossier: Path):
        self.dossier = dossier
        self.fichier = dossier / "state.json"
        self.fichier_historique = dossier / "historique.jsonl"
        self.data = self._lire()
        self._historique: list[dict] = []

    def _lire(self) -> dict:
        data = json.loads(json.dumps(VIDE))
        if self.fichier.exists():
            data.update(json.loads(self.fichier.read_text(encoding="utf-8")))
        return data

    def __getattr__(self, nom):
        # memoire.fiches, memoire.domaines… -> sections de data
        if nom != "data" and nom in VIDE:
            return self.data[nom]
        raise AttributeError(nom)

    def historiser(self, evenement: dict) -> None:
        self._historique.append(evenement)

    def sauver(self, simulation: bool = False) -> None:
        self.dossier.mkdir(parents=True, exist_ok=True)
        if simulation:
            sur_disque = self._lire()
            for s in SECTIONS_POLITESSE:
                sur_disque[s] = self.data[s]
            a_ecrire = sur_disque
        else:
            self._elaguer_signaux()
            a_ecrire = self.data
            if self._historique:
                with self.fichier_historique.open("a", encoding="utf-8") as f:
                    for ev in self._historique:
                        f.write(json.dumps(ev, ensure_ascii=False) + "\n")
                self._historique.clear()
                self._elaguer_historique()
        _ecrire_atomique(self.fichier, json.dumps(a_ecrire, ensure_ascii=False, indent=1, sort_keys=True))

    def _elaguer_historique(self) -> None:
        lignes = self.fichier_historique.read_text(encoding="utf-8").splitlines(keepends=True)
        if len(lignes) > MAX_LIGNES_HISTORIQUE:
            _ecrire_atomique(self.fichier_historique, "".join(lignes[-MAX_LIGNES_HISTORIQUE:]))

    def _elaguer_signaux(self) -> None:
        s = self.data["signaux"]
        if len(s) > MAX_SIGNAUX:
            garder = sorted(s.items(), key=lambda kv: kv[1].get("vu", 0))[-MAX_SIGNAUX:]
            self.data["signaux"] = dict(garder)


def _ecrire_atomique(chemin: Path, texte: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=chemin.parent, prefix=".state-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(texte)
    os.replace(tmp, chemin)
