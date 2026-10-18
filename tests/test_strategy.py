"""Tests der Tippstrategien — von der Quote bis zum abgesendeten Tipp, offline.

Entscheidend ist nicht nur, dass die Regeln rechnen, sondern dass genau das
abgesendet und gegengelesen wird, was die Vorschau zeigt — und dass ohne
Strategie alles beim Alten bleibt.
"""

from dataclasses import replace
from pathlib import Path

import pytest

from kicktipp_autopilot import runner
from kicktipp_autopilot.config import (
    GroupConfig,
    load_group_config,
    resolve_league_ref,
    with_strategies,
)
from kicktipp_autopilot.errors import ConfigError
from kicktipp_autopilot.matching.matcher import TeamMatcher, load_aliases
from kicktipp_autopilot.models import Prediction, dedupe_predictions
from kicktipp_autopilot.sources.predicd import parse_slides
from kicktipp_autopilot.strategy import (
    FAUSTREGEL,
    FAVORIT,
    apply,
    parse_strategies,
    probabilities,
)
from kicktipp_autopilot.targets.kicktipp_parse import parse_fixtures, parse_page

FIXTURES = Path(__file__).parent / "fixtures"
BL = resolve_league_ref("bundesliga")
BEIDE = (FAVORIT, FAUSTREGEL)

#  Quoten (Heim, Remis, Gast)
HEIM_KLAR = (1.32, 6.5, 7.25)   # Heim ≈ 72 %
HEIM_KNAPP = (1.70, 4.0, 4.6)   # Heim ≈ 55 %
GAST_KLAR = (7.25, 6.5, 1.32)   # Gast ≈ 72 %
GAST_KNAPP = (2.8, 3.7, 2.3)    # Gast ≈ 41 %


def _tipp(heim: int, gast: int) -> Prediction:
    return Prediction("Heim", "Gast", heim, gast)


class TestWahrscheinlichkeiten:
    def test_marge_wird_herausgerechnet(self) -> None:
        p = probabilities(HEIM_KLAR)
        assert sum(p) == pytest.approx(1.0)
        assert p[0] == pytest.approx(0.717, abs=0.005)

    def test_faire_quoten_bleiben_unveraendert(self) -> None:
        assert probabilities((2.0, 4.0, 4.0)) == pytest.approx((0.5, 0.25, 0.25))


class TestFaustregel:
    @pytest.mark.parametrize(
        "vorhersage, quoten, erwartet",
        [
            ((2, 0), HEIM_KLAR, (3, 0)),   # klarer Favorit: größere Marge
            ((2, 0), HEIM_KNAPP, (2, 1)),  # 2:0 verschwindet
            ((3, 1), HEIM_KNAPP, (2, 1)),
            ((0, 2), GAST_KLAR, (0, 3)),   # spiegelbildlich für Auswärtssiege
            ((1, 2), GAST_KNAPP, (1, 2)),
            ((2, 2), HEIM_KNAPP, (1, 1)),  # Remis bleibt Remis
            ((1, 0), GAST_KLAR, (2, 1)),   # Tendenz bleibt, auch gegen den Favoriten
        ],
    )
    def test_ergebnis(self, vorhersage, quoten, erwartet) -> None:
        assert apply(_tipp(*vorhersage), quoten, (FAUSTREGEL,)).score == erwartet

    def test_grund_nur_bei_abweichung(self) -> None:
        assert apply(_tipp(2, 0), HEIM_KNAPP, (FAUSTREGEL,)).reason == "Faustregel"
        assert apply(_tipp(2, 1), HEIM_KNAPP, (FAUSTREGEL,)).reason is None


