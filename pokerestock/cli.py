"""Ligne de commande.

    python -m pokerestock run [--dry-run]     un passage (à lancer toutes les 5 à 10 min)
    python -m pokerestock boucle              passages en continu (Raspberry Pi, PC allumé)
    python -m pokerestock etat                tableau de l'état connu
    python -m pokerestock lire ENSEIGNE URL   tester un adaptateur sur une fiche
    python -m pokerestock test-notif          envoyer une notification de test
    python -m pokerestock resume              envoyer le résumé quotidien maintenant
    python -m pokerestock tableau             régénérer le tableau de bord (docs/)
"""

from __future__ import annotations

import argparse
import logging
import os
import random
import sys
import time
from datetime import datetime
from pathlib import Path

from pokerestock import config as config_mod
from pokerestock import resume as resume_mod
from pokerestock import tableau as tableau_mod
from pokerestock.etat import Memoire
from pokerestock.http import domaine
from pokerestock.models import PARIS, Alerte
from pokerestock.moteur import Moteur
from pokerestock.notif import LIBELLES, NotifieurConsole, depuis_environnement, euros

RACINE = Path(__file__).resolve().parent.parent
log = logging.getLogger("pokerestock")


def charger_env(fichier: Path) -> None:
    """Lit un fichier .env simple (CLE=valeur) sans écraser l'environnement."""
    if not fichier.exists():
        return
    for ligne in fichier.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if ligne and not ligne.startswith("#") and "=" in ligne:
            cle, val = ligne.split("=", 1)
            os.environ.setdefault(cle.strip(), val.strip().strip('"').strip("'"))


def _journaux(verbeux: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbeux else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s : %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    for bruyant in ("urllib3", "asyncio"):
        logging.getLogger(bruyant).setLevel(logging.WARNING)


def un_passage(args, simulation: bool) -> int:
    cfg = config_mod.charger(args.config)
    memoire = Memoire(args.data)
    notifieur = depuis_environnement(simulation=simulation)
    moteur = Moteur(cfg, memoire, notifieur, simulation=simulation)
    try:
        moteur.passage()
    finally:
        moteur.fermer()
    if not simulation and resume_mod.est_l_heure(memoire):
        if notifieur.envoyer(resume_mod.construire(cfg, memoire)):
            memoire.data["dernier_resume"] = datetime.now(PARIS).date().isoformat()
    memoire.sauver(simulation=simulation)
    if not simulation:
        tableau_mod.generer(cfg, memoire, args.docs)
    log.info(
        "passage terminé : %d alerte(s)%s",
        len(notifieur.envoyees),
        " (simulation : rien envoyé, état non enregistré)" if simulation else "",
    )
    return 0


def cmd_run(args) -> int:
    return un_passage(args, args.dry_run)


def cmd_boucle(args) -> int:
    """Pour un Raspberry Pi : un passage par minute environ. Les délais par site
    (≥ 5 min + aléa) sont gérés par le moteur, pas par cette boucle."""
    while True:
        try:
            un_passage(args, simulation=False)
        except Exception:
            log.exception("passage en échec, on continue")
        time.sleep(60 + random.uniform(0, 20))


def cmd_etat(args) -> int:
    memoire = Memoire(args.data)
    lignes = sorted(memoire.fiches.values(), key=lambda f: (f["produit"], f["enseigne"]))
    if not lignes:
        print("Aucune fiche lue pour l'instant.")
    for f in lignes:
        print(f"{f['produit']:<16} {f['enseigne']:<14} {LIBELLES.get(f['etat'], f['etat']):<18} {euros(f['prix']):<12} {f['verifie']}")
    for dom, i in memoire.illisibles.items():
        print(f"ILLISIBLE : {i['enseigne']} ({dom}) depuis {i['depuis']} — {i['raison']}")
    return 0


def cmd_lire(args) -> int:
    cfg = config_mod.charger(args.config)
    memoire = Memoire(args.data)
    dom = domaine(args.url)
    info = memoire.domaines.setdefault(dom, {})
    attente = info.get("prochaine_visite", 0) - time.time()
    if attente > 0:
        print(f"{dom} a été visité récemment : réessaie dans {int(attente) + 1} s (règle des 5 min).")
        return 2
    moteur = Moteur(cfg, memoire, NotifieurConsole(simulation=True), simulation=True)
    try:
        lec = moteur.adaptateur(args.enseigne).lire_fiche(args.url)
    finally:
        moteur.fermer()
    r = cfg.reglages
    info["prochaine_visite"] = time.time() + r["intervalle_min_s"] + random.uniform(0, r["alea_max_s"])
    memoire.sauver(simulation=True)
    print(f"état brut : {lec.etat}\nprix      : {euros(lec.prix)}\nvendeur   : {lec.vendeur}\ntitre     : {lec.titre}\ndétail    : {lec.detail}")
    return 0


def cmd_test_notif(args) -> int:
    notifieur = depuis_environnement()
    ok = notifieur.envoyer(
        Alerte(
            type="test",
            titre="PokeRestock : test de notification",
            message="Si tu lis ceci, les alertes arrivent bien. Touche la notification pour ouvrir le lien.",
            url="https://www.pokemon.com/fr/jcc-pokemon",
            chaud=True,
        )
    )
    return 0 if ok else 1


def cmd_resume(args) -> int:
    cfg = config_mod.charger(args.config)
    memoire = Memoire(args.data)
    alerte = resume_mod.construire(cfg, memoire)
    ok = depuis_environnement(simulation=args.dry_run).envoyer(alerte)
    return 0 if ok else 1


def cmd_tableau(args) -> int:
    cfg = config_mod.charger(args.config)
    chemin = tableau_mod.generer(cfg, Memoire(args.data), args.docs)
    print(f"tableau de bord : {chemin}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pokerestock", description="Surveillance personnelle des restocks Pokémon")
    ap.add_argument("--config", type=Path, default=RACINE / "config")
    ap.add_argument("--data", type=Path, default=RACINE / "data")
    ap.add_argument("--docs", type=Path, default=RACINE / "docs")
    ap.add_argument("-v", "--verbeux", action="store_true")
    sous = ap.add_subparsers(dest="commande", required=True)
    run = sous.add_parser("run", help="un passage de surveillance")
    run.add_argument("--dry-run", action="store_true", help="simulation : rien n'est envoyé ni enregistré (sauf les délais de politesse)")
    run.set_defaults(f=cmd_run)
    sous.add_parser("boucle", help="passages en continu (Raspberry Pi)").set_defaults(f=cmd_boucle)
    sous.add_parser("etat", help="afficher l'état connu").set_defaults(f=cmd_etat)
    lire = sous.add_parser("lire", help="lire une fiche avec l'adaptateur d'une enseigne")
    lire.add_argument("enseigne")
    lire.add_argument("url")
    lire.set_defaults(f=cmd_lire)
    sous.add_parser("test-notif", help="envoyer une notification de test").set_defaults(f=cmd_test_notif)
    res = sous.add_parser("resume", help="envoyer le résumé quotidien maintenant")
    res.add_argument("--dry-run", action="store_true")
    res.set_defaults(f=cmd_resume)
    sous.add_parser("tableau", help="régénérer le tableau de bord").set_defaults(f=cmd_tableau)
    args = ap.parse_args(argv)
    charger_env(RACINE / ".env")
    _journaux(args.verbeux)
    return args.f(args)
