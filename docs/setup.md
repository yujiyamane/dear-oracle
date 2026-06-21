# Setup

## Prerequisites

- Python 3.10+ (standard library only — no pip installs for runtime)
- Google account — required only for the GAS delivery adapter (optional; SMTP is the server-less alternative)

## Running the Predictor

```
python oracle.py "Who will win the 2026 World Cup?"
```

Works on first clone with no config. If `config/interests.json` exists it filters results to your tracked interests; cold (no file) it ranks by market volume.

## Running the daily pipeline

```
python core/run_daily.py
```

Collects market snapshots, computes deltas, checks thresholds, and writes the day's letter to `data/letters/`. Reads `config/delivery.json` for the delivery adapter.

## Config

Copy the examples and fill in your values:

```
cp config/delivery.example.json config/delivery.json
cp config/interests.example.json config/interests.json
```

`config/delivery.json` — set `adapter` to `"gas"` or `"smtp"` and fill in the corresponding block. Both files are gitignored.

## Delivery adapters

**GAS (default)** — deploy `delivery/gas/01_dear_oracle.js` as a Google Apps Script web app (see the inline comments for deployment steps). Paste the deployment URL into `config/delivery.json` → `gas.webapp_url`. The daily runner writes the letter HTML to the Drive-for-Desktop synced folder at `drive_letters_path`; the GAS `doGet` endpoint reads and serves it; `MailApp` sends the digest email.

**SMTP** — set `adapter: "smtp"` and fill in `config/delivery.json` → `smtp`. Run `delivery/smtp/send.py` after the daily runner. No Google account required.

## Task Scheduler (Windows)

The `scripts/` directory contains ready-made wrappers:

- `scripts/run_daily.bat` — runs `python core/run_daily.py` from the repo root
- `scripts/run_daily_hidden.vbs` — launches the `.bat` without a console window

**Task name:** `DearOracle-Daily`  
**Trigger:** daily at 04:30 local time (AEST), `StartWhenAvailable`, `WakeToRun`  
**Action:** `wscript.exe "C:\Users\Admin\Documents\Life\repos\dear-oracle\scripts\run_daily_hidden.vbs"`  
**Log:** `data/logs/dear-oracle.log`

The scan step (DK Watchlist → Polymarket → `do_hits.json`) runs first inside `run_daily.py`, so `do_hits.json` lands on Drive before DK's GAS trigger fires at ~05:13.

To register with the recommended settings (no battery restrictions, StartWhenAvailable, WakeToRun):

```powershell
$xml = @'
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>2026-06-23T04:30:00</StartBoundary>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Settings>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <WakeToRun>true</WakeToRun>
    <ExecutionTimeLimit>PT30M</ExecutionTimeLimit>
    <RunLevel>LeastPrivilege</RunLevel>
  </Settings>
  <Actions>
    <Exec>
      <Command>wscript.exe</Command>
      <Arguments>"C:\Users\Admin\Documents\Life\repos\dear-oracle\scripts\run_daily_hidden.vbs"</Arguments>
    </Exec>
  </Actions>
</Task>
'@
Register-ScheduledTask -TaskName 'DearOracle-Daily' -Xml $xml -Force
```

## Tests

```
pip install pytest
python -m pytest
```

The test suite uses in-memory SQLite and fixture files — no live API calls, no Google credentials needed.
