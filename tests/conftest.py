from pathlib import Path

import pytest
import requests

from pokerestock.http import Absente, Bloque, Reponse, detecter_blocage

FIXTURES = Path(__file__).parent / "fixtures"


def page(nom: str) -> str:
    return (FIXTURES / nom).read_text(encoding="utf-8")


class FauxClient:
    """Remplace le réseau : url -> (status, html). Compte les requêtes par URL."""

    def __init__(self, pages: dict[str, tuple[int, str]] | None = None):
        self.pages = pages or {}
        self.requetes: list[str] = []

    def get(self, url: str) -> Reponse:
        self.requetes.append(url)
        if url not in self.pages:
            raise requests.ConnectionError(f"pas de page pour {url}")
        status, texte = self.pages[url]
        raison = detecter_blocage(status, texte)
        if raison:
            raise Bloque(raison)
        if status in (404, 410):
            raise Absente(f"HTTP {status}")
        if status >= 400:
            raise requests.HTTPError(f"HTTP {status}")
        return Reponse(status, texte, url)


@pytest.fixture
def faux_client():
    return FauxClient()
