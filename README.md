# Argus Ticker

A small desktop watchlist with live prices for stocks and crypto, built to run
as a single Windows `.exe` (it also runs on macOS/Linux from source).

- **Crypto:** live stream from Coinbase's public feed (no account needed).
  Change is over the last 24 hours.
- **Stocks:** Alpaca market-data snapshots with your own API keys, refreshed
  every 5 s by default. Change is since the previous close. Stocks are polled
  instead of streamed because an Alpaca account gets a single stock stream,
  which another program (e.g. a trading bot) may already be using.
- **Watchlist:** add, edit, delete and reorder entries. Each entry can have a
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

Get `ArgusTicker.exe` from the repo's **Releases** page. To update, close the
app and replace the exe with the new one — the watchlist, settings and keys are
stored outside the exe and are kept. With *Check for updates at startup* on
(Settings), the app says when a newer release exists (only possible while the
releases are publicly visible; Help → Check for updates tells you if it can't look).

## Releasing a new version

1. Bump `__version__` in `ticker/__init__.py` and commit.
2. Tag and push: `git tag v0.3.0 && git push origin v0.3.0`.

The tag build runs the tests, checks the tag matches `__version__`, builds the
exe and publishes it as a GitHub Release. Pushes to `main` also build the exe
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
| `ticker/providers/coinbase.py` | Coinbase WebSocket + REST |
| `ticker/providers/alpaca.py` | Alpaca snapshot polling |
| `ticker/quotes.py` | Runs providers on a background asyncio loop, batches updates to the UI |
| `ticker/ui/` | Main window, table model, dialogs |
