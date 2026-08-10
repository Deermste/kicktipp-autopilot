"""Fehlerklassen des Autopiloten.

Alle erwarteten Fehler erben von AutopilotError. Die CLI fängt genau diese ab
und gibt sie als verständliche Meldung aus, statt einen Traceback zu zeigen.
"""


class AutopilotError(Exception):
    """Basisklasse für alle erwarteten Fehler."""


class PredictionError(AutopilotError):
    """Vorhersagen konnten nicht geladen oder dekodiert werden."""


class MappingError(AutopilotError):
    """Vorhersagen ließen sich den Kicktipp-Spielen nicht zuordnen."""


class NotDrawnError(MappingError):
    """Kicktipp kennt die Paarungen des Spieltags noch gar nicht.

    Eine eigene Klasse, weil das kein Fehler im Sinne von „etwas ist kaputt"
    ist: Es ist schlicht zu früh. Über mehrere Gruppen hinweg darf so eine
    Runde deshalb weder den Lauf röten noch den Rückgabecode verderben — sonst
    meldet ein Timer aus Phase 5 wochenlang Fehlalarm, bis die Auslosung war.
    """


class SubmissionError(AutopilotError):
    """Tipps konnten nicht eingetragen oder abgesendet werden."""


class ConfigError(AutopilotError):
    """Konfiguration ist unvollständig oder ungültig."""
