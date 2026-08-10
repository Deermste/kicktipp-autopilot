"""Gemeinsame Schnittstelle der Kicktipp-Anbindungen.

Es gibt zwei Umsetzungen mit identischem Verhalten:

* `kicktipp_http.KicktippHttp`   — reines HTTP, der Standardweg
* `kicktipp.KicktippBrowser`     — Selenium, Rückfallebene hinter `--browser`

Beide werten dieselben Seiten mit demselben Parser aus; sie unterscheiden sich
nur darin, wie sie die Seiten holen und den Tipp absenden. Dass zwei
unabhängige Wege dasselbe Ergebnis liefern müssen, ist zugleich das beste
Prüfmittel gegen stille Lesefehler.
"""

from __future__ import annotations

from typing import Protocol

from .kicktipp_parse import TippabgabePage


class TippTarget(Protocol):
    """Anmelden, Spiele lesen, Tipps absenden."""

    name: str

    def login(self) -> None:
        """Meldet sich an. Wirft SubmissionError bei falschen Zugangsdaten."""
        ...

    def list_groups(self) -> list[str]:
        """Die Tippgruppen des angemeldeten Kontos."""
        ...

    def load_page(
        self, group: str, matchday: int | None = None, require_fixtures: bool = True
    ) -> TippabgabePage:
        """Lädt die Tippabgabe-Seite; ohne Angabe den aktuellen Spieltag.

        `matchday` ist der `spieltagIndex` der Gruppe, nicht die angezeigte
        Spieltagnummer — in Gruppen mit mehreren Wettbewerben zählt der Index
        über alle hinweg durch.

        `require_fixtures=False` erlaubt das Lesen einer Seite ohne offene
        Tippabgabe. Das wird zum Auflisten der Spieltage gebraucht: Gerade
        dann, wenn gerade nichts tippbar ist, will man ja nachsehen können.
        """
        ...

    def submit(
        self, page: TippabgabePage, changes: dict[str, tuple[int, int]]
    ) -> TippabgabePage:
        """Sendet die Änderungen ab und liefert den neu gelesenen Zustand."""
        ...
