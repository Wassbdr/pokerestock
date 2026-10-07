"""Navigateur headless (Playwright/Chromium) pour les sites rendus en JavaScript.

Aucune technique furtive : User-Agent honnête, pas de masquage de
`navigator.webdriver`, pas de faux profil. Si le site affiche un challenge,
on le détecte et la source passe illisible.
"""

from __future__ import annotations

import logging

import requests

from pokerestock.http import Absente, Bloque, Client, Reponse, detecter_blocage

log = logging.getLogger(__name__)

RESSOURCES_IGNOREES = {"image", "media", "font"}


class Navigateur:
    def __init__(self, client: Client, delai_rendu_ms: int = 2500, timeout_ms: int = 30000):
        self.client = client  # pour robots.txt et le User-Agent
        self.delai_rendu_ms = delai_rendu_ms
        self.timeout_ms = timeout_ms
        self._pw = None
        self._navigateur = None
        self._contexte = None

    def _demarrer(self):
        if self._contexte:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("Playwright n'est pas installé (pip install playwright && playwright install chromium)") from e
        self._pw = sync_playwright().start()
        self._navigateur = self._pw.chromium.launch(headless=True)
        self._contexte = self._navigateur.new_context(
            user_agent=self.client.user_agent,
            locale="fr-FR",
            timezone_id="Europe/Paris",
            viewport={"width": 1280, "height": 900},
        )
        self._contexte.route(
            "**/*",
            lambda route: route.abort() if route.request.resource_type in RESSOURCES_IGNOREES else route.continue_(),
        )

    def charger(self, url: str, attendre: str | None = None) -> Reponse:
        if not self.client.autorise(url):
            raise Bloque("interdit par robots.txt")
        self._demarrer()
        page = self._contexte.new_page()
        try:
            rep = page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            status = rep.status if rep else 0
            if attendre:
                try:
                    page.wait_for_selector(attendre, timeout=self.timeout_ms // 2)
                except Exception:
                    log.debug("sélecteur %s absent sur %s", attendre, url)
            page.wait_for_timeout(self.delai_rendu_ms)
            html = page.content()
            url_finale = page.url
        finally:
            page.close()
        raison = detecter_blocage(status, html)
        if raison:
            raise Bloque(f"{raison} (navigateur)")
        if status in (404, 410):
            raise Absente(f"HTTP {status}")
        if status >= 400:
            raise requests.HTTPError(f"HTTP {status} (navigateur)")
        return Reponse(status, html, url_finale)

    def fermer(self):
        for f in (lambda: self._contexte and self._contexte.close(), lambda: self._navigateur and self._navigateur.close(), lambda: self._pw and self._pw.stop()):
            try:
                f()
            except Exception:
                pass
        self._pw = self._navigateur = self._contexte = None
