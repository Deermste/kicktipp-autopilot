"""Tests der Konfiguration."""

import pytest

from kicktipp_autopilot.config import (
    PROJECT_ROOT,
    config_path,
    DEFAULT_LEAGUE_ID,
    LEAGUES,
    LeagueRef,
    leagues_for,
    load_credentials,
    load_group_config,
    resolve_league,
    resolve_league_ref,
    resolve_leagues,
)
from kicktipp_autopilot.errors import ConfigError


class TestLigaAufloesung:
    @pytest.mark.parametrize(
        "eingabe, erwartet",
        [
            ("bundesliga", 4331),
            ("champions-league", 4480),
            ("BUNDESLIGA", 4331),
            ("  bundesliga  ", 4331),
            ("4480", 4480),
            (4480, 4480),
            (None, DEFAULT_LEAGUE_ID),
        ],
    )
    def test_gueltige_eingaben(self, eingabe, erwartet: int) -> None:
        assert resolve_league(eingabe) == erwartet

    def test_unbekannte_liga_nennt_alternativen(self) -> None:
        with pytest.raises(ConfigError, match="Unbekannte Liga"):
            resolve_league("gibt-es-nicht")

    def test_alle_ligen_haben_eindeutige_ids(self) -> None:
        assert len(set(LEAGUES.values())) == len(LEAGUES)


class TestLigaReferenzen:
    """`resolve_league` liefert nur die Zahl — der Slug wird aber gebraucht.

    An ihm hängt die Alias-Datei und die Herkunftsangabe jeder Vorhersage.
    """

    def test_referenz_behaelt_den_namen(self) -> None:
        ref = resolve_league_ref("champions-league")
        assert ref == LeagueRef(slug="champions-league", predicd_id=4480)

    def test_numerische_id_wird_zurueckuebersetzt(self) -> None:
        assert resolve_league_ref("4480").slug == "champions-league"

    def test_unbekannte_id_behaelt_die_zahl_als_namen(self) -> None:
        assert resolve_league_ref("9999").slug == "9999"

    @pytest.mark.parametrize(
        "eingabe",
        [
            ["bundesliga", "champions-league"],
            ["bundesliga,champions-league"],
            ["bundesliga", "champions-league", "bundesliga"],
            [" bundesliga , champions-league "],
        ],
    )
    def test_mehrfachangabe_und_kommaliste(self, eingabe: list[str]) -> None:
        assert [ref.slug for ref in resolve_leagues(eingabe)] == [
            "bundesliga",
            "champions-league",
        ]

    def test_ohne_angabe_leer(self) -> None:
        assert resolve_leagues(None) == []
        assert resolve_leagues([]) == []


def _schreibe_config(pfad, inhalt: str):
    datei = pfad / "config.toml"
    datei.write_text(inhalt, encoding="utf-8")
    return datei


class TestGruppenkonfiguration:
    def test_fehlende_datei_ist_kein_fehler(self, tmp_path) -> None:
        """Wer nur eine Liga tippt, braucht die Datei nie anzulegen."""
        assert load_group_config(tmp_path / "config.toml") == {}

    def test_liest_ligen_je_gruppe(self, tmp_path) -> None:
        datei = _schreibe_config(
            tmp_path,
            """
            [[gruppen]]
            name  = "bl-cl-1"
            ligen = ["bundesliga", "champions-league"]

            [[gruppen]]
            name  = "nur-bl"
            ligen = ["bundesliga"]
            """,
        )
        gruppen = load_group_config(datei)

        assert set(gruppen) == {"bl-cl-1", "nur-bl"}
        assert [ref.slug for ref in gruppen["bl-cl-1"].leagues] == [
            "bundesliga",
            "champions-league",
        ]
        assert gruppen["bl-cl-1"].leagues[1].predicd_id == 4480

    def test_einzelne_liga_auch_als_zeichenkette(self, tmp_path) -> None:
        datei = _schreibe_config(
            tmp_path, '[[gruppen]]\nname = "g"\nligen = "bundesliga"\n'
        )
        assert [ref.slug for ref in load_group_config(datei)["g"].leagues] == [
            "bundesliga"
        ]

    def test_unbekannte_liga_nennt_gruppe_und_datei(self, tmp_path) -> None:
        datei = _schreibe_config(
            tmp_path, '[[gruppen]]\nname = "g"\nligen = ["gibt-es-nicht"]\n'
        )
        with pytest.raises(ConfigError) as fehler:
            load_group_config(datei)

        text = str(fehler.value)
        assert "'g'" in text and "Unbekannte Liga" in text

    def test_fehlender_name_wird_gemeldet(self, tmp_path) -> None:
        datei = _schreibe_config(tmp_path, '[[gruppen]]\nligen = ["bundesliga"]\n')
        with pytest.raises(ConfigError, match="kein 'name'-Feld"):
            load_group_config(datei)

    def test_doppelte_gruppe_wird_gemeldet(self, tmp_path) -> None:
        datei = _schreibe_config(
            tmp_path,
            '[[gruppen]]\nname = "g"\n[[gruppen]]\nname = "g"\n',
        )
        with pytest.raises(ConfigError, match="mehrfach"):
            load_group_config(datei)

    def test_kaputtes_toml_wird_gemeldet(self, tmp_path) -> None:
        datei = _schreibe_config(tmp_path, "[[gruppen]\nname =")
        with pytest.raises(ConfigError, match="kein gültiges TOML"):
            load_group_config(datei)


