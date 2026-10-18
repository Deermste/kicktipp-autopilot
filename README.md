# ⚽ Kicktipp Autopilot

**Automatically predict Bundesliga matches — powered by data, not gut feeling.**

Kicktipp Autopilot is a Python bot that fetches score predictions from [predicd.com](https://www.predicd.com) and automatically submits them to your [Kicktipp](https://www.kicktipp.de) fantasy league. Set it up once, run it each matchday, and let the data do the work.


https://github.com/user-attachments/assets/4c21c799-8883-435b-b7d7-60eed546c59d


---

## Features

- **No browser required** — Both predicd and Kicktipp are driven over plain HTTP. A full run takes ~1 second instead of ~20
- **Dry run by default** — Shows exactly what it would submit; writing requires `--submit`
- **Verified writes** — After submitting, the saved tips are read back and compared against the plan
- **Fixture-based matching** — Pairs games by home *and* away team, so it works even when the matchday label is missing (`Finale`, `Achtelfinale`, …)
- **Smart team name mapping** — Normalisation handles most spelling differences (*TSG Hoffenheim* ↔ *1899 Hoffenheim*); per-league alias files cover the rest
- **Never guesses** — Anything it cannot match confidently is reported by name and skipped, including Kicktipp bonus questions
- **Protects manual tips** — Existing tips are left untouched unless you pass `--overwrite` or set `ueberschreiben = true` for the group
- **Group discovery** — `--list-groups` reads your leagues straight from your account
- **Several competitions per group** — A group playing Bundesliga *and* Champions League is handled from one `config.toml` entry
- **All your groups in one go** — `--all-groups` works through every group in `config.toml` on a single login, with a summary at the end
- **Interactive menu** — `-i` lets you pick groups with the arrow keys, shows a preview, and asks before writing anything
- **Stops instead of half-tipping** — If any game on the page has no clear prediction, nothing is submitted at all
- **Optional tip strategies** — Uses the bookmaker odds Kicktipp shows next to each game to pick better scores (`faustregel`) and to side with the favourite (`favorit`); off unless you switch it on
- **Knows when it is too early** — Rounds that Kicktipp has not drawn yet are named as such, not blamed on your config
- **Offline tests** — 279 tests run against saved HTML, catching layout changes before they cost you points

---

## How It Works

```
┌─────────────┐        ┌──────────────────┐       ┌─────────────┐
│ predicd.com │──────▶│ Kicktipp Autopilot│───▶  │  Kicktipp   │
│             │        │                  │       │             │
│ Predictions │ Fetch  │ Decode scores    │ Login │ Submit tips │
│ + Scores    │ ────▶ │ Map team names   │ ───▶  │ for current │
│             │        │ Validate matchday│       │ matchday    │
└─────────────┘        └──────────────────┘       └─────────────┘
```

1. **Fetch** — Opens predicd.com in a headless browser and extracts predicted scores for all Bundesliga matches
2. **Match** — Decodes the scores, translates team names, and verifies the matchday number
3. **Submit** — Logs into your Kicktipp account, fills in all predictions, and submits them

---

## Prerequisites

- **Python 3.11+** (`tomllib` from the standard library is used for `config.toml`)
- **Google Chrome** — only for the optional `--browser` fallback; the default HTTP path needs no browser at all

> **No manual ChromeDriver download needed.** Selenium 4.6+ ships with the
> built-in *Selenium Manager*, which automatically fetches the driver matching
> your installed Chrome version.

On Debian/Ubuntu-based systems `pip` and `venv` are not
part of the default Python installation and must be installed first:

```bash
sudo apt update
sudo apt install -y python3-pip python3-venv
```

If Chrome is not installed yet:

```bash
wget -O /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo apt install -y /tmp/chrome.deb
```

---

## Installation

1. **Clone the repository**

   ```bash
   git clone https://github.com/TrustPaddy/kicktipp-autopilot.git
   cd kicktipp-autopilot
   ```

2. **Create a virtual environment and install dependencies**

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Configure your credentials**

   ```bash
   cp example.env .env
   ```

   Edit `.env` with your Kicktipp login details:

   ```env
   KICKTIPP_EMAIL=your@email.com
   KICKTIPP_PASSWORD=yourPassword
   KICKTIPP_GROUP=yourGroupName
   ```

   `KICKTIPP_GROUP` is the part of your league's URL between `kicktipp.de/`
   and `/tippabgabe`.

   > `.env` holds your credentials in plain text and is excluded from git via
   > `.gitignore`. Never commit it.

---

## Configuration

| Variable            | Description                          | Required |
|---------------------|--------------------------------------|----------|
| `KICKTIPP_EMAIL`    | Your Kicktipp account email address  | Yes      |
| `KICKTIPP_PASSWORD` | Your Kicktipp account password       | Yes      |
| `KICKTIPP_GROUP`    | Your Kicktipp group/league name (as it appears in the URL) | Yes      |

### Several competitions in one group

Many private groups cover more than one competition — Bundesliga *and*
Champions League, say. Kicktipp shows **one competition per matchday**, and the
game rows do not say which one. So you tell the bot once which competitions a
group plays, and it loads the predictions for all of them:

```bash
cp example.config.toml config.toml
```

```toml
[[gruppen]]
name  = "bl-cl-1"
ligen = ["bundesliga", "champions-league"]

[[gruppen]]
name  = "bundesliga-tippspiel"
ligen = ["bundesliga"]
```

Which competition is actually due is never guessed — it follows from which
predictions matched, and is printed on every run:

```
1. Spieltag - CL · erkannt als champions-league (18 von 18 Spielen)
```

`config.toml` is optional: without it, `--league` applies, defaulting to
Bundesliga. It holds no secrets, but it does contain your group names and is
therefore gitignored like `.env`.

---

## Usage

```bash
source .venv/bin/activate   # if not already active
python -m kicktipp_autopilot
```

**Nothing is ever submitted without `--submit`.** The default is a dry run that
shows exactly what would be entered.

### Common commands

```bash
# Which leagues do I play in? (reads them from your Kicktipp account)
python -m kicktipp_autopilot --list-groups

# Preview — shows the planned tips, submits nothing
python -m kicktipp_autopilot --group my-league

# Actually submit
python -m kicktipp_autopilot --group my-league --submit

# Every group from config.toml in one run — preview first, then submit
python -m kicktipp_autopilot --all-groups
python -m kicktipp_autopilot --all-groups --submit

# Pick the groups from a menu, preview, confirm
python -m kicktipp_autopilot -i

# Which matchdays does this group have, and what is each one called?
python -m kicktipp_autopilot --group my-league --list-matchdays

# A different competition or matchday
python -m kicktipp_autopilot --league bundesliga,champions-league
python -m kicktipp_autopilot --matchday 25
python -m kicktipp_autopilot --list-leagues

# Predictions only, no Kicktipp login at all
python -m kicktipp_autopilot --no-kicktipp
```

### Options

| Option | Effect |
|---|---|
| `--submit` | Actually enter and send the tips (otherwise: dry run) |
| `--overwrite` / `--no-overwrite` | Replace tips you already submitted, or protect them for this run. Without either, `ueberschreiben` from `config.toml` decides; default: leave them alone |
| `--strategie NAME` | Tip strategy: `favorit`, `faustregel`, both (`favorit,faustregel`) or `keine`. Overrides `strategie` in `config.toml` for every group of the run |
| `--group NAME` | Kicktipp group, overrides `.env` |
| `--all-groups` | Work through every group in `config.toml` on one login |
| `-i`, `--interactive` | Pick groups from a menu, preview, confirm before writing |
| `--league NAME\|ID` | Competition. Repeatable or comma-separated. Overrides `config.toml`; default `bundesliga` |
| `--matchday N` | Matchday of the group — the `spieltagIndex`, see below (default: the upcoming one) |
| `--allow-partial` | Submit even if some games have no clear prediction (default: abort, write nothing) |
| `--no-kicktipp` | Only fetch predictions, no login |
| `--list-matchdays` | Show the group's matchdays with their `--matchday` number |
| `--browser` | Use Selenium instead of HTTP (fallback, ~20× slower) |
| `--show-browser` | Show the browser window (implies `--browser`) |
| `-v` | Verbose output |

### Tip strategies

predicd delivers the *most likely* score. That is not the same as the tip that
earns the most Kicktipp points. Two optional strategies sit on top of the
prediction; both use the 1/X/2 odds Kicktipp shows next to every game:

| Strategy | What it does |
|---|---|
| `faustregel` | Keeps predicd's tendency, replaces the score: a clear favourite (win probability ≥ 65 %) wins **3:0**, every other win is **2:1**, a draw is **1:1**. Above all, 2:0 disappears |
| `favorit` | Where predicd's tendency disagrees with the bookmakers' favourite, the favourite is tipped instead (a draw included) |

Both rules come from a backtest over 396 games (Bundesliga 25/26 in full, BL
and CL 26/27 up to matchday 6 and 2). 2:0 scored worse than 2:1 or 1:0 in
almost every favourite class of both seasons. The score rule was worth about
**+1 point per 10 games** in both scoring types: fixed points (2/3/5) and
odds-based points. The favourite rule touches roughly one game in eight. It
lifts the hit rate slightly, but its effect on points was not conclusive so
far. With only that much data, treat the numbers as a direction, not a promise.

Switch them on per group in `config.toml`, or for a single run on the command
line:

```toml
[[gruppen]]
name      = "bundesliga-tippspiel"
ligen     = ["bundesliga"]
strategie = ["favorit", "faustregel"]
```

```bash
python -m kicktipp_autopilot --all-groups                      # as in config.toml
python -m kicktipp_autopilot --group my-league --strategie faustregel
python -m kicktipp_autopilot --all-groups --strategie keine    # plain predicd
```

The preview shows predicd's original tip in an extra column and names the
reason for every change. A game without odds keeps predicd's tip, so nothing is
guessed. Kicktipp does not show odds in every group at the same time: a mixed
BL+CL group can still have empty CL odds while a pure CL group already has
them. During `--all-groups` a group without odds reuses those of an earlier
group in the same run (same pairing, same kick-off). So put mixed groups last
in `config.toml`.

### Overwriting by default

By default a tip that is already on Kicktipp is never touched. That protects
tips you entered by hand. It also means a matchday the bot tipped days ago
keeps the old prediction, even when predicd or the odds have moved since. To
let the bot re-tip a group on every run:

```toml
[[gruppen]]
name           = "bundesliga-tippspiel"
ligen          = ["bundesliga"]
ueberschreiben = true
```

Games that have already kicked off have no input fields any more and are
never changed. `--no-overwrite` protects existing tips for a single run, for
example after tipping one game by hand. `--overwrite` does the opposite for
groups without the setting.

### `--matchday` is the group's index, not the number on screen

In a group with one competition the two are the same. In a mixed group they are
not: the index counts through *all* competitions, so `--matchday 25` is the page
titled `8. Spieltag - CL`. `--list-matchdays` prints the mapping:

```
 --matchday   Bezeichnung                  Wettbewerb
         23   17. Spieltag                 —
         24   7. Spieltag - CL             CL
         25   8. Spieltag - CL ← aktuell   CL
```

### When a game cannot be matched

A Kicktipp page shows exactly one competition, so every game on it should be
matchable. If any is left over, that usually means a competition is missing from
`config.toml` — or a team needs an alias. In that case **nothing is submitted**:

```
Fehler: 4 von 18 Spielen ohne eindeutige Vorhersage: Sporting Lissabon vs
FC Bologna; … Geladen waren: bundesliga. Fehlt eine Liga in config.toml, oder
braucht ein Team einen Alias in matching/aliases/? Nichts abgesendet.
Zum Absenden der übrigen Tipps: --allow-partial
```

The dry run never aborts — it always shows the full picture first.

### All groups in one run

`--all-groups` works through every `[[gruppen]]` entry of your `config.toml` —
one login, one predicd fetch per competition, one summary at the end:

```
                                Zusammenfassung
┏━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Gruppe               ┃ Spieltag         ┃ erkannt ┃ getippt ┃ Status                ┃
┡━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━┩
│ bundesliga-tippspiel │ 1. Spieltag      │     9/9 │       9 │ eingetragen           │
│ cl-tippspiel         │ —                │       — │       — │ noch nicht ausgelost  │
│ bl-cl-1              │ 8. Spieltag - CL │       — │       — │ kein offener Spieltag │
│ bl-cl-2              │ Finale           │       — │       — │ kein offener Spieltag │
└──────────────────────┴──────────────────┴─────────┴─────────┴───────────────────────┘
```

The groups come from `config.toml`, not from your account — expired seasons stay
out of it, and every group listed there has its competitions on record.

**A failing group does not stop the others.** Each group is handled on its own;
whatever goes wrong is printed under that group and repeated in the summary,
while the remaining groups are still tipped. The exit code is `1` if any group
actually failed. *Not* counted as failures: a group with no open matchday and a
round Kicktipp has not drawn yet — neither is something you can act on, and a
permanently red exit code would make the signal worthless.

Since the `spieltagIndex` counts per group, `--matchday` cannot be combined with
`--all-groups`; the same goes for `--league`, which would override every group's
competitions. Both are refused before anything is loaded.

### The interactive menu

`kicktipp -i` asks which groups to tip (space to toggle, enter to confirm), shows
the full preview, and only then asks whether to submit — defaulting to *No*.
Preview and submission share the same session and the same predictions, so what
gets written is exactly what you saw.

The menu needs a terminal. In a script or a systemd timer it refuses to start and
points to `--all-groups` instead, rather than silently waiting for an answer
nobody will give.

### Before the draw

Kicktipp creates the whole schedule up front — for a Champions League group all
17 rounds from `1. Spieltag` to `Finale` — and fills every row with `unbekannt`
until the draw happens. Those games are not a configuration problem, so they are
reported as such and never block anything:

```
cl-tippspiel: Kicktipp hat die Paarungen für 1. Spieltag noch nicht gesetzt —
alle 18 Spiele stehen als „unbekannt" in der Tabelle. Das ist kein Fehler in der
Konfiguration; sobald ausgelost ist, funktioniert der Lauf. Nichts abgesendet.
```

If a round is only partly drawn, the known games are tipped and the rest is
listed as `noch nicht ausgelost` — just run again once the draw is complete.

### Two ways to reach Kicktipp

The default is plain HTTP. Selenium remains available via `--browser` as a
fallback in case Kicktipp changes something — and as an independent second
opinion: both paths share the same parser and must produce identical results,
which is how a silent misread was caught during development.

```bash
kicktipp              # HTTP      ~1 s
kicktipp --browser    # Selenium  ~11 s
```

> **Why HTTP is the better default:** Kicktipp's cookie banner loads
> asynchronously and covers the "Tipps speichern" button, which made the
> browser path fail until it was worked around with scrolling, re-dismissing
> and a scripted click. Over HTTP that problem does not exist at all.

### How matches are paired

Predictions are matched to Kicktipp games by **fixture** — both the home *and*
away team must match. Team names are normalised first (`TSG Hoffenheim` and
`1899 Hoffenheim` become the same key), with a per-league alias file for the
rest. If a game cannot be matched confidently, it is reported by name and
skipped — never guessed. Kicktipp bonus questions are skipped the same way.

This is also what makes several competitions work: the predictions of every
configured competition go into one pool, and the pairing decides. No matchday
numbers have to line up — which is just as well, since Kicktipp's numbering is
the group's own and matches neither competition's.

Should the same pairing appear twice — Bayern vs Dortmund exists in the league
*and* in the cup — the kickoff date decides. If even that leaves it open, the
game is reported as ambiguous and left untipped rather than guessed.

### Legacy script

`BL-Tipp.py` is the original single-file version. It still works and is kept as
a fallback, but it is no longer developed.

The bot will:

1. Open predicd.com and fetch the latest predictions
2. Log into your Kicktipp account
3. Fill in and submit all match predictions
4. Exit with code `0` on success or `1` on failure

### Example Output

```
11:23:45 [INFO] ==================================================
11:23:45 [INFO] BL-Tipp gestartet
11:23:45 [INFO] ==================================================
11:23:46 [INFO] Öffne predicd.com …
11:23:48 [INFO] Cookie-Banner akzeptiert.
11:23:52 [INFO] Predictions für Spieltag 18
11:23:53 [INFO]   FC Bayern München vs RB Leipzig → 2:1
11:23:53 [INFO]   Borussia Dortmund vs VfB Stuttgart → 2:0
11:23:55 [INFO] 9 Vorhersagen geladen.
11:24:05 [INFO] Anmeldung gesendet.
11:24:12 [INFO] Spieltag 18 bestätigt – trage Tipps ein …
11:24:13 [INFO] 9 / 9 Tipps eingetragen.
11:24:14 [INFO] Tipps erfolgreich abgesendet!
11:24:17 [INFO] ==================================================
11:24:17 [INFO] Fertig – alle Tipps gespeichert!
11:24:17 [INFO] ==================================================
```

---

## Project Structure

```
Kicktipp-Autopilot/
├── kicktipp_autopilot/
│   ├── cli.py            # Command line: arguments and dispatch
│   ├── runner.py         # The actual run: match, render, submit, one or many groups
│   ├── interactive.py    # The menu behind -i
│   ├── config.py         # .env + config.toml + league registry
│   ├── models.py         # Prediction, Fixture, MatchResult
│   ├── strategy.py       # Optional tip strategies (odds -> adjusted score)
│   ├── errors.py         # Typed errors
│   ├── selectors.py      # ALL CSS selectors, with verification dates
│   ├── sources/
│   │   └── predicd.py    # Prediction scraping over plain HTTP (no browser)
│   ├── matching/
│   │   ├── normalize.py  # "1. FSV Mainz 05" -> "mainz"
│   │   ├── matcher.py    # Fixture-based pairing, never guesses
│   │   └── aliases/      # Per-league name aliases
│   └── targets/
│       ├── base.py           # Shared interface for both transports
│       ├── kicktipp_parse.py # HTML -> objects (shared, offline-testable)
│       ├── kicktipp_http.py  # Default transport: plain HTTP
│       └── kicktipp.py       # Fallback transport: Selenium
├── tests/                # 279 tests, run fully offline
│   ├── test_mehrere_ligen.py  # Groups with several competitions
│   ├── test_alle_gruppen.py   # --all-groups: loop, isolation, summary
│   ├── test_interaktiv.py     # The menu, with questionary stubbed out
│   ├── test_strategy.py       # Tip strategies, from odds to the verified submit
│   ├── test_ueberschreiben.py # ueberschreiben in config.toml vs. --(no-)overwrite
│   └── fixtures/         # Saved HTML pages (anonymised)
├── kicktipp              # Launcher script (symlinked into ~/.local/bin)
├── BL-Tipp.py            # Original single-file version (fallback)
├── pyproject.toml        # Package metadata and `kicktipp` entry point
├── requirements.txt      # Pinned dependencies
├── example.env           # Template for environment variables
├── example.config.toml   # Template for the group/competition mapping
├── .gitignore            # Ignores .env, config.toml, .venv and other local files
├── plan.md               # Development roadmap
└── README.md             # You are here
```

## Tests

```bash
pytest -q
```

All tests run offline against saved HTML fixtures — no network, no browser, no
credentials. If predicd or Kicktipp change their layout, the tests fail before a
wrong tip can reach your account.

The Kicktipp fixtures are anonymised: e-mail, display name, user ID, season ID
and the group name are replaced; only the structure is real. The Champions
League fixture comes from a real Bundesliga+CL group whose season had already
ended, so its result cells carried no input fields any more — those were
restored from the tippable Bundesliga page of the same account. Everything else
is untouched.

The most important tests cover the **submit body**. Kicktipp processes the tip
form as a whole — any field missing from the POST counts as cleared. That
includes the answers to the bonus questions, so the body is always rebuilt from
the page that was just read, never assembled by hand.

---

## Disclaimer

This project is intended for **personal and educational use only**. Use it responsibly and in accordance with the terms of service of both predicd.com and Kicktipp. The authors are not responsible for any misuse or consequences arising from the use of this software.
Furthermore, the script depends on the website predicd.com. The layout may change at any time, which would cause the script to stop working. This programme was last tested in February 2026.
