"""Tests für `--all-groups` — mehrere Gruppen in einem Lauf, offline.

Der Kern dieser Phase ist nicht die Schleife selbst, sondern was sie aushält:
Eine Gruppe, in der gerade kein Spieltag offen ist, darf die übrigen nicht
aufhalten; eine Gruppe, die scheitert, ebenso wenig. Und die Sitzung wie die
Vorhersagen sollen dabei genau *einmal* geholt werden — sonst wächst die Last
auf beiden Seiten mit jeder Gruppe.
"""

from dataclasses import replace
from pathlib import Path

import pytest

from kicktipp_autopilot.config import Credentials, GroupConfig, resolve_league_ref
from kicktipp_autopilot.errors import ConfigError, MappingError
from kicktipp_autopilot.models import Prediction, dedupe_predictions
from kicktipp_autopilot.runner import run_groups
from kicktipp_autopilot.sources.predicd import parse_slides
from kicktipp_autopilot.targets.kicktipp_parse import TippabgabePage, parse_page

FIXTURES = Path(__file__).parent / "fixtures"
BL_SEITE = FIXTURES / "kicktipp_tippabgabe.html"
CL_SEITE = FIXTURES / "kicktipp_cl_tippabgabe.html"
PREDICD_BL = FIXTURES / "predicd_4331.html"
PREDICD_CL = FIXTURES / "predicd_4480.html"

BL = resolve_league_ref("bundesliga")
CL = resolve_league_ref("champions-league")
ZUGANG = Credentials("a@b.de", "geheim", "")


