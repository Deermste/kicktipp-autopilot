"""Kicktipp über reines HTTP — der Standardweg.

Kicktipp ist eine klassische serverseitig gerenderte Anwendung: Der Login ist
ein Form-POST, die Sitzung hängt an einem Cookie, und die Tippabgabe ist ein
gewöhnliches Formular. Ein Browser wird dafür nicht gebraucht.

Gegenüber dem Selenium-Weg entfallen damit: Chrome als Abhängigkeit, rund
zwanzig Sekunden Laufzeit und das Cookie-Banner, das sich als Overlay über den
Absende-Button legt.

Verifiziert am 09.08.2026:
    POST /info/profil/loginaction   Felder: kennung, passwort  (kein CSRF-Token)
    GET  /<gruppe>/tippabgabe       302 auf die Login-Seite, wenn nicht angemeldet
    GET  /<gruppe>/tippabgabe?tippsaisonId=<id>&spieltagIndex=<n>   gezielter Spieltag
"""

from __future__ import annotations

import logging
from urllib.parse import urljoin

import httpx

from ..config import Credentials
from ..errors import SubmissionError
from .kicktipp_parse import TippabgabePage, build_submit_body, parse_groups, parse_page

log = logging.getLogger(__name__)

BASE_URL = "https://www.kicktipp.de"
LOGIN_PATH = "/info/profil/loginaction"
GROUPS_PATH = "/info/profil/meinetipprunden"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/151.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9",
}


class KicktippHttp:
    """Anmelden, lesen und tippen über HTTP."""

    name = "http"

    def __init__(self, credentials: Credentials, timeout: float = 20.0) -> None:
        self._credentials = credentials
        self._timeout = timeout
        self._client: httpx.Client | None = None

    # ── Lebenszyklus ────────────────────────────────────────────────────

    def __enter__(self) -> KicktippHttp:
        self._client = httpx.Client(
            base_url=BASE_URL,
            headers=_HEADERS,
            timeout=self._timeout,
            follow_redirects=True,
        )
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            raise SubmissionError(
                "HTTP-Sitzung nicht gestartet — KicktippHttp als Kontextmanager verwenden."
            )
        return self._client

    # ── Anmeldung ───────────────────────────────────────────────────────

    def login(self) -> None:
        try:
            self.client.post(
                LOGIN_PATH,
                data={
                    "kennung": self._credentials.email,
                    "passwort": self._credentials.password,
                    "submitbutton": "",
                },
            )
        except httpx.HTTPError as exc:
            raise SubmissionError(f"Kicktipp nicht erreichbar: {exc}") from exc

        if not self.is_logged_in():
            raise SubmissionError(
                "Anmeldung fehlgeschlagen — E-Mail oder Passwort in der .env prüfen."
            )
        log.info("Bei Kicktipp angemeldet.")

    def is_logged_in(self) -> bool:
        """Geschützte Seite ohne Weiterleitung erreichbar?

        Ohne gültige Sitzung antwortet Kicktipp mit 302 auf die Login-Seite.
        """
        response = self.client.get(GROUPS_PATH, follow_redirects=False)
        return response.status_code == 200

    # ── Lesen ───────────────────────────────────────────────────────────

    def list_groups(self) -> list[str]:
        response = self.client.get(GROUPS_PATH)
        groups = parse_groups(response.text, BASE_URL)
        log.info("%d Tippgruppe(n) gefunden: %s", len(groups), ", ".join(groups) or "—")
        return groups

    def load_page(
        self, group: str, matchday: int | None = None, require_fixtures: bool = True
    ) -> TippabgabePage:
        """Lädt einen Spieltag. `matchday` ist der `spieltagIndex` der Gruppe.

        Das ist **nicht** zwangsläufig die angezeigte Spieltagnummer: In einer
        Gruppe mit mehreren Wettbewerben zählt der Index über alle hinweg
        durch, dort trägt Index 25 den Titel "8. Spieltag - CL". Verglichen
        wird deshalb gegen das Formularfeld `spieltagIndex`, nicht gegen die
        Nummer aus der Überschrift. `--list-matchdays` zeigt die Zuordnung.
        """
        page = self._get_page(f"/{group}/tippabgabe")

        if matchday is not None and page.form_fields.get("spieltagIndex") != str(matchday):
            # Der gewünschte Spieltag ist über Parameter erreichbar; dafür wird
            # die Saison-ID aus dem gerade gelesenen Formular gebraucht.
            season_id = page.form_fields.get("tippsaisonId")
            if not season_id:
                raise SubmissionError(
                    f"Spieltag {matchday} kann nicht angesteuert werden: "
                    "tippsaisonId fehlt im Formular."
                )
            page = self._get_page(
                f"/{group}/tippabgabe",
                params={"tippsaisonId": season_id, "spieltagIndex": matchday},
            )

        if require_fixtures and not page.fixtures:
            raise SubmissionError(
                f"Keine Spiele in Gruppe {group!r} gefunden. Existiert die Gruppe, "
                "und ist ein Spieltag zur Tippabgabe offen?"
            )

        log.info("%d Spiele auf der Tippabgabe-Seite gelesen.", len(page.fixtures))
        return page

    def _get_page(self, path: str, params: dict | None = None) -> TippabgabePage:
        try:
            response = self.client.get(path, params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SubmissionError(f"Seite {path} nicht abrufbar: {exc}") from exc

        if "loginformular" in response.text.lower() or "/profil/login" in str(response.url):
            raise SubmissionError(
                "Sitzung abgelaufen — Kicktipp hat auf die Login-Seite umgeleitet."
            )
        return parse_page(response.text)

    # ── Schreiben ───────────────────────────────────────────────────────

    def submit(
        self, page: TippabgabePage, changes: dict[str, tuple[int, int]]
    ) -> TippabgabePage:
        """Sendet das vollständige Formular ab und liest den Stand neu ein.

        Der Rumpf enthält *alle* Felder der Seite — auch unveränderte Tipps und
        die Sonderfragen. Kicktipp wertet das Formular als Ganzes aus: Ein
        fehlendes Feld gilt als geleert.
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

        body = build_submit_body(page, changes)
        url = urljoin(BASE_URL, page.action)

        try:
            response = self.client.post(url, data=body)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SubmissionError(
                f"Absenden fehlgeschlagen: {exc} — Tipps wurden NICHT gespeichert."
            ) from exc

        log.info("Tipps abgesendet.")
        return parse_page(response.text)
