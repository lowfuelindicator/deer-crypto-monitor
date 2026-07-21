# Deer Crypto Monitor

Local mining portfolio dashboard for XMRig fleets — Stockie-inspired UI, MoneroOcean pool stats, AI hashrate forecast, candlesticks, hardware sensors, and Windows fan control options.

**Version:** 1.2.0

---

## Quick start (development)

```powershell
cd "C:\Users\notmy\Desktop\menero esta"
pip install -r requirements.txt
python deer_crypto_monitor.py
```

Or:

```powershell
python xmrig_web_ui.py.py
```

Open **http://127.0.0.1:5000** (browser opens automatically by default).

Point **Settings → Miners** at your XMRig HTTP API (default `http://127.0.0.1:8080/1/summary`).

---

## Export for anyone (Windows Setup Wizard)

This project can compile itself into a Windows installer wizard so others install with Next → Next → Finish.

### One command

```powershell
cd "C:\Users\notmy\Desktop\menero esta"
powershell -ExecutionPolicy Bypass -File .\build_release.ps1
```

### What you get

| Output | Path |
|--------|------|
| App folder (EXE) | `dist\DeerCryptoMonitor\DeerCryptoMonitor.exe` |
| Portable ZIP | `dist\DeerCryptoMonitor-Portable-1.2.0.zip` |
| **Setup Wizard** | `dist\installer\DeerCryptoMonitor-Setup-1.2.0.exe` |

### Setup wizard requirements

1. **Python 3.10+** on the *build* machine (end users do **not** need Python).
2. Run `build_release.ps1` once — it installs Flask / Requests / PyInstaller.
3. For the full **Setup.exe wizard**, install [Inno Setup 6](https://jrsoftware.org/isinfo.php) (free), then re-run the script.

Without Inno Setup you still get:

- Portable ZIP
- `Install-Portable.bat` inside the app folder (copies to `%LOCALAPPDATA%` + Desktop shortcut)

### Wizard features

- Welcome / install path / Start Menu group  
- Optional Desktop shortcut  
- Optional “Start when I log in”  
- Optional “Open dashboard in browser after install”  
- Launch app on finish  
- Clean uninstall from Windows Apps & Features  

---

## Settings customization

Open **Settings** in the UI:

### Branding
- Window title, brand name, logo letters (e.g. `DC`)
- Tagline, portfolio hero label

### Look & feel
- Dark / light theme  
- Color presets: Stockie, Monero, Ocean, Sunset, Violet, or custom accents  
- Density (compact / comfortable / spacious)  
- Font scale (90–130%)  
- Card corner radius  
- Background style  
- Currency symbol  

### Layout visibility
- Portfolio hero, watchlist, holdings, details, footer  
- Chart fill / smooth curves  
- Compact numbers (1.8k H/s)  
- Reduce motion  

### App behavior
- Open browser on start  
- Start with Windows (user login)  

### Mining / AI / pool / hardware
- Multi-miner URLs, poll intervals, LAN bind  
- AI classic / neural + realtime accuracy  
- History: JSON or improved SQLite  
- MoneroOcean wallet  
- Windows sensors / Lenovo fan tools (opt-in warnings)  

---

## Data files (per install)

Stored next to the EXE (or script folder):

- `dashboard_settings.json` — settings  
- `mining_history.json` or `mining_history.db` — history  
- `pool_cache.json` — pool cache  

---

## Notes

- Dashboard is **monitoring only** — XMRig must expose its HTTP API.  
- Fan / power control is optional and can affect thermals; use carefully.  
- Earnings are estimates, not financial advice.  

---

## License / use

Local personal / fleet tooling. Package and share the Setup wizard as needed.
