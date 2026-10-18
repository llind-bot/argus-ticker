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

## Windows .exe

Every push to `main` builds `ArgusTicker.exe` on GitHub Actions (Actions →
Windows build → artifact *ArgusTicker-windows*). To build it on a Windows PC:

```
pip install -r requirements-dev.txt
pyinstaller --noconfirm --onefile --windowed --name ArgusTicker --collect-submodules keyring.backends run_ticker.py
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
| `ticker/db.py` | SQLite watchlist (CRUD, ordering) |
| `ticker/providers/coinbase.py` | Coinbase WebSocket + REST |
| `ticker/providers/alpaca.py` | Alpaca snapshot polling |
| `ticker/quotes.py` | Runs providers on a background asyncio loop, batches updates to the UI |
| `ticker/ui/` | Main window, table model, dialogs |