class TestFavorit:
    def test_tendenz_gegen_den_favoriten_wird_gedreht(self) -> None:
        tip = apply(_tipp(2, 1), GAST_KNAPP, (FAVORIT,))
        assert tip.score == (1, 2)
        assert "Favorit (41%)" in tip.reason
        assert "Heimsieg" in tip.reason

    def test_remis_wird_zum_favoritensieg(self) -> None:
        assert apply(_tipp(1, 1), HEIM_KNAPP, (FAVORIT,)).score == (2, 1)

    def test_favoritentipp_bleibt_wie_er_ist(self) -> None:
        tip = apply(_tipp(2, 0), HEIM_KNAPP, (FAVORIT,))
        assert tip.score == (2, 0) and tip.reason is None

    def test_zusammen_mit_faustregel(self) -> None:
        # predicd tippt Heimsieg, Gast ist klarer Favorit → 0:3
        tip = apply(_tipp(2, 1), GAST_KLAR, BEIDE)
        assert tip.score == (0, 3)
        assert tip.reason.startswith("Favorit")

    def test_gleich_starke_teams_gelten_als_heimfavorit(self) -> None:
        assert apply(_tipp(1, 1), (3.0, 3.0, 3.0), (FAVORIT,)).score == (2, 1)


class TestOhneGrundlage:
    def test_ohne_strategie_bleibt_alles(self) -> None:
        tip = apply(_tipp(2, 0), HEIM_KLAR, ())
        assert tip.score == (2, 0) and tip.reason is None

    def test_ohne_quoten_wird_nicht_geraten(self) -> None:
        tip = apply(_tipp(2, 0), None, BEIDE)
        assert tip.score == (2, 0)
        assert "keine Quoten" in tip.reason


class TestNamen:
    def test_kommaliste_und_reihenfolge(self) -> None:
        assert parse_strategies(["faustregel, Favorit"]) == (FAVORIT, FAUSTREGEL)

    def test_keine_schaltet_ab(self) -> None:
        assert parse_strategies(["favorit", "keine"]) == ()

    def test_unbekannt_ist_ein_fehler(self) -> None:
        with pytest.raises(ConfigError, match="Unbekannte Strategie"):
            parse_strategies(["glueck"])


class TestQuotenParser:
    def test_quoten_aus_der_tippabgabe(self) -> None:
        page = parse_page((FIXTURES / "kicktipp_tippabgabe.html").read_text(encoding="utf-8"))
        assert all(f.odds is not None for f in page.fixtures)
        assert page.fixtures[0].odds == (1.32, 6.5, 7.25)

    def test_leere_quotenzelle(self) -> None:
        # So sieht eine gemischte Gruppe aus, bevor Kicktipp Quoten hat.
        html = (
            "<table><tr><td class='nw kicktipp-time'>20.10.26 18:45</td>"
            "<td class='nw'>Fenerbahce Istanbul</td><td class='nw'>Slavia Prag</td>"
            "<td class='kicktipp-tippabgabe'>"
            "<input name='spieltippForms[1].heimTipp' type='text'/>"
            "<input name='spieltippForms[1].gastTipp' type='text'/></td>"
            "<td class='nw quoten'></td></tr></table>"
        )
        (fixture,) = parse_fixtures(html)
        assert fixture.home_team == "Fenerbahce Istanbul"
        assert fixture.odds is None


class TestKonfiguration:
    def test_strategie_aus_config(self, tmp_path) -> None:
        datei = tmp_path / "config.toml"
        datei.write_text(
            '[[gruppen]]\nname = "a"\nligen = ["bundesliga"]\n'
            'strategie = ["faustregel", "favorit"]\n'
            '[[gruppen]]\nname = "b"\nligen = ["bundesliga"]\n',
            encoding="utf-8",
        )
        gruppen = load_group_config(datei)
        assert gruppen["a"].strategies == (FAVORIT, FAUSTREGEL)
        assert gruppen["b"].strategies == ()

    def test_tippfehler_nennt_die_gruppe(self, tmp_path) -> None:
        datei = tmp_path / "config.toml"
        datei.write_text(
            '[[gruppen]]\nname = "a"\nligen = ["bundesliga"]\nstrategie = ["faustreegel"]\n',
            encoding="utf-8",
        )
        with pytest.raises(ConfigError, match="Gruppe 'a'"):
            load_group_config(datei)

    def test_kommandozeile_schlaegt_config(self) -> None:
        runs = [GroupConfig("a", [BL], strategies=BEIDE), GroupConfig("b", [BL])]
        assert with_strategies(runs, None) == runs
        assert [r.strategies for r in with_strategies(runs, ["keine"])] == [(), ()]
        assert [r.strategies for r in with_strategies(runs, ["faustregel"])] == [
            (FAUSTREGEL,), (FAUSTREGEL,)
        ]


