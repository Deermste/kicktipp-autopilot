"""Vereinsnamen auf eine vergleichbare Form bringen.

predicd und Kicktipp schreiben dieselben Vereine unterschiedlich:

    predicd                 Kicktipp
    ------------------------------------------
    TSG Hoffenheim          1899 Hoffenheim
    Bayer Leverkusen        Bayer 04 Leverkusen
    1. FSV Mainz 05         FSV Mainz 05
    SV Elversberg           SV 07 Elversberg

Alle vier Paare werden allein durch Normalisierung identisch — Rechtsformen,
Gründungsjahre und Ordnungszahlen tragen keine Bedeutung zur Unterscheidung
bei. Nur Fälle, die danach immer noch abweichen (etwa "M'Gladbach" gegen
"Mönchengladbach"), brauchen einen expliziten Alias.
"""

from __future__ import annotations

import re
import unicodedata

# Muss vor dem Entfernen von Akzenten greifen: "ö" soll "oe" werden, nicht "o".
_CHARACTER_MAP = {
    "ä": "ae",
    "ö": "oe",
    "ü": "ue",
    "ß": "ss",
    "æ": "ae",
    "ø": "oe",
    "å": "aa",
    "đ": "d",
    "ł": "l",
}

# Rechtsformen und Vereinskürzel ohne unterscheidende Bedeutung.
#
# Bewusst NICHT enthalten: "united", "city", "real", "athletic", "atletico",
# "sporting". Diese Wörter unterscheiden Vereine tatsächlich voneinander —
# ohne sie würden etwa Manchester United und Manchester City zum selben
# Schlüssel zusammenfallen.
_NOISE_TOKENS = {
    "fc", "sv", "sc", "vfl", "vfb", "vfr", "tsg", "tsv", "fsv", "rb", "msv",
    "spvgg", "sg", "bsc", "kfc", "afc", "cf", "ac", "as", "ssc", "sd", "rcd",
    "cd", "ud", "bor", "borussia", "eintracht", "verein", "club",
    # "sk" (Sportklub) belegt am 10.08.2026: Kicktipp schreibt in der Champions
    # League "SK Sturm Graz" und "SK Slovan Bratislava", predicd "Sturm Graz"
    # und "Slovan Bratislava". Ohne das Kürzel griff nur die unscharfe Suche
    # (0.87 bzw. 0.92) — mit ihm sind beide Paare exakt gleich.
    "sk",
}


def normalize(name: str) -> str:
    """Bringt einen Vereinsnamen auf eine vergleichbare Grundform.

    >>> normalize("1. FSV Mainz 05")
    'mainz'
    >>> normalize("TSG Hoffenheim") == normalize("1899 Hoffenheim")
    True
    """
    if not name:
        return ""

    text = name.casefold()
    for source, target in _CHARACTER_MAP.items():
        text = text.replace(source, target)

    # Verbliebene Akzente entfernen (é, ñ, č …) — relevant ab CL/EM/WM.
    text = "".join(
        ch
        for ch in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(ch)
    )

    # Alles außer Buchstaben/Ziffern wird zum Trenner; "M'Gladbach" -> "m gladbach"
    text = re.sub(r"[^a-z0-9]+", " ", text)

    tokens = text.split()
    meaningful = [
        token
        for token in tokens
        if token not in _NOISE_TOKENS and not token.isdigit()
    ]

    # Falls die Filter alles verschluckt haben (z. B. "FC 05"), lieber die
    # ungefilterte Form behalten als einen leeren Schlüssel zu erzeugen.
    if not meaningful:
        meaningful = tokens

    return " ".join(meaningful)


def normalize_pair(home: str, away: str) -> tuple[str, str]:
    """Normalisiert eine Paarung."""
    return normalize(home), normalize(away)
