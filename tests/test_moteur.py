"""Scénarios de bout en bout du moteur, avec faux réseau et fausse horloge."""

import random

from pokerestock.config import Config
from pokerestock.etat import Memoire
from pokerestock.models import Produit
from pokerestock.moteur import Moteur
from pokerestock.notif import NotifieurConsole
from tests.conftest import FauxClient, page

JC = "https://www.joueclub.fr/pokemon/bundle.html"
JC2 = "https://www.joueclub.fr/pokemon/tin.html"
SMYTHS = "https://www.smythstoys.com/p/1"
DEALABS = "https://www.dealabs.com/search?q=pokemon"

REGLAGES = {
    "user_agent": "test",
    "intervalle_min_s": 300,
    "alea_max_s": 120,
    "pages_par_visite": 1,
    "retest_bloque_s": 86400,
    "decouverte_toutes_les_s": 7200,
    "respecter_robots": True,
}


class Horloge:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


def monter(tmp_path, pages, produits=None, enseignes=None, secours=None):
    produits = produits or [
        Produit(id="tin", nom="Mini Tin 30 ans", plafond=16.99, priorite="chaud", urls={"joueclub": [JC]}, mots_cles=["mini tin 30 ans"]),
    ]
    cfg = Config(produits, enseignes or {"joueclub": {"nom": "JouéClub", "adaptateur": "proximis"}}, REGLAGES, secours or {})
    memoire = Memoire(tmp_path)
    notif = NotifieurConsole()
    horloge = Horloge()
    client = FauxClient(pages)
    m = Moteur(cfg, memoire, notif, client=client, horloge=horloge, pause=lambda s: None, alea=random.Random(1))
    return m, memoire, notif, horloge, client


def test_restock_alerte_une_seule_fois(tmp_path):
    m, mem, notif, h, client = monter(tmp_path, {JC: (200, page("proximis/joueclub_rupture.html"))})
    m.passage()
    assert notif.envoyees == []
    assert mem.fiches[f"tin|joueclub|{JC}"]["etat"] == "rupture"

    client.pages[JC] = (200, page("proximis/joueclub_en_stock.html"))
    h.t += 60  # trop tôt : le domaine n'est pas revisité
    m.passage()
    assert len(client.requetes) == 1 and notif.envoyees == []

    h.t += 600
    m.passage()
    assert [a.type for a in notif.envoyees] == ["restock"]
    a = notif.envoyees[0]
    assert a.chaud and a.url == JC and a.prix == 16.99 and "EN STOCK" in a.titre

    h.t += 600
    m.passage()  # toujours en stock : pas de deuxième alerte
    assert len(notif.envoyees) == 1


def test_delai_entre_deux_visites_toujours_respecte(tmp_path):
    m, mem, notif, h, client = monter(tmp_path, {JC: (200, page("proximis/joueclub_rupture.html"))})
    visites = []
    for _ in range(40):
        avant = len(client.requetes)
        m.passage()
        if len(client.requetes) > avant:
            visites.append(h.t)
        h.t += 30
    ecarts = [b - a for a, b in zip(visites, visites[1:])]
    assert ecarts and min(ecarts) >= 300


def test_une_page_par_visite_et_priorite_aux_produits_chauds(tmp_path):
    produits = [
        Produit(id="normal", nom="Normal", plafond=99, urls={"joueclub": [JC2]}),
        Produit(id="chaud", nom="Chaud", plafond=99, priorite="chaud", urls={"joueclub": [JC]}),
    ]
    pages = {JC: (200, page("proximis/joueclub_rupture.html")), JC2: (200, page("proximis/joueclub_rupture.html"))}
    m, mem, notif, h, client = monter(tmp_path, pages, produits=produits)
    h.t = 10_000  # les deux fiches n'ont jamais été lues : le poids départage
    m.passage()
    assert client.requetes == [JC]
    h.t += 600
    m.passage()
    assert client.requetes == [JC, JC2]


