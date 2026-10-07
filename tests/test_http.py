from pokerestock.http import detecter_blocage
from tests.conftest import page


def test_imperva():
    assert "Imperva" in detecter_blocage(403, page("bloque/imperva.html"))


def test_cloudflare_403():
    assert "Cloudflare" in detecter_blocage(403, page("bloque/cloudflare.html"))


def test_captcha_amazon_meme_en_200():
    assert "Amazon" in detecter_blocage(200, page("amazon/captcha.html"))


def test_page_normale_avec_script_recaptcha_non_bloquee():
    # JouéClub charge reCAPTCHA pour ses formulaires : ce n'est pas un blocage.
    grande = page("proximis/joueclub_rupture.html") + "<script src='https://www.google.com/recaptcha/api.js'></script>" + "x" * 60_000
    assert detecter_blocage(200, grande) is None


def test_dealabs_grande_page_avec_script_cloudflare_non_bloquee():
    assert detecter_blocage(200, page("secours/dealabs_search.html")) is None
