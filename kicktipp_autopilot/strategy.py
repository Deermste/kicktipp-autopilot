"""Tippstrategien — was aus einer predicd-Vorhersage tatsächlich getippt wird.

predicd liefert das *wahrscheinlichste* Ergebnis. Für Kicktipp ist das nicht
dasselbe wie das Ergebnis mit den meisten erwarteten Punkten. Die Strategien
hier setzen auf der Vorhersage auf und nutzen dafür die Wettquoten, die
Kicktipp neben jedem Spiel zeigt.

Beide sind abgeleitet aus einem Rückblick auf 396 Spiele (Bundesliga 25/26
komplett, BL und CL 26/27 bis zum 6. bzw. 2. Spieltag):

``faustregel`` — die Tendenz bleibt, nur das Ergebnis wird ersetzt:
    Sieg eines klaren Favoriten (≥ 65 %) → 3:0, jeder andere Sieg → 2:1,
    Remis → 1:1. Vor allem verschwindet damit 2:0, das in fast jeder
    Favoritenklasse schlechter abschnitt als 2:1. Im Rückblick +0,9 bis
    +1,0 Punkte je zehn Spiele, in beiden Wertungsarten.

``favorit`` — weicht predicds Tendenz vom Favoriten der Buchmacher ab,
    wird der Favorit getippt. Betrifft etwa jedes achte Spiel und hebt die
    Trefferquote leicht; der Punkteeffekt war bisher nicht eindeutig.

Ohne Quoten bleibt der predicd-Tipp unverändert. Geraten wird nie.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import ConfigError
from .models import Prediction

FAUSTREGEL = "faustregel"
FAVORIT = "favorit"
KEINE = "keine"

#  Reihenfolge = Anwendungsreihenfolge: erst die Tendenz, dann das Ergebnis.
STRATEGIES = (FAVORIT, FAUSTREGEL)

#  Ab dieser Siegwahrscheinlichkeit gilt ein Team als klarer Favorit.
STRONG_FAVORITE = 0.65

_STANDARD_SCORE = {1: (2, 1), 0: (1, 1), -1: (1, 2)}


@dataclass(frozen=True)
class Tip:
    """Was eingetragen wird — und warum es vom predicd-Tipp abweicht."""

    home_score: int
    away_score: int
    #  None, wenn der predicd-Tipp unverändert bleibt
    reason: str | None = None

    @property
    def score(self) -> tuple[int, int]:
        return self.home_score, self.away_score


def parse_strategies(values: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    """Liest Strategienamen aus config.toml oder `--strategie`.

    Kommalisten sind erlaubt. "keine" schaltet alles ab — nötig, um eine in
    der config.toml gesetzte Strategie für einen Lauf zu übergehen.
    """
    chosen: set[str] = set()
    for value in values or ():
        for part in str(value).split(","):
            name = part.strip().casefold()
            if not name:
                continue
            if name == KEINE:
                return ()
            if name not in STRATEGIES:
                raise ConfigError(
                    f"Unbekannte Strategie {part.strip()!r}. "
                    f"Möglich: {', '.join(STRATEGIES)} oder {KEINE}."
                )
            chosen.add(name)
    return tuple(name for name in STRATEGIES if name in chosen)


def probabilities(odds: tuple[float, float, float]) -> tuple[float, float, float]:
    """Quoten → Wahrscheinlichkeiten (Heim, Remis, Gast) ohne Buchmachermarge.

    Die Marge wird proportional herausgerechnet: Die Kehrwerte der Quoten
    summieren sich auf etwas über 1, geteilt durch diese Summe ergeben sie 1.
    """
    inverse = [1 / value for value in odds]
    total = sum(inverse)
    return inverse[0] / total, inverse[1] / total, inverse[2] / total


def _tendency(home: int, away: int) -> int:
    return (home > away) - (home < away)


def _label(tendency: int) -> str:
    return {1: "Heimsieg", 0: "Remis", -1: "Auswärtssieg"}[tendency]


def apply(
    prediction: Prediction,
    odds: tuple[float, float, float] | None,
    strategies: tuple[str, ...],
) -> Tip:
    """Der Tipp für ein Spiel nach den gewählten Strategien."""
    original = (prediction.home_score, prediction.away_score)
    if not strategies:
        return Tip(*original)
    if odds is None:
        return Tip(*original, reason="keine Quoten — predicd-Tipp bleibt")

    p_home, _, p_away = probabilities(odds)
    favorite = 1 if p_home >= p_away else -1
    tendency = _tendency(*original)
    score = original
    reasons: list[str] = []

    if FAVORIT in strategies and tendency != favorite:
        tendency = favorite
        p_favorite = p_home if favorite == 1 else p_away
        reasons.append(f"Favorit ({p_favorite:.0%}) statt {_label(_tendency(*original))}")
        # Die neue Tendenz braucht ein Ergebnis; die Faustregel verfeinert es
        # gleich darauf, ohne sie gilt das Standardergebnis.
        score = _STANDARD_SCORE[tendency]

    if FAUSTREGEL in strategies:
        if tendency == 0:
            score = (1, 1)
        else:
            p_winner = p_home if tendency == 1 else p_away
            margin = (3, 0) if p_winner >= STRONG_FAVORITE else (2, 1)
            score = margin if tendency == 1 else (margin[1], margin[0])
        if score != original and not reasons:
            reasons.append("Faustregel")

    if score == original:
        return Tip(*original)
    return Tip(*score, reason=", ".join(reasons))
