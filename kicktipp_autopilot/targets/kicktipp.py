"""Kicktipp über einen Browser — die Rückfallebene hinter `--browser`.

Der Standardweg ist `kicktipp_http.py`. Diese Umsetzung bleibt erhalten, damit
bei Änderungen an Kicktipp sofort ein zweiter Weg zur Verfügung steht, statt
dass der Bot stillsteht. Sie ist außerdem das unabhängige Gegenstück, mit dem
sich der HTTP-Weg überprüfen lässt.

Das Auswerten der Seiten übernimmt derselbe Parser wie beim HTTP-Weg
(`kicktipp_parse.py`); hier steht nur, wie die Seiten geholt und wie die
Felder befüllt werden.
"""

from __future__ import annotations

import logging
import time

from selenium import webdriver
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    NoSuchElementException,
    TimeoutException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from ..config import Credentials
from ..errors import SubmissionError
from ..selectors import Kicktipp as S
from .kicktipp_parse import TippabgabePage, parse_groups, parse_page

log = logging.getLogger(__name__)

BASE_URL = "https://www.kicktipp.de"
GROUPS_PATH = "/info/profil/meinetipprunden"


class KicktippBrowser:
    """Anmelden, lesen und tippen über einen echten Browser."""

    name = "browser"

    def __init__(self, credentials: Credentials, headless: bool = True) -> None:
        self._credentials = credentials
        self._headless = headless
        self._driver: webdriver.Chrome | None = None

    # ── Lebenszyklus ────────────────────────────────────────────────────

    def __enter__(self) -> KicktippBrowser:
        options = Options()
        options.add_experimental_option("excludeSwitches", ["enable-logging"])
        options.add_argument("--blink-settings=imagesEnabled=false")
        if self._headless:
            options.add_argument("--headless=new")
            options.add_argument("--window-size=1920,1080")
        else:
            options.add_argument("--start-maximized")
        self._driver = webdriver.Chrome(service=Service(), options=options)
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self._driver is not None:
            self._driver.quit()
            self._driver = None

    @property
    def driver(self) -> webdriver.Chrome:
        if self._driver is None:
            raise SubmissionError(
                "Browser nicht gestartet — KicktippBrowser als Kontextmanager verwenden."
            )
        return self._driver

    # ── Cookie-Banner ───────────────────────────────────────────────────

    def _accept_cookie_banner(self, timeout: int = 8) -> bool:
        """Cookie-Banner wegklicken. Fehlt es, ist das kein Fehler.

        Das Banner wird asynchron nachgeladen und legt sich als Overlay über
        die Seite — unter anderem genau über den Absende-Button. Es muss
        deshalb nach *jedem* Seitenwechsel behandelt werden, nicht nur beim
        Login. Über HTTP tritt dieses Problem gar nicht erst auf.
        """
        frames = self.driver.find_elements(
            By.CSS_SELECTOR, f"iframe[id^='{S.COOKIE_IFRAME_ID_PREFIX}']"
        )
        if not frames:
            return False

        try:
            self.driver.switch_to.frame(frames[0])
            button = WebDriverWait(self.driver, timeout).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, S.COOKIE_BUTTON))
            )
            button.click()
            log.debug("Cookie-Banner akzeptiert.")
            return True
        except TimeoutException:
            for candidate in self.driver.find_elements(By.CSS_SELECTOR, "button"):
                label = f"{candidate.get_attribute('title') or ''} {candidate.text or ''}"
                if any(word in label.lower() for word in ("akzeptier", "zustimm", "accept")):
                    candidate.click()
                    return True
            return False
        finally:
            try:
                self.driver.switch_to.default_content()
            except Exception:  # noqa: BLE001 — Frame-Wechsel darf nie den Lauf stoppen
                pass

    def _wait_for_cookie_banner(self, seconds: float = 4.0) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self._accept_cookie_banner(timeout=2):
                return
            time.sleep(0.4)

    # ── Anmeldung ───────────────────────────────────────────────────────

    def login(self) -> None:
        self.driver.get(f"{BASE_URL}/info/profil/login")
        self._wait_for_cookie_banner(seconds=6)

        try:
            self.driver.find_element(By.CSS_SELECTOR, S.EMAIL_INPUT).send_keys(
                self._credentials.email
            )
            self.driver.find_element(By.CSS_SELECTOR, S.PASSWORD_INPUT).send_keys(
                self._credentials.password
            )
            self.driver.find_element(By.CSS_SELECTOR, S.SUBMIT_BUTTON).click()
        except NoSuchElementException as exc:
            raise SubmissionError(
                "Login-Formular nicht gefunden. Selektoren in "
                "kicktipp_autopilot/selectors.py prüfen."
            ) from exc
        except ElementClickInterceptedException as exc:
            raise SubmissionError(
                "Anmelde-Button war blockiert (vermutlich das Cookie-Banner)."
            ) from exc

        time.sleep(2)
        self._accept_cookie_banner(timeout=3)

        self.driver.get(f"{BASE_URL}{GROUPS_PATH}")
        if "passwort" in self.driver.page_source.lower() and "tipprunden" not in (
            self.driver.title or ""
        ).lower():
            raise SubmissionError(
                "Anmeldung fehlgeschlagen — E-Mail oder Passwort in der .env prüfen."
            )
        log.info("Bei Kicktipp angemeldet.")

    # ── Lesen ───────────────────────────────────────────────────────────

    def list_groups(self) -> list[str]:
        self.driver.get(f"{BASE_URL}{GROUPS_PATH}")
        time.sleep(1)
        groups = parse_groups(self.driver.page_source, BASE_URL)
        log.info("%d Tippgruppe(n) gefunden: %s", len(groups), ", ".join(groups) or "—")
        return groups

    def load_page(
        self, group: str, matchday: int | None = None, require_fixtures: bool = True
    ) -> TippabgabePage:
        """Lädt einen Spieltag. `matchday` ist der `spieltagIndex` der Gruppe.

        Gleiche Bedeutung wie beim HTTP-Weg — siehe `KicktippHttp.load_page`.
        """
        page = self._open(f"{BASE_URL}/{group}/tippabgabe")

        if matchday is not None and page.form_fields.get("spieltagIndex") != str(matchday):
            season_id = page.form_fields.get("tippsaisonId")
            if not season_id:
                raise SubmissionError(
                    f"Spieltag {matchday} kann nicht angesteuert werden: "
                    "tippsaisonId fehlt im Formular."
                )
            page = self._open(
                f"{BASE_URL}/{group}/tippabgabe"
                f"?tippsaisonId={season_id}&spieltagIndex={matchday}"
            )

        if require_fixtures and not page.fixtures:
            raise SubmissionError(
                f"Keine Spiele in Gruppe {group!r} gefunden. Existiert die Gruppe, "
                "und ist ein Spieltag zur Tippabgabe offen?"
            )

        log.info("%d Spiele auf der Tippabgabe-Seite gelesen.", len(page.fixtures))
        return page

    def _open(self, url: str) -> TippabgabePage:
        self.driver.get(url)
        try:
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "input[name^='spieltippForms']")
                )
            )
        except TimeoutException as exc:
            raise SubmissionError(f"Tippabgabe-Seite {url} nicht geladen.") from exc

        self._wait_for_cookie_banner()
        return parse_page(self.driver.page_source)

    # ── Schreiben ───────────────────────────────────────────────────────

    def submit(
        self, page: TippabgabePage, changes: dict[str, tuple[int, int]]
    ) -> TippabgabePage:
        """Füllt die Felder im Browser und schickt das Formular ab.

        Hidden-Felder und Sonderfragen sendet der Browser automatisch mit —
        das Formular geht als Ganzes raus.
        """
        if not changes:
            raise SubmissionError("Nichts zu senden — keine Änderungen übergeben.")

        known = {fixture.tip_id for fixture in page.fixtures}
        unknown = set(changes) - known
        if unknown:
            raise SubmissionError(
                f"Unbekannte Spiel-IDs sollen getippt werden: {sorted(unknown)}. "
                "Die Seite wurde vermutlich zwischenzeitlich gewechselt."
            )

        for tip_id, (home_score, away_score) in changes.items():
            for side, value in (("heimTipp", home_score), ("gastTipp", away_score)):
                element_id = f"spieltippForms_{tip_id}_{side}"
                try:
                    field = self.driver.find_element(By.ID, element_id)
                except NoSuchElementException as exc:
                    raise SubmissionError(
                        f"Tippfeld {element_id} nicht gefunden."
                    ) from exc
                field.clear()
                field.send_keys(str(value))
            time.sleep(0.2)

        self._click_submit()
        time.sleep(2)
        log.info("Tipps abgesendet.")
        return parse_page(self.driver.page_source)

    def _click_submit(self) -> None:
        self._accept_cookie_banner(timeout=2)
        try:
            button = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, S.SUBMIT_BUTTON))
            )
        except TimeoutException as exc:
            raise SubmissionError(
                "Absende-Button nicht gefunden — Tipps wurden NICHT gespeichert."
            ) from exc

        self.driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center'});", button
        )
        time.sleep(0.3)

        try:
            button.click()
        except ElementClickInterceptedException:
            log.debug("Klick abgefangen — entferne Overlay und versuche erneut.")
            self._accept_cookie_banner(timeout=2)
            try:
                button.click()
            except ElementClickInterceptedException:
                log.warning("Button weiterhin verdeckt — sende das Formular direkt.")
                self.driver.execute_script("arguments[0].click();", button)


# Alter Name, damit bestehende Aufrufe nicht brechen.
KicktippTarget = KicktippBrowser
