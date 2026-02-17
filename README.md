# ⚽ Kicktipp Autopilot

**Automatically predict Bundesliga matches — powered by data, not gut feeling.**

Kicktipp Autopilot is a Python bot that fetches score predictions from [predicd.com](https://www.predicd.com) and automatically submits them to your [Kicktipp](https://www.kicktipp.de) fantasy league. Set it up once, run it each matchday, and let the data do the work.

---

## Features

- **Automated predictions** — Scrapes match forecasts from predicd.com and enters them into Kicktipp with zero manual input
- **Smart team name mapping** — Translates team names between platforms (e.g. *Bayer Leverkusen* → *Bayer 04 Leverkusen*)
- **Matchday validation** — Verifies that predictions and Kicktipp are on the same matchday before submitting
- **Retry logic** — Automatically retries up to 3 times with a 5-second delay on failure
- **Cookie banner handling** — Gracefully dismisses cookie consent popups on both websites
- **Structured logging** — Clear, timestamped log output so you always know what's happening

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

- **Python 3.8+**
- **Google Chrome** (installed on your system)
- **ChromeDriver** (matching your Chrome version) — [Download here](https://googlechromelabs.github.io/chrome-for-testing/)

---

## Installation

1. **Clone the repository**

   ```bash
   git clone https://github.com/TrustPaddy/Kicktipp-Autopilot.git
   cd Kicktipp-Autopilot
   ```

2. **Install dependencies**

   ```bash
   pip install selenium python-dotenv
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

---

## Configuration

| Variable            | Description                          | Required |
|---------------------|--------------------------------------|----------|
| `KICKTIPP_EMAIL`    | Your Kicktipp account email address  | Yes      |
| `KICKTIPP_PASSWORD` | Your Kicktipp account password       | Yes      |
| `KICKTIPP_GROUP`    | Your Kicktipp group/league name (as it appears in the URL) | Yes      |

---

## Usage

```bash
python BL-Tipp.py
```

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
├── BL-Tipp.py      # Main automation script
├── example.env      # Template for environment variables
├── .gitignore       # Ignores .env and other local files
└── README.md        # You are here
```

---

## Disclaimer

This project is intended for **personal and educational use only**. Use it responsibly and in accordance with the terms of service of both predicd.com and Kicktipp. The authors are not responsible for any misuse or consequences arising from the use of this software.
