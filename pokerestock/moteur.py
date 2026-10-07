"""Un « passage » : choisit quoi visiter en respectant les délais, lit, décide, alerte.

Politesse (règle non négociable) : une visite par domaine au plus toutes les
`intervalle_min_s` secondes + un aléa de 0 à `alea_max_s`. À chaque visite on lit
au plus `pages_par_visite` pages de ce domaine, choisies par ancienneté de la
dernière lecture (les produits « chauds » comptent double).
"""

from __future__ import annotations

import logging
import random
import re
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable

import xml.etree.ElementTree as ET

import requests

from pokerestock import regles
from pokerestock.adapters import ADAPTATEURS, Adaptateur
from pokerestock.config import Config
from pokerestock.etat import Memoire
from pokerestock.http import Bloque, Client, domaine
from pokerestock.models import Alerte, Etat, Lecture, Produit, maintenant_iso
from pokerestock.notif import LIBELLES, Notifieur, euros
from pokerestock.secours import Signal
from pokerestock.secours import sources

log = logging.getLogger(__name__)

SECOURS_INTERVALLE_S = 900  # sources de secours : au plus toutes les 15 min
NOMS_SECOURS = {"dealabs": "Dealabs", "crocodeal": "Le CrocoDeal", "alertetgo": "Alerte&Go"}


@dataclass
class Tache:
    cle: str
    url: str
    poids: float
    action: Callable[[], None]
    intervalle_s: float = 0  # délai minimal propre à la tâche (en plus de celui du domaine)

    @property
    def domaine(self) -> str:
        return domaine(self.url)


