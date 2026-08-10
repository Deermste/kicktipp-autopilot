"""Tests für Gruppen, die mehrere Wettbewerbe tippen — offline.

Grundlage sind zwei echte Abzüge:

* ``kicktipp_cl_tippabgabe.html`` — ein Champions-League-Spieltag aus einer
  Gruppe, die Bundesliga *und* Champions League tippt. Anonymisiert wie die
  Bundesliga-Fixture. Die Saison war beim Abzug bereits beendet, die
  Ergebniszellen enthielten deshalb keine Tippfelder mehr; sie wurden durch
  das Tippfeld-Markup der tippbaren Bundesliga-Seite desselben Kontos ersetzt,
  damit die Zuordnung überhaupt prüfbar ist. Alles Übrige ist unverändert.
* ``predicd_4480.html`` — die predicd-Seite der Champions League. Auf
  Dateigröße gekürzt (Skripte, Stile und die nie ausgewerteten Aufklappzeilen
  entfernt), die Karussell-Struktur ist unangetastet.

Der wichtigste Befund, den diese Tests festhalten: Kicktipp zeigt je Spieltag
**genau einen** Wettbewerb, verrät in den Spielzeilen aber nicht, welchen.
Die Zuordnung muss deshalb allein über die Paarung tragen.
"""

from dataclasses import replace
from pathlib import Path

import pytest

from kicktipp_autopilot.matching.matcher import TeamMatcher, load_aliases
from kicktipp_autopilot.models import Fixture, Prediction, dedupe_predictions
from kicktipp_autopilot.runner import EINGETRAGEN, VORSCHAU
from kicktipp_autopilot.sources.predicd import parse_slides
from kicktipp_autopilot.targets.kicktipp_parse import parse_page

FIXTURES = Path(__file__).parent / "fixtures"
CL_SEITE = FIXTURES / "kicktipp_cl_tippabgabe.html"
BL_SEITE = FIXTURES / "kicktipp_tippabgabe.html"
PREDICD_CL = FIXTURES / "predicd_4480.html"
PREDICD_BL = FIXTURES / "predicd_4331.html"


