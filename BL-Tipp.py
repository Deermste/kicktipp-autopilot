"""
BL-Tipp: Automatischer Bundesliga-Tippabgabe-Bot
=================================================
Liest Vorhersagen von predicd.com und trägt sie automatisch bei Kicktipp ein.

Voraussetzungen:
    - Python 3.8+
    - selenium, python-dotenv
    - Chrome + ChromeDriver

Konfiguration:
    Erstelle eine .env-Datei im selben Verzeichnis mit:
        KICKTIPP_EMAIL=deine@email.de
        KICKTIPP_PASSWORD=deinPasswort
        KICKTIPP_GROUP=deinGruppenname
"""

import base64
import logging
import os
import re
import sys
import time
from dataclasses import dataclass

from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    ElementClickInterceptedException,
)

# ─── Konfiguration ──────────────────────────────────────────────────────────────

load_dotenv()

KICKTIPP_EMAIL = os.getenv("KICKTIPP_EMAIL")
KICKTIPP_PASSWORD = os.getenv("KICKTIPP_PASSWORD")
KICKTIPP_GROUP = os.getenv("KICKTIPP_GROUP")

PREDICD_URL = "https://www.predicd.com/de/football/league/4331/"
KICKTIPP_URL = f"https://www.kicktipp.de/{KICKTIPP_GROUP}/tippabgabe"

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5

# Mapping: Predicd-Teamname → Kicktipp-Teamname
NAME_MAP = {
    "FC Bayern München": "FC Bayern München",
    "RB Leipzig": "RB Leipzig",
    "1. FC Heidenheim": "1. FC Heidenheim 1846",
    "VfL Wolfsburg": "VfL Wolfsburg",
    "1. FC Union Berlin": "1. FC Union Berlin",
    "VfB Stuttgart": "VfB Stuttgart",
    "Bayer Leverkusen": "Bayer 04 Leverkusen",
    "TSG Hoffenheim": "1899 Hoffenheim",
    "Eintracht Frankfurt": "Eintracht Frankfurt",
    "Werder Bremen": "Werder Bremen",
    "SC Freiburg": "SC Freiburg",
    "FC Augsburg": "FC Augsburg",
    "FC St. Pauli": "FC St. Pauli",
    "Borussia Dortmund": "Borussia Dortmund",
    "1. FSV Mainz 05": "FSV Mainz 05",
    "1. FC Köln": "1. FC Köln",
    "Borussia M'Gladbach": "Bor. Mönchengladbach",
    "Hamburger SV": "Hamburger SV",
}

# ─── Logging ─────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ─── Datenklasse ─────────────────────────────────────────────────────────────────

@dataclass
class MatchPrediction:
    """Speichert eine einzelne Spielvorhersage."""
    home_team: str
    away_team: str
    home_score: str
    away_score: str

    def __str__(self) -> str:
        return f"{self.home_team} vs {self.away_team} → {self.home_score}:{self.away_score}"


# ─── Hilfsfunktionen ────────────────────────────────────────────────────────────

def translate_club_name(name: str) -> str:
    """Übersetzt einen Predicd-Teamnamen in den Kicktipp-Namen."""
    return NAME_MAP.get(name, name)


def extract_spieltag_number(text: str) -> int | None:
    """Extrahiert die Spieltagnummer aus einem beliebigen Text."""
    match = re.search(r"\d+", text)
    return int(match.group()) if match else None


def decode_score_part(meta_info: str) -> str:
    """Dekodiert einen base64-kodierten Score-Teil von predicd.com."""
    decoded_bytes = base64.b64decode(meta_info)
    decoded_text = decoded_bytes.decode("utf-16-be")
    code_points = "".join(str(ord(ch)) for ch in decoded_text)
    return str(int((int(code_points[-4:]) - 1760) / 256))


def accept_cookie_banner(driver, selector: str, timeout: int = 10, iframe_id: str | None = None):
    """Versucht, ein Cookie-Banner zu akzeptieren. Ignoriert es, falls nicht vorhanden."""
    try:
        if iframe_id:
            WebDriverWait(driver, timeout).until(
                EC.frame_to_be_available_and_switch_to_it((By.CSS_SELECTOR, f"iframe[id^='{iframe_id}']"))
            )

        button = WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
        )
        button.click()
        log.info("Cookie-Banner akzeptiert.")

        if iframe_id:
            driver.switch_to.default_content()

    except TimeoutException:
        log.debug("Kein Cookie-Banner gefunden oder bereits akzeptiert.")
        if iframe_id:
            try:
                driver.switch_to.default_content()
            except Exception:
                pass