def test_site_bloque_signale_une_fois_puis_reteste_le_lendemain(tmp_path):
    produits = [Produit(id="b", nom="Bundle", plafond=39.99, urls={"smyths": [SMYTHS]})]
    m, mem, notif, h, client = monter(
        tmp_path, {SMYTHS: (403, page("bloque/imperva.html"))}, produits=produits, enseignes={"smyths": {"nom": "Smyths Toys"}}
    )
    m.passage()
    assert [a.type for a in notif.envoyees] == ["illisible"]
    assert "Imperva" in notif.envoyees[0].message
    assert "www.smythstoys.com" in mem.illisibles

    h.t += 3600
    m.passage()
    assert len(client.requetes) == 1  # pas de nouvel essai avant 24 h

    h.t += 86400
    m.passage()
    assert len(client.requetes) == 2
    assert len(notif.envoyees) == 1  # toujours bloqué : pas de nouvelle alerte

    client.pages[SMYTHS] = (200, page("proximis/joueclub_en_stock.html"))
    h.t += 86400 + 200
    m.passage()
    assert [a.type for a in notif.envoyees] == ["illisible", "de_nouveau_lisible", "restock"]


def test_trop_cher_pas_d_alerte(tmp_path):
    produits = [Produit(id="tin", nom="Tin", plafond=14.99, urls={"joueclub": [JC]})]
    m, mem, notif, h, client = monter(tmp_path, {JC: (200, page("proximis/joueclub_en_stock.html"))}, produits=produits)
    m.passage()
    assert notif.envoyees == []
    assert mem.fiches[f"tin|joueclub|{JC}"]["etat"] == "trop_cher"


def test_secours_premiere_lecture_muette_puis_nouvelles_annonces(tmp_path):
    produits = [Produit(id="c", nom="Coffret 30 ans", plafond=25, mots_cles=["coffret 30 ans"])]
    html = page("secours/dealabs_search.html")
    m, mem, notif, h, client = monter(tmp_path, {DEALABS: (200, html)}, produits=produits, secours={"dealabs": {"url": DEALABS}})
    m.passage()
    assert notif.envoyees == []  # vieilles annonces mémorisées sans alerte

    # Une nouvelle annonce active, sous le plafond, apparaît.
    nouvelle = html.replace("3303750", "9999999").replace('"isExpired":true', '"isExpired":false', 1)
    client.pages[DEALABS] = (200, nouvelle)
    h.t += 1000
    m.passage()
    assert [a.type for a in notif.envoyees] == ["signal_secours"]
    assert "9999999" in notif.envoyees[0].url and notif.envoyees[0].prix == 18.99


def test_decouverte_nouvelle_fiche_puis_surveillee(tmp_path):
    recherche = "https://www.amazon.fr/s?k={q}"
    url_recherche = "https://www.amazon.fr/s?k=0196214145221"
    resultats = """<html><body>
      <div data-component-type="s-search-result" data-asin="B0NOUVEAU1"><h2 aria-label="Pokémon Bundle 30 ans 6 boosters"></h2>
        <span class="a-price"><span class="a-offscreen">35,99 €</span></span></div>
      <div data-component-type="s-search-result" data-asin="B0AUTRE001"><h2 aria-label="Pokémon Display 36 boosters"></h2></div>
    </body></html>"""
    produits = [Produit(id="b", nom="Bundle 30 ans", plafond=39.99, ean="0196214145221", mots_cles=["bundle 30 ans"])]
    pages = {url_recherche: (200, resultats), "https://www.amazon.fr/dp/B0NOUVEAU1": (200, page("amazon/en_stock.html"))}
    m, mem, notif, h, client = monter(
        tmp_path, pages, produits=produits, enseignes={"amazon": {"nom": "Amazon.fr", "adaptateur": "amazon", "recherche": recherche}}
    )
    m.passage()
    assert [a.type for a in notif.envoyees] == ["nouvelle_fiche"]
    assert notif.envoyees[0].url == "https://www.amazon.fr/dp/B0NOUVEAU1"
    h.t += 600
    m.passage()  # la nouvelle fiche est maintenant lue
    assert [a.type for a in notif.envoyees] == ["nouvelle_fiche", "restock"]


def test_simulation_n_enregistre_que_les_delais(tmp_path):
    m, mem, notif, h, client = monter(tmp_path, {JC: (200, page("proximis/joueclub_en_stock.html"))})
    m.passage()
    mem.sauver(simulation=True)
    relu = Memoire(tmp_path)
    assert relu.fiches == {}
    assert relu.domaines["www.joueclub.fr"]["prochaine_visite"] > h.t
    assert not (tmp_path / "historique.jsonl").exists()


def test_sauvegarde_reelle_et_historique(tmp_path):
    m, mem, notif, h, client = monter(tmp_path, {JC: (200, page("proximis/joueclub_en_stock.html"))})
    m.passage()
    mem.sauver()
    relu = Memoire(tmp_path)
    assert relu.fiches[f"tin|joueclub|{JC}"]["etat"] == "en_stock"
    lignes = (tmp_path / "historique.jsonl").read_text().splitlines()
    assert any('"alerte"' in l for l in lignes) and any('"changement"' in l for l in lignes)


