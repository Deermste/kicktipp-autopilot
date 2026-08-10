"""Tests für das Menü hinter `-i` — offline, ohne echtes Terminal.

Der Punkt, an dem hier alles hängt: Zwischen Vorschau und Abgabe darf nichts
dazwischenkommen. Wer die Rückfrage verneint, darf **kein** geschriebenes Tipp
vorfinden — und ohne Terminal darf das Menü gar nicht erst anlaufen, sonst
bliebe ein Timer aus Phase 5 stumm an einer Frage hängen.
"""

from dataclasses import replace
from pathlib import Path

import pytest

from kicktipp_autopilot import interactive
from kicktipp_autopilot.config import Credentials, GroupConfig, resolve_league_ref
from kicktipp_autopilot.errors import ConfigError
from kicktipp_autopilot.models import Prediction, dedupe_predictions
from kicktipp_autopilot.sources.predicd import parse_slides
from kicktipp_autopilot.targets.kicktipp_parse import parse_page

from test_alle_gruppen import _FakeKicktipp, _quelle

FIXTURES = Path(__file__).parent / "fixtures"
BL = resolve_league_ref("bundesliga")
ZUGANG = Credentials("a@b.de", "geheim", "")


@pytest.fixture(scope="module")
def bl_seite():
    return parse_page((FIXTURES / "kicktipp_tippabgabe.html").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def topf() -> list[Prediction]:
    slides, _ = parse_slides((FIXTURES / "predicd_4331.html").read_text(encoding="utf-8"))
    return dedupe_predictions(
        [replace(p, league="bundesliga") for slide in slides for p in slide]
    )


class _Args:
    """Nur die Felder, die `run_interactive` aus der Kommandozeile liest."""

    overwrite = True
    allow_partial = False


def _aufbau(monkeypatch, ziel, topf, *, gruppen, auswahl, bestaetigt):
    """Terminal, Gruppen, Sitzung und Menüantworten vortäuschen."""
    monkeypatch.setattr(interactive.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(interactive, "all_configured_groups", lambda: gruppen)
    monkeypatch.setattr(interactive, "make_target", lambda *a, **k: ziel)
    monkeypatch.setattr(interactive, "PredicdSource", lambda: _quelle(topf))
    monkeypatch.setattr(interactive, "choose_groups", lambda _: auswahl)
    monkeypatch.setattr(interactive, "confirm_submit", lambda _: bestaetigt)


class TestNachfrage:
    def test_ohne_bestaetigung_wird_nichts_geschrieben(
        self, monkeypatch, bl_seite, topf
    ) -> None:
        gruppen = [GroupConfig("meine-gruppe", [BL])]
        ziel = _FakeKicktipp({"meine-gruppe": replace(bl_seite)})
        _aufbau(
            monkeypatch, ziel, topf,
            gruppen=gruppen, auswahl=gruppen, bestaetigt=False,
        )

        code = interactive.run_interactive(ZUGANG, _Args())

        assert code == 0
        assert ziel.gesendet == {}, "Trotz verneinter Rückfrage wurde getippt."
        assert ziel.geladen == ["meine-gruppe"], "Die Vorschau blieb aus."

    def test_mit_bestaetigung_wird_abgesendet(self, monkeypatch, bl_seite, topf) -> None:
        gruppen = [GroupConfig("meine-gruppe", [BL])]
        ziel = _FakeKicktipp({"meine-gruppe": replace(bl_seite)})
        _aufbau(
            monkeypatch, ziel, topf,
            gruppen=gruppen, auswahl=gruppen, bestaetigt=True,
        )

        code = interactive.run_interactive(ZUGANG, _Args())

        assert code == 0
        assert len(ziel.gesendet["meine-gruppe"]) == 9

    def test_eine_anmeldung_fuer_vorschau_und_abgabe(
        self, monkeypatch, bl_seite, topf
    ) -> None:
        """Vorschau und Abgabe teilen sich die Sitzung — sonst könnte sich
        zwischen Anzeige und Absenden etwas ändern."""
        gruppen = [GroupConfig("meine-gruppe", [BL])]
        ziel = _FakeKicktipp({"meine-gruppe": replace(bl_seite)})
        _aufbau(
            monkeypatch, ziel, topf,
            gruppen=gruppen, auswahl=gruppen, bestaetigt=True,
        )

        interactive.run_interactive(ZUGANG, _Args())

        assert ziel.logins == 1


class TestAuswahl:
    def test_leere_auswahl_tut_nichts(self, monkeypatch, bl_seite, topf) -> None:
        gruppen = [GroupConfig("meine-gruppe", [BL])]
        ziel = _FakeKicktipp({"meine-gruppe": replace(bl_seite)})
        _aufbau(
            monkeypatch, ziel, topf,
            gruppen=gruppen, auswahl=[], bestaetigt=True,
        )

        code = interactive.run_interactive(ZUGANG, _Args())

        assert code == 0
        assert ziel.logins == 0, "Ohne Auswahl braucht es keine Anmeldung."
        assert ziel.gesendet == {}

    def test_nur_die_gewaehlten_gruppen_laufen(self, monkeypatch, bl_seite, topf) -> None:
        gruppen = [GroupConfig(f"gruppe-{i}", [BL]) for i in range(1, 4)]
        ziel = _FakeKicktipp({g.name: replace(bl_seite) for g in gruppen})
        _aufbau(
            monkeypatch, ziel, topf,
            gruppen=gruppen, auswahl=[gruppen[0], gruppen[2]], bestaetigt=True,
        )

        interactive.run_interactive(ZUGANG, _Args())

        assert set(ziel.gesendet) == {"gruppe-1", "gruppe-3"}


class TestOhneTerminal:
    def test_menue_verweigert_sich_im_skript(self, monkeypatch) -> None:
        """Ein Timer darf nicht an einer Rückfrage hängen bleiben."""
        monkeypatch.setattr(interactive.sys.stdin, "isatty", lambda: False)

        with pytest.raises(ConfigError) as fehler:
            interactive.run_interactive(ZUGANG, _Args())

        text = str(fehler.value)
        assert "Terminal" in text
        assert "--all-groups" in text


class TestAbbruch:
    def test_strg_c_in_der_auswahl_ist_kein_leeres_ergebnis(self, monkeypatch) -> None:
        """`questionary.ask()` liefert bei Strg-C None — das ist ein Abbruch."""
        class _Frage:
            def ask(self):
                return None

        monkeypatch.setattr(
            interactive, "_questionary", lambda: type("Q", (), {
                "checkbox": staticmethod(lambda *a, **k: _Frage()),
                "Choice": staticmethod(lambda **k: k),
            })
        )

        with pytest.raises(KeyboardInterrupt):
            interactive.choose_groups([GroupConfig("gruppe", [BL])])
