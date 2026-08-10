"""Regressionstest mit echten Namen beider Seiten.

Die Namenspaare stammen aus einem direkten Vergleich der Kicktipp-Tippabgabe
mit der predicd-Ligaseite (Bundesliga, 1. Spieltag, erfasst am 09.08.2026).

Dieser Test ist die Absicherung des heikelsten Teils des Autopiloten: Wenn die
Zuordnung kippt, landen Tipps beim falschen Spiel. Änderungen an
`normalize.py` oder an den Alias-Dateien müssen hier vorbeikommen.
"""

import pytest

from kicktipp_autopilot.matching.matcher import TeamMatcher, load_aliases
from kicktipp_autopilot.models import Fixture, Prediction

# (Kicktipp-Heim, Kicktipp-Gast, predicd-Heim, predicd-Gast, Tipp)
ECHTE_PAARUNGEN = [
    ("FC Bayern München", "VfB Stuttgart", "FC Bayern München", "VfB Stuttgart", (3, 1)),
    ("1. FC Köln", "1899 Hoffenheim", "1. FC Köln", "TSG Hoffenheim", (1, 1)),
    ("SV Elversberg", "Bayer 04 Leverkusen", "SV Elversberg", "Bayer Leverkusen", (1, 2)),
    ("FSV Mainz 05", "SC Paderborn 07", "1. FSV Mainz 05", "SC Paderborn", (2, 1)),
    (
        "1. FC Union Berlin", "Eintracht Frankfurt",
        "1. FC Union Berlin", "Eintracht Frankfurt", (1, 0),
    ),
    ("RB Leipzig", "Bor. Mönchengladbach", "RB Leipzig", "Borussia M'Gladbach", (2, 0)),
    ("Borussia Dortmund", "Hamburger SV", "Borussia Dortmund", "Hamburger SV", (2, 0)),
    ("SC Freiburg", "Werder Bremen", "SC Freiburg", "Werder Bremen", (2, 1)),
    ("FC Augsburg", "FC Schalke 04", "FC Augsburg", "FC Schalke 04", (2, 1)),
]


@pytest.fixture
def bericht():
    fixtures = [Fixture(kh, ka) for kh, ka, *_ in ECHTE_PAARUNGEN]
    predictions = [
        Prediction(ph, pa, tipp[0], tipp[1], matchday=1)
        for _, _, ph, pa, tipp in ECHTE_PAARUNGEN
    ]
    return TeamMatcher(load_aliases("bundesliga")).match(fixtures, predictions)


def test_alle_spiele_werden_zugeordnet(bericht) -> None:
    assert len(bericht.matched) == len(ECHTE_PAARUNGEN)
    assert not bericht.unmatched_fixtures
    assert not bericht.unused_predictions


def test_kein_spiel_beruht_auf_ratenden_treffern(bericht) -> None:
    """Unscharfe Treffer sind bei bekannten Namen ein Warnsignal."""
    unscharf = [m for m in bericht.matched if m.method == "fuzzy"]
    assert not unscharf, f"unscharf zugeordnet: {[str(m.fixture) for m in unscharf]}"


def test_richtiger_tipp_beim_richtigen_spiel(bericht) -> None:
    erwartet = {kh: tipp for kh, _, _, _, tipp in ECHTE_PAARUNGEN}
    for match in bericht.matched:
        tipp = (match.prediction.home_score, match.prediction.away_score)
        assert tipp == erwartet[match.fixture.home_team], str(match.fixture)


def test_moenchengladbach_laeuft_ueber_den_alias(bericht) -> None:
    """Der einzige Fall, den die Normalisierung nicht allein löst."""
    match = next(m for m in bericht.matched if m.fixture.home_team == "RB Leipzig")
    assert match.method == "alias"


@pytest.mark.parametrize(
    "kicktipp_name, predicd_name",
    [(kh, ph) for kh, _, ph, _, _ in ECHTE_PAARUNGEN]
    + [(ka, pa) for _, ka, _, pa, _ in ECHTE_PAARUNGEN],
)
def test_jeder_einzelne_name_ist_zuordenbar(kicktipp_name: str, predicd_name: str) -> None:
    """Zeigt bei einem Fehlschlag genau, welcher Verein hakt."""
    matcher = TeamMatcher(load_aliases("bundesliga"))
    assert matcher._key(kicktipp_name) == matcher._key(predicd_name)
