"""Chargement de config/produits.yaml et config/enseignes.yaml."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from pokerestock.models import Produit


@dataclass
class Config:
    produits: list[Produit]
    enseignes: dict[str, dict]
    reglages: dict
    secours: dict = field(default_factory=dict)

    def enseigne(self, cle: str) -> dict:
        return self.enseignes.get(cle, {"nom": cle, "adaptateur": "jsonld"})


def _liste(v) -> list[str]:
    if v is None:
        return []
    return [v] if isinstance(v, str) else list(v)


def charger(dossier: Path) -> Config:
    p = yaml.safe_load((dossier / "produits.yaml").read_text(encoding="utf-8"))
    e = yaml.safe_load((dossier / "enseignes.yaml").read_text(encoding="utf-8"))
    reglages = {
        "user_agent": "PokeRestockPerso/0.1 (usage personnel non commercial)",
        "intervalle_min_s": 300,
        "alea_max_s": 120,
        "pages_par_visite": 1,
        "retest_bloque_s": 86400,
        "decouverte_toutes_les_s": 7200,
        "respecter_robots": True,
        "marge_plafond_eur": 0,
        **(e.get("reglages") or {}),
    }
    produits = []
    ids = set()
    for d in p["produits"]:
        if d["id"] in ids:
            raise ValueError(f"id de produit en double : {d['id']}")
        ids.add(d["id"])
        produits.append(
            Produit(
                id=d["id"],
                nom=d["nom"],
                plafond=float(d["plafond"]),
                priorite=d.get("priorite", "normal"),
                ean=str(d["ean"]) if d.get("ean") else None,
                mots_cles=_liste(d.get("mots_cles")),
                exclure=_liste(d.get("exclure")),
                urls={k: _liste(v) for k, v in (d.get("urls") or {}).items()},
                secours={k: _liste(v) for k, v in (d.get("secours") or {}).items()},
                marge=float(d.get("marge", reglages["marge_plafond_eur"])),
            )
        )
    if reglages["intervalle_min_s"] < 300:
        raise ValueError("intervalle_min_s doit rester ≥ 300 s (5 min) : règle non négociable")
    return Config(produits, e.get("enseignes") or {}, reglages, e.get("secours") or {})
