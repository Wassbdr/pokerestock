"""Décisions : état final d'une fiche et opportunité d'une alerte."""

from __future__ import annotations

from pokerestock.models import ACHETABLES, Etat, Lecture, Produit

EPSILON = 0.005


def etat_final(lec: Lecture, produit: Produit, enseigne: dict) -> Etat:
    """Applique le vendeur officiel et le plafond à l'état brut lu sur la page."""
    if lec.etat not in ACHETABLES:
        return lec.etat
    officiels = enseigne.get("vendeurs_officiels")
    if officiels and lec.vendeur and "non vérifié" not in lec.vendeur:
        if not any(o.lower() in lec.vendeur.lower() for o in officiels):
            return Etat.MARKETPLACE
    if lec.prix is not None and lec.prix > produit.limite + EPSILON:
        return Etat.TROP_CHER
    return lec.etat


def doit_alerter(ancien: dict | None, etat: Etat, prix: float | None) -> bool:
    """Alerte quand une fiche DEVIENT achetable (ou que son prix baisse alors
    qu'elle l'est déjà). Tant que rien ne change, aucune nouvelle alerte."""
    if etat not in ACHETABLES:
        return False
    if ancien is None or ancien.get("etat") != etat:
        return True
    ancien_prix = ancien.get("prix")
    return prix is not None and ancien_prix is not None and prix < ancien_prix - EPSILON


def signal_qualifie(produit: Produit, prix: float | None, disponible: bool) -> bool:
    return disponible and (prix is None or prix <= produit.limite + EPSILON)