def create_driver(headless: bool = True) -> webdriver.Chrome:
    """Erstellt eine Chrome-WebDriver-Instanz mit passenden Optionen."""
    chrome_options = Options()
    chrome_options.add_experimental_option("excludeSwitches", ["enable-logging"])

    if headless:
        chrome_options.add_argument("--headless")
    else:
        chrome_options.add_argument("--start-maximized")
        chrome_options.add_argument("--blink-settings=imagesEnabled=false")

    return webdriver.Chrome(service=Service(), options=chrome_options)


# ─── Hauptfunktionen ────────────────────────────────────────────────────────────

def fetch_predictions() -> tuple[list[MatchPrediction], int | None]:
    """
    Ruft die Vorhersagen von predicd.com ab.

    Returns:
        Ein Tupel aus (Liste von Vorhersagen, Spieltagnummer).
    """
    predictions: list[MatchPrediction] = []
    spieltag_nr: int | None = None
    driver = create_driver(headless=True)

    try:
        log.info("Öffne predicd.com …")
        driver.get(PREDICD_URL)

        accept_cookie_banner(
            driver,
            selector=".fc-button.fc-cta-consent.fc-primary-button",
        )

        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "span[id^='predResult_']"))
        )

        spieltag_text = driver.find_element(By.ID, "matchdayNumber").text.strip()
        spieltag_nr = extract_spieltag_number(spieltag_text)
        log.info("Predictions für Spieltag %s", spieltag_nr)

        match_rows = driver.find_elements(By.CSS_SELECTOR, "tr.tr-body")

        for row in match_rows:
            try:
                teams = row.find_elements(By.CSS_SELECTOR, "div#teamname")
                if len(teams) < 2:
                    continue

                home_team = teams[0].text.strip()
                away_team = teams[1].text.strip()

                if not home_team or not away_team:
                    continue

                score_elements = row.find_elements(
                    By.CSS_SELECTOR, "span[id^='predResult_'] .of-meta"
                )

                score_parts = []
                for element in score_elements:
                    meta_info = element.get_attribute("meta-info")
                    if meta_info:
                        score_parts.append(decode_score_part(meta_info))

                if len(score_parts) < 2:
                    log.warning("Unvollständiger Score für %s vs %s", home_team, away_team)
                    continue

                prediction = MatchPrediction(
                    home_team=translate_club_name(home_team),
                    away_team=translate_club_name(away_team),
                    home_score=score_parts[0],
                    away_score=score_parts[1],
                )
                predictions.append(prediction)
                log.info("  %s", prediction)

            except Exception as e:
                log.error("Fehler beim Verarbeiten einer Zeile: %s", e)

    finally:
        driver.quit()

    log.info("%d Vorhersagen geladen.", len(predictions))
    return predictions, spieltag_nr


