"""JouéClub et La Grande Récré (même plateforme Proximis « Planet Unified Commerce »).

Audit du 07/10/2026 : JSON-LD Product complet (prix + availability). En secours,
le JSON de la page contient `"threshold":"UNAVAILABLE"` / `"thresholdTitle"`.
"""

from __future__ import annotations

import re

from pokerestock.adapters.jsonld import AdaptateurJsonLd, lecture_depuis_jsonld
from pokerestock.models import Etat, Lecture

_SEUIL = re.compile(r'"threshold"\s*:\s*"([A-Z_]+)"')
_SEUILS = {
    "AVAILABLE": Etat.EN_STOCK,
    "LOW_STOCK": Etat.EN_STOCK,
    "UNAVAILABLE": Etat.RUPTURE,
    "PREORDER": Etat.PRECOMMANDE,
}


class AdaptateurProximis(AdaptateurJsonLd):
    def analyser(self, html: str, url: str) -> Lecture:
        lec = lecture_depuis_jsonld(html, vendeur_defaut=self.nom_enseigne)
        if lec:
            return lec
        m = _SEUIL.search(html)
        if m and m.group(1) in _SEUILS:
            return Lecture(_SEUILS[m.group(1)], vendeur=self.nom_enseigne, detail=f"seuil {m.group(1)}")
        return Lecture(Etat.ILLISIBLE, detail="ni JSON-LD ni seuil de stock Proximis", bloque=True)
