"""Regressionstest mit echten Namen beider Seiten — Champions League.

Das Gegenstück zu `test_echte_paarungen.py`, nur für die CL-Ligaphase. Die
Namenspaare stammen aus einem direkten Vergleich der Kicktipp-Tippabgabe mit
der predicd-Ligaseite (1. Spieltag, erfasst am 31.08.2026).

Der 1. Spieltag ist als Prüfmenge bewusst gewählt: In der Ligaphase tritt
jedes der 36 Teams dort genau einmal an, deshalb deckt dieser eine Spieltag
den gesamten Teilnehmerkreis ab.

Drei dieser Paarungen (AEK Athen, OSC Lille, Como) haben die Abgabe am
31.08.2026 blockiert, bis die Aliasse in `aliases/champions-league.json`
standen. Ändert sich dort etwas, muss es hier vorbeikommen.
"""

import pytest

from kicktipp_autopilot.matching.matcher import TeamMatcher, load_aliases
from kicktipp_autopilot.models import Fixture, Prediction

# (Kicktipp-Heim, Kicktipp-Gast, predicd-Heim, predicd-Gast, Tipp)
ECHTE_PAARUNGEN = [
    ("FC Brügge", "Aston Villa", "FC Brügge", "Aston Villa", (1, 1)),
    ("Real Madrid", "Inter Mailand", "Real Madrid", "Inter Mailand", (2, 1)),
    ("FC Porto", "Manchester City", "FC Porto", "Manchester City", (1, 2)),
    ("Borussia Dortmund", "FC Villarreal", "Borussia Dortmund", "FC Villarreal", (2, 1)),
    ("FC Barcelona", "Feyenoord Rotterdam", "FC Barcelona", "Feyenoord Rotterdam", (2, 1)),
    ("VfB Stuttgart", "Viking Stavanger", "VfB Stuttgart", "Viking Stavanger", (2, 0)),
    ("FC Liverpool", "Atletico Madrid", "FC Liverpool", "Atlético Madrid", (2, 1)),
    ("SSC Neapel", "FC Arsenal", "SSC Neapel", "FC Arsenal", (2, 1)),
    (
        "Sporting Lissabon", "Galatasaray Istanbul",
        "Sporting Lissabon", "Galatasaray Istanbul", (2, 1),
    ),
    ("Fenerbahce Istanbul", "AS Rom", "Fenerbahçe Istanbul", "AS Rom", (1, 1)),
    ("FC Bayern München", "FK Bodö/Glimt", "FC Bayern München", "FK Bodø/Glimt", (2, 0)),
    ("Manchester United", "Sabah FK", "Manchester United", "Sabah FK", (3, 1)),
    ("Slavia Prag", "RC Lens", "Slavia Prag", "RC Lens", (2, 1)),
    (
        "Paris St. Germain", "SK Slovan Bratislava",
        "Paris Saint-Germain", "Slovan Bratislava", (2, 0),
    ),
    ("PSV Eindhoven", "Schachtjor Donezk", "PSV Eindhoven", "Schachtar Donezk", (2, 1)),
    ("AEK Athen", "Linzer ASK", "AEK Athen", "LASK", (2, 0)),
    ("OSC Lille", "Real Betis Sevilla", "OSC Lille", "Betis Sevilla", (2, 1)),
    ("Como Calcio", "RB Leipzig", "Como 1907", "RB Leipzig", (2, 1)),
]

# Vereine, die ohne Alias gar nicht bzw. nur unscharf zugeordnet wurden.
BRAUCHEN_ALIAS = {"Linzer ASK", "Real Betis Sevilla", "Como Calcio",
                  "Paris St. Germain", "Schachtjor Donezk"}


@pytest.fixture
def bericht():
    fixtures = [Fixture(kh, ka) for kh, ka, *_ in ECHTE_PAARUNGEN]
    predictions = [
        Prediction(ph, pa, tipp[0], tipp[1], matchday=1)
        for _, _, ph, pa, tipp in ECHTE_PAARUNGEN
    ]
    return TeamMatcher(load_aliases("champions-league")).match(fixtures, predictions)


def test_alle_spiele_werden_zugeordnet(bericht) -> None:
    offen = [str(f) for f in bericht.unmatched_fixtures]
    assert not offen, f"nicht zugeordnet: {offen}"
    assert len(bericht.matched) == len(ECHTE_PAARUNGEN)
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


@pytest.mark.parametrize(
    "kicktipp_name, predicd_name",
    [(kh, ph) for kh, _, ph, _, _ in ECHTE_PAARUNGEN]
    + [(ka, pa) for _, ka, _, pa, _ in ECHTE_PAARUNGEN],
)
def test_jeder_einzelne_name_ist_zuordenbar(kicktipp_name: str, predicd_name: str) -> None:
    """Zeigt bei einem Fehlschlag genau, welcher Verein hakt."""
    matcher = TeamMatcher(load_aliases("champions-league"))
    assert matcher._key(kicktipp_name) == matcher._key(predicd_name)


@pytest.mark.parametrize("kicktipp_name", sorted(BRAUCHEN_ALIAS))
def test_alias_statt_aehnlichkeitssuche(bericht, kicktipp_name: str) -> None:
    """Die fünf Sonderfälle müssen über den Alias laufen, nicht über Fuzzy."""
    match = next(
        m for m in bericht.matched
        if kicktipp_name in (m.fixture.home_team, m.fixture.away_team)
    )
    assert match.method == "alias", str(match.fixture)


def test_gemischte_gruppe_laedt_beide_alias_tabellen() -> None:
    """In Gruppen mit BL und CL dürfen sich die Tabellen nicht in die Quere kommen."""
    beide = load_aliases(["bundesliga", "champions-league"])
    assert beide["LASK"] == "Linzer ASK"
    assert beide["Borussia M'Gladbach"] == "Bor. Mönchengladbach"
