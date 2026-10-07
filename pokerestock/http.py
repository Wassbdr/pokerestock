"""Accès réseau : User-Agent honnête, robots.txt, détection des blocages.

Aucun contournement : si un site répond par un challenge, un captcha ou un 403,
on lève `Bloque` et l'appelant marque la source illisible.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests

log = logging.getLogger(__name__)

ROBOTS_VALIDITE_S = 24 * 3600


class Bloque(Exception):
    """Le site refuse la lecture (protection anti-robot, 403, robots.txt…)."""


class Absente(Exception):
    """La fiche n'existe pas (HTTP 404/410) : produit pas (encore) au catalogue."""


@dataclass
class Reponse:
    status: int
    texte: str
    url: str


# Marqueurs de pages de protection. On ne les cherche que dans des pages courtes
# ou en erreur : beaucoup de pages normales chargent un script reCAPTCHA ou
# Cloudflare sans pour autant bloquer.
_MARQUEURS_FORTS = [
    (re.compile(r"captcha-delivery\.com|datadome", re.I), "DataDome"),
    (re.compile(r"validateCaptcha|Saisissez les caract[eè]res", re.I), "captcha Amazon"),
    (re.compile(r"<title>\s*Just a moment", re.I), "challenge Cloudflare"),
]
_MARQUEURS_PAGE_COURTE = [
    (re.compile(r"_Incapsula_Resource|Incapsula incident", re.I), "Imperva/Incapsula"),
    (re.compile(r"challenge-platform|cf-chl-", re.I), "challenge Cloudflare"),
    (re.compile(r"captcha", re.I), "captcha"),
]
PAGE_COURTE = 50_000


def detecter_blocage(status: int, texte: str) -> str | None:
    """Renvoie la raison du blocage, ou None si la page semble normale."""
    for motif, nom in _MARQUEURS_FORTS:
        if motif.search(texte):
            return f"{nom} (HTTP {status})"
    if status in (401, 403, 429, 503) or len(texte) < PAGE_COURTE:
        for motif, nom in _MARQUEURS_PAGE_COURTE:
            if motif.search(texte):
                return f"{nom} (HTTP {status})"
    if status in (401, 403, 429):
        return f"HTTP {status}"
    return None


class Client:
    def __init__(
        self,
        user_agent: str,
        robots_cache: dict | None = None,
        timeout: float = 25,
        session: requests.Session | None = None,
        respecter_robots: bool = True,
    ):
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "fr-FR,fr;q=0.9",
            }
        )
        self.user_agent = user_agent
        self.timeout = timeout
        self.respecter_robots = respecter_robots
        # {domaine: {"texte": str, "lu": float}} — persisté dans l'état.
        self.robots_cache = robots_cache if robots_cache is not None else {}

    def _robots(self, url: str) -> RobotFileParser:
        parts = urlsplit(url)
        domaine = parts.netloc
        entree = self.robots_cache.get(domaine)
        if not entree or time.time() - entree.get("lu", 0) > ROBOTS_VALIDITE_S:
            texte = ""
            try:
                r = self.session.get(f"{parts.scheme}://{domaine}/robots.txt", timeout=self.timeout)
                # 4xx = pas de robots.txt = tout est permis ; 5xx = on reste prudent.
                if r.status_code < 400:
                    texte = r.text
                elif r.status_code >= 500:
                    texte = "User-agent: *\nDisallow: /"
            except requests.RequestException as e:
                log.warning("robots.txt illisible pour %s : %s", domaine, e)
            entree = {"texte": texte, "lu": time.time()}
            self.robots_cache[domaine] = entree
        rp = RobotFileParser()
        rp.parse(entree["texte"].splitlines())
        return rp

    def autorise(self, url: str) -> bool:
        if not self.respecter_robots:
            return True
        return self._robots(url).can_fetch(self.user_agent, url)

    def get(self, url: str) -> Reponse:
        if not self.autorise(url):
            raise Bloque("interdit par robots.txt")
        r = self.session.get(url, timeout=self.timeout, allow_redirects=True)
        if "charset" not in r.headers.get("Content-Type", "").lower() and "xml" not in r.headers.get("Content-Type", ""):
            # Sans charset annoncé, requests suppose ISO-8859-1 (« Ã© » au lieu de « é »).
            r.encoding = "utf-8"
        texte = r.text
        raison = detecter_blocage(r.status_code, texte)
        if raison:
            raise Bloque(raison)
        if r.status_code in (404, 410):
            raise Absente(f"HTTP {r.status_code}")
        if r.status_code >= 400:
            raise requests.HTTPError(f"HTTP {r.status_code}", response=r)
        return Reponse(r.status_code, texte, r.url)


def domaine(url: str) -> str:
    return urlsplit(url).netloc