@pytest.fixture(scope="module")
def cl_seite():
    return parse_page(CL_SEITE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def bl_seite():
    return parse_page(BL_SEITE.read_text(encoding="utf-8"))


def _fenster(datei: Path, slug: str) -> list[Prediction]:
    """Wie `PredicdSource.get_window`, nur aus einer Datei statt aus dem Netz."""
    slides, _ = parse_slides(datei.read_text(encoding="utf-8"))
    return dedupe_predictions(
        [replace(p, league=slug) for slide in slides for p in slide]
    )


@pytest.fixture(scope="module")
def topf() -> list[Prediction]:
    """Der gemischte Vorhersagetopf, so wie ihn ein Lauf zusammenstellt."""
    return _fenster(PREDICD_BL, "bundesliga") + _fenster(PREDICD_CL, "champions-league")


@pytest.fixture(scope="module")
def aliasse() -> dict[str, str]:
    return load_aliases(["bundesliga", "champions-league"])


class TestGemischteGruppeWirdErkannt:
    def test_wettbewerb_steht_im_titel(self, cl_seite) -> None:
        assert cl_seite.title == "8. Spieltag - CL"
        assert cl_seite.competition == "CL"

    def test_reine_gruppe_hat_kein_kuerzel(self, bl_seite) -> None:
        assert bl_seite.title == "1. Spieltag"
        assert bl_seite.competition is None

    def test_spieltagnummer_bleibt_die_angezeigte(self, cl_seite) -> None:
        assert cl_seite.matchday == 8

    def test_index_und_angezeigte_nummer_laufen_auseinander(self, cl_seite) -> None:
        """Der springende Punkt für --matchday.

        Die Seite trägt "8. Spieltag - CL", steckt aber hinter
        ``spieltagIndex=25`` — in einer gemischten Gruppe zählt der Index über
        alle Wettbewerbe hinweg durch.
        """
        assert cl_seite.form_fields["spieltagIndex"] == "25"
        assert cl_seite.matchday == 8

        aktiv = [option for option in cl_seite.matchdays if option.active]
        assert [(o.index, o.label) for o in aktiv] == [(25, "8. Spieltag - CL")]

    def test_spieltagsauswahl_trennt_die_wettbewerbe(self, cl_seite) -> None:
        cl = [o for o in cl_seite.matchdays if o.competition == "CL"]
        bl = [o for o in cl_seite.matchdays if o.competition is None]

        assert len(cl) == 8
        assert len(bl) == 17
        # Der Bonus-Reiter ist kein Spieltag und darf nicht in der Liste stehen.
        assert all("Bonus" not in o.label for o in cl_seite.matchdays)

    def test_reine_gruppe_kennt_nur_einen_wettbewerb(self, bl_seite) -> None:
        assert {o.competition for o in bl_seite.matchdays} == {None}


class TestSpielzeilen:
    def test_alle_paarungen_gelesen(self, cl_seite) -> None:
        assert len(cl_seite.fixtures) == 18

    def test_keine_zusaetzliche_spalte_verrutscht_die_teams(self, cl_seite) -> None:
        """Der Parser filtert Spalten inhaltlich, nicht nach Position.

        Eine unbekannte Textspalte würde als Heimteam gelesen. Die
        CL-Seite hat eine Spalte weniger als die Bundesliga-Seite (keine
        Punkteregel) — genau deshalb muss die Prüfung an echten Namen hängen.
        """
        erste = cl_seite.fixtures[0]
        assert (erste.home_team, erste.away_team) == ("Sporting Lissabon", "FC Bologna")

    def test_anstosszeit_wird_an_folgezeilen_weitergereicht(self, cl_seite) -> None:
        """Kicktipp schreibt die Zeit nur in die erste Zeile eines Blocks."""
        assert all(f.kickoff for f in cl_seite.fixtures)
        assert cl_seite.fixtures[0].kickoff == "29.01.25 20:55"
        assert cl_seite.fixtures[3].kickoff == "29.01.25 20:55"

    def test_bundesliga_seite_hat_mehrere_bloecke(self, bl_seite) -> None:
        zeiten = [f.kickoff for f in bl_seite.fixtures]
        assert zeiten[0] == "28.08.26 20:30"
        assert zeiten[1] == "29.08.26 15:30"
        assert len(set(zeiten)) > 1


class TestPredicdBeiKoWettbewerben:
    """Die CL-Seite ist anders gebaut als eine Ligaseite."""

    def test_zwei_folien_mit_identischem_inhalt(self) -> None:
        slides, aktiv = parse_slides(PREDICD_CL.read_text(encoding="utf-8"))

        assert len(slides) == 2
        assert aktiv == 0
        paarungen = [[(p.home_team, p.away_team) for p in s] for s in slides]
        assert paarungen[0] == paarungen[1]

    def test_ohne_spieltagnummer(self) -> None:
        """Die Überschrift lautet "Qualifikation", nicht "1. Spieltag"."""
        slides, _ = parse_slides(PREDICD_CL.read_text(encoding="utf-8"))
        assert {p.matchday for slide in slides for p in slide} == {None}

    def test_fenster_entfernt_die_doppelung(self) -> None:
        slides, _ = parse_slides(PREDICD_CL.read_text(encoding="utf-8"))
        roh = sum(len(s) for s in slides)

        fenster = _fenster(PREDICD_CL, "champions-league")

        assert roh == 2 * len(fenster)
        assert len({(p.home_team, p.away_team) for p in fenster}) == len(fenster)

    def test_ligaseite_hat_weiterhin_drei_echte_spieltage(self) -> None:
        fenster = _fenster(PREDICD_BL, "bundesliga")
        assert sorted({p.matchday for p in fenster}) == [1, 2, 3]

    def test_herkunft_wird_mitgefuehrt(self) -> None:
        assert {p.league for p in _fenster(PREDICD_CL, "champions-league")} == {
            "champions-league"
        }


class TestZuordnungImGemischtenTopf:
    """Beide Ligen werden geladen; die Seite zeigt nur eine davon."""

    def test_bundesliga_spieltag_wird_vollstaendig_zugeordnet(
        self, bl_seite, topf, aliasse
    ) -> None:
        bericht = TeamMatcher(aliasse).match(bl_seite.fixtures, topf)

        assert len(bericht.matched) == len(bl_seite.fixtures) == 9
        assert not bericht.has_gaps

    def test_nur_die_passende_liga_liefert_treffer(self, bl_seite, topf, aliasse) -> None:
        bericht = TeamMatcher(aliasse).match(bl_seite.fixtures, topf)

        assert {m.prediction.league for m in bericht.matched} == {"bundesliga"}

    def test_ungenutzte_vorhersagen_sind_der_normalfall(
        self, bl_seite, topf, aliasse
    ) -> None:
        """Die jeweils andere Liga bleibt zwangsläufig übrig — kein Fehler."""
        bericht = TeamMatcher(aliasse).match(bl_seite.fixtures, topf)

        assert bericht.unused_predictions
        assert {p.league for p in bericht.unused_predictions} >= {"champions-league"}

    def test_keine_falschen_treffer_quer_ueber_die_ligen(
        self, bl_seite, topf, aliasse
    ) -> None:
        """Der größere Topf darf keine unscharfen Fehlgriffe erzeugen."""
        bericht = TeamMatcher(aliasse).match(bl_seite.fixtures, topf)

        assert all(m.method in {"exact", "alias"} for m in bericht.matched)
        assert not bericht.ambiguous

    def test_fehlende_liga_faellt_als_luecke_auf(self, cl_seite, aliasse) -> None:
        """Nur Bundesliga geladen, aber ein CL-Spieltag steht an.

        Genau der Fall, den die Absende-Sperre abfangen muss: Es wird nicht
        halb getippt, sondern gemeldet.
        """
        nur_bl = _fenster(PREDICD_BL, "bundesliga")

        bericht = TeamMatcher(aliasse).match(cl_seite.fixtures, nur_bl)

        assert bericht.is_empty
        assert len(bericht.unmatched_fixtures) == len(cl_seite.fixtures)
        assert bericht.has_gaps


class TestCLNamenGegenPredicd:
    """Belegt, dass die Normalisierung die CL-Schreibweisen trägt.

    Die Paarungen der Fixtures überschneiden sich nicht (Kicktipp zeigt die
    Ligaphase 2024/25, predicd die Qualifikation 2026), die *Namen* lassen sich
    aber gegeneinander prüfen — und das ist es, worauf die Zuordnung beruht.
    """

    @pytest.mark.parametrize(
        "predicd_name, kicktipp_name",
        [
            ("Sturm Graz", "SK Sturm Graz"),
            ("Slovan Bratislava", "SK Slovan Bratislava"),
            ("Bayer Leverkusen", "Bayer 04 Leverkusen"),
            ("Celtic Glasgow", "Celtic Glasgow"),
            ("Roter Stern Belgrad", "Roter Stern Belgrad"),
            ("Sparta Prag", "Sparta Prag"),
            ("Dinamo Zagreb", "Dinamo Zagreb"),
        ],
    )
    def test_paarung_findet_zusammen(self, predicd_name: str, kicktipp_name: str) -> None:
        fixtures = [Fixture(kicktipp_name, "FC Bayern München", tip_id="1")]
        vorhersagen = [
            Prediction(predicd_name, "FC Bayern München", 1, 2, league="champions-league")
        ]

        bericht = TeamMatcher(load_aliases(["champions-league"])).match(
            fixtures, vorhersagen
        )

        assert len(bericht.matched) == 1, f"{predicd_name!r} fand {kicktipp_name!r} nicht"
        assert bericht.matched[0].method != "fuzzy"


class _FakeKicktipp:
    """Ersetzt den Transportweg, damit der CLI-Ablauf offline prüfbar ist."""

    name = "fake"

    def __init__(self, page, *, fehler_bei_submit: bool = False) -> None:
        self.page = page
        self.gesendet: dict | None = None
        self._fehler = fehler_bei_submit

    def __enter__(self):
        return self

    def __exit__(self, *_) -> bool:
        return False

    def login(self) -> None:
        pass

    def list_groups(self) -> list[str]:
        return ["bl-cl-gruppe"]

    def load_page(self, group: str, matchday=None, require_fixtures: bool = True):
        return self.page

    def submit(self, page, changes):
        if self._fehler:
            raise AssertionError("Es hätte nichts abgesendet werden dürfen.")
        self.gesendet = dict(changes)
        # Gegenlesen: Kicktipp gibt die Seite mit den gespeicherten Werten zurück.
        gespeichert = dict(page.existing_tips)
        for tip_id, (heim, gast) in changes.items():
            gespeichert[tip_id] = (str(heim), str(gast))
        return replace(page, existing_tips=gespeichert)


class TestAbsendeSperre:
    """Bleibt ein Spiel ohne Tipp, wird gar nicht erst abgeschickt."""

    def _lauf(self, monkeypatch, page, vorhersagen, **kwargs):
        """Führt den Ablauf einer Gruppe gegen ein Fake-Ziel aus.

        `run_one_group` bekommt die Sitzung von außen — das Fake-Ziel wird
        deshalb einfach übergeben, ohne `make_target` zu ersetzen.
        """
        from kicktipp_autopilot import runner
        from kicktipp_autopilot.config import resolve_league_ref

        ziel = _FakeKicktipp(page, fehler_bei_submit=kwargs.pop("darf_nicht_senden", False))

        ergebnis = runner.run_one_group(
            ziel,
            "bl-cl-gruppe",
            vorhersagen,
            [resolve_league_ref("bundesliga"), resolve_league_ref("champions-league")],
            matchday=None,
            submit=kwargs.pop("submit", True),
            overwrite=kwargs.pop("overwrite", True),
            allow_partial=kwargs.pop("allow_partial", False),
        )
        return ergebnis, ziel

    def test_luecke_verhindert_die_abgabe(self, monkeypatch, bl_seite, topf) -> None:
        from kicktipp_autopilot.errors import MappingError

        # Eine Vorhersage fehlt -> ein Spiel bleibt ohne Tipp.
        ohne_eine = [
            p for p in topf
            if not (p.home_team == "FC Bayern München" and p.away_team == "VfB Stuttgart")
        ]

        with pytest.raises(MappingError) as fehler:
            self._lauf(monkeypatch, bl_seite, ohne_eine, darf_nicht_senden=True)

        text = str(fehler.value)
        assert "FC Bayern München vs VfB Stuttgart" in text
        assert "--allow-partial" in text
        assert "config.toml" in text

    def test_allow_partial_sendet_den_rest(self, monkeypatch, bl_seite, topf) -> None:
        ohne_eine = [
            p for p in topf
            if not (p.home_team == "FC Bayern München" and p.away_team == "VfB Stuttgart")
        ]

        ergebnis, ziel = self._lauf(
            monkeypatch, bl_seite, ohne_eine, allow_partial=True
        )

        assert ergebnis.status == EINGETRAGEN
        assert ziel.gesendet is not None and len(ziel.gesendet) == 8

    def test_vollstaendiger_spieltag_geht_durch(self, monkeypatch, bl_seite, topf) -> None:
        ergebnis, ziel = self._lauf(monkeypatch, bl_seite, topf)

        assert ergebnis.status == EINGETRAGEN
        assert ergebnis.written == 9
        assert ziel.gesendet is not None and len(ziel.gesendet) == 9

    def test_dry_run_bricht_nie_ab(self, monkeypatch, bl_seite, topf) -> None:
        """Lesen ist harmlos — die Sperre gilt nur fürs Schreiben."""
        ohne_eine = [
            p for p in topf
            if not (p.home_team == "FC Bayern München" and p.away_team == "VfB Stuttgart")
        ]

        ergebnis, ziel = self._lauf(
            monkeypatch, bl_seite, ohne_eine, submit=False, darf_nicht_senden=True
        )

        assert ergebnis.status == VORSCHAU
        assert ziel.gesendet is None

    def test_falscher_wettbewerb_nennt_die_geladenen_ligen(
        self, monkeypatch, cl_seite
    ) -> None:
        from kicktipp_autopilot.errors import MappingError

        nur_bl = _fenster(PREDICD_BL, "bundesliga")

        with pytest.raises(MappingError) as fehler:
            self._lauf(monkeypatch, cl_seite, nur_bl, darf_nicht_senden=True)

        text = str(fehler.value)
        assert "Kein einziges" in text
        assert "champions-league" in text
        assert "--list-matchdays" in text


OFFENE_AUSLOSUNG = FIXTURES / "kicktipp_offene_auslosung.html"


@pytest.fixture(scope="module")
def offene_seite():
    """Ein Champions-League-Spieltag, bevor ausgelost wurde.

    Echter Abzug einer CL-Gruppe (anonymisiert): Kicktipp legt den kompletten
    Spielplan von "1. Spieltag" bis "Finale" schon an, trägt aber überall
    "unbekannt" ein und einen Sammeltermin.
    """
    return parse_page(OFFENE_AUSLOSUNG.read_text(encoding="utf-8"))


class TestNochNichtAusgelost:
    def test_platzhalter_werden_erkannt(self, offene_seite) -> None:
        assert len(offene_seite.fixtures) == 18
        assert len(offene_seite.pending_fixtures) == 18

    def test_echte_paarungen_gelten_nicht_als_offen(self, bl_seite, cl_seite) -> None:
        assert bl_seite.pending_fixtures == []
        assert cl_seite.pending_fixtures == []

    def test_meldung_verweist_nicht_auf_die_konfiguration(
        self, monkeypatch, offene_seite, topf
    ) -> None:
        """Der Grund ist die fehlende Auslosung, nicht eine fehlende Liga.

        Vorher lief die Diagnose in die Irre und schickte zur config.toml.
        """
        from kicktipp_autopilot.errors import MappingError

        with pytest.raises(MappingError) as fehler:
            TestAbsendeSperre()._lauf(
                monkeypatch, offene_seite, topf, darf_nicht_senden=True
            )

        text = str(fehler.value)
        assert "noch nicht gesetzt" in text
        assert "unbekannt" in text
        assert "config.toml" not in text

    def test_teilweise_ausgelost_blockiert_den_rest_nicht(self, monkeypatch, bl_seite, topf) -> None:
        """Halb ausgeloste Runde: Was bekannt ist, wird getippt."""
        from dataclasses import replace as _replace

        gemischt = _replace(
            bl_seite,
            fixtures=[
                _replace(f, home_team="unbekannt", away_team="unbekannt")
                if index < 3
                else f
                for index, f in enumerate(bl_seite.fixtures)
            ],
        )
        assert len(gemischt.pending_fixtures) == 3

        ergebnis, ziel = TestAbsendeSperre()._lauf(monkeypatch, gemischt, topf)

        assert ergebnis.status == EINGETRAGEN
        assert ziel.gesendet is not None and len(ziel.gesendet) == 6
