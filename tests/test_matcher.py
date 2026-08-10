"""Tests der Zuordnung Vorhersage → Kicktipp-Spiel."""

import pytest

from kicktipp_autopilot.matching.matcher import TeamMatcher, load_aliases
from kicktipp_autopilot.models import Fixture, Prediction


def prediction(home: str, away: str, tipp: tuple[int, int] = (2, 1)) -> Prediction:
    return Prediction(
        home_team=home, away_team=away, home_score=tipp[0], away_score=tipp[1], matchday=1
    )


class TestExakteZuordnung:
    def test_identische_namen(self) -> None:
        fixtures = [Fixture("FC Bayern München", "VfB Stuttgart")]
        vorhersagen = [prediction("FC Bayern München", "VfB Stuttgart", (3, 1))]

        bericht = TeamMatcher().match(fixtures, vorhersagen)

        assert len(bericht.matched) == 1
        assert bericht.matched[0].prediction.home_score == 3
        assert not bericht.unmatched_fixtures

    def test_ueber_normalisierung(self) -> None:
        """'TSG Hoffenheim' (predicd) trifft '1899 Hoffenheim' (Kicktipp)."""
        fixtures = [Fixture("1899 Hoffenheim", "Bayer 04 Leverkusen")]
        vorhersagen = [prediction("TSG Hoffenheim", "Bayer Leverkusen")]

        bericht = TeamMatcher().match(fixtures, vorhersagen)

        assert len(bericht.matched) == 1
        assert bericht.matched[0].method == "exact"

    def test_ueber_alias(self) -> None:
        """M'Gladbach löst die Normalisierung nicht — dafür gibt es den Alias."""
        aliases = load_aliases("bundesliga")
        fixtures = [Fixture("Bor. Mönchengladbach", "SV 07 Elversberg")]
        vorhersagen = [prediction("Borussia M'Gladbach", "SV Elversberg")]

        bericht = TeamMatcher(aliases).match(fixtures, vorhersagen)

        assert len(bericht.matched) == 1
        assert not bericht.unmatched_fixtures


class TestReihenfolgeUndPaarung:
    def test_zuordnung_ist_unabhaengig_von_der_reihenfolge(self) -> None:
        fixtures = [
            Fixture("SC Freiburg", "Werder Bremen"),
            Fixture("FC Bayern München", "VfB Stuttgart"),
        ]
        vorhersagen = [
            prediction("FC Bayern München", "VfB Stuttgart", (3, 1)),
            prediction("SC Freiburg", "Werder Bremen", (2, 1)),
        ]

        bericht = TeamMatcher().match(fixtures, vorhersagen)

        zuordnung = {m.fixture.home_team: m.prediction for m in bericht.matched}
        assert zuordnung["FC Bayern München"].home_score == 3
        assert zuordnung["SC Freiburg"].home_score == 2

    def test_heimrecht_wird_beachtet(self) -> None:
        """Ein vertauschtes Heimrecht ist ein anderes Spiel und darf nicht greifen."""
        fixtures = [Fixture("VfB Stuttgart", "FC Bayern München")]
        vorhersagen = [prediction("FC Bayern München", "VfB Stuttgart", (3, 1))]

        bericht = TeamMatcher().match(fixtures, vorhersagen)

        assert not bericht.matched
        assert len(bericht.unmatched_fixtures) == 1


class TestNichtRaten:
    """Der Matcher soll im Zweifel melden statt zu raten."""

    def test_voellig_unbekanntes_team(self) -> None:
        fixtures = [Fixture("Irgendein FC", "Anderer SV")]
        vorhersagen = [prediction("FC Bayern München", "VfB Stuttgart")]

        bericht = TeamMatcher().match(fixtures, vorhersagen)

        assert not bericht.matched
        assert bericht.unmatched_fixtures[0].home_team == "Irgendein FC"
        assert len(bericht.unused_predictions) == 1

    def test_teiltreffer_laesst_rest_durch(self) -> None:
        """Ein unbekanntes Spiel darf die übrigen nicht blockieren."""
        fixtures = [
            Fixture("FC Bayern München", "VfB Stuttgart"),
            Fixture("Unbekannt A", "Unbekannt B"),
        ]
        vorhersagen = [prediction("FC Bayern München", "VfB Stuttgart", (3, 1))]

        bericht = TeamMatcher().match(fixtures, vorhersagen)

        assert len(bericht.matched) == 1
        assert len(bericht.unmatched_fixtures) == 1

    def test_nur_ein_team_passt_reicht_nicht(self) -> None:
        fixtures = [Fixture("FC Bayern München", "Hansa Rostock")]
        vorhersagen = [prediction("FC Bayern München", "VfB Stuttgart")]

        bericht = TeamMatcher().match(fixtures, vorhersagen)

        assert not bericht.matched

    def test_keine_vorhersagen(self) -> None:
        bericht = TeamMatcher().match([Fixture("A", "B")], [])
        assert bericht.is_empty
        assert len(bericht.unmatched_fixtures) == 1


