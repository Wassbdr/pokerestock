"""Amazon.fr — pas de JSON-LD : lecture du HTML visible.

Audit du 07/10/2026 : lisible depuis une IP résidentielle ; « Disponible sur
invitation » présent dans #availability. Depuis une IP de datacenter (GitHub
Actions), Amazon renvoie souvent une page captcha : on la détecte (http.py) et
la source passe illisible, sans tentative de contournement.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from pokerestock.adapters.base import Adaptateur, lire_prix
from pokerestock.models import Etat, Lecture, Trouvaille

VENDEURS_AMAZON = ("amazon",)

_SELECTEURS_PRIX = [
    "#corePrice_feature_div .a-offscreen",
    "#corePriceDisplay_desktop_feature_div .a-price .a-offscreen",
    "#apex_desktop .a-price .a-offscreen",
    "#price_inside_buybox",
]
_SELECTEURS_VENDEUR = [
    '[offer-display-feature-name="desktop-merchant-info"] .offer-display-feature-text-message',
    '[offer-display-feature-name="desktop-merchant-info"] .offer-display-feature-text',
    "#sellerProfileTriggerId",
    "#merchantInfo",
    "#merchant-info",
]


def _texte(soup: BeautifulSoup, selecteur: str) -> str | None:
    e = soup.select_one(selecteur)
    if not e:
        return None
    t = re.sub(r"\s+", " ", e.get_text(" ")).strip()
    return t or None


class AdaptateurAmazon(Adaptateur):
    def analyser(self, html: str, url: str) -> Lecture:
        soup = BeautifulSoup(html, "html.parser")
        titre = _texte(soup, "#productTitle")
        if not titre:
            return Lecture(Etat.ILLISIBLE, detail="pas de titre produit (page inattendue)", bloque=True)

        dispo = (_texte(soup, "#availability") or "").lower()
        prix = None
        for sel in _SELECTEURS_PRIX:
            prix = lire_prix(_texte(soup, sel))
            if prix:
                break
        vendeur = None
        for sel in _SELECTEURS_VENDEUR:
            vendeur = _texte(soup, sel)
            if vendeur:
                break

        a_panier = soup.select_one("#add-to-cart-button") is not None
        bouton_precommande = soup.select_one("#buy-now-button")
        precommande = "précommande" in dispo or "pré-commande" in dispo or (
            bouton_precommande is not None and "précommander" in bouton_precommande.get("value", "").lower()
        )

        if "invitation" in dispo:
            etat = Etat.INVITATION
        elif "indisponible" in dispo or "non disponible" in dispo:
            etat = Etat.RUPTURE
        elif precommande:
            etat = Etat.PRECOMMANDE
        elif a_panier or "en stock" in dispo or "il ne reste plus" in dispo:
            etat = Etat.EN_STOCK
        elif soup.select_one("#buybox-see-all-buying-choices, #buybox-see-all-buying-choices-announce"):
            # Pas d'offre mise en avant : uniquement des vendeurs tiers.
            return Lecture(Etat.MARKETPLACE, prix=prix, titre=titre, detail="aucune offre principale")
        else:
            etat = Etat.RUPTURE

        if etat in (Etat.EN_STOCK, Etat.PRECOMMANDE) and vendeur and not any(
            v in vendeur.lower() for v in VENDEURS_AMAZON
        ):
            return Lecture(Etat.MARKETPLACE, prix=prix, vendeur=vendeur, titre=titre)

        return Lecture(etat, prix=prix, vendeur=vendeur or "Amazon (non vérifié)", titre=titre)

    def analyser_recherche(self, html: str, url: str) -> list[Trouvaille]:
        soup = BeautifulSoup(html, "html.parser")
        trouvailles = []
        for bloc in soup.select('div[data-component-type="s-search-result"][data-asin]'):
            asin = bloc.get("data-asin")
            if not asin or "AdHolder" in (bloc.get("class") or []):
                continue
            if bloc.select_one(".puis-sponsored-label-text, .s-sponsored-label-text"):
                continue
            h2 = bloc.select_one("h2")
            titre = (h2.get("aria-label") or h2.get_text(" ")).strip() if h2 else ""
            prix = lire_prix(_texte(bloc, ".a-price .a-offscreen"))
            trouvailles.append(Trouvaille(f"https://www.amazon.fr/dp/{asin}", re.sub(r"\s+", " ", titre), prix))
        return trouvailles
