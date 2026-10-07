"""Types partagés : états, lectures de fiche, alertes."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")


class Etat(StrEnum):
    EN_STOCK = "en_stock"
    RUPTURE = "rupture"
    PRECOMMANDE = "precommande"
    INVITATION = "invitation"  # Amazon : « Disponible sur invitation »
    TROP_CHER = "trop_cher"
    MARKETPLACE = "marketplace"  # vendeur tiers
    ILLISIBLE = "illisible"


# États où l'on peut agir : ils déclenchent une alerte.
ACHETABLES = {Etat.EN_STOCK, Etat.PRECOMMANDE, Etat.INVITATION}


def maintenant_iso() -> str:
    return datetime.now(PARIS).isoformat(timespec="seconds")


@dataclass
class Lecture:
    """Résultat de lire_fiche(url)."""

    etat: Etat
    prix: float | None = None
    vendeur: str | None = None
    titre: str | None = None
    stock_magasin: dict[str, str] = field(default_factory=dict)
    horodatage: str = field(default_factory=maintenant_iso)
    detail: str = ""  # raison d'un état illisible, remarque…
    # La source entière est illisible (403, captcha, challenge, page vide rendue
    # en JavaScript…), pas seulement cette fiche.
    bloque: bool = False
    # Page reçue mais sans données : probablement rendue en JavaScript.
    besoin_navigateur: bool = False


@dataclass
class Trouvaille:
    """Une fiche trouvée par une recherche (découverte)."""

    url: str
    titre: str
    prix: float | None = None


@dataclass
class Produit:
    id: str
    nom: str
    plafond: float
    priorite: str = "normal"  # "chaud" ou "normal"
    ean: str | None = None
    mots_cles: list[str] = field(default_factory=list)
    exclure: list[str] = field(default_factory=list)
    urls: dict[str, list[str]] = field(default_factory=dict)  # enseigne -> URLs
    secours: dict[str, list[str]] = field(default_factory=dict)
    marge: float = 0.0  # tolérance au-dessus du plafond (€)

    @property
    def limite(self) -> float:
        """Prix maximum déclenchant une alerte : plafond + marge."""
        return self.plafond + self.marge

    @property
    def chaud(self) -> bool:
        return self.priorite == "chaud"

    def correspond(self, texte: str) -> bool:
        """Vrai si `texte` (titre d'annonce, de fiche…) désigne ce produit."""
        t = normaliser(texte)
        if self.ean and self.ean.lstrip("0") in t:
            return True
        if any(f" {normaliser(x)} " in f" {t} " for x in self.exclure):
            return False
        mots_texte = set(t.split())
        for phrase in self.mots_cles:
            if all(m in mots_texte for m in normaliser(phrase).split()):
                return True
        return False


def normaliser(texte: str) -> str:
    """Minuscules, sans accents ni ponctuation : « 30ᵉ Anniversaire » -> « 30e anniversaire »."""
    t = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode()
    t = "".join(c if c.isalnum() else " " for c in t.lower())
    return " ".join(t.split())


@dataclass
class Alerte:
    type: str  # restock, nouvelle_fiche, signal_secours, illisible, de_nouveau_lisible
    titre: str
    message: str
    url: str | None = None
    chaud: bool = False
    produit: str | None = None
    enseigne: str | None = None
    prix: float | None = None
    etat: str | None = None
    heure: str = field(default_factory=maintenant_iso)