class TestUnscharfeZuordnung:
    def test_kleiner_schreibfehler_wird_erkannt(self) -> None:
        fixtures = [Fixture("Borussia Dortmond", "Hamburger SV")]  # Tippfehler
        vorhersagen = [prediction("Borussia Dortmund", "Hamburger SV", (2, 0))]

        bericht = TeamMatcher().match(fixtures, vorhersagen)

        assert len(bericht.matched) == 1
        assert bericht.matched[0].method == "fuzzy"
        assert bericht.matched[0].confidence >= 0.85

    def test_zu_unaehnlich_wird_verworfen(self) -> None:
        fixtures = [Fixture("Hansa Rostock", "Dynamo Dresden")]
        vorhersagen = [prediction("Borussia Dortmund", "Hamburger SV")]

        bericht = TeamMatcher().match(fixtures, vorhersagen)

        assert not bericht.matched

    def test_mehrdeutigkeit_wird_verworfen(self) -> None:
        """Zwei gleich gute Kandidaten -> keine Zuordnung."""
        fixtures = [Fixture("FC Muster", "SV Beispiel")]
        vorhersagen = [
            prediction("FC Musterx", "SV Beispielx"),
            prediction("FC Mustery", "SV Beispiely"),
        ]

        bericht = TeamMatcher().match(fixtures, vorhersagen)

        assert not bericht.matched


class TestAliasDatei:
    def test_kommentarfelder_werden_ignoriert(self) -> None:
        aliases = load_aliases("bundesliga")
        assert not any(key.startswith("_") for key in aliases)

    def test_unbekannte_liga_ist_kein_fehler(self) -> None:
        assert load_aliases("gibt-es-nicht") == {}


class TestMehrereLigen:
    """Verhalten, sobald Vorhersagen aus mehreren Wettbewerben in einem Topf sind."""

    def test_aliasse_mehrerer_ligen_werden_zusammengefuehrt(self) -> None:
        einzeln = load_aliases("bundesliga")
        zusammen = load_aliases(["bundesliga", "champions-league"])

        assert einzeln.items() <= zusammen.items()

    def test_unbekannte_liga_liefert_leere_tabelle(self) -> None:
        assert load_aliases(["gibt-es-nicht"]) == {}

    def test_widerspruechlicher_alias_wird_gemeldet(self, tmp_path, monkeypatch, caplog) -> None:
        import json

        for slug, ziel in [("liga-a", "Ziel A"), ("liga-b", "Ziel B")]:
            (tmp_path / f"{slug}.json").write_text(
                json.dumps({"Verein": ziel}), encoding="utf-8"
            )
        monkeypatch.setattr("kicktipp_autopilot.matching.matcher.ALIAS_DIR", tmp_path)

        with caplog.at_level("WARNING"):
            tabelle = load_aliases(["liga-a", "liga-b"])

        assert tabelle["Verein"] == "Ziel A"  # der zuerst geladene gilt
        assert "Widersprüchlicher Alias" in caplog.text

    def test_gleiche_paarung_in_zwei_ligen_wird_nicht_geraten(self) -> None:
        """Der Kern der Absicherung: Bayern gegen Dortmund gibt es doppelt.

        Vor der Umstellung überschrieben sich die beiden Vorhersagen im Index
        stillschweigend — die zuletzt geladene hätte den Tipp bestimmt.
        """
        fixtures = [Fixture("FC Bayern München", "Borussia Dortmund", tip_id="1")]
        vorhersagen = [
            Prediction("FC Bayern München", "Borussia Dortmund", 2, 1, league="bundesliga"),
            Prediction("FC Bayern München", "Borussia Dortmund", 0, 3, league="dfb-pokal"),
        ]

        bericht = TeamMatcher().match(fixtures, vorhersagen)

        assert not bericht.matched
        assert len(bericht.ambiguous) == 1
        assert bericht.has_gaps
        fixture, kandidaten = bericht.ambiguous[0]
        assert {p.league for p in kandidaten} == {"bundesliga", "dfb-pokal"}

    def test_anstosszeit_entscheidet_bei_gleicher_paarung(self) -> None:
        fixtures = [
            Fixture(
                "FC Bayern München", "Borussia Dortmund",
                tip_id="1", kickoff="29.01.25 20:55",
            )
        ]
        vorhersagen = [
            Prediction(
                "FC Bayern München", "Borussia Dortmund", 2, 1,
                kickoff="14.09. 18:30", league="bundesliga",
            ),
            Prediction(
                "FC Bayern München", "Borussia Dortmund", 0, 3,
                kickoff="29.01. 21:00", league="champions-league",
            ),
        ]

        bericht = TeamMatcher().match(fixtures, vorhersagen)

        assert not bericht.ambiguous
        assert len(bericht.matched) == 1
        treffer = bericht.matched[0].prediction
        assert treffer.league == "champions-league"
        assert (treffer.home_score, treffer.away_score) == (0, 3)

    def test_identische_doppelung_ist_keine_mehrdeutigkeit(self) -> None:
        """predicd liefert bei K.-o.-Runden denselben Spielplan zweimal aus."""
        fixtures = [Fixture("Sparta Prag", "Olympique Lyon", tip_id="1")]
        eine = Prediction(
            "Sparta Prag", "Olympique Lyon", 1, 2,
            kickoff="04.08. 18:00", league="champions-league",
        )

        bericht = TeamMatcher().match(fixtures, [eine, eine])

        assert len(bericht.matched) == 1
        assert not bericht.ambiguous

    def test_vorhersagen_der_anderen_liga_stoeren_nicht(self) -> None:
        fixtures = [Fixture("FC Bayern München", "VfB Stuttgart", tip_id="1")]
        vorhersagen = [
            prediction("Sparta Prag", "Olympique Lyon"),
            prediction("FC Bayern München", "VfB Stuttgart", (3, 1)),
            prediction("Celtic Glasgow", "LASK"),
        ]

        bericht = TeamMatcher().match(fixtures, vorhersagen)

        assert len(bericht.matched) == 1
        assert len(bericht.unused_predictions) == 2
        assert not bericht.has_gaps