class TestLigaVorrang:
    """CLI schlägt config.toml schlägt Vorgabe."""

    def test_cli_hat_vorrang(self, tmp_path) -> None:
        datei = _schreibe_config(
            tmp_path, '[[gruppen]]\nname = "g"\nligen = ["bundesliga"]\n'
        )
        gruppen = load_group_config(datei)

        ligen = leagues_for("g", ["champions-league"], gruppen)

        assert [ref.slug for ref in ligen] == ["champions-league"]

    def test_config_gilt_ohne_cli_angabe(self, tmp_path) -> None:
        datei = _schreibe_config(
            tmp_path,
            '[[gruppen]]\nname = "g"\nligen = ["bundesliga", "champions-league"]\n',
        )
        gruppen = load_group_config(datei)

        ligen = leagues_for("g", None, gruppen)

        assert [ref.slug for ref in ligen] == ["bundesliga", "champions-league"]

    def test_ohne_beides_gilt_bundesliga(self) -> None:
        assert [ref.slug for ref in leagues_for("unbekannt", None, {})] == ["bundesliga"]


@pytest.fixture
def ohne_env_datei(monkeypatch):
    """Neutralisiert die lokale .env.

    python-dotenv sucht die Datei relativ zum Paket, nicht zum
    Arbeitsverzeichnis — ohne diesen Eingriff würden die echten Zugangsdaten
    der Entwicklungsmaschine in die Tests sickern und das Ergebnis von
    Rechner zu Rechner unterschiedlich ausfallen.
    """
    monkeypatch.setattr("kicktipp_autopilot.config.load_dotenv", lambda *a, **k: False)
    for key in ("KICKTIPP_EMAIL", "KICKTIPP_PASSWORD", "KICKTIPP_GROUP"):
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


class TestZugangsdaten:
    def test_fehlende_angaben_werden_benannt(self, ohne_env_datei) -> None:
        with pytest.raises(ConfigError) as fehler:
            load_credentials()

        text = str(fehler.value)
        assert "KICKTIPP_EMAIL" in text
        assert "KICKTIPP_PASSWORD" in text

    def test_fehlende_gruppe_verweist_auf_list_groups(self, ohne_env_datei) -> None:
        ohne_env_datei.setenv("KICKTIPP_EMAIL", "test@example.com")
        ohne_env_datei.setenv("KICKTIPP_PASSWORD", "geheim")

        with pytest.raises(ConfigError, match="--list-groups"):
            load_credentials()

    def test_gruppe_optional_fuer_uebersicht(self, ohne_env_datei) -> None:
        """--list-groups braucht keine Gruppe — sie soll ja erst ermittelt werden."""
        ohne_env_datei.setenv("KICKTIPP_EMAIL", "test@example.com")
        ohne_env_datei.setenv("KICKTIPP_PASSWORD", "geheim")

        credentials = load_credentials(require_group=False)

        assert credentials.email == "test@example.com"
        assert credentials.group == ""

    def test_parameter_schlaegt_umgebungsvariable(self, ohne_env_datei) -> None:
        ohne_env_datei.setenv("KICKTIPP_EMAIL", "test@example.com")
        ohne_env_datei.setenv("KICKTIPP_PASSWORD", "geheim")
        ohne_env_datei.setenv("KICKTIPP_GROUP", "aus-env")

        assert load_credentials("aus-parameter").group == "aus-parameter"


class TestConfigFundort:
    """Die config.toml darf nicht davon abhängen, von wo aus gestartet wird."""

    def test_arbeitsverzeichnis_hat_vorrang(self, tmp_path, monkeypatch) -> None:
        _schreibe_config(tmp_path, '[[gruppen]]\nname = "lokal"\n')
        monkeypatch.chdir(tmp_path)

        assert config_path() == tmp_path / "config.toml"
        assert set(load_group_config()) == {"lokal"}

    def test_ohne_lokale_datei_gilt_die_beim_paket(self, tmp_path, monkeypatch) -> None:
        """Sonst liefe ein Aufruf aus einem fremden Verzeichnis wortlos ohne
        Konfiguration — und eine gemischte Gruppe schlüge unerklärlich fehl."""
        monkeypatch.chdir(tmp_path)

        assert config_path() == PROJECT_ROOT / "config.toml"

    def test_ausdrueckliche_angabe_schlaegt_beides(self, tmp_path) -> None:
        assert config_path(tmp_path / "eigene.toml") == tmp_path / "eigene.toml"
