# Argus Ticker

A small desktop watchlist with live prices for stocks and crypto, built to run
as a single Windows `.exe` (it also runs on macOS/Linux from source).

- **Crypto:** live stream from Coinbase's public feed (no account needed).
  Change is over the last 24 hours.
- **Stocks:** Alpaca market-data snapshots with your own API keys, refreshed
  every 5 s by default. Change is since the previous close. Stocks are polled
  instead of streamed because an Alpaca account gets a single stock stream,
  which another program (e.g. a trading bot) may already be using.
- **Four live views** (pick one from the top bar, View menu or tray icon; the
  app remembers it):
  - **Cards** — a tile per asset: big price, change, 24 h / last-session trend line.
  - **List** — clean rows grouped into crypto and stocks, trend line and a % badge.
  - **Floating widget** — small always-on-top panel; click a row to make it the
    headline, drag to move.
  - **Ticker strip** — full-width scrolling bar at the top or bottom of the
    screen (right-click: position, speed); pauses while the mouse is over it.

  The widget and strip stay up until closed from their right-click menu, so
  they can run alongside the main window or on their own. Trend lines: crypto
  = last 24 h (Coinbase 15-minute candles), stocks = last regular session
  (Alpaca 15-minute bars), refreshed every 5 minutes. Settings → *Up / down
  colors* offers green/red or blue/orange.
- **Watchlist (Edit view):** add, edit, delete and reorder entries. Each entry can have a
  name, notes and price alerts (above / below), which pop up a Windows
  notification once per crossing.

## Run from source

```
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m ticker
```

Open **Settings** to enter your Alpaca API key and secret (free account at
alpaca.markets — paper-trading keys work). They are stored in Windows
Credential Manager, never in a file. For development you can set
`ALPACA_API_KEY` / `ALPACA_SECRET_KEY` instead. The free plan's data feed is
**IEX**; choose **SIP** only if your Alpaca plan includes it.

The watchlist lives in `%APPDATA%\ArgusTicker\ticker.db`
(`~/.argus-ticker/ticker.db` elsewhere).

- **Market status:** the status bar shows whether the US market is open,
  pre-market, after hours or closed (holidays and early closes from Alpaca's
  calendar); stock rows are greyed while the regular session is closed.
- **Export / import** the watchlist as JSON or CSV (File menu) — for backups
  or moving to another PC. Import adds new entries and skips ones already there.

## Download and update

Get `ArgusTicker.exe` from the repo's **Releases** page and run it from a
folder you own (Desktop, Documents, …) so it can update itself.

**Updates:** at startup (Settings → *Check for updates at startup*) or from
Help → Check for updates, the app looks for a newer release. **Download and
install** fetches the new exe, checks it against the release's SHA-256
checksum, swaps it in and restarts — the watchlist, settings and keys live
outside the exe and are kept. You can also update by hand: close the app and
replace the exe.

## Releasing a new version

1. Bump `__version__` in `ticker/__init__.py` and commit.
2. Tag and push: `git tag v0.3.0 && git push origin v0.3.0`.

The tag build runs the tests, checks the tag matches `__version__`, builds the
exe and publishes it with its `ArgusTicker.exe.sha256` as a GitHub Release —
installed apps offer it on their next update check. Pushes to `main` also build the exe
(Actions → Windows build → artifact *ArgusTicker-windows*).

### Changing the database

The watchlist database carries a version (`PRAGMA user_version`). To change
the schema, append a step to `MIGRATIONS` in `ticker/db.py` — never edit a
released step. Each install upgrades itself on startup; an older app refuses
to open a database made by a newer one instead of damaging it.

## Build on a Windows PC

```
pip install -r requirements-dev.txt
pyinstaller --noconfirm --onefile --windowed --name ArgusTicker --collect-submodules keyring.backends --collect-data tzdata run_ticker.py
```

The exe isn't code-signed, so Windows SmartScreen will warn on first launch
(More info → Run anyway).

## Development

```
pip install -r requirements-dev.txt
python -m pytest -q
```

| Path | What |
|---|---|
| `ticker/db.py` | SQLite watchlist (CRUD, ordering, migrations) |
| `ticker/transfer.py` | Export / import (JSON, CSV) |
| `ticker/market.py` | Market session from Alpaca's clock and calendar |
| `ticker/updates.py` | Update check against GitHub Releases |
| `ticker/selfupdate.py` | Download, verify and swap in a new exe |
| `ticker/providers/coinbase.py` | Coinbase WebSocket + REST |
| `ticker/providers/alpaca.py` | Alpaca snapshot polling |
| `ticker/quotes.py` | Runs providers on a background asyncio loop, batches updates to the UI |
| `ticker/ui/state.py` | Shared live state the views draw from |
| `ticker/ui/live_views.py` | Cards and List views (painted) |
| `ticker/ui/overlays.py` | Floating widget and ticker strip windows |
| `ticker/ui/theme.py` | Colors, fonts, trend-line painting |
| `ticker/ui/` (rest) | Main window, edit table, dialogs |
