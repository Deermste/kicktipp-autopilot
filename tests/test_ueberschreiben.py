"""Tests für `ueberschreiben` in config.toml und `--overwrite`/`--no-overwrite`.

Wer überschreiben als Standard einschaltet, braucht trotzdem einen Weg, für
einen Lauf seine Tipps zu schützen — und eine Gruppe ohne Eintrag darf davon
nichts abbekommen.
"""

from dataclasses import replace
from pathlib import Path

import pytest

from kicktipp_autopilot.cli import build_parser
from kicktipp_autopilot.config import (
    Credentials,
    GroupConfig,
    load_group_config,
    resolve_league_ref,
)
from kicktipp_autopilot.errors import ConfigError
from kicktipp_autopilot.models import dedupe_predictions
from kicktipp_autopilot.runner import run_groups
from kicktipp_autopilot.sources.predicd import parse_slides
from kicktipp_autopilot.targets.kicktipp_parse import parse_page

FIXTURES = Path(__file__).parent / "fixtures"
BL = resolve_league_ref("bundesliga")
ZUGANG = Credentials("a@b.de", "geheim", "")


@pytest.fixture(scope="module")
def getippte_seite():
    """Die BL-Seite, auf der jedes Spiel schon mit 9:9 getippt ist."""
    page = parse_page((FIXTURES / "kicktipp_tippabgabe.html").read_text(encoding="utf-8"))
    return replace(page, existing_tips={f.tip_id: ("9", "9") for f in page.fixtures})


class _Quelle:
    def __init__(self) -> None:
        slides, _ = parse_slides((FIXTURES / "predicd_4331.html").read_text(encoding="utf-8"))
        self._fenster = dedupe_predictions(
            [replace(p, league="bundesliga") for s in slides for p in s]
        )

    def get_window(self, league):
        return self._fenster


class _FakeKicktipp:
    name = "fake"

    def __init__(self, page) -> None:
        self.page = page
        self.geladen: list[str] = []
        self.gesendet: dict[str, dict] = {}

    def login(self) -> None:
        pass

    def load_page(self, group, matchday=None, require_fixtures=True):
        self.geladen.append(group)
        return self.page

    def submit(self, page, changes):
        self.gesendet[self.geladen[-1]] = dict(changes)
        gespeichert = dict(page.existing_tips)
        for tip_id, (heim, gast) in changes.items():
            gespeichert[tip_id] = (str(heim), str(gast))
        return replace(page, existing_tips=gespeichert)


def _lauf(page, runs, overwrite=None):
    ziel = _FakeKicktipp(page)
    run_groups(
        credentials=ZUGANG, runs=runs, submit=True, overwrite=overwrite,
        target=ziel, source=_Quelle(),
    )
    return ziel.gesendet


class TestAblauf:
    def test_config_ueberschreibt_je_gruppe(self, getippte_seite) -> None:
        runs = [GroupConfig("immer", [BL], overwrite=True), GroupConfig("nie", [BL])]
        gesendet = _lauf(getippte_seite, runs)
        assert len(gesendet["immer"]) == len(getippte_seite.fixtures)
        assert "nie" not in gesendet

    def test_no_overwrite_schuetzt_trotz_config(self, getippte_seite) -> None:
        runs = [GroupConfig("immer", [BL], overwrite=True)]
        assert _lauf(getippte_seite, runs, overwrite=False) == {}

    def test_overwrite_gilt_fuer_alle(self, getippte_seite) -> None:
        runs = [GroupConfig("a", [BL]), GroupConfig("b", [BL])]
        assert set(_lauf(getippte_seite, runs, overwrite=True)) == {"a", "b"}


class TestKonfiguration:
    def test_ueberschreiben_wird_gelesen(self, tmp_path) -> None:
        datei = tmp_path / "config.toml"
        datei.write_text(
            '[[gruppen]]\nname = "a"\nligen = ["bundesliga"]\nueberschreiben = true\n'
            '[[gruppen]]\nname = "b"\nligen = ["bundesliga"]\n',
            encoding="utf-8",
        )
        gruppen = load_group_config(datei)
        assert gruppen["a"].overwrite is True
        assert gruppen["b"].overwrite is False

    def test_nur_wahrheitswerte(self, tmp_path) -> None:
        datei = tmp_path / "config.toml"
        datei.write_text(
            '[[gruppen]]\nname = "a"\nligen = ["bundesliga"]\nueberschreiben = "ja"\n',
            encoding="utf-8",
        )
        with pytest.raises(ConfigError, match="true oder false"):
            load_group_config(datei)


class TestKommandozeile:
    @pytest.mark.parametrize(
        "argv, erwartet",
        [([], None), (["--overwrite"], True), (["--no-overwrite"], False)],
    )
    def test_drei_zustaende(self, argv, erwartet) -> None:
        assert build_parser().parse_args(argv).overwrite is erwartet
