"""Analyse des sources de secours (fonctions pures, testables hors ligne)."""

from __future__ import annotations

import html as html_mod
import json
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit, urlunsplit

from pokerestock.adapters.jsonld import etat_disponibilite, offres, produits_jsonld
from pokerestock.adapters.base import lire_prix
from pokerestock.models import Etat
from pokerestock.secours import Signal

_VUE3 = re.compile(r"data-vue3='([^']*)'")


def dealabs_recherche(page: str) -> list[Signal]:
    """Page https://www.dealabs.com/search?q=… : chaque deal est décrit en JSON
    dans un attribut data-vue3 (composant ThreadMainListItemNormalizer)."""
    signaux = []
    for brut in _VUE3.findall(page):
        if "ThreadMainListItemNormalizer" not in brut:
            continue
        try:
            donnee = json.loads(html_mod.unescape(brut))
        except json.JSONDecodeError:
            continue
        t = donnee.get("props", {}).get("thread") or {}
        if not t.get("threadId"):
            continue
        marchand = (t.get("merchant") or {}).get("merchantName")
        slug = t.get("titleSlug") or ""
        url = f"https://www.dealabs.com/bons-plans/{slug}-{t['threadId']}" if slug else t.get("shareableLink", "")
        signaux.append(
            Signal(
                source="dealabs",
                id=str(t["threadId"]),
                titre=t.get("title", ""),
                url=url,
                prix=lire_prix(t.get("price")) or None,
                marchand=marchand,
                disponible=not t.get("isExpired", False) and t.get("status") == "Activated",
            )
        )
    return signaux


def flux_rss(xml: str, source: str) -> list[Signal]:
    """Flux RSS 2.0 (WordPress : CrocoDeal, Alerte&Go…)."""
    signaux = []
    racine = ET.fromstring(xml.encode() if isinstance(xml, str) else xml)
    for item in racine.iter("item"):
        titre = html_mod.unescape(item.findtext("title") or "").strip()
        lien = (item.findtext("link") or "").strip()
        guid = (item.findtext("guid") or lien).strip()
        signaux.append(Signal(source=source, id=guid, titre=titre, url=lien, prix=lire_prix(_prix_titre(titre))))
    return signaux


def _prix_titre(titre: str) -> str | None:
    m = re.search(r"(\d+[.,]\d{2})\s*€|(\d+)\s*€", titre)
    return m.group(0) if m else None


def nettoyer_lien(url: str) -> str:
    """Retire les paramètres d'affiliation (tag=…, linkCode=…) des liens Amazon."""
    p = urlsplit(url)
    if "amazon." in p.netloc:
        m = re.search(r"/dp/([A-Z0-9]{10})", p.path)
        if m:
            return f"https://{p.netloc}/dp/{m.group(1)}"
    return urlunsplit((p.scheme, p.netloc, p.path, "", ""))


def alertetgo_fiche(page: str, url_page: str) -> list[Signal]:
    """Fiche produit Alerte&Go : JSON-LD avec la meilleure offre repérée
    (vendeur, prix, disponibilité). Attention : peut avoir du retard sur l'enseigne."""
    signaux = []
    for p in produits_jsonld(page):
        for o in offres(p):
            etat = etat_disponibilite(o.get("availability"))
            vendeur = o.get("seller")
            if isinstance(vendeur, dict):
                vendeur = vendeur.get("name")
            lien = nettoyer_lien(o.get("url") or url_page)
            prix = lire_prix(o.get("price"))
            signaux.append(
                Signal(
                    source="alertetgo",
                    id=lien,  # stable : le moteur suit les transitions dispo/indispo
                    titre=p.get("name", ""),
                    url=lien,
                    prix=prix,
                    marchand=vendeur,
                    disponible=etat in (Etat.EN_STOCK, Etat.PRECOMMANDE),
                )
            )
    return signaux