@pytest.fixture(scope="module")
def bl_seite() -> TippabgabePage:
    return parse_page(BL_SEITE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def cl_seite() -> TippabgabePage:
    return parse_page(CL_SEITE.read_text(encoding="utf-8"))


def _fenster(datei: Path, slug: str) -> list[Prediction]:
    slides, _ = parse_slides(datei.read_text(encoding="utf-8"))
    return dedupe_predictions(
        [replace(p, league=slug) for slide in slides for p in slide]
    )


@pytest.fixture(scope="module")
def topf() -> list[Prediction]:
    return _fenster(PREDICD_BL, "bundesliga") + _fenster(PREDICD_CL, "champions-league")


class _FakeKicktipp:
    """Ein Kicktipp mit mehreren Gruppen — protokolliert, was verlangt wurde."""

    name = "fake"

    def __init__(self, seiten: dict[str, TippabgabePage]) -> None:
        self.seiten = seiten
        self.logins = 0
        self.geladen: list[str] = []
        self.gesendet: dict[str, dict] = {}

    def __enter__(self):
        return self

    def __exit__(self, *_) -> bool:
        return False

    def login(self) -> None:
        self.logins += 1

    def list_groups(self) -> list[str]:
        return list(self.seiten)

    def load_page(self, group: str, matchday=None, require_fixtures: bool = True):
        self.geladen.append(group)
        if group not in self.seiten:
            from kicktipp_autopilot.errors import SubmissionError

            raise SubmissionError(f"Keine Spiele in Gruppe {group!r} gefunden.")
        return self.seiten[group]

    def submit(self, page, changes):
        gruppe = self.geladen[-1]
        self.gesendet[gruppe] = dict(changes)
        gespeichert = dict(page.existing_tips)
        for tip_id, (heim, gast) in changes.items():
            gespeichert[tip_id] = (str(heim), str(gast))
        return replace(page, existing_tips=gespeichert)


class _ZaehlendeQuelle:
    """Zählt die Abrufe je Liga, ohne ins Netz zu gehen."""

    def __init__(self, fenster: dict[int, list[Prediction]]) -> None:
        self._fenster = fenster
        self.abrufe: list[int] = []
        self._cache: dict[int, list[Prediction]] = {}

    def get_window(self, league) -> list[Prediction]:
        if league.predicd_id not in self._cache:
            self.abrufe.append(league.predicd_id)
            self._cache[league.predicd_id] = self._fenster[league.predicd_id]
        return self._cache[league.predicd_id]


def _quelle(topf: list[Prediction]) -> _ZaehlendeQuelle:
    return _ZaehlendeQuelle(
        {
            BL.predicd_id: [p for p in topf if p.league == "bundesliga"],
            CL.predicd_id: [p for p in topf if p.league == "champions-league"],
        }
    )


def _lauf(ziel, runs, topf, **kwargs) -> int:
    return run_groups(
        credentials=ZUGANG,
        runs=runs,
        submit=kwargs.pop("submit", True),
        overwrite=kwargs.pop("overwrite", True),
        target=ziel,
        source=kwargs.pop("source", None) or _quelle(topf),
        **kwargs,
    )


class TestAlleGruppenInEinemLauf:
    def test_jede_gruppe_wird_getippt(self, bl_seite, topf) -> None:
        runs = [GroupConfig(f"gruppe-{i}", [BL, CL]) for i in range(1, 4)]
        # Jede Gruppe braucht ihre eigene Seite: Der Zustand (bereits
        # getippt/nicht) gehört zur Gruppe, nicht zum Spieltag.
        ziel = _FakeKicktipp({run.name: replace(bl_seite) for run in runs})

        code = _lauf(ziel, runs, topf)

        assert code == 0
        assert ziel.geladen == ["gruppe-1", "gruppe-2", "gruppe-3"]
        assert set(ziel.gesendet) == {"gruppe-1", "gruppe-2", "gruppe-3"}
        assert all(len(tipps) == 9 for tipps in ziel.gesendet.values())

    def test_anmeldung_genau_einmal(self, monkeypatch, bl_seite, topf) -> None:
        """Die Sitzung bleibt über alle Gruppen hinweg offen.

        Ohne übergebenes `target` legt `run_groups` die Sitzung selbst an —
        genau der Weg, den die Kommandozeile nimmt.
        """
        from kicktipp_autopilot import runner

        runs = [GroupConfig(f"gruppe-{i}", [BL]) for i in range(1, 5)]
        ziel = _FakeKicktipp({run.name: replace(bl_seite) for run in runs})
        monkeypatch.setattr(runner, "make_target", lambda *a, **k: ziel)

        code = run_groups(
            credentials=ZUGANG,
            runs=runs,
            submit=True,
            overwrite=True,
            source=_quelle(topf),
        )

        assert code == 0
        assert ziel.logins == 1, "Jede Gruppe hat sich neu angemeldet."
        assert len(ziel.gesendet) == 4

    def test_liga_wird_nur_einmal_geladen(self, bl_seite, topf) -> None:
        """Drei Bundesliga-Gruppen, ein predicd-Abruf."""
        runs = [GroupConfig(f"gruppe-{i}", [BL]) for i in range(1, 4)]
        ziel = _FakeKicktipp({run.name: replace(bl_seite) for run in runs})
        quelle = _quelle(topf)

        _lauf(ziel, runs, topf, source=quelle)

        assert quelle.abrufe == [BL.predicd_id]

    def test_dry_run_schreibt_in_keiner_gruppe(self, bl_seite, topf) -> None:
        runs = [GroupConfig(f"gruppe-{i}", [BL, CL]) for i in range(1, 4)]
        ziel = _FakeKicktipp({run.name: replace(bl_seite) for run in runs})

        code = _lauf(ziel, runs, topf, submit=False)

        assert code == 0
        assert ziel.gesendet == {}


class TestFehlerBleibenLokal:
    def test_eine_gescheiterte_gruppe_stoppt_die_uebrigen_nicht(
        self, bl_seite, cl_seite, topf
    ) -> None:
        """Gruppe 2 tippt CL, hat aber nur Bundesliga konfiguriert.

        Das ist der wahrscheinlichste Fehler im Alltag — und er darf die
        Gruppen 1 und 3 nicht mitreißen.
        """
        runs = [
            GroupConfig("gruppe-1", [BL, CL]),
            GroupConfig("falsch-konfiguriert", [BL]),
            GroupConfig("gruppe-3", [BL, CL]),
        ]
        ziel = _FakeKicktipp(
            {
                "gruppe-1": replace(bl_seite),
                "falsch-konfiguriert": replace(cl_seite),
                "gruppe-3": replace(bl_seite),
            }
        )

        code = _lauf(ziel, runs, topf)

        assert code == 1, "Ein Fehler muss sich im Rückgabecode niederschlagen."
        assert set(ziel.gesendet) == {"gruppe-1", "gruppe-3"}
        assert "falsch-konfiguriert" not in ziel.gesendet

    def test_gruppe_ohne_offenen_spieltag_ist_kein_fehler(self, bl_seite, topf) -> None:
        leer = TippabgabePage(title="Kein Spieltag offen")
        runs = [GroupConfig("laeuft", [BL]), GroupConfig("pause", [BL])]
        ziel = _FakeKicktipp({"laeuft": replace(bl_seite), "pause": leer})

        code = _lauf(ziel, runs, topf)

        assert code == 0, "Kein offener Spieltag ist ein Normalzustand."
        assert set(ziel.gesendet) == {"laeuft"}

    def test_nicht_ausgeloste_runde_ist_kein_fehler(self, bl_seite, topf) -> None:
        """Zu früh ist nicht kaputt.

        Eine CL-Gruppe, deren Ligaphase noch nicht ausgelost ist, würde sonst
        wochenlang jeden Lauf röten — und der Rückgabecode wäre als Warnsignal
        wertlos, weil er dauerhaft auf 1 stünde.
        """
        offen = parse_page(
            (FIXTURES / "kicktipp_offene_auslosung.html").read_text(encoding="utf-8")
        )
        runs = [GroupConfig("laeuft", [BL]), GroupConfig("vor-auslosung", [CL])]
        ziel = _FakeKicktipp({"laeuft": replace(bl_seite), "vor-auslosung": offen})

        code = _lauf(ziel, runs, topf)

        assert code == 0
        assert set(ziel.gesendet) == {"laeuft"}

    def test_ausgefallene_vorhersagequelle_kostet_nur_ihre_gruppe(
        self, bl_seite, topf
    ) -> None:
        from kicktipp_autopilot.errors import PredictionError

        class _KaputtBeiCl(_ZaehlendeQuelle):
            def get_window(self, league):
                if league.predicd_id == CL.predicd_id:
                    raise PredictionError("predicd nicht erreichbar")
                return super().get_window(league)

        runs = [GroupConfig("bl-gruppe", [BL]), GroupConfig("cl-gruppe", [CL])]
        ziel = _FakeKicktipp({run.name: replace(bl_seite) for run in runs})
        quelle = _KaputtBeiCl(
            {BL.predicd_id: [p for p in topf if p.league == "bundesliga"]}
        )

        code = _lauf(ziel, runs, topf, source=quelle)

        assert code == 1
        assert set(ziel.gesendet) == {"bl-gruppe"}

    def test_zusammenfassung_nennt_jede_gruppe(self, capsys, bl_seite, cl_seite, topf) -> None:
        leer = TippabgabePage(title="—")
        runs = [
            GroupConfig("getippt", [BL, CL]),
            GroupConfig("kaputt", [BL]),
            GroupConfig("pause", [BL]),
        ]
        ziel = _FakeKicktipp(
            {
                "getippt": replace(bl_seite),
                "kaputt": replace(cl_seite),
                "pause": leer,
            }
        )

        _lauf(ziel, runs, topf)

        ausgabe = capsys.readouterr().out
        assert "Zusammenfassung" in ausgabe
        for gruppe in ("getippt", "kaputt", "pause"):
            assert gruppe in ausgabe


class TestWiederholung:
    def test_abgabefehler_wird_wiederholt(self, monkeypatch, bl_seite, topf) -> None:
        """Ein Netzfehler beim Absenden ist ein Fall für den zweiten Versuch."""
        from kicktipp_autopilot import runner
        from kicktipp_autopilot.errors import SubmissionError

        monkeypatch.setattr(runner, "RETRY_DELAY_SECONDS", 0)

        class _ErstFehler(_FakeKicktipp):
            versuche = 0

            def submit(self, page, changes):
                self.versuche += 1
                if self.versuche == 1:
                    raise SubmissionError("Verbindung abgebrochen")
                return super().submit(page, changes)

        runs = [GroupConfig("gruppe", [BL])]
        ziel = _ErstFehler({"gruppe": replace(bl_seite)})

        code = _lauf(ziel, runs, topf)

        assert code == 0
        assert ziel.versuche == 2
        assert ziel.logins == 1, "Vor dem zweiten Versuch fehlt die neue Anmeldung."

    def test_zuordnungsfehler_wird_nicht_wiederholt(
        self, monkeypatch, cl_seite, topf
    ) -> None:
        """Ein zweiter Versuch ändert an einer fehlenden Liga nichts."""
        from kicktipp_autopilot import runner

        monkeypatch.setattr(runner, "RETRY_DELAY_SECONDS", 0)

        runs = [GroupConfig("gruppe", [BL])]
        ziel = _FakeKicktipp({"gruppe": replace(cl_seite)})

        code = _lauf(ziel, runs, topf)

        assert code == 1
        assert ziel.geladen == ["gruppe"], "Die Gruppe wurde mehrfach geladen."


class TestOptionspruefung:
    """Widersprüchliche Angaben fallen auf, bevor irgendetwas geladen wird."""

    def _args(self, argv: list[str]):
        from kicktipp_autopilot.cli import build_parser

        return build_parser().parse_args(argv)

    def test_all_groups_und_matchday(self) -> None:
        from kicktipp_autopilot.cli import check_combinations

        with pytest.raises(ConfigError, match="spieltagIndex"):
            check_combinations(self._args(["--all-groups", "--matchday", "5"]))

    def test_all_groups_und_group(self) -> None:
        from kicktipp_autopilot.cli import check_combinations

        with pytest.raises(ConfigError, match="schließen einander aus"):
            check_combinations(self._args(["--all-groups", "--group", "irgendwas"]))

    def test_all_groups_und_league(self) -> None:
        from kicktipp_autopilot.cli import check_combinations

        with pytest.raises(ConfigError, match="Wettbewerbe"):
            check_combinations(self._args(["--all-groups", "--league", "bundesliga"]))

    def test_einzelne_gruppe_bleibt_erlaubt(self) -> None:
        from kicktipp_autopilot.cli import check_combinations

        check_combinations(self._args(["--group", "meine", "--matchday", "5"]))

    def test_ohne_config_toml_kommt_eine_anleitung(self, tmp_path) -> None:
        from kicktipp_autopilot.config import all_configured_groups

        with pytest.raises(ConfigError) as fehler:
            all_configured_groups(tmp_path / "gibt-es-nicht.toml")

        text = str(fehler.value)
        assert "config.toml" in text
        assert "--list-groups" in text


class TestEinzelneGruppe:
    """Der bisherige Weg bleibt derselbe — nur intern über run_groups."""

    def test_ohne_offenen_spieltag_meldet_der_einzelaufruf_einen_fehler(
        self, monkeypatch, topf
    ) -> None:
        """Bei genau einer genannten Gruppe ist der Tippfehler im Namen
        die näherliegende Ursache — anders als bei --all-groups."""
        from kicktipp_autopilot import runner
        from kicktipp_autopilot.errors import SubmissionError

        monkeypatch.setattr(runner, "RETRY_DELAY_SECONDS", 0)

        class _Streng(_FakeKicktipp):
            def load_page(self, group, matchday=None, require_fixtures: bool = True):
                self.geladen.append(group)
                if require_fixtures:
                    raise SubmissionError(f"Keine Spiele in Gruppe {group!r} gefunden.")
                return TippabgabePage()

        ziel = _Streng({})
        code = run_groups(
            credentials=ZUGANG,
            runs=[GroupConfig("gibt-es-nicht", [BL])],
            submit=False,
            target=ziel,
            source=_quelle(topf),
        )

        assert code == 1

    def test_leere_gruppenliste_ist_ein_fehler(self, topf) -> None:
        with pytest.raises(MappingError, match="Keine Gruppe"):
            run_groups(credentials=ZUGANG, runs=[], source=_quelle(topf))