def test_signal_secours_ignore_si_fiche_lue_directement(tmp_path):
    amazon = "https://www.amazon.fr/dp/B0H8T1LY94"
    ag = "https://alertetgo.com/bundle/"
    produits = [
        Produit(
            id="b", nom="Bundle 30 ans", plafond=39.99, ean="0196214145221", mots_cles=["bundle 30e anniversaire"],
            urls={"amazon": [amazon]}, secours={"alertetgo": [ag]},
        )
    ]
    pages = {amazon: (200, page("amazon/invitation.html")), ag: (200, page("secours/alertetgo.html"))}
    m, mem, notif, h, client = monter(
        tmp_path, pages, produits=produits, enseignes={"amazon": {"nom": "Amazon.fr", "adaptateur": "amazon"}}
    )
    m.passage()
    # Amazon lu directement (invitation) ; Alerte&Go dit « InStock » sur la même URL : ignoré.
    assert [a.type for a in notif.envoyees] == ["restock"]
    assert notif.envoyees[0].etat == "invitation"


def test_fiche_deduite_de_l_ean(tmp_path):
    url = "https://www.e.leclerc/fp/0196214145221"
    produits = [Produit(id="b", nom="Bundle", plafond=39.99, ean="0196214145221")]
    m, mem, notif, h, client = monter(
        tmp_path,
        {url: (200, page("proximis/joueclub_en_stock.html"))},
        produits=produits,
        enseignes={"leclerc": {"nom": "E.Leclerc", "adaptateur": "jsonld", "fiche_ean": "https://www.e.leclerc/fp/{ean}"}},
    )
    m.passage()
    assert client.requetes == [url]
    assert [a.type for a in notif.envoyees] == ["restock"]


def test_marge_au_dessus_du_plafond(tmp_path):
    # Bundle JouéClub à 16,99 € ; plafond 14,99 € + 10 € de marge -> alerte.
    produits = [Produit(id="tin", nom="Tin", plafond=14.99, marge=10, urls={"joueclub": [JC]})]
    m, mem, notif, h, client = monter(tmp_path, {JC: (200, page("proximis/joueclub_en_stock.html"))}, produits=produits)
    m.passage()
    assert [a.type for a in notif.envoyees] == ["restock"]
    assert "10,00 € de marge" in notif.envoyees[0].message


def test_fiche_404_ne_bloque_pas_le_site_puis_alerte_a_l_apparition(tmp_path):
    url = "https://www.e.leclerc/fp/0196214145221"
    produits = [Produit(id="b", nom="Bundle", plafond=39.99, ean="0196214145221")]
    m, mem, notif, h, client = monter(
        tmp_path, {url: (404, "<html>Introuvable</html>")}, produits=produits,
        enseignes={"leclerc": {"nom": "E.Leclerc", "fiche_ean": "https://www.e.leclerc/fp/{ean}"}},
    )
    m.passage()
    assert notif.envoyees == [] and mem.illisibles == {}
    assert mem.fiches[f"b|leclerc|{url}"]["etat"] == "rupture"
    client.pages[url] = (200, page("proximis/joueclub_en_stock.html"))
    h.t += 600
    m.passage()
    assert [a.type for a in notif.envoyees] == ["restock"]


class FauxNavigateur:
    def __init__(self, pages):
        self.pages, self.charges = pages, []

    def charger(self, url, attendre=None):
        from pokerestock.http import Reponse

        self.charges.append(url)
        return Reponse(200, self.pages[url], url)


def test_page_rendue_en_js_relue_avec_le_navigateur(tmp_path):
    url = "https://www.cultura.com/p/bundle.html"
    produits = [Produit(id="b", nom="Bundle", plafond=39.99, urls={"cultura": [url]})]
    m, mem, notif, h, client = monter(
        tmp_path, {url: (200, page("proximis/vide.html"))}, produits=produits, enseignes={"cultura": {"nom": "Cultura"}}
    )
    m.navigateur = FauxNavigateur({url: page("proximis/joueclub_en_stock.html")})
    m.passage()
    assert m.navigateur.charges == [url]
    assert [a.type for a in notif.envoyees] == ["restock"]
    assert mem.illisibles == {}
