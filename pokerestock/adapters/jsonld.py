"""Lecture générique des données schema.org (JSON-LD) d'une fiche produit.

C'est la méthode la plus fiable : les enseignes publient ces données pour
Google. Utilisée telle quelle pour toute enseigne qui les expose.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterator

from pokerestock.adapters.base import Adaptateur, lire_prix
from pokerestock.models import Etat, Lecture

_SCRIPT = re.compile(
    r"<script[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", re.S | re.I
)

DISPONIBILITES = {
    "instock": Etat.EN_STOCK,
    "limitedavailability": Etat.EN_STOCK,
    "onlineonly": Etat.EN_STOCK,
    "instoreonly": Etat.EN_STOCK,
    "outofstock": Etat.RUPTURE,
    "soldout": Etat.RUPTURE,
    "discontinued": Etat.RUPTURE,
    "preorder": Etat.PRECOMMANDE,
    "presale": Etat.PRECOMMANDE,
    "backorder": Etat.PRECOMMANDE,  # commandable, livraison différée
}


def _noeuds(donnee: Any) -> Iterator[dict]:
    if isinstance(donnee, list):
        for x in donnee:
            yield from _noeuds(x)
    elif isinstance(donnee, dict):
        yield donnee
        for cle in ("@graph", "mainEntity", "itemListElement", "item"):
            if cle in donnee:
                yield from _noeuds(donnee[cle])


def _est_type(noeud: dict, nom: str) -> bool:
    t = noeud.get("@type")
    return t == nom or (isinstance(t, list) and nom in t)


def produits_jsonld(html: str) -> list[dict]:
    resultats = []
    for bloc in _SCRIPT.findall(html):
        try:
            donnee = json.loads(bloc.strip())
        except json.JSONDecodeError:
            # Certains sites mettent des retours à la ligne bruts dans les chaînes.
            try:
                donnee = json.loads(re.sub(r"[\r\n\t]+", " ", bloc.strip()))
            except json.JSONDecodeError:
                continue
        resultats.extend(n for n in _noeuds(donnee) if _est_type(n, "Product"))
    return resultats


def offres(produit: dict) -> list[dict]:
    o = produit.get("offers")
    if o is None:
        return []
    liste = o if isinstance(o, list) else [o]
    plat = []
    for x in liste:
        if isinstance(x, dict) and _est_type(x, "AggregateOffer") and "offers" in x:
            sous = x["offers"]
            plat.extend(sous if isinstance(sous, list) else [sous])
        if isinstance(x, dict):
            plat.append(x)
    return plat


def etat_disponibilite(valeur: str | None) -> Etat | None:
    if not valeur:
        return None
    cle = valeur.rstrip("/").rsplit("/", 1)[-1].lower()
    return DISPONIBILITES.get(cle)


def lecture_depuis_jsonld(html: str, vendeur_defaut: str | None = None) -> Lecture | None:
    """Construit une Lecture à partir du premier Product avec une offre exploitable."""
    for p in produits_jsonld(html):
        for o in offres(p):
            etat = etat_disponibilite(o.get("availability"))
            if etat is None:
                continue
            prix = lire_prix(o.get("price") or o.get("lowPrice"))
            vendeur = o.get("seller")
            if isinstance(vendeur, dict):
                vendeur = vendeur.get("name")
            return Lecture(
                etat=etat,
                prix=prix,
                vendeur=vendeur or vendeur_defaut,
                titre=(p.get("name") or "").strip() or None,
            )
    # Sans `availability` : AggregateOffer avec un nombre d'offres (E.Leclerc).
    for p in produits_jsonld(html):
        for o in offres(p):
            if _est_type(o, "AggregateOffer") and "offerCount" in o:
                try:
                    n = int(o["offerCount"])
                except (TypeError, ValueError):
                    continue
                return Lecture(
                    etat=Etat.EN_STOCK if n > 0 else Etat.RUPTURE,
                    prix=lire_prix(o.get("lowPrice")) if n > 0 else None,
                    vendeur=f"{vendeur_defaut} (vendeur non vérifié)" if n > 0 and vendeur_defaut else None,
                    titre=(p.get("name") or "").strip() or None,
                    detail=f"{n} offre(s)",
                )
    return None


def lecture_depuis_microdata(html: str, vendeur_defaut: str | None = None) -> Lecture | None:
    """Même chose pour les balises schema.org en microdata (itemprop=…), ex. Auchan."""
    if "itemprop" not in html:
        return None
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for produit in soup.select('[itemscope][itemtype*="schema.org/Product"]'):
        for offre in produit.select('[itemprop="offers"]'):
            dispo = offre.select_one('[itemprop="availability"]')
            etat = etat_disponibilite(dispo and (dispo.get("content") or dispo.get("href")))
            if etat is None:
                continue
            prix = offre.select_one('[itemprop="price"]')
            vendeur = offre.select_one('[itemprop="seller"] [itemprop="name"]')
            nom = produit.select_one('[itemprop="name"]')
            return Lecture(
                etat=etat,
                prix=lire_prix(prix and (prix.get("content") or prix.get_text())),
                vendeur=(vendeur and (vendeur.get("content") or vendeur.get_text(strip=True))) or vendeur_defaut,
                titre=nom and (nom.get("content") or nom.get_text(" ", strip=True)),
                detail="microdata schema.org",
            )
    return None


class AdaptateurJsonLd(Adaptateur):
    def analyser(self, html: str, url: str) -> Lecture:
        lec = lecture_depuis_jsonld(html, vendeur_defaut=self.nom_enseigne) or lecture_depuis_microdata(
            html, vendeur_defaut=self.nom_enseigne
        )
        if lec:
            return lec
        return Lecture(
            Etat.ILLISIBLE,
            detail="aucune donnée schema.org dans la page (contenu chargé en JavaScript ?)",
            bloque=True,
            besoin_navigateur=True,
        )
