"""Vorhersagen von predicd.com — ohne Browser.

Die Seite ist vollständig server-seitig gerendert; ein einfacher HTTP-Abruf
genügt. Das spart gegenüber der früheren Selenium-Lösung rund zehn Sekunden pro
Lauf, macht den Parser offline testbar und beseitigt die Abhängigkeit von
Chrome und ChromeDriver.

Aufbau der Seite (verifiziert am 09.08.2026):
Die Fixtures stehen in einem Bootstrap-Karussell mit drei Folien. Genau eine
Folie trägt die Klasse "active" und entspricht dem Spieltag, der in
`#matchdayNumber` als Text steht ("1. Spieltag"). Die weiteren Folien sind die
darauffolgenden Spieltage. Ohne dieses Scoping bekäme man alle 27 Spiele aus
drei Spieltagen in einem Topf — genau die Falle, in die das Altskript lief.
"""

from __future__ import annotations

import base64
import logging
import re
from dataclasses import replace

import httpx
from bs4 import BeautifulSoup, Tag

from ..config import LeagueRef
from ..errors import PredictionError
from ..models import Prediction, dedupe_predictions
from ..selectors import Predicd as S

log = logging.getLogger(__name__)

BASE_URL = "https://www.predicd.com/de/football/league/{league_id}/"

# Ohne gesetzten User-Agent antwortet die Seite nicht zuverlässig.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/151.0 Safari/537.36"
    )
}

_KICKOFF_RE = re.compile(r"\d{1,2}\.\d{1,2}\.\s*\d{1,2}:\d{2}")


def decode_score(meta_info: str) -> int:
    """Dekodiert einen einzelnen Score aus dem `meta-info`-Attribut.

    predicd verschleiert die Ergebnisse base64-kodiert in UTF-16-BE. Der
    Algorithmus stammt aus dem Altskript und ist gegen die Live-Seite
    verifiziert; hier ist er lediglich mit Fehlerbehandlung versehen, damit ein
    Formatwechsel als klarer Fehler auffällt statt als Zufallszahl.
    """
    try:
        decoded = base64.b64decode(meta_info).decode("utf-16-be")
        code_points = "".join(str(ord(ch)) for ch in decoded)
        return int((int(code_points[-4:]) - 1760) / 256)
    except Exception as exc:  # bewusst breit: alles hier ist ein Formatbruch
        raise PredictionError(
            f"Score konnte nicht dekodiert werden (meta-info={meta_info!r}). "
            "Vermutlich hat predicd das Format geändert."
        ) from exc


def parse_matchday_label(text: str) -> int | None:
    """'1. Spieltag' -> 1"""
    match = re.search(r"\d+", text or "")
    return int(match.group()) if match else None


def _parse_row(row: Tag, matchday: int | None) -> Prediction | None:
    """Wandelt eine Tabellenzeile in eine Prediction um.

    Gibt None zurück, wenn die Zeile keine auswertbare Paarung enthält
    (z. B. Zwischenüberschriften).
    """
    teams = [t.get_text(strip=True) for t in row.select(S.TEAM_NAME)]
    teams = [t for t in teams if t]
    if len(teams) < 2:
        return None

    metas = [
        el.get(S.SCORE_ATTR)
        for el in row.select(S.SCORE_META)
        if el.get(S.SCORE_ATTR)
    ]
    if len(metas) < 2:
        log.warning("Kein Ergebnis gefunden für %s vs %s", teams[0], teams[1])
        return None

    kickoff_match = _KICKOFF_RE.search(row.get_text(" ", strip=True))

    return Prediction(
        home_team=teams[0],
        away_team=teams[1],
        home_score=decode_score(str(metas[0])),
        away_score=decode_score(str(metas[1])),
        matchday=matchday,
        kickoff=kickoff_match.group().replace("  ", " ") if kickoff_match else None,
    )


def parse_slides(html: str) -> tuple[list[list[Prediction]], int]:
    """Parst eine predicd-Ligaseite folienweise.

    Returns:
        (Folien, Index der aktiven Folie). Jede Folie ist ein Spieltag bzw. eine
        Runde. Die Folie ist die verlässlichere Einheit als die Spieltagnummer:
        Bei K.-o.-Wettbewerben (Champions League, Pokal) fehlt die Nummer, das
        Karussell gibt es aber trotzdem.
    """
    soup = BeautifulSoup(html, "html.parser")

    label = soup.select_one(S.MATCHDAY_LABEL)
    base_matchday = parse_matchday_label(label.get_text()) if label else None

    items = soup.select(S.CAROUSEL_ITEMS)
    if not items:
        raise PredictionError(
            "Keine Spieltag-Folien gefunden. Das Layout von predicd hat sich "
            "vermutlich geändert (Selektor: "
            f"{S.CAROUSEL_ITEMS!r} in kicktipp_autopilot/selectors.py)."
        )

    active_index = next(
        (i for i, item in enumerate(items) if S.ACTIVE_CLASS in item.get("class", [])),
        0,
    )

    slides: list[list[Prediction]] = []
    for index, item in enumerate(items):
        matchday = (
            base_matchday + (index - active_index) if base_matchday is not None else None
        )
        slide = [
            prediction
            for row in item.select(S.MATCH_ROW)
            if (prediction := _parse_row(row, matchday)) is not None
        ]
        slides.append(slide)

    if not any(slides):
        raise PredictionError(
            "Seite geladen, aber keine einzige Paarung erkannt. "
            "Selektoren in kicktipp_autopilot/selectors.py prüfen."
        )

    return slides, active_index


