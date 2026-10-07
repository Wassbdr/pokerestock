from pokerestock.secours import sources
from tests.conftest import page


def test_dealabs_vraie_page():
    s = sources.dealabs_recherche(page("secours/dealabs_search.html"))
    assert len(s) == 5
    premier = s[0]
    assert premier.id == "3303750"
    assert premier.prix == 18.99
    assert premier.marchand == "Courses U"
    assert premier.disponible is False  # deal expiré
    assert premier.url.startswith("https://www.dealabs.com/bons-plans/")


def test_flux_crocodeal():
    s = sources.flux_rss(page("secours/crocodeal_feed.xml"), "crocodeal")
    assert len(s) == 30
    assert all(x.url.startswith("https://lecrocodeal.com/") for x in s)


def test_alertetgo_fiche_nettoie_le_lien_affilie():
    s = sources.alertetgo_fiche(page("secours/alertetgo.html"), "https://alertetgo.com/x")
    assert len(s) == 1
    assert s[0].url == "https://www.amazon.fr/dp/B0H8T1LY94"
    assert s[0].prix == 35.94 and s[0].marchand == "Amazon" and s[0].disponible


def test_dealabs_groupe_trie_par_nouveaute():
    s = sources.dealabs_recherche(page("secours/dealabs_groupe.html"))
    assert len(s) == 31
    assert sum(x.disponible for x in s) >= 25
    assert any(x.marchand == "Fnac" and x.prix == 35.99 for x in s)