class Moteur:
    def __init__(
        self,
        config: Config,
        memoire: Memoire,
        notifieur: Notifieur,
        client: Client | None = None,
        simulation: bool = False,
        horloge: Callable[[], float] = time.time,
        pause: Callable[[float], None] = time.sleep,
        alea: random.Random | None = None,
        navigateur=None,
    ):
        self.config = config
        self.memoire = memoire
        self.notifieur = notifieur
        self.simulation = simulation
        self.horloge = horloge
        self.pause = pause
        self.alea = alea or random.Random()
        r = config.reglages
        self.client = client or Client(
            r["user_agent"], robots_cache=memoire.robots, respecter_robots=r["respecter_robots"]
        )
        self.navigateur = navigateur  # créé à la demande (Playwright)
        self._adaptateurs: dict[str, Adaptateur] = {}
        self._bloque_pendant_visite: set[str] = set()

    # ------------------------------------------------------------------ outils
    def adaptateur(self, cle_enseigne: str) -> Adaptateur:
        if cle_enseigne not in self._adaptateurs:
            cfg = self.config.enseigne(cle_enseigne)
            nom_adaptateur = cfg.get("adaptateur", "jsonld")
            classe = ADAPTATEURS[nom_adaptateur]
            if nom_adaptateur == "navigateur":
                if self.navigateur is None:
                    from pokerestock.navigateur import Navigateur

                    self.navigateur = Navigateur(self.client)
                ad = classe(self.client, cfg.get("nom", cle_enseigne), cfg.get("recherche"), navigateur=self.navigateur, cfg=cfg)
            else:
                ad = classe(self.client, cfg.get("nom", cle_enseigne), cfg.get("recherche"))
            self._adaptateurs[cle_enseigne] = ad
        return self._adaptateurs[cle_enseigne]

    def navigateur_disponible(self) -> bool:
        if self.navigateur is not None:
            return True
        try:
            import playwright  # noqa: F401
        except ImportError:
            return False
        return True

    def adaptateur_navigateur(self, cle_enseigne: str) -> Adaptateur:
        cle = f"{cle_enseigne}#navigateur"
        if cle not in self._adaptateurs:
            cfg = self.config.enseigne(cle_enseigne)
            if self.navigateur is None:
                from pokerestock.navigateur import Navigateur

                self.navigateur = Navigateur(self.client)
            self._adaptateurs[cle] = ADAPTATEURS["navigateur"](
                self.client, cfg.get("nom", cle_enseigne), cfg.get("recherche"), navigateur=self.navigateur, cfg=cfg
            )
        return self._adaptateurs[cle]

    def fermer(self) -> None:
        if self.navigateur is not None and hasattr(self.navigateur, "fermer"):
            self.navigateur.fermer()

    def _alerter(self, alerte: Alerte) -> None:
        if not self.notifieur.envoyer(alerte):
            log.error("alerte non envoyée, remise en file : %s", alerte.titre)
            self.memoire.en_attente.append(alerte.__dict__)
            del self.memoire.en_attente[:-50]
        self.memoire.historiser({"heure": alerte.heure, "evenement": "alerte", **_sans_vide(alerte.__dict__)})

    def renvoyer_en_attente(self) -> None:
        file, self.memoire.data["en_attente"] = list(self.memoire.en_attente), []
        for d in file:
            alerte = Alerte(**d)
            alerte.titre = alerte.titre if alerte.titre.startswith("(retard) ") else f"(retard) {alerte.titre}"
            if not self.notifieur.envoyer(alerte):
                self.memoire.en_attente.append(alerte.__dict__)

    # ----------------------------------------------------------------- tâches
    def taches(self) -> list[Tache]:
        t: list[Tache] = []
        decouvertes = self.memoire.decouvertes
        for p in self.config.produits:
            poids = 2.0 if p.chaud else 1.0
            urls = defaultdict(list)
            for ens, liste in p.urls.items():
                urls[ens].extend(liste)
            for ens, liste in decouvertes.get(p.id, {}).items():
                urls[ens].extend(u for u in liste if u not in urls[ens])
            if p.ean:
                # Enseignes dont l'URL de fiche se déduit de l'EAN (Leclerc : /fp/<EAN>).
                for ens, cfg in self.config.enseignes.items():
                    if cfg.get("fiche_ean"):
                        u = cfg["fiche_ean"].format(ean=p.ean)
                        if u not in urls[ens]:
                            urls[ens].append(u)
            for ens, liste in urls.items():
                for url in liste:
                    t.append(Tache(f"fiche|{p.id}|{ens}|{url}", url, poids, _lier(self.verifier_fiche, p, ens, url)))
            for ens, cfg in self.config.enseignes.items():
                if cfg.get("recherche"):
                    mots = p.mots_cles[0] if p.mots_cles else p.nom
                    requete = mots if cfg.get("recherche_par") == "mots_cles" else (p.ean or mots)
                    url = cfg["recherche"].format(q=requete)
                    t.append(
                        Tache(
                            f"decouverte|{p.id}|{ens}",
                            url,
                            poids * 0.5,
                            _lier(self.decouvrir, p, ens, requete),
                            self.config.reglages["decouverte_toutes_les_s"],
                        )
                    )
            for url in p.secours.get("alertetgo", []):
                t.append(Tache(f"secours|alertetgo|{url}", url, poids, _lier(self.secours_alertetgo, url), SECOURS_INTERVALLE_S))
        for ens, cfg in self.config.enseignes.items():
            if cfg.get("sitemap_index"):
                t.append(
                    Tache(
                        f"sitemap|{ens}",
                        cfg["sitemap_index"],
                        0.8,
                        _lier(self.decouvrir_sitemap, ens),
                        cfg.get("sitemap_toutes_les_s", 3600),
                    )
                )
        s = self.config.secours
        if "dealabs" in s:
            t.append(Tache("secours|dealabs", s["dealabs"]["url"], 1.5, _lier(self.secours_dealabs, s["dealabs"]["url"]), SECOURS_INTERVALLE_S))
        for nom in ("crocodeal", "alertetgo"):
            if nom in s and s[nom].get("flux"):
                url = s[nom]["flux"]
                t.append(Tache(f"secours|{nom}|flux", url, 1.5, _lier(self.secours_flux, nom, url), SECOURS_INTERVALLE_S))
        return t

    # ---------------------------------------------------------------- passage
    def passage(self) -> None:
        if self.memoire.en_attente and not self.simulation:
            self.renvoyer_en_attente()
        maintenant = self.horloge()
        r = self.config.reglages
        par_domaine: dict[str, list[Tache]] = defaultdict(list)
        for tache in self.taches():
            par_domaine[tache.domaine].append(tache)

        domaines = list(par_domaine)
        self.alea.shuffle(domaines)
        # Les enseignes d'abord, les sources de secours ensuite : une lecture
        # directe faite dans ce passage prime sur un agrégateur.
        domaines.sort(key=lambda d: all(t.cle.startswith("secours|") for t in par_domaine[d]))
        for dom in domaines:
            info = self.memoire.domaines.setdefault(dom, {})
            attente = info.get("prochaine_visite", 0) - maintenant
            if attente > 0:
                log.debug("%s : prochaine visite dans %d s", dom, attente)
                continue
            derniere = self.memoire.taches
            eligibles = [
                t for t in par_domaine[dom] if maintenant - derniere.get(t.cle, 0) >= t.intervalle_s
            ]
            if not eligibles:
                continue
            eligibles.sort(key=lambda t: (maintenant - derniere.get(t.cle, 0)) * t.poids, reverse=True)
            self._bloque_pendant_visite.discard(dom)
            for i, tache in enumerate(eligibles[: r["pages_par_visite"]]):
                if i:
                    self.pause(self.alea.uniform(5, 15))
                log.info("visite %s : %s", dom, tache.cle)
                try:
                    tache.action()
                except Exception:
                    log.exception("échec de la tâche %s", tache.cle)
                derniere[tache.cle] = self.horloge()
                if dom in self._bloque_pendant_visite:
                    break
            fin = self.horloge()
            info["derniere_visite"] = fin
            if dom in self._bloque_pendant_visite:
                info["prochaine_visite"] = fin + r["retest_bloque_s"]
            else:
                info["prochaine_visite"] = fin + r["intervalle_min_s"] + self.alea.uniform(0, r["alea_max_s"])
        self.memoire.data["dernier_passage"] = maintenant_iso()

    # ------------------------------------------------- disponibilité de source
    def _source(self, dom: str, nom: str, bloque: bool, raison: str = "") -> None:
        """Signale une seule fois qu'une source devient illisible, et quand elle revient."""
        ill = self.memoire.illisibles
        if bloque:
            self._bloque_pendant_visite.add(dom)
            if dom not in ill:
                ill[dom] = {"depuis": maintenant_iso(), "raison": raison, "enseigne": nom}
                self._alerter(
                    Alerte(
                        type="illisible",
                        titre=f"{nom} : source illisible",
                        message=f"{raison}\nPas de contournement : nouvel essai dans 24 h. "
                        "En attendant, les sources de secours (Dealabs, CrocoDeal, Alerte&Go) prennent le relais.",
                        enseigne=nom,
                    )
                )
        elif dom in ill:
            del ill[dom]
            self._alerter(Alerte(type="de_nouveau_lisible", titre=f"{nom} : de nouveau lisible", message="La surveillance directe reprend.", enseigne=nom))

    # ----------------------------------------------------------------- fiches
    def verifier_fiche(self, produit: Produit, cle_ens: str, url: str) -> Lecture:
        cfg = self.config.enseigne(cle_ens)
        nom = cfg.get("nom", cle_ens)
        lec = self.adaptateur(cle_ens).lire_fiche(url)
        if lec.besoin_navigateur and cfg.get("navigateur_si_besoin", True) and self.navigateur_disponible():
            log.info("%s : page sans données, nouvelle lecture avec le navigateur", nom)
            lec = self.adaptateur_navigateur(cle_ens).lire_fiche(url)
        if lec.bloque or lec.etat != Etat.ILLISIBLE:
            self._source(domaine(url), nom, lec.bloque, lec.detail)
        final = regles.etat_final(lec, produit, cfg)
        cle = f"{produit.id}|{cle_ens}|{url}"
        ancien = self.memoire.fiches.get(cle)
        log.info("%s @ %s : %s %s %s", produit.nom, nom, final, euros(lec.prix), lec.detail)

        if regles.doit_alerter(ancien, final, lec.prix):
            prix_txt = euros(lec.prix) + ("" if lec.prix is not None else " — vérifie le prix avant d'acheter")
            self._alerter(
                Alerte(
                    type="restock",
                    titre=f"{LIBELLES[final]} : {produit.nom}",
                    message=f"{nom} · {prix_txt} ({plafond_txt(produit)})"
                    + (f"\nVendeur : {lec.vendeur}" if lec.vendeur and lec.vendeur != nom else ""),
                    url=url,
                    chaud=produit.chaud,
                    produit=produit.nom,
                    enseigne=nom,
                    prix=lec.prix,
                    etat=str(final),
                )
            )
        if ancien is None or ancien.get("etat") != final or ancien.get("prix") != lec.prix:
            self.memoire.historiser(
                {
                    "heure": lec.horodatage,
                    "evenement": "changement",
                    "produit": produit.id,
                    "enseigne": cle_ens,
                    "url": url,
                    "avant": (ancien or {}).get("etat"),
                    "apres": str(final),
                    "prix": lec.prix,
                }
            )
        self.memoire.fiches[cle] = {
            "produit": produit.id,
            "enseigne": cle_ens,
            "url": url,
            "etat": str(final),
            "brut": str(lec.etat),
            "prix": lec.prix,
            "vendeur": lec.vendeur,
            "titre": lec.titre,
            "detail": lec.detail,
            "verifie": lec.horodatage,
            "depuis": lec.horodatage if not ancien or ancien.get("etat") != final else ancien.get("depuis"),
            # Dernier état réellement lu (survit aux périodes illisibles).
            "dernier_lisible": (
                {"etat": str(final), "heure": lec.horodatage}
                if final != Etat.ILLISIBLE
                else (ancien or {}).get("dernier_lisible")
            ),
        }
        return lec

    # ------------------------------------------------------------- découverte
    def decouvrir(self, produit: Produit, cle_ens: str, requete: str) -> None:
        cfg = self.config.enseigne(cle_ens)
        nom = cfg.get("nom", cle_ens)
        try:
            trouvailles = self.adaptateur(cle_ens).rechercher(requete)
        except Bloque as e:
            self._source(domaine(cfg["recherche"]), nom, True, f"recherche : {e}")
            return
        except requests.RequestException as e:
            log.warning("recherche %s impossible : %s", nom, e)
            return
        connues = set(produit.urls.get(cle_ens, []))
        deja = self.memoire.decouvertes.setdefault(produit.id, {}).setdefault(cle_ens, [])
        connues.update(deja)
        for t in trouvailles:
            if t.url in connues or not produit.correspond(t.titre):
                continue
            deja.append(t.url)
            connues.add(t.url)
            if t.prix is not None and t.prix > produit.limite + regles.EPSILON:
                log.info("nouvelle fiche hors budget, surveillée sans alerte : %s (%s)", t.titre, euros(t.prix))
                continue
            self._alerter(
                Alerte(
                    type="nouvelle_fiche",
                    titre=f"NOUVELLE FICHE : {produit.nom}",
                    message=f"{nom} · {t.titre}\n{euros(t.prix)} ({plafond_txt(produit)}). Ajoutée à la surveillance.",
                    url=t.url,
                    chaud=produit.chaud,
                    produit=produit.nom,
                    enseigne=nom,
                    prix=t.prix,
                )
            )

    def decouvrir_sitemap(self, cle_ens: str) -> None:
        """Une requête par visite : l'index (une fois par jour) ou le fichier suivant."""
        cfg = self.config.enseigne(cle_ens)
        nom = cfg.get("nom", cle_ens)
        st = self.memoire.sitemaps.setdefault(cle_ens, {"liste": [], "lu": 0, "i": 0})
        try:
            if not st["liste"] or self.horloge() - st["lu"] > 86400:
                rep = self.client.get(cfg["sitemap_index"])
                filtre = cfg.get("sitemap_filtre", "")
                st["liste"] = [u for u in sources.locs_sitemap(rep.texte) if filtre in u]
                st["lu"], st["i"] = self.horloge(), 0
                log.info("%s : %d sitemap(s) produits", nom, len(st["liste"]))
                return
            url = st["liste"][st["i"] % len(st["liste"])]
            st["i"] = (st["i"] + 1) % len(st["liste"])
            rep = self.client.get(url)
        except Bloque as e:
            self._source(domaine(cfg["sitemap_index"]), nom, True, f"sitemap : {e}")
            return
        except (requests.RequestException, ET.ParseError) as e:
            log.warning("sitemap %s illisible : %s", nom, e)
            return
        except Exception as e:  # Absente…
            log.warning("sitemap %s : %s", nom, e)
            return
        urls = sources.locs_sitemap(rep.texte)
        log.info("%s : %d URL(s) dans %s", nom, len(urls), url.rsplit("/", 1)[-1])
        rattachees: set[str] = set()
        for p in self.config.produits:
            connues = set(p.urls.get(cle_ens, [])) | set(self.memoire.decouvertes.get(p.id, {}).get(cle_ens, []))
            for u in urls:
                if u in connues or not p.correspond(u.rsplit("/", 1)[-1].replace("-", " ").replace(".html", "")):
                    continue
                self.memoire.decouvertes.setdefault(p.id, {}).setdefault(cle_ens, []).append(u)
                connues.add(u)
                rattachees.add(u)
                self._alerter(
                    Alerte(
                        type="nouvelle_fiche",
                        titre=f"NOUVELLE FICHE : {p.nom}",
                        message=f"{nom} (sitemap) · ajoutée à la surveillance, état et prix au prochain passage.",
                        url=u,
                        chaud=p.chaud,
                        produit=p.nom,
                        enseigne=nom,
                    )
                )
        self._veille_ean(cle_ens, nom, url, urls, rattachees)

    def _veille_ean(self, cle_ens: str, nom: str, fichier: str, urls: list[str], rattachees: set[str]) -> None:
        """Toute nouvelle fiche dont l'URL porte le préfixe EAN surveillé (0196214 =
        The Pokémon Company) : alerte « nouveau produit JCC », même hors de ta liste.
        Première lecture d'un fichier sitemap : mémorisation sans alerte."""
        prefixe = self.config.reglages.get("veille_prefixe_ean")
        if not prefixe:
            return
        vues = self.memoire.veille.setdefault(cle_ens, [])
        deja = set(vues)
        cle_init = f"sitemap:{fichier}"
        premiere = cle_init not in self.memoire.sources_initialisees
        motif = re.compile(rf"(?<!\d){re.escape(prefixe)}\d{{{13 - len(prefixe)}}}(?!\d)")
        for u in urls:
            if u in deja or not motif.search(u.rsplit("/", 1)[-1]):
                continue
            vues.append(u)
            deja.add(u)
            if premiere or u in rattachees:
                continue
            slug = re.sub(r"[-_]+", " ", u.rsplit("/", 1)[-1].rsplit(".", 1)[0])
            self._alerter(
                Alerte(
                    type="nouvelle_fiche",
                    titre=f"NOUVEAU PRODUIT JCC chez {nom}",
                    message=f"{slug}\nPas dans ta liste : ajoute-le à config/produits.yaml s'il t'intéresse.",
                    url=u,
                    enseigne=nom,
                )
            )
        if premiere:
            self.memoire.sources_initialisees.append(cle_init)

    # ---------------------------------------------------------------- secours
    def _lire_source(self, nom: str, url: str) -> str | None:
        try:
            rep = self.client.get(url)
        except Bloque as e:
            self._source(domaine(url), NOMS_SECOURS.get(nom, nom), True, str(e))
            return None
        except requests.RequestException as e:
            log.warning("source %s indisponible : %s", nom, e)
            return None
        self._source(domaine(url), NOMS_SECOURS.get(nom, nom), False)
        return rep.texte

    def _traiter_signaux(self, nom_source: str, signaux: list[Signal], premiere_lecture_possible: bool = True) -> None:
        """Alerte sur les annonces nouvelles qui correspondent à un produit, sous son plafond.
        À la toute première lecture d'une source, tout est mémorisé sans alerter
        (sinon on recevrait les vieilles annonces)."""
        initialisees = self.memoire.sources_initialisees
        premiere = premiere_lecture_possible and nom_source not in initialisees
        # Une fiche lue directement et lisible fait foi : on ignore l'agrégateur
        # (Alerte&Go affichait « en stock » une fiche Amazon « sur invitation »).
        lues_directement = {f["url"] for f in self.memoire.fiches.values() if f["etat"] != Etat.ILLISIBLE}
        # Fiches connues « sur invitation » : un agrégateur qui les dit « en stock » se trompe.
        sur_invitation = {
            f["url"] for f in self.memoire.fiches.values() if (f.get("dernier_lisible") or {}).get("etat") == Etat.INVITATION
        }
        for s in signaux:
            cle = f"{s.source}|{s.id}"
            avant = self.memoire.signaux.get(cle)
            for p in self.config.produits:
                if not p.correspond(s.titre):
                    continue
                qualifie = (
                    regles.signal_qualifie(p, s.prix, s.disponible)
                    and s.url not in lues_directement
                    and s.url not in sur_invitation
                )
                if qualifie and not premiere and not (avant and avant.get("qualifie")):
                    origine = NOMS_SECOURS.get(s.source, s.source)
                    self._alerter(
                        Alerte(
                            type="signal_secours",
                            titre=f"SIGNAL {origine.upper()} : {p.nom}",
                            message=f"{s.titre}\n{(s.marchand + ' · ') if s.marchand else ''}{euros(s.prix)} "
                            f"({plafond_txt(p)}). Source indirecte : vérifie sur le site."
                            + (" Amazon : peut être « sur invitation »." if "amazon." in s.url else ""),
                            url=s.url,
                            chaud=p.chaud,
                            produit=p.nom,
                            enseigne=s.marchand,
                            prix=s.prix,
                        )
                    )
                self.memoire.signaux[cle] = {"qualifie": qualifie, "vu": self.horloge()}
                break
            else:
                self.memoire.signaux.setdefault(cle, {"qualifie": False, "vu": self.horloge()})
        if premiere_lecture_possible and nom_source not in initialisees:
            initialisees.append(nom_source)

    def secours_dealabs(self, url: str) -> None:
        page = self._lire_source("dealabs", url)
        if page is not None:
            self._traiter_signaux("dealabs", sources.dealabs_recherche(page))

    def secours_flux(self, nom: str, url: str) -> None:
        page = self._lire_source(nom, url)
        if page is not None:
            self._traiter_signaux(f"{nom}-flux", sources.flux_rss(page, nom))

    def secours_alertetgo(self, url: str) -> None:
        page = self._lire_source("alertetgo", url)
        if page is not None:
            # Fiche suivie volontairement : pas de « première lecture » muette.
            self._traiter_signaux("alertetgo-fiche", sources.alertetgo_fiche(page, url), premiere_lecture_possible=False)


def plafond_txt(p: Produit) -> str:
    if p.marge:
        return f"plafond {euros(p.plafond)} + {euros(p.marge)} de marge"
    return f"plafond {euros(p.plafond)}"


def _lier(f, *args):
    return lambda: f(*args)


def _sans_vide(d: dict) -> dict:
    return {k: v for k, v in d.items() if v not in (None, "", False)}
