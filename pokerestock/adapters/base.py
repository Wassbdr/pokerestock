"""Interface commune des adaptateurs d'enseigne."""

from __future__ import annotations

import logging
import re
from urllib.parse import quote_plus

import requests

from pokerestock.http import Absente, Bloque, Client
from pokerestock.models import Etat, Lecture, Trouvaille

log = logging.getLogger(__name__)


class Adaptateur:
    """Un adaptateur sait lire une fiche produit d'une enseigne (et parfois chercher).

    Les sous-classes implémentent `analyser(html, url)` : une fonction pure,
    testable sur des pages HTML enregistrées, sans réseau.
    """

    def __init__(self, client: Client, nom_enseigne: str, recherche: str | None = None):
        self.client = client
        self.nom_enseigne = nom_enseigne
        self.url_recherche = recherche  # modèle avec {q}

    def lire_fiche(self, url: str) -> Lecture:
        try:
            rep = self.client.get(url)
        except Bloque as e:
            return Lecture(Etat.ILLISIBLE, detail=str(e), bloque=True)
        except Absente as e:
            return fiche_absente(e)
        except requests.RequestException as e:
            return Lecture(Etat.ILLISIBLE, detail=f"erreur réseau : {e}")
        try:
            return self.analyser(rep.texte, rep.url)
        except Exception as e:  # une page inattendue ne doit pas arrêter le passage
            log.exception("analyse impossible : %s", url)
            return Lecture(Etat.ILLISIBLE, detail=f"analyse impossible : {e}")

    def analyser(self, html: str, url: str) -> Lecture:
        raise NotImplementedError

    def rechercher(self, requete: str) -> list[Trouvaille]:
        """Découverte de nouvelles fiches. Lève Bloque si le site refuse."""
        if not self.url_recherche:
            return []
        rep = self.client.get(self.url_recherche.format(q=quote_plus(requete)))
        return self.analyser_recherche(rep.texte, rep.url)

    def analyser_recherche(self, html: str, url: str) -> list[Trouvaille]:
        return []


def fiche_absente(e: Exception) -> Lecture:
    """Fiche pas en ligne : on la compte comme une rupture. Le jour où elle
    apparaît en stock, la transition déclenche l'alerte."""
    return Lecture(Etat.RUPTURE, detail=f"fiche pas en ligne ({e})")


def lire_prix(texte: str | float | int | None) -> float | None:
    """« 35,94 € », « 1 234,50€ », "41.99", 41.99 -> float."""
    if texte is None:
        return None
    if isinstance(texte, (int, float)):
        return float(texte)
    t = texte.replace("\xa0", " ").replace(" ", " ")
    m = re.search(r"\d[\d ]*(?:[.,]\d{1,2})?", t)
    if not m:
        return None
    nombre = m.group(0).replace(" ", "").replace(",", ".")
    try:
        return float(nombre)
    except ValueError:
        return None