def submit_to_kicktipp(
    predictions: list[MatchPrediction], spieltag_nr: int | None
) -> bool:
    """
    Meldet sich bei Kicktipp an und trägt die Vorhersagen ein.

    Returns:
        True bei Erfolg, False bei Fehler.
    """
    if not predictions:
        log.error("Keine Vorhersagen vorhanden – Abbruch.")
        return False

    if not KICKTIPP_EMAIL or not KICKTIPP_PASSWORD:
        log.error(
            "Zugangsdaten fehlen! Bitte KICKTIPP_EMAIL und KICKTIPP_PASSWORD "
            "in der .env-Datei setzen."
        )
        return False

    if not KICKTIPP_GROUP:
        log.error(
            "Gruppenname fehlt! Bitte KICKTIPP_GROUP in der .env-Datei setzen "
            "(der Teil aus der URL: kicktipp.de/DEIN-GRUPPENNAME/tippabgabe)."
        )
        return False

    driver = create_driver(headless=False)

    try:
        log.info("Öffne Kicktipp …")
        driver.get(KICKTIPP_URL)

        # ── Anmeldung ────────────────────────────────────────────────────────
        anmelden_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, 'button[name="submitbutton"][type="submit"]')
            )
        )

        try:
            email_field = driver.find_element(By.CSS_SELECTOR, 'input#kennung[type="email"]')
            email_field.send_keys(KICKTIPP_EMAIL)
        except NoSuchElementException:
            log.error("E-Mail-Eingabefeld nicht gefunden.")
            return False

        try:
            password_field = driver.find_element(By.CSS_SELECTOR, "#passwort")
            password_field.send_keys(KICKTIPP_PASSWORD)
        except NoSuchElementException:
            log.error("Passwort-Eingabefeld nicht gefunden.")
            return False

        try:
            anmelden_button.click()
        except ElementClickInterceptedException:
            log.error("Anmelden-Button konnte nicht geklickt werden.")
            return False

        log.info("Anmeldung gesendet.")

        # ── Cookie-Banner (Kicktipp) ─────────────────────────────────────────
        accept_cookie_banner(
            driver,
            selector=".message-component.message-button.no-children.focusable.action_button.sp_choice_type_11",
            iframe_id="sp_message_iframe_",
        )

        # ── Zur Tippabgabe navigieren ────────────────────────────────────────
        time.sleep(2)
        driver.get(KICKTIPP_URL)
        log.info("Navigiere zur Tippabgabe …")

        # ── Spieltag prüfen ──────────────────────────────────────────────────
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "tr.datarow"))
        )

        kicktipp_spieltag_text = driver.find_element(
            By.CSS_SELECTOR, "div.prevnextTitle"
        ).text.strip()
        kicktipp_spieltag_nr = extract_spieltag_number(kicktipp_spieltag_text)

        if spieltag_nr != kicktipp_spieltag_nr:
            log.error(
                "Spieltag stimmt nicht überein! Predicd: %s, Kicktipp: %s",
                spieltag_nr,
                kicktipp_spieltag_nr,
            )
            return False

        log.info("Spieltag %s bestätigt – trage Tipps ein …", spieltag_nr)

        # ── Tipps eintragen ──────────────────────────────────────────────────
        # Lookup-Dict für schnellen Zugriff statt verschachtelter Schleifen
        prediction_by_team = {p.home_team: p for p in predictions}

        match_rows = driver.find_elements(By.CSS_SELECTOR, "tr.datarow")
        tipps_eingetragen = 0

        for row in match_rows:
            try:
                home_team_cell = row.find_element(By.CSS_SELECTOR, "td.nw.cell.col1")
                team_name = home_team_cell.text.strip()

                if team_name not in prediction_by_team:
                    log.warning("Kein Tipp gefunden für: %s", team_name)
                    continue

                prediction = prediction_by_team[team_name]

                tipp_inputs = row.find_elements(
                    By.CSS_SELECTOR, "input[id^='spieltippForms'][type='text']"
                )

                if len(tipp_inputs) < 2:
                    log.warning("Tipp-Felder nicht gefunden für: %s", team_name)
                    continue

                tipp_inputs[0].clear()
                tipp_inputs[1].clear()
                tipp_inputs[0].send_keys(prediction.home_score)
                tipp_inputs[1].send_keys(prediction.away_score)
                tipps_eingetragen += 1
                time.sleep(0.3)

            except NoSuchElementException:
                continue

        log.info("%d / %d Tipps eingetragen.", tipps_eingetragen, len(predictions))

        # ── Absenden ─────────────────────────────────────────────────────────
        try:
            submit_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, 'button[name="submitbutton"][type="submit"]')
                )
            )
            submit_button.click()
            time.sleep(3)
            log.info("Tipps erfolgreich abgesendet!")
            return True

        except TimeoutException:
            log.error("Submit-Button nicht gefunden – Tipps nicht gespeichert.")
            return False

    except TimeoutException:
        log.error("Timeout beim Laden der Kicktipp-Seite.")
        return False
    except Exception as e:
        log.error("Unbekannter Fehler: %s", e)
        return False
    finally:
        driver.quit()


# ─── Einstiegspunkt ──────────────────────────────────────────────────────────────

def main():
    """Hauptfunktion: Vorhersagen laden und bei Kicktipp eintragen."""
    log.info("═" * 50)
    log.info("BL-Tipp gestartet")
    log.info("═" * 50)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            predictions, spieltag_nr = fetch_predictions()

            if not predictions:
                log.error("Keine Vorhersagen erhalten – Abbruch.")
                sys.exit(1)

            success = submit_to_kicktipp(predictions, spieltag_nr)

            if success:
                log.info("═" * 50)
                log.info("Fertig – alle Tipps gespeichert!")
                log.info("═" * 50)
                sys.exit(0)
            else:
                log.error("Tipps konnten nicht eingetragen werden.")
                if attempt < MAX_RETRIES:
                    log.info(
                        "Neuer Versuch in %d Sekunden … (%d/%d)",
                        RETRY_DELAY_SECONDS, attempt, MAX_RETRIES,
                    )
                    time.sleep(RETRY_DELAY_SECONDS)

        except Exception as e:
            log.error("Unerwarteter Fehler: %s", e)
            if attempt < MAX_RETRIES:
                log.info(
                    "Neuer Versuch in %d Sekunden … (%d/%d)",
                    RETRY_DELAY_SECONDS, attempt, MAX_RETRIES,
                )
                time.sleep(RETRY_DELAY_SECONDS)

    log.error("Alle %d Versuche fehlgeschlagen.", MAX_RETRIES)
    sys.exit(1)


if __name__ == "__main__":
    main()