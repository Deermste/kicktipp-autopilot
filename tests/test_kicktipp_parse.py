"""Tests des Kicktipp-Parsers — ohne Netzwerk, ohne Browser, ohne Zugangsdaten.

Grundlage ist ein anonymisierter Abzug einer echten Tippabgabe-Seite
(Bundesliga, 1. Spieltag, 09.08.2026). E-Mail, Anzeigename, Nutzer- und
Saison-ID sowie der Gruppenname wurden ersetzt; die Struktur ist unverändert.

Dieser Teil bestimmt, welche Werte ins Live-Konto geschrieben werden — deshalb
liegt der Schwerpunkt auf dem Formularrumpf: Kicktipp wertet das Formular als
Ganzes aus, ein fehlendes Feld gilt als geleert.
"""

from pathlib import Path

import pytest

from kicktipp_autopilot.targets.kicktipp_parse import (
    build_submit_body,
    parse_existing_tips,
    parse_fixtures,
    parse_form_fields,
    parse_groups,
    parse_matchday,
    parse_page,
)

FIXTURE = Path(__file__).parent / "fixtures" / "kicktipp_tippabgabe.html"


@pytest.fixture(scope="module")
def html() -> str:
    return FIXTURE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def page(html: str):
    return parse_page(html)


class TestPaarungen:
    def test_neun_spiele(self, page) -> None:
        assert len(page.fixtures) == 9

    def test_sonderfragen_werden_ausgeschlossen(self, page) -> None:
        """Bonusfragen stehen in denselben Tabellenzeilen wie Spiele.

        Sie tragen `fragetippForms`-Felder statt `spieltippForms` und fallen
        dadurch strukturell heraus — nicht erst dadurch, dass die Zuordnung
        fehlschlägt.
        """
        namen = " ".join(f.home_team for f in page.fixtures)
        assert "Wer wird" not in namen
        assert "Welche Mannschaft" not in namen
        assert all(f.away_team != "4 Punkte" for f in page.fixtures)

    def test_heim_und_gast_korrekt(self, page) -> None:
        spiel = next(f for f in page.fixtures if f.home_team == "FC Bayern München")
        assert spiel.away_team == "VfB Stuttgart"

    def test_jedes_spiel_hat_eine_id(self, page) -> None:
        assert all(f.tip_id and f.tip_id.isdigit() for f in page.fixtures)
        assert len({f.tip_id for f in page.fixtures}) == 9

    def test_ohne_klassen_im_rohen_html(self, html: str) -> None:
        """Die Zeilen tragen im ausgelieferten HTML keine Klassen.

        `datarow` und `col1`/`col2` ergänzt erst JavaScript im Browser. Ein
        Parser, der sich darauf stützt, funktioniert nur im Browser — genau
        daran ist die erste Fassung gescheitert.
        """
        assert 'class="datarow"' not in html
        assert len(parse_fixtures(html)) == 9

    def test_feldnamen_und_element_ids(self, page) -> None:
        spiel = page.fixtures[0]
        assert spiel.field_name("heimTipp") == f"spieltippForms[{spiel.tip_id}].heimTipp"
        assert spiel.element_id("gastTipp") == f"spieltippForms_{spiel.tip_id}_gastTipp"


class TestVorhandeneTipps:
    def test_alle_neun_gelesen(self, html: str) -> None:
        assert len(parse_existing_tips(html)) == 9

    def test_werte_stimmen(self, page) -> None:
        spiel = next(f for f in page.fixtures if f.home_team == "FC Bayern München")
        assert page.tip_of(spiel) == ("3", "1")
        assert page.is_tipped(spiel)

    def test_unbekanntes_spiel_gilt_als_ungetippt(self, page) -> None:
        from kicktipp_autopilot.models import Fixture

        assert page.tip_of(Fixture("A", "B", tip_id="0")) == ("", "")


class TestSpieltag:
    def test_nummer_wird_gelesen(self, page) -> None:
        assert page.matchday == 1

    @pytest.mark.parametrize("titel", ["Finale", "Achtelfinale", ""])
    def test_ohne_zahl_kein_absturz(self, titel: str) -> None:
        """K.-o.-Runden haben keine Spieltagnummer — das darf nicht scheitern."""
        html = f'<div class="prevnextTitle">{titel}</div>'
        assert parse_matchday(html) is None


class TestFormularrumpf:
    """Der heikelste Teil: Was gesendet wird, entscheidet über die Daten."""

    def test_alle_felder_erfasst(self, page) -> None:
        assert len(page.form_fields) == 44

    def test_versteckte_felder_enthalten(self, page) -> None:
        for name in ("tipperId", "tippsaisonId", "spieltagIndex", "bonus"):
            assert name in page.form_fields, name

    def test_sonderfragen_im_rumpf(self, page) -> None:
        """Antworten auf Bonusfragen müssen mitgesendet werden.

        Fehlen sie im POST, löscht Kicktipp sie.
        """
        antworten = [k for k in page.form_fields if "antwortIds" in k]
        assert len(antworten) == 7
        assert all(page.form_fields[k] for k in antworten), "Antworten dürfen nicht leer sein"

    def test_rundlauf_ohne_aenderung_ist_identisch(self, page) -> None:
        assert build_submit_body(page, {}) == page.form_fields

    def test_aenderung_trifft_nur_zwei_felder(self, page) -> None:
        spiel = next(f for f in page.fixtures if f.home_team == "FC Bayern München")
        body = build_submit_body(page, {spiel.tip_id: (4, 0)})

        abweichend = {k for k in body if body[k] != page.form_fields.get(k)}
        assert abweichend == {
            f"spieltippForms[{spiel.tip_id}].heimTipp",
            f"spieltippForms[{spiel.tip_id}].gastTipp",
        }
        assert len(body) == len(page.form_fields), "Es darf kein Feld verloren gehen"

    def test_aenderung_setzt_tippAbgegeben(self, page) -> None:
        spiel = page.fixtures[0]
        body = build_submit_body(page, {spiel.tip_id: (1, 1)})
        assert body[f"spieltippForms[{spiel.tip_id}].tippAbgegeben"] == "true"

    def test_andere_spiele_bleiben_unberuehrt(self, page) -> None:
        erstes, zweites = page.fixtures[0], page.fixtures[1]
        body = build_submit_body(page, {erstes.tip_id: (5, 5)})
        assert body[f"spieltippForms[{zweites.tip_id}].heimTipp"] == page.tip_of(zweites)[0]

    def test_submitbutton_gehoert_dazu(self, page) -> None:
        assert "submitbutton" in page.form_fields


class TestGruppenliste:
    def test_gruppen_erkannt(self) -> None:
        html = """
        <a href="/info/profil/meinetipprunden">Übersicht</a>
        <a href="/meine-gruppe/">Meine Gruppe</a>
        <a href="/andere-runde/">Andere</a>
        <a href="/info/service/impressum">Impressum</a>
        <a href="/info/profil/logout">Abmelden</a>
        """
        assert parse_groups(html) == ["meine-gruppe", "andere-runde"]

    def test_leere_seite(self) -> None:
        assert parse_groups("<html></html>") == []


class TestFehlendesFormular:
    def test_kein_formular_liefert_leeren_rumpf(self) -> None:
        assert parse_form_fields("<html><body>nichts</body></html>") == {}

    def test_leere_seite_ergibt_leere_seite(self) -> None:
        page = parse_page("<html><body></body></html>")
        assert not page.fixtures
        assert page.matchday is None