def parse(html: str) -> list[Prediction]:
    """Alle Vorhersagen der Seite, über alle Folien hinweg."""
    slides, _ = parse_slides(html)
    return [prediction for slide in slides for prediction in slide]


class PredicdSource:
    """Vorhersagequelle predicd.com."""

    name = "predicd"

    def __init__(self, timeout: float = 20.0) -> None:
        self._timeout = timeout
        #  Abgerufene Seiten je Liga-ID. Sobald mehrere Gruppen in einem Lauf
        #  drankommen, tippen mehrere davon dieselbe Liga — ohne den Cache wäre
        #  das jedes Mal derselbe Abruf. Die Lebensdauer ist die der Instanz,
        #  also ein Programmlauf; über Läufe hinweg wird nichts aufgehoben.
        self._html_cache: dict[int, str] = {}
        #  Dasselbe eine Ebene höher: das fertig ausgewertete Fenster je Liga.
        self._window_cache: dict[str, list[Prediction]] = {}

    def fetch_html(self, league_id: int) -> str:
        if league_id in self._html_cache:
            log.debug("Liga %d bereits geladen — Abruf übersprungen.", league_id)
            return self._html_cache[league_id]

        url = BASE_URL.format(league_id=league_id)
        log.info("Lade Vorhersagen von %s", url)
        try:
            response = httpx.get(
                url, headers=_HEADERS, timeout=self._timeout, follow_redirects=True
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise PredictionError(f"predicd nicht erreichbar: {exc}") from exc

        self._html_cache[league_id] = response.text
        return response.text

    def get_predictions(
        self, league_id: int, matchday: int | None = None
    ) -> list[Prediction]:
        slides, active_index = parse_slides(self.fetch_html(league_id))

        if matchday is None:
            # Ohne Vorgabe gilt die aktive Folie. Bewusst nicht "alle Spiele":
            # bei fehlender Spieltagnummer (K.-o.-Runden) wären das sonst auch
            # längst gespielte Begegnungen.
            selected = slides[active_index]
            label = selected[0].matchday if selected else None
            if label is None:
                log.warning(
                    "Kein Spieltag-Label gefunden (bei K.-o.-Wettbewerben normal) — "
                    "verwende die aktuell angezeigte Runde mit %d Spielen.",
                    len(selected),
                )
            else:
                log.info("Spieltag %s: %d Vorhersagen geladen.", label, len(selected))
            return selected

        available = sorted({p.matchday for slide in slides for p in slide if p.matchday})
        selected = [p for slide in slides for p in slide if p.matchday == matchday]
        if not selected:
            raise PredictionError(
                f"Für Spieltag {matchday} liegen keine Vorhersagen vor. "
                f"Verfügbar sind: {', '.join(map(str, available)) or 'keine'}. "
                "predicd zeigt immer nur wenige Spieltage rund um den aktuellen."
            )

        log.info("Spieltag %s: %d Vorhersagen geladen.", matchday, len(selected))
        return selected

    def get_window(self, league: LeagueRef) -> list[Prediction]:
        """Alle Runden, die die Ligaseite gerade hergibt — mit Liga-Herkunft.

        Für den Abgleich mit Kicktipp ist das der verlässlichere Weg als eine
        einzelne Folie: Kicktipps Spieltagzählung ist die der *Gruppe* und
        deckt sich mit keiner Liga. Welche Vorhersage zu welchem Spiel gehört,
        entscheidet ohnehin die Paarung — ein größeres Fenster erhöht nur die
        Trefferwahrscheinlichkeit, nicht das Risiko.

        Ein zusätzlicher Abruf entsteht dabei nicht: Die Folien stehen alle in
        derselben Antwort. Auch das Auswerten passiert nur einmal je Liga —
        über mehrere Gruppen hinweg ist dieselbe Liga der Normalfall.
        """
        if league.slug in self._window_cache:
            return list(self._window_cache[league.slug])

        slides, _ = parse_slides(self.fetch_html(league.predicd_id))
        window = dedupe_predictions(
            [
                replace(prediction, league=league.slug)
                for slide in slides
                for prediction in slide
            ]
        )
        log.info(
            "%s: %d Vorhersagen aus %d Runden geladen.",
            league.slug, len(window), len(slides),
        )
        self._window_cache[league.slug] = window
        return list(window)