# ── Ablauf ──────────────────────────────────────────────────────────────


class _FakeKicktipp:
    name = "fake"

    def __init__(self, page) -> None:
        self.page = page
        self.gesendet: dict[str, tuple[int, int]] = {}

    def load_page(self, group, matchday=None, require_fixtures=True):
        return self.page

    def submit(self, page, changes):
        self.gesendet = dict(changes)
        gespeichert = dict(page.existing_tips)
        for tip_id, (heim, gast) in changes.items():
            gespeichert[tip_id] = (str(heim), str(gast))
        return replace(page, existing_tips=gespeichert)


@pytest.fixture(scope="module")
def bl_seite():
    return parse_page((FIXTURES / "kicktipp_tippabgabe.html").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def vorhersagen() -> list[Prediction]:
    slides, _ = parse_slides((FIXTURES / "predicd_4331.html").read_text(encoding="utf-8"))
    return dedupe_predictions([replace(p, league="bundesliga") for s in slides for p in s])


def _lauf(page, vorhersagen, strategies, odds_seen=None):
    ziel = _FakeKicktipp(page)
    ergebnis = runner.run_one_group(
        ziel, "gruppe", vorhersagen, [BL],
        submit=True, overwrite=True, strategies=strategies, odds_seen=odds_seen,
    )
    return ergebnis, ziel.gesendet


def _erwartet(page, vorhersagen, strategies):
    """Was `apply` je Spiel liefert — unabhängig vom Ablauf berechnet."""
    report = TeamMatcher(load_aliases(["bundesliga"])).match(page.fixtures, vorhersagen)
    quoten = {f.tip_id: f.odds for f in page.fixtures}
    return {
        m.fixture.tip_id: apply(m.prediction, quoten[m.fixture.tip_id], strategies).score
        for m in report.matched
    }


class TestAblauf:
    def test_ohne_strategie_wird_predicd_getippt(self, bl_seite, vorhersagen) -> None:
        ergebnis, gesendet = _lauf(bl_seite, vorhersagen, ())
        assert ergebnis.status == runner.EINGETRAGEN
        assert gesendet == _erwartet(bl_seite, vorhersagen, ())

    def test_strategie_wird_gesendet_und_gegengelesen(self, bl_seite, vorhersagen) -> None:
        ohne = _erwartet(bl_seite, vorhersagen, ())
        mit = _erwartet(bl_seite, vorhersagen, BEIDE)
        assert mit != ohne, "Die Fixture sollte mindestens einen Tipp ändern"

        # Das Gegenlesen vergleicht mit dem angepassten Tipp — sonst schlüge
        # es hier mit SubmissionError fehl.
        ergebnis, gesendet = _lauf(bl_seite, vorhersagen, BEIDE)
        assert ergebnis.status == runner.EINGETRAGEN
        assert gesendet == mit

    def test_quoten_einer_anderen_gruppe_springen_ein(self, bl_seite, vorhersagen) -> None:
        ohne_quoten = replace(
            bl_seite, fixtures=[replace(f, odds=None) for f in bl_seite.fixtures]
        )

        _, ohne_hilfe = _lauf(ohne_quoten, vorhersagen, BEIDE)
        assert ohne_hilfe == _erwartet(bl_seite, vorhersagen, ())

        gesammelt: dict = {}
        _lauf(bl_seite, vorhersagen, (), odds_seen=gesammelt)   # erste Gruppe mit Quoten
        _, mit_hilfe = _lauf(ohne_quoten, vorhersagen, BEIDE, odds_seen=gesammelt)
        assert mit_hilfe == _erwartet(bl_seite, vorhersagen, BEIDE)
