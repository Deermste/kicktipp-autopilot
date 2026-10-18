"""Datenmodelle des Autopiloten."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Prediction:
    """Eine Vorhersage von einer Quelle (z. B. predicd).

    Die Teamnamen sind die *Originalnamen der Quelle*, nicht die von Kicktipp.
    Die Übersetzung passiert erst beim Matching.
    """

    home_team: str
    away_team: str
    home_score: int
    away_score: int
    matchday: int | None = None
    kickoff: str | None = None  # z. B. "28.08. 20:30" (predicd liefert kein Jahr)
    # Liga-Slug der Herkunft ("bundesliga", "champions-league", …). Nötig,
    # sobald mehrere Ligen in einem Topf landen: Ohne die Herkunft ließe sich
    # weder die richtige Alias-Datei wählen noch eine doppelte Paarung aus zwei
    # Wettbewerben auseinanderhalten.
    league: str | None = None

    def __str__(self) -> str:
        return (
            f"{self.home_team} vs {self.away_team} "
            f"→ {self.home_score}:{self.away_score}"
        )


@dataclass
class Fixture:
    """Eine Spielzeile auf der Kicktipp-Tippabgabe-Seite.

    `tip_id` ist Kicktipps interne Spiel-ID. Sie taucht in beiden Welten mit
    derselben Zahl auf — als Formularfeld `spieltippForms[<id>].heimTipp` und
    als DOM-Element `spieltippForms_<id>_heimTipp`. Dadurch funktioniert
    dieselbe Zuordnung für den HTTP- wie für den Browserweg.
    """

    home_team: str
    away_team: str
    tip_id: str | None = None
    # Anstoßzeit aus der Terminspalte, z. B. "29.01.25 20:55". Kicktipp zeigt
    # sie nur in der ersten Zeile eines Anstoßblocks; der Parser reicht sie an
    # die Folgezeilen weiter. Dient als Unterscheidungsmerkmal, wenn dieselbe
    # Paarung in zwei Wettbewerben vorkommt.
    kickoff: str | None = None
    # Wettquoten (Heim, Remis, Gast), wie Kicktipp sie neben dem Spiel zeigt.
    # None, solange Kicktipp noch keine anbietet. Grundlage der Tippstrategien
    # in `strategy.py`.
    odds: tuple[float, float, float] | None = None

    def __str__(self) -> str:
        return f"{self.home_team} vs {self.away_team}"

    def field_name(self, side: str) -> str:
        """Formularfeldname, z. B. 'spieltippForms[123].heimTipp'."""
        return f"spieltippForms[{self.tip_id}].{side}"

    def element_id(self, side: str) -> str:
        """DOM-Element-ID, z. B. 'spieltippForms_123_heimTipp'."""
        return f"spieltippForms_{self.tip_id}_{side}"


@dataclass
class MatchResult:
    """Ergebnis der Zuordnung Vorhersage → Kicktipp-Spiel."""

    fixture: Fixture
    prediction: Prediction
    #  "alias" | "exact" | "fuzzy" — wie die Zuordnung zustande kam
    method: str
    confidence: float = 1.0


def dedupe_predictions(predictions: list[Prediction]) -> list[Prediction]:
    """Entfernt buchstäbliche Doppelungen unter Beibehaltung der Reihenfolge.

    Nötig, weil predicd bei K.-o.-Wettbewerben denselben Spielplan in zwei
    Karussellfolien ausliefert (verifiziert am 10.08.2026 an der Champions
    League: zwei Folien, beide `active`, mit identischem Inhalt). Ohne diesen
    Schritt gälte anschließend jede einzelne Paarung als mehrdeutig.

    Verglichen wird der *vollständige* Datensatz. Zwei Einträge mit gleicher
    Paarung, aber abweichendem Ergebnis, bleiben also beide erhalten — sie
    sind ein echter Widerspruch und sollen als solcher auffallen.
    """
    seen: set[tuple[Any, ...]] = set()
    unique: list[Prediction] = []

    for prediction in predictions:
        marker = (
            prediction.home_team, prediction.away_team,
            prediction.home_score, prediction.away_score,
            prediction.matchday, prediction.kickoff, prediction.league,
        )
        if marker in seen:
            continue
        seen.add(marker)
        unique.append(prediction)

    return unique
