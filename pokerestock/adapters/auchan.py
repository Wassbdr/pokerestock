"""Auchan : fiches et recherche en HTML serveur, données schema.org en microdata.

Audit du 07/10/2026 : la recherche par mots-clés est lisible sans navigateur
(cartes `article.product-thumbnail`, mention « Vendu par Auchan » ou vendeur
marketplace). La recherche par EAN ne trouve pas les produits 30 ans : ils ne
sont pas (encore) au catalogue en ligne.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from pokerestock.adapters.base import lire_prix
from pokerestock.adapters.jsonld import AdaptateurJsonLd
from pokerestock.models import Lecture, Trouvaille


class AdaptateurAuchan(AdaptateurJsonLd):
    def analyser(self, html: str, url: str) -> Lecture:
        lec = super().analyser(html, url)
        # Vendeur de l'offre principale : « Vendu par Auchan » ou un vendeur marketplace.
        vendeur = BeautifulSoup(html, "html.parser").select_one(".offer-selector__seller")
        if vendeur:
            nom = re.sub(r"\s+", " ", vendeur.get_text(" ")).strip()
            lec.vendeur = re.sub(r"^Vendu par\s*", "", nom) or lec.vendeur
        return lec

    def analyser_recherche(self, html: str, url: str) -> list[Trouvaille]:
        soup = BeautifulSoup(html, "html.parser")
        trouvailles = []
        for carte in soup.select("article.product-thumbnail"):
            lien = carte.select_one("a.productThumbnailLink[href], a[href*='/pr-']")
            if not lien:
                continue
            titre = carte.select_one(".product-thumbnail__description")
            prix = carte.select_one('[itemprop="price"]')
            vendeur = carte.select_one(".product-thumbnail__seller-label")
            texte_titre = re.sub(r"\s+", " ", titre.get_text(" ")).strip() if titre else lien.get_text(" ", strip=True)
            if vendeur:
                texte_titre += f" ({vendeur.get_text(' ', strip=True)})"
            trouvailles.append(Trouvaille(urljoin(url, lien["href"]), texte_titre, lire_prix(prix and prix.get("content"))))
        return trouvailles
