"""Adaptateur générique pour les sites rendus en JavaScript (Leclerc, Auchan, Cultura…).

La page est rendue par Playwright, puis lue comme les autres : JSON-LD d'abord,
sinon sélecteurs CSS et textes déclarés dans config/enseignes.yaml :

    selecteurs:
      attendre: "css à attendre"
      prix: "css du prix"
      dispo: "css du bloc disponibilité"
      bouton: "css du bouton d'achat (désactivé = rupture)"
      titre: "css du titre"
    textes_rupture: [...]
    textes_stock: [...]
    resultats: {carte: css, lien: css, titre: css, prix: css}   # page de recherche
"""

from __future__ import annotations

import re
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

from pokerestock.adapters.base import Adaptateur, fiche_absente, lire_prix
from pokerestock.adapters.jsonld import lecture_depuis_jsonld
from pokerestock.http import Absente, Bloque
from pokerestock.models import Etat, Lecture, Trouvaille, normaliser

TEXTES_RUPTURE = ["rupture de stock", "indisponible", "epuise", "plus disponible", "victime de son succes", "non disponible"]
TEXTES_STOCK = ["en stock", "ajouter au panier", "disponible en ligne", "livraison a domicile"]
TEXTES_PRECOMMANDE = ["precommande", "pre commande", "precommander", "disponible a partir du"]


class AdaptateurNavigateur(Adaptateur):
    def __init__(self, client, nom_enseigne, recherche=None, navigateur=None, cfg: dict | None = None):
        super().__init__(client, nom_enseigne, recherche)
        self.navigateur = navigateur
        self.cfg = cfg or {}
        self.sel = self.cfg.get("selecteurs", {})

    def lire_fiche(self, url: str) -> Lecture:
        if self.navigateur is None:
            return Lecture(Etat.ILLISIBLE, detail="navigateur indisponible (Playwright non installé)")
        try:
            rep = self.navigateur.charger(url, self.sel.get("attendre"))
        except Bloque as e:
            return Lecture(Etat.ILLISIBLE, detail=str(e), bloque=True)
        except Absente as e:
            return fiche_absente(e)
        except (requests.RequestException, RuntimeError) as e:
            return Lecture(Etat.ILLISIBLE, detail=f"navigateur : {e}")
        except Exception as e:  # timeout Playwright, crash…
            return Lecture(Etat.ILLISIBLE, detail=f"navigateur : {type(e).__name__} {e}"[:300])
        return self.analyser(rep.texte, rep.url)

    def analyser(self, html: str, url: str) -> Lecture:
        lec = lecture_depuis_jsonld(html, vendeur_defaut=self.nom_enseigne)
        if lec:
            lec.detail = "JSON-LD (rendu navigateur)"
            return lec
        soup = BeautifulSoup(html, "html.parser")
        titre = _txt(soup, self.sel.get("titre", "h1"))
        prix = lire_prix(_txt(soup, self.sel["prix"])) if self.sel.get("prix") else _prix_meta(soup)
        zone = _txt(soup, self.sel["dispo"]) if self.sel.get("dispo") else None
        texte = normaliser(zone or soup.get_text(" "))
        rupture = [normaliser(t) for t in self.cfg.get("textes_rupture", TEXTES_RUPTURE)]
        stock = [normaliser(t) for t in self.cfg.get("textes_stock", TEXTES_STOCK)]

        bouton = soup.select_one(self.sel["bouton"]) if self.sel.get("bouton") else None
        if bouton is not None and (bouton.has_attr("disabled") or "disabled" in " ".join(bouton.get("class", []))):
            etat = Etat.RUPTURE
        elif any(t in texte for t in (normaliser(x) for x in TEXTES_PRECOMMANDE)):
            etat = Etat.PRECOMMANDE
        elif any(t in texte for t in rupture):
            etat = Etat.RUPTURE
        elif bouton is not None or any(t in texte for t in stock):
            etat = Etat.EN_STOCK
        else:
            return Lecture(Etat.ILLISIBLE, titre=titre, prix=prix, detail="page rendue mais disponibilité introuvable", bloque=not titre)
        return Lecture(etat, prix=prix, vendeur=self.nom_enseigne, titre=titre, detail="texte de la page (rendu navigateur)")

    def rechercher(self, requete: str) -> list[Trouvaille]:
        if not self.url_recherche or self.navigateur is None:
            return []
        r = self.cfg.get("resultats", {})
        rep = self.navigateur.charger(self.url_recherche.format(q=quote_plus(requete)), r.get("carte"))
        return self.analyser_recherche(rep.texte, rep.url)

    def analyser_recherche(self, html: str, url: str) -> list[Trouvaille]:
        r = self.cfg.get("resultats", {})
        soup = BeautifulSoup(html, "html.parser")
        trouvailles, vues = [], set()
        cartes = soup.select(r["carte"]) if r.get("carte") else []
        for carte in cartes:
            lien = carte.select_one(r.get("lien", "a[href]")) if r.get("lien") else carte.find("a", href=True)
            if not lien or not lien.get("href"):
                continue
            href = urljoin(url, lien["href"]).split("#")[0]
            if href in vues:
                continue
            vues.add(href)
            titre = _txt(carte, r["titre"]) if r.get("titre") else lien.get_text(" ", strip=True)
            prix = lire_prix(_txt(carte, r["prix"])) if r.get("prix") else None
            trouvailles.append(Trouvaille(href, titre or "", prix))
        return trouvailles


def _txt(soup, selecteur: str | None) -> str | None:
    if not selecteur:
        return None
    e = soup.select_one(selecteur)
    if not e:
        return None
    t = re.sub(r"\s+", " ", e.get_text(" ")).strip()
    return t or e.get("content") or None


def _prix_meta(soup) -> float | None:
    for sel in ['meta[property="product:price:amount"]', 'meta[itemprop="price"]', '[itemprop="price"]']:
        e = soup.select_one(sel)
        if e:
            p = lire_prix(e.get("content") or e.get_text())
            if p:
                return p
    return None
