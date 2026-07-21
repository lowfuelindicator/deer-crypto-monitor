"""
Deer Crypto Monitor — local mining portfolio dashboard.
Multi-miner · MoneroOcean · AI forecast · candlesticks · Windows installable.
"""
import json
import math
import os
import statistics
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta

import requests
from flask import Flask, jsonify, render_template_string, request

APP_NAME = "Deer Crypto Monitor"
APP_VERSION = "1.2.0"
APP_SLUG = "DeerCryptoMonitor"

app = Flask(__name__)


def _app_base_dir():
    """Writable app data dir — next to .exe when frozen, else script folder."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = _app_base_dir()
HISTORY_FILE = os.path.join(BASE_DIR, "mining_history.json")
SETTINGS_FILE = os.path.join(BASE_DIR, "dashboard_settings.json")
POOL_CACHE_FILE = os.path.join(BASE_DIR, "pool_cache.json")

XMR_ATOMIC = 1e12  # MoneroOcean amounts are in atomic units
MO_API = "https://api.moneroocean.stream"

DEFAULT_MINER = {
    "id": "miner-1",
    "name": "Local XMRig",
    "url": "http://127.0.0.1:8080/1/summary",
    "enabled": True,
}

DEFAULT_SETTINGS = {
    "poll_seconds": 6,
    "history_keep": 2500,
    "history_backend": "json",  # json (default) | sqlite (improved)
    "ai_realtime": True,  # classic AI multi-task realtime accuracy
    "bind_host": "127.0.0.1",
    "bind_port": 5000,
    "pool_fee_factor": 0.91,
    "earnings_factor": 0.58,
    "fallback_xmr_per_kh": 0.00092,
    "price_fallback": 165.0,
    # UI theme colors (buttons, logo, badges) — separate from chart colors
    "theme_accent": "#12B76A",
    "theme_accent2": "#4E7CFF",
    "refresh_ui_ms": 5000,
    "ai_forecast_enabled": True,
    "ai_mode": "classic",  # classic | neural | hybrid
    "neural_net_enabled": False,
    "nn_mode": "balanced",  # balanced | aggressive | conservative | deep | custom
    "nn_hidden": 10,
    "nn_lr": 0.025,
    "nn_epochs": 50,
    "nn_window": 16,
    "nn_classic_blend": 0.55,  # weight of classic in hybrid (0–1)
    "nn_train_pairs": 120,
    "nn_clip": 2.5,  # normalized forecast clip
    "ai_price_intel_enabled": False,  # optional: live XMR trend fetch (slower)
    "price_provider": "auto",  # auto | cryptocompare | coinpaprika | kraken | binance | coincap | coingecko
    "predict_horizon_min": 60,
    "predict_lookback": 120,
    "dashboard_title": APP_NAME,
    "show_price_chart": True,
    "show_earnings_card": True,
    "ui_mode": "default",  # default | pro | minimal
    "miners": [dict(DEFAULT_MINER)],
    "xmrig_api_url": "http://127.0.0.1:8080/1/summary",
    # Pool (MoneroOcean)
    "pool_enabled": False,
    "pool_provider": "moneroocean",
    "pool_wallet": "",
    "pool_poll_seconds": 30,
    # Charts
    "chart_mode": "line",  # line | candle
    "candle_interval_sec": 60,
    "candle_metric": "hashrate",  # hashrate | xmr
    # Separate chart series colors (do not overwrite UI theme)
    "chart_hs_color": "#12B76A",
    "chart_price_color": "#F79009",
    "chart_forecast_color": "#4E7CFF",
    "chart_fill": True,
    "chart_smooth": True,
    # Hardware / Windows (optional — read mostly; control is cautious)
    "hw_sensors_enabled": True,
    "pc_vendor": "auto",  # auto | dell | hp | lenovo | asus | msi | acer | generic
    "windows_mode_enabled": False,
    "windows_fan_control_enabled": False,  # dangerous-ish; opt-in + warning
    "ai_fan_control_enabled": False,  # classic or neural AI may nudge fan/power profile
    "request_admin": False,  # re-launch elevated for sensors / Lenovo fan tools
    "fan_profile": "balanced",  # eco | balanced | performance | max_hash
    "lenovo_fan_control_path": "",  # path to LenovoFanControl-x64.exe (optional)
    # ── Branding & customization (Deer Crypto Monitor) ──
    "brand_name": APP_NAME,
    "brand_tagline": "Crypto mining portfolio monitor",
    "logo_letters": "DC",
    "portfolio_label": "Fleet portfolio · hashrate",
    "theme_mode": "dark",  # dark | light
    "color_preset": "stockie",  # stockie | monero | ocean | sunset | violet | custom
    "density": "comfortable",  # comfortable | compact | spacious
    "font_scale": 100,  # 90–130 %
    "card_radius": 20,  # 8–28
    "background_style": "soft_glow",  # solid | soft_glow
    "reduced_motion": False,
    "show_watchlist": True,
    "show_holdings": True,
    "show_details": True,
    "show_footer": True,
    "show_portfolio_hero": True,
    "number_compact": False,
    "currency_symbol": "$",
    "open_browser_on_start": True,
    "start_with_windows": False,
}

NN_MODE_PRESETS = {
    # hidden, window, epochs, lr, classic_blend, train_pairs, clip
    "balanced": (10, 16, 50, 0.025, 0.55, 120, 2.5),
    "aggressive": (16, 12, 80, 0.04, 0.35, 160, 3.0),
    "conservative": (8, 20, 30, 0.015, 0.75, 80, 2.0),
    "deep": (24, 24, 100, 0.02, 0.45, 200, 2.8),
    "custom": None,
}

COLOR_PRESETS = {
    "stockie": ("#12B76A", "#4E7CFF"),
    "monero": ("#FF6600", "#F2A900"),
    "ocean": ("#0EA5E9", "#6366F1"),
    "sunset": ("#F97316", "#EC4899"),
    "violet": ("#A855F7", "#22D3EE"),
    "custom": None,
}

PRICE_PROVIDERS = (
    "auto",
    "cryptocompare",
    "coinpaprika",
    "kraken",
    "binance",
    "coincap",
    "coingecko",
)

HISTORY = []
SETTINGS = dict(DEFAULT_SETTINGS)
_last_miners = []
_last_price = None
_last_pool = None
_last_price_intel = None
_last_price_intel_ts = 0.0
_last_price_intel_ok = None  # last successful intel (for stale fallback on 429)
_last_hw = None
_last_hw_ts = 0.0
_nn_state = None  # trained weights cache
_lock = threading.Lock()
_updater_stop = threading.Event()
_last_pool_fetch = 0.0
# Lenovo EnergyDrv fan worker (direct driver, not GUI spam)
_lfc_worker_stop = threading.Event()
_lfc_worker_thread = None
_lfc_worker_mode = None  # "low" | "high" | "normal" | None
_lfc_last_applied_profile = None
_lfc_last_apply_ts = 0.0
_lfc_pending_profile = None
_lfc_pending_count = 0
_lfc_min_change_sec = 300  # don't thrash fan modes (5 min)
_lfc_thermal_hold_until = 0.0  # sticky emergency cool-down window
_lfc_thermal_enter_c = 99.0  # only emergency at near-critical
_lfc_thermal_exit_c = 88.0  # wide hysteresis so mining heat doesn't bounce
_last_hw_bg_ts = 0.0
_cached_pred = None
_cached_pred_ts = 0.0
_cached_pred_live_hs = None
_sqlite_conn = None
_sqlite_lock = threading.Lock()
_json_dirty = False
_json_last_save_ts = 0.0
_last_offline_hist_ts = 0.0
HISTORY_DB = os.path.join(BASE_DIR, "mining_history.db")


# ── persistence ──────────────────────────────────────────────────────────────

def _normalize_miners(raw):
    miners = []
    if not isinstance(raw, list):
        return [dict(DEFAULT_MINER)]
    for i, m in enumerate(raw):
        if not isinstance(m, dict):
            continue
        url = str(m.get("url") or "").strip()
        if not url:
            continue
        mid = str(m.get("id") or f"miner-{i+1}-{uuid.uuid4().hex[:6]}")
        name = str(m.get("name") or f"Miner {i+1}").strip() or f"Miner {i+1}"
        enabled = m.get("enabled", True)
        if isinstance(enabled, str):
            enabled = enabled.lower() in ("1", "true", "yes", "on")
        miners.append(
            {
                "id": mid,
                "name": name[:64],
                "url": url[:300],
                "enabled": bool(enabled),
            }
        )
    return miners[:24] if miners else [dict(DEFAULT_MINER)]


def load_settings():
    global SETTINGS
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            SETTINGS = {**DEFAULT_SETTINGS, **saved}
        except Exception:
            SETTINGS = dict(DEFAULT_SETTINGS)
    else:
        SETTINGS = dict(DEFAULT_SETTINGS)

    # Migrate old product name
    old_titles = ("XMRig Ops", "xmrig ops", "XMRig Ops Dashboard")
    if str(SETTINGS.get("dashboard_title") or "") in old_titles:
        SETTINGS["dashboard_title"] = APP_NAME
    if not SETTINGS.get("brand_name") or SETTINGS.get("brand_name") in old_titles:
        SETTINGS["brand_name"] = APP_NAME
    if str(SETTINGS.get("logo_letters") or "").upper() in ("XO", ""):
        SETTINGS["logo_letters"] = "DC"

    if not SETTINGS.get("miners") and SETTINGS.get("xmrig_api_url"):
        SETTINGS["miners"] = [
            {
                "id": "miner-1",
                "name": "Local XMRig",
                "url": SETTINGS["xmrig_api_url"],
                "enabled": True,
            }
        ]
    SETTINGS["miners"] = _normalize_miners(SETTINGS.get("miners"))
    enabled = [m for m in SETTINGS["miners"] if m.get("enabled")]
    if enabled:
        SETTINGS["xmrig_api_url"] = enabled[0]["url"]
    SETTINGS["pool_wallet"] = str(SETTINGS.get("pool_wallet") or "").strip()
    SETTINGS["pool_enabled"] = bool(SETTINGS.get("pool_enabled")) and bool(
        SETTINGS["pool_wallet"]
    )
    # Apply UI color preset only when not custom (never touch chart colors here)
    preset = str(SETTINGS.get("color_preset") or "stockie").lower()
    if preset != "custom" and preset in COLOR_PRESETS and COLOR_PRESETS[preset]:
        a, b = COLOR_PRESETS[preset]
        SETTINGS["theme_accent"] = a
        SETTINGS["theme_accent2"] = b
    # Apply neural mode preset if not custom
    nn_mode = str(SETTINGS.get("nn_mode") or "balanced").lower()
    if nn_mode != "custom" and nn_mode in NN_MODE_PRESETS and NN_MODE_PRESETS[nn_mode]:
        h, w, ep, lr, blend, pairs, clip = NN_MODE_PRESETS[nn_mode]
        SETTINGS["nn_hidden"] = h
        SETTINGS["nn_window"] = w
        SETTINGS["nn_epochs"] = ep
        SETTINGS["nn_lr"] = lr
        SETTINGS["nn_classic_blend"] = blend
        SETTINGS["nn_train_pairs"] = pairs
        SETTINGS["nn_clip"] = clip


def save_settings():
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(SETTINGS, f, indent=2)
    except Exception:
        pass


def _sqlite():
    global _sqlite_conn
    import sqlite3

    if _sqlite_conn is None:
        _sqlite_conn = sqlite3.connect(HISTORY_DB, check_same_thread=False, timeout=30)
        try:
            _sqlite_conn.execute("PRAGMA journal_mode=WAL")
            _sqlite_conn.execute("PRAGMA synchronous=NORMAL")
            _sqlite_conn.execute("PRAGMA temp_store=MEMORY")
        except Exception:
            pass
        _sqlite_conn.execute(
            """
            CREATE TABLE IF NOT EXISTS samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                hs REAL,
                price REAL,
                xmr_daily REAL,
                usd_daily REAL,
                pool_due REAL,
                pool_hs REAL,
                online_count INTEGER,
                offline INTEGER DEFAULT 0,
                by_miner TEXT
            )
            """
        )
        _sqlite_conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_samples_ts ON samples(ts)"
        )
        _sqlite_conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_samples_offline_hs ON samples(offline, hs)"
        )
        _sqlite_conn.commit()
    return _sqlite_conn


def migrate_json_to_sqlite(force=False):
    """One-way import of JSON history into SQLite (keeps JSON as backup)."""
    if not os.path.exists(HISTORY_FILE):
        return 0
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            rows = json.load(f)
    except Exception:
        return 0
    if not rows:
        return 0
    with _sqlite_lock:
        conn = _sqlite()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM samples")
        existing = cur.fetchone()[0]
        if existing > 0 and not force:
            return 0  # already has data
        n = 0
        for h in rows:
            try:
                hs = float(h.get("hs") or 0)
            except (TypeError, ValueError):
                hs = 0.0
            offline = 1 if h.get("offline") or hs <= 1.0 else 0
            cur.execute(
                """
                INSERT INTO samples (ts, hs, price, xmr_daily, usd_daily, pool_due, pool_hs, online_count, offline, by_miner)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    h.get("time"),
                    h.get("hs"),
                    h.get("price"),
                    h.get("xmr_daily"),
                    h.get("usd_daily"),
                    h.get("pool_due_xmr"),
                    h.get("pool_hs"),
                    h.get("online_count"),
                    offline,
                    json.dumps(h.get("by_miner") or {}),
                ),
            )
            n += 1
        conn.commit()
        return n


def load_history():
    global HISTORY
    backend = str(SETTINGS.get("history_backend") or "json").lower()
    keep = int(SETTINGS.get("history_keep", 2500))
    if backend == "sqlite":
        # SQLite can hold much more; allow higher cap for accuracy
        keep = max(keep, min(20000, keep * 2 if keep < 5000 else keep))
        try:
            migrated = migrate_json_to_sqlite()
            if migrated:
                print(f"Migrated {migrated} JSON samples → SQLite")
            with _sqlite_lock:
                conn = _sqlite()
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT ts, hs, price, xmr_daily, usd_daily, pool_due, pool_hs, online_count, offline, by_miner
                    FROM samples ORDER BY id DESC LIMIT ?
                    """,
                    (keep,),
                )
                rows = cur.fetchall()
            HISTORY = []
            for r in reversed(rows):
                try:
                    bm = json.loads(r[9] or "{}")
                except Exception:
                    bm = {}
                try:
                    hs_v = float(r[1] or 0)
                except (TypeError, ValueError):
                    hs_v = 0.0
                HISTORY.append(
                    {
                        "time": r[0],
                        "hs": r[1],
                        "price": r[2],
                        "xmr_daily": r[3],
                        "usd_daily": r[4],
                        "pool_due_xmr": r[5],
                        "pool_hs": r[6],
                        "online_count": r[7],
                        "offline": bool(r[8]) or hs_v <= 1.0,
                        "by_miner": bm,
                    }
                )
            print(f"Loaded {len(HISTORY)} history records (SQLite)")
            return
        except Exception as e:
            print(f"SQLite load failed, falling back to JSON: {e}")

    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                HISTORY = json.load(f)
            # normalize offline flags for chart/AI accuracy
            for h in HISTORY:
                try:
                    if float(h.get("hs") or 0) <= 1.0:
                        h["offline"] = True
                except (TypeError, ValueError):
                    h["offline"] = True
            print(f"Loaded {len(HISTORY)} history records (JSON)")
        except Exception:
            HISTORY = []
    else:
        HISTORY = []


def append_history(row):
    """Append one sample to memory + configured backend."""
    global HISTORY, _json_dirty, _json_last_save_ts, _last_offline_hist_ts
    # Throttle offline zeros — they wreck chart scale + AI if spammed every poll
    try:
        hs_v = float(row.get("hs") or 0)
    except (TypeError, ValueError):
        hs_v = 0.0
    if row.get("offline") or hs_v <= 1.0:
        now = time.time()
        if now - _last_offline_hist_ts < 45:
            return
        _last_offline_hist_ts = now
        row = dict(row)
        row["hs"] = 0.0
        row["offline"] = True
    else:
        # Skip near-duplicate consecutive samples (noise) for cleaner charts
        if HISTORY:
            prev = HISTORY[-1]
            try:
                prev_hs = float(prev.get("hs") or 0)
            except (TypeError, ValueError):
                prev_hs = 0.0
            if (
                not prev.get("offline")
                and prev_hs > 1
                and abs(prev_hs - hs_v) < max(8.0, 0.004 * hs_v)
            ):
                try:
                    prev_price = float(prev.get("price") or 0)
                    cur_price = float(row.get("price") or 0)
                except (TypeError, ValueError):
                    prev_price = cur_price = 0
                if abs(prev_price - cur_price) < 0.05:
                    # still refresh last point time/price lightly for freshness
                    prev["time"] = row.get("time") or prev.get("time")
                    if row.get("price") is not None:
                        prev["price"] = row.get("price")
                    return

    HISTORY.append(row)
    keep = int(SETTINGS.get("history_keep", 2500))
    backend = str(SETTINGS.get("history_backend") or "json").lower()
    if backend == "sqlite":
        keep = max(keep, min(20000, keep if keep >= 2500 else keep * 2))
    while len(HISTORY) > keep:
        HISTORY.pop(0)

    if backend == "sqlite":
        try:
            with _sqlite_lock:
                conn = _sqlite()
                conn.execute(
                    """
                    INSERT INTO samples (ts, hs, price, xmr_daily, usd_daily, pool_due, pool_hs, online_count, offline, by_miner)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        row.get("time"),
                        row.get("hs"),
                        row.get("price"),
                        row.get("xmr_daily"),
                        row.get("usd_daily"),
                        row.get("pool_due_xmr"),
                        row.get("pool_hs"),
                        row.get("online_count"),
                        1 if row.get("offline") or hs_v <= 1.0 else 0,
                        json.dumps(row.get("by_miner") or {}),
                    ),
                )
                # prune occasionally (every ~40 inserts) for speed
                if len(HISTORY) % 40 == 0:
                    conn.execute(
                        """
                        DELETE FROM samples WHERE id NOT IN (
                            SELECT id FROM samples ORDER BY id DESC LIMIT ?
                        )
                        """,
                        (keep,),
                    )
                conn.commit()
        except Exception as e:
            print(f"sqlite append error: {e}")
    else:
        # Debounced JSON write — full rewrite every sample was slow
        _json_dirty = True
        now = time.time()
        if now - _json_last_save_ts >= 8.0:
            save_history_json()
            _json_last_save_ts = now
            _json_dirty = False


def save_history_json():
    keep = int(SETTINGS.get("history_keep", 2500))
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(HISTORY[-keep:], f)
    except Exception:
        pass


def save_history():
    """Compat alias / flush dirty JSON."""
    global _json_dirty, _json_last_save_ts
    if str(SETTINGS.get("history_backend") or "json").lower() == "sqlite":
        return
    save_history_json()
    _json_dirty = False
    _json_last_save_ts = time.time()


def switch_history_backend(new_backend):
    """Switch JSON ↔ SQLite and reload memory. Returns status dict."""
    global HISTORY, _sqlite_conn
    new_backend = (new_backend or "json").lower()
    if new_backend not in ("json", "sqlite"):
        new_backend = "json"
    old = str(SETTINGS.get("history_backend") or "json").lower()
    if old == "json" and _json_dirty:
        save_history()
    SETTINGS["history_backend"] = new_backend
    migrated = 0
    if new_backend == "sqlite" and old != "sqlite":
        migrated = migrate_json_to_sqlite(force=False)
    load_history()
    return {
        "ok": True,
        "backend": new_backend,
        "samples": len(HISTORY),
        "migrated": migrated,
        "warning": (
            "SQLite migrated existing JSON once. Switching back will NOT auto-export SQLite→JSON. "
            "Keep mining_history.json as backup."
            if new_backend == "sqlite"
            else "Using default JSON storage."
        ),
    }


# ── data sources ─────────────────────────────────────────────────────────────

def fetch_xmrig_url(url, timeout=3):
    """
    Returns (data_dict_or_None, error_string_or_None).
    """
    try:
        r = requests.get(url, timeout=timeout)
        if r.status_code == 200:
            try:
                return r.json(), None
            except Exception:
                return None, "invalid JSON from XMRig"
        if r.status_code in (401, 403):
            return None, f"HTTP {r.status_code} — enable unrestricted HTTP API or set access token"
        return None, f"HTTP {r.status_code}"
    except requests.exceptions.ConnectionError:
        return None, "connection refused — is XMRig running with HTTP API?"
    except requests.exceptions.Timeout:
        return None, "timeout talking to XMRig"
    except Exception as e:
        return None, str(e)[:120]


def _extract_xmrig_hashrate(data):
    """XMRig total[0] is often null at startup — fall through 60s / 15m / highest."""
    hr = (data or {}).get("hashrate") or {}
    total = hr.get("total") or []
    for v in total:
        if v is not None:
            try:
                fv = float(v)
                if fv >= 0:
                    return fv
            except (TypeError, ValueError):
                pass
    for key in ("highest", "total"):
        v = hr.get(key)
        if isinstance(v, (int, float)):
            return float(v)
    # thread sum fallback
    threads = hr.get("threads") or []
    s = 0.0
    n = 0
    for t in threads:
        if isinstance(t, (list, tuple)) and t and t[0] is not None:
            s += float(t[0])
            n += 1
        elif isinstance(t, (int, float)):
            s += float(t)
            n += 1
    return s if n else 0.0


def parse_miner_snapshot(miner_cfg, data, err=None):
    snap = {
        "id": miner_cfg["id"],
        "name": miner_cfg["name"],
        "url": miner_cfg["url"],
        "enabled": True,
        "online": False,
        "hashrate": 0.0,
        "uptime": 0,
        "shares_good": 0,
        "shares_total": 0,
        "algo": "—",
        "worker": "—",
        "pool": "—",
        "error": err,
    }
    if not data:
        snap["error"] = err or "unreachable"
        return snap
    if "hashrate" not in data and "results" not in data:
        snap["error"] = err or "unexpected XMRig response"
        return snap
    hs = _extract_xmrig_hashrate(data)
    results = data.get("results", {}) or {}
    conn = data.get("connection", {}) or {}
    # Consider online if we got a valid summary (even hs=0 while starting)
    snap.update(
        {
            "online": True,
            "hashrate": float(hs),
            "uptime": conn.get("uptime", 0) or data.get("uptime", 0) or 0,
            "shares_good": results.get("shares_good", 0) or 0,
            "shares_total": results.get("shares_total", results.get("shares_good", 0))
            or 0,
            "algo": data.get("algo") or data.get("algorithm") or "rx/0",
            "worker": (
                data.get("worker_id")
                or data.get("id")
                or conn.get("ip")
                or miner_cfg["name"]
            ),
            "pool": conn.get("pool") or "—",
            "error": None if hs > 0 else "online but hashrate 0 (warming up?)",
        }
    )
    return snap


def poll_all_miners():
    miners = _normalize_miners(SETTINGS.get("miners"))
    snaps = []
    for m in miners:
        if not m.get("enabled", True):
            snaps.append(
                {
                    "id": m["id"],
                    "name": m["name"],
                    "url": m["url"],
                    "enabled": False,
                    "online": False,
                    "hashrate": 0.0,
                    "uptime": 0,
                    "shares_good": 0,
                    "shares_total": 0,
                    "algo": "—",
                    "worker": "—",
                    "pool": "—",
                    "error": "disabled",
                }
            )
            continue
        data, err = fetch_xmrig_url(m["url"])
        snaps.append(parse_miner_snapshot(m, data, err))
    return snaps


def fetch_xmr_price():
    """Lightweight spot price — prefer free resilient providers (avoid CG 429)."""
    for name in ("coinpaprika", "kraken", "binance", "coincap", "cryptocompare", "coingecko"):
        try:
            data = _provider_fetch(name)
            if data and data.get("ok") and data.get("price"):
                return float(data["price"])
        except Exception:
            continue
    return None


def _trend_from_ch24(ch24):
    if ch24 is None:
        return "unknown"
    if float(ch24) > 1.0:
        return "up"
    if float(ch24) < -1.0:
        return "down"
    return "flat"


def _pack_intel(provider, price, ch24=None, ch7=None, high=None, low=None, mcap=None, sparkline=None):
    return {
        "ok": True,
        "provider": provider,
        "price": float(price) if price is not None else None,
        "change_24h_pct": round(float(ch24), 3) if ch24 is not None else None,
        "change_7d_pct": round(float(ch7), 3) if ch7 is not None else None,
        "high_24h": float(high) if high is not None else None,
        "low_24h": float(low) if low is not None else None,
        "market_cap": float(mcap) if mcap is not None else None,
        "trend": _trend_from_ch24(ch24),
        "sparkline": sparkline or [],
        "error": None,
        "stale": False,
        "fetched_at": datetime.now().isoformat(),
    }


def _provider_fetch(name):
    """Fetch XMR market intel from a single provider. Returns pack or {ok:False,error}."""
    name = (name or "").lower().strip()
    try:
        if name == "cryptocompare":
            r = requests.get(
                "https://min-api.cryptocompare.com/data/pricemultifull"
                "?fsyms=XMR&tsyms=USD",
                timeout=8,
            )
            if r.status_code != 200:
                return {"ok": False, "error": f"CryptoCompare HTTP {r.status_code}", "provider": name}
            raw = ((r.json() or {}).get("RAW") or {}).get("XMR", {}).get("USD") or {}
            if not raw.get("PRICE"):
                return {"ok": False, "error": "CryptoCompare empty", "provider": name}
            return _pack_intel(
                name,
                raw.get("PRICE"),
                ch24=raw.get("CHANGEPCT24HOUR"),
                high=raw.get("HIGH24HOUR"),
                low=raw.get("LOW24HOUR"),
                mcap=raw.get("MKTCAP"),
            )

        if name == "coinpaprika":
            r = requests.get("https://api.coinpaprika.com/v1/tickers/xmr-monero", timeout=8)
            if r.status_code != 200:
                return {"ok": False, "error": f"CoinPaprika HTTP {r.status_code}", "provider": name}
            j = r.json() or {}
            q = (j.get("quotes") or {}).get("USD") or {}
            if q.get("price") is None:
                return {"ok": False, "error": "CoinPaprika empty", "provider": name}
            return _pack_intel(
                name,
                q.get("price"),
                ch24=q.get("percent_change_24h"),
                ch7=q.get("percent_change_7d"),
                mcap=q.get("market_cap"),
            )

        if name == "kraken":
            r = requests.get(
                "https://api.kraken.com/0/public/Ticker?pair=XMRUSD",
                timeout=8,
            )
            if r.status_code != 200:
                return {"ok": False, "error": f"Kraken HTTP {r.status_code}", "provider": name}
            result = (r.json() or {}).get("result") or {}
            # key may be XXMRZUSD
            block = None
            for k, v in result.items():
                if "XMR" in k.upper():
                    block = v
                    break
            if not block:
                return {"ok": False, "error": "Kraken empty", "provider": name}
            # c = last trade [price, lot], h = high today/24h, l = low, o = open
            last = float((block.get("c") or [0])[0])
            high = float((block.get("h") or [0, 0])[-1] or (block.get("h") or [0])[0])
            low = float((block.get("l") or [0, 0])[-1] or (block.get("l") or [0])[0])
            open_p = float(block.get("o") or last)
            ch24 = ((last - open_p) / open_p) * 100 if open_p else None
            return _pack_intel(name, last, ch24=ch24, high=high, low=low)

        if name == "binance":
            r = requests.get(
                "https://api.binance.com/api/v3/ticker/24hr?symbol=XMRUSDT",
                timeout=8,
            )
            if r.status_code != 200:
                return {"ok": False, "error": f"Binance HTTP {r.status_code}", "provider": name}
            j = r.json() or {}
            last = j.get("lastPrice")
            if last is None:
                return {"ok": False, "error": "Binance empty / delisted?", "provider": name}
            return _pack_intel(
                name,
                float(last),
                ch24=j.get("priceChangePercent"),
                high=j.get("highPrice"),
                low=j.get("lowPrice"),
            )

        if name == "coincap":
            r = requests.get("https://api.coincap.io/v2/assets/monero", timeout=8)
            if r.status_code != 200:
                return {"ok": False, "error": f"CoinCap HTTP {r.status_code}", "provider": name}
            d = (r.json() or {}).get("data") or {}
            if d.get("priceUsd") is None:
                return {"ok": False, "error": "CoinCap empty", "provider": name}
            return _pack_intel(
                name,
                float(d["priceUsd"]),
                ch24=d.get("changePercent24Hr"),
                mcap=d.get("marketCapUsd"),
            )

        if name == "coingecko":
            # Prefer lightweight simple price + optional chart (heavy endpoints rate-limit hard)
            r = requests.get(
                "https://api.coingecko.com/api/v3/simple/price"
                "?ids=monero&vs_currencies=usd"
                "&include_24hr_change=true&include_24hr_vol=false",
                timeout=8,
            )
            if r.status_code == 429:
                return {"ok": False, "error": "CoinGecko HTTP 429 (rate limited)", "provider": name}
            if r.status_code != 200:
                return {"ok": False, "error": f"CoinGecko HTTP {r.status_code}", "provider": name}
            mon = (r.json() or {}).get("monero") or {}
            price = mon.get("usd")
            ch24 = mon.get("usd_24h_change")
            if price is None:
                return {"ok": False, "error": "CoinGecko empty", "provider": name}
            return _pack_intel(name, price, ch24=ch24)

        return {"ok": False, "error": f"Unknown provider {name}", "provider": name}
    except Exception as e:
        return {"ok": False, "error": str(e), "provider": name}


def fetch_xmr_price_intel(force=False):
    """
    Multi-provider XMR market intel with cache + stale fallback.
    Provider from settings: auto tries resilient sources first (avoids CG 429).
    """
    global _last_price_intel, _last_price_intel_ts, _last_price_intel_ok
    import time as _time

    now = _time.time()
    cache_ttl = 600  # 10 min fresh cache
    stale_ttl = 3600  # serve last good for 1h if all fail

    if (
        not force
        and _last_price_intel
        and _last_price_intel.get("ok")
        and (now - _last_price_intel_ts) < cache_ttl
    ):
        return _last_price_intel

    provider = str(SETTINGS.get("price_provider") or "auto").lower().strip()
    if provider not in PRICE_PROVIDERS:
        provider = "auto"

    # Prefer free resilient feeds first (CoinGecko rate-limits; CryptoCompare may need API key)
    order = (
        ["coinpaprika", "kraken", "binance", "coincap", "cryptocompare", "coingecko"]
        if provider == "auto"
        else [provider]
    )

    errors = []
    for name in order:
        data = _provider_fetch(name)
        if data and data.get("ok") and data.get("price"):
            _last_price_intel = data
            _last_price_intel_ts = now
            _last_price_intel_ok = dict(data)
            return data
        if data:
            errors.append(f"{name}: {data.get('error') or 'fail'}")

    # Stale successful cache
    if _last_price_intel_ok and (now - _last_price_intel_ts) < stale_ttl:
        stale = dict(_last_price_intel_ok)
        stale["stale"] = True
        stale["error"] = None
        stale["note"] = "Serving cached intel (providers busy/rate-limited)"
        stale["errors"] = errors
        _last_price_intel = stale
        return stale

    out = {
        "ok": False,
        "provider": provider,
        "price": None,
        "change_24h_pct": None,
        "change_7d_pct": None,
        "high_24h": None,
        "low_24h": None,
        "market_cap": None,
        "trend": "unknown",
        "sparkline": [],
        "error": "All providers failed: " + "; ".join(errors[:4]),
        "errors": errors,
        "stale": False,
        "fetched_at": datetime.now().isoformat(),
    }
    _last_price_intel = out
    _last_price_intel_ts = now
    return out


def estimate_earnings(hashrate):
    if hashrate is None or hashrate <= 0:
        return 0.0
    factor = float(SETTINGS.get("earnings_factor", 0.58))
    # Try network difficulty from MoneroOcean-compatible endpoints
    for url in (
        f"{MO_API}/network/stats",
        "https://moneroocean.stream/api/network/stats",
    ):
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                data = r.json()
                diff = data.get("difficulty") or data.get("network", {}).get("difficulty")
                if diff:
                    return (hashrate * 86400) / (float(diff) * 2.0) * factor
        except Exception:
            pass
    return (hashrate / 1000) * float(SETTINGS.get("fallback_xmr_per_kh", 0.00092))


def fetch_moneroocean_wallet(address):
    """Pull due balance, paid, hashrate, workers from MoneroOcean."""
    address = (address or "").strip()
    if not address or len(address) < 90:
        return {
            "ok": False,
            "error": "Enter a valid Monero wallet address in Settings",
            "provider": "moneroocean",
        }

    out = {
        "ok": False,
        "provider": "moneroocean",
        "wallet": address,
        "wallet_short": address[:8] + "…" + address[-6:],
        "hashrate": 0.0,
        "amt_due_xmr": 0.0,
        "amt_paid_xmr": 0.0,
        "amt_due_atomic": 0,
        "amt_paid_atomic": 0,
        "valid_shares": 0,
        "invalid_shares": 0,
        "total_hashes": 0,
        "workers": [],
        "workers_online": 0,
        "workers_total": 0,
        "last_share_ts": None,
        "fetched_at": datetime.now().isoformat(),
        "error": None,
    }

    try:
        r = requests.get(f"{MO_API}/miner/{address}/stats", timeout=8)
        if r.status_code != 200:
            out["error"] = f"Pool returned HTTP {r.status_code}"
            return out
        s = r.json()
        due = float(s.get("amtDue") or 0)
        paid = float(s.get("amtPaid") or 0)
        out.update(
            {
                "ok": True,
                "hashrate": float(s.get("hash") or s.get("hash2") or 0),
                "amt_due_atomic": due,
                "amt_paid_atomic": paid,
                "amt_due_xmr": round(due / XMR_ATOMIC, 8),
                "amt_paid_xmr": round(paid / XMR_ATOMIC, 8),
                "valid_shares": int(s.get("validShares") or 0),
                "invalid_shares": int(s.get("invalidShares") or 0),
                "total_hashes": float(s.get("totalHashes") or 0),
                "last_share_ts": s.get("lastHash"),
                "last_share_algo": s.get("lastShareAlgo"),
            }
        )
    except Exception as e:
        out["error"] = str(e)
        return out

    try:
        rw = requests.get(f"{MO_API}/miner/{address}/stats/allWorkers", timeout=8)
        if rw.status_code == 200:
            workers_raw = rw.json() or {}
            workers = []
            now = datetime.now().timestamp()
            for name, w in workers_raw.items():
                if name == "global":
                    continue
                lts = w.get("lts") or 0
                # consider online if share within ~15 min
                online = (now - float(lts)) < 900 if lts else False
                workers.append(
                    {
                        "name": name,
                        "hashrate": float(w.get("hash") or w.get("hash2") or 0),
                        "valid_shares": int(w.get("validShares") or 0),
                        "invalid_shares": int(w.get("invalidShares") or 0),
                        "algo": w.get("lastShareAlgo") or "—",
                        "last_share_ts": lts,
                        "online": online,
                    }
                )
            workers.sort(key=lambda x: x["hashrate"], reverse=True)
            out["workers"] = workers
            out["workers_total"] = len(workers)
            out["workers_online"] = sum(1 for w in workers if w["online"])
    except Exception:
        pass

    return out


# ── local hashrate prediction ────────────────────────────────────────────────

def _linear_regression(xs, ys):
    n = len(xs)
    if n < 2:
        return 0.0, (ys[-1] if ys else 0.0)
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs) or 1.0
    return num / den, my - (num / den) * mx


def _sigmoid(x):
    x = max(-30.0, min(30.0, x))
    return 1.0 / (1.0 + math.exp(-x))


def _relu(x):
    return x if x > 0 else 0.0


def _active_hash_samples(history, lookback=120, max_age_sec=None, live_hs=None, regime_pct=0.35):
    """
    Positive hashrate points only. When live_hs is set, prefer the current
    mining regime (samples near live) so old low/high sessions can't stick the AI.
    """
    hist = history if history is not None else HISTORY
    lookback = int(lookback or 120)
    cutoff = None
    if max_age_sec is not None:
        cutoff = datetime.now() - timedelta(seconds=max_age_sec)
    live = None
    try:
        if live_hs is not None and float(live_hs) > 1.0:
            live = float(live_hs)
    except (TypeError, ValueError):
        live = None

    raw = []  # (hs, age_weight index)
    scan = hist[-max(lookback * 4, lookback, 80) :]
    for h in scan:
        if h.get("offline"):
            continue
        if cutoff is not None:
            try:
                t = datetime.fromisoformat(h.get("time") or "")
                if t < cutoff:
                    continue
            except Exception:
                continue
        try:
            hs = float(h.get("hs"))
        except (TypeError, ValueError):
            continue
        if hs > 1.0:
            raw.append(hs)

    if not raw:
        return []

    if live is not None:
        lo = live * (1.0 - regime_pct)
        hi = live * (1.0 + regime_pct)
        regime = [v for v in raw if lo <= v <= hi]
        # Prefer last ~20 min worth: if regime is thin, widen once
        if len(regime) < 8:
            lo2 = live * 0.55
            hi2 = live * 1.55
            regime = [v for v in raw if lo2 <= v <= hi2]
        if len(regime) >= 4:
            raw = regime
        # Always append live so series ends at truth
        raw = (raw + [live])[-lookback:]
    else:
        raw = raw[-lookback:]
    return raw


def _mining_is_live(history, local_hs=0.0, pool_hs=0.0, pool_workers_online=0, grace_sec=120):
    """
    True only if something is actually hashing right now (or very recently).
    Prevents sticky ~750 H/s after miner + pool go idle.
    """
    if (local_hs or 0) > 1.0:
        return True
    if (pool_workers_online or 0) > 0 and (pool_hs or 0) > 1.0:
        return True
    # recent positive sample in history?
    recent = _active_hash_samples(history, lookback=5, max_age_sec=grace_sec)
    return bool(recent)


def live_display_hashrate(local_online, local_hs, pool_stats):
    """Single source of truth for the big hashrate number."""
    local_hs = float(local_hs or 0)
    if local_online and local_hs > 1.0:
        return local_hs
    # Local online but 0 (starting) — show 0, not stale pool
    if local_online:
        return max(0.0, local_hs)
    ps = pool_stats or {}
    if not ps.get("ok"):
        return 0.0
    pool_hs = float(ps.get("hashrate") or 0)
    workers_on = int(ps.get("workers_online") or 0)
    # Pool often keeps a stale hashrate for a while; require live workers
    if workers_on > 0 and pool_hs > 1.0:
        return pool_hs
    return 0.0


def _reanchor_prediction(pred, live_hs):
    """Shift cached/stale forecast so UI + chart track live hashrate immediately."""
    if not pred or not isinstance(pred, dict) or not pred.get("ok"):
        return pred
    try:
        live = float(live_hs)
    except (TypeError, ValueError):
        return pred
    if live <= 1.0:
        return pred
    out = dict(pred)
    old_live = out.get("live_hs")
    try:
        old_live = float(old_live) if old_live is not None else None
    except (TypeError, ValueError):
        old_live = None
    old_pred = float(out.get("predicted_avg_hs") or live)
    # Scale forecast around live so it never sticks far from reality
    if old_live and old_live > 1 and abs(old_live - live) > 1:
        scale = live / old_live
        # blend: mostly live + residual trend from previous prediction
        residual = (old_pred - old_live) * min(1.2, max(0.4, scale))
        new_pred = live + residual * 0.55
    else:
        new_pred = 0.72 * live + 0.28 * old_pred
    # clamp mild band around live
    new_pred = max(live * 0.82, min(live * 1.22, new_pred))
    out["predicted_avg_hs"] = round(new_pred, 2)
    out["live_hs"] = round(live, 2)
    out["recent_avg_hs"] = round(
        0.6 * live + 0.4 * float(out.get("recent_avg_hs") or live), 2
    )
    out["ewma_hs"] = round(0.55 * live + 0.45 * float(out.get("ewma_hs") or live), 2)
    out["current_avg_hs"] = round(
        0.5 * live + 0.5 * float(out.get("current_avg_hs") or live), 2
    )
    if live:
        out["trend_pct"] = round(((new_pred - live) / live) * 100.0, 2)
    # Rebuild projected path from live → target with fresh timestamps (chart line)
    poll = max(3, float(SETTINGS.get("poll_seconds", 6)))
    horizon_min = int(out.get("horizon_min") or SETTINGS.get("predict_horizon_min", 60))
    n_pts = max(12, min(36, len(out.get("projected") or []) or 24))
    target = new_pred
    # mild direction bias so the line isn't perfectly flat
    try:
        trend = float(out.get("trend_pct") or 0) / 100.0
    except (TypeError, ValueError):
        trend = 0.0
    end_target = target * (1.0 + max(-0.06, min(0.06, trend)))
    rebuilt = []
    base_time = datetime.now()
    step_sec = max(poll, (horizon_min * 60) / n_pts)
    for i in range(n_pts):
        t = (i + 1) / n_pts
        # ease-out from live to end_target
        ease = 1.0 - (1.0 - t) ** 1.6
        x = live + (end_target - live) * ease
        x = max(live * 0.78, min(live * 1.28, x))
        rebuilt.append(
            {
                "time": (base_time + timedelta(seconds=step_sec * (i + 1))).isoformat(),
                "hs": round(x, 2),
            }
        )
    out["projected"] = rebuilt
    horizons = dict(out.get("horizons") or {})
    if horizons:
        for k, v in list(horizons.items()):
            try:
                vv = float(v)
                # pull each horizon toward live + small residual
                horizons[k] = round(0.65 * live + 0.35 * vv, 2)
            except (TypeError, ValueError):
                pass
        out["horizons"] = horizons
    out["summary"] = (
        f"Realtime forecast {new_pred:,.0f} H/s · live {live:,.0f} · "
        f"{out.get('trend_pct', 0):+.1f}% · {out.get('direction', 'flat')} · "
        f"n={out.get('points_used', 0)}"
    )
    return out


def predict_hashrate_classic(history=None, lookback=None, horizon_min=None, live_hs=None):
    """
    Realtime multi-task classic AI:
    - Hard live anchor (instant response — no slow crawl from old sessions)
    - Parallel tasks: momentum, volatility, jump detect, multi-horizon, slope
    - Regime filter so stale ~750 H/s history can't stick the forecast
    """
    hist = history if history is not None else HISTORY
    lookback = int(lookback or SETTINGS.get("predict_lookback", 120))
    horizon_min = int(horizon_min or SETTINGS.get("predict_horizon_min", 60))
    realtime = bool(SETTINGS.get("ai_realtime", True))

    live = None
    try:
        if live_hs is not None and float(live_hs) > 1.0:
            live = float(live_hs)
    except (TypeError, ValueError):
        live = None

    # Multi-window sample sets (parallel tasks)
    ys = _active_hash_samples(hist, lookback, max_age_sec=3600 * 4, live_hs=live)
    ys_short = _active_hash_samples(hist, min(24, lookback), max_age_sec=900, live_hs=live)
    ys_med = _active_hash_samples(hist, min(60, lookback), max_age_sec=3600, live_hs=live)

    if live is not None:
        if ys:
            ys = (ys + [live])[-lookback:]
        else:
            ys = [live]
        ys_short = (ys_short + [live])[-24:] if ys_short else [live]
        ys_med = (ys_med + [live])[-60:] if ys_med else [live]

    if not ys:
        return {
            "ok": False,
            "reason": "No active hashrate samples yet",
            "predicted_avg_hs": 0,
            "current_avg_hs": 0,
            "trend_pct": 0,
            "confidence": 0,
            "band_low": 0,
            "band_high": 0,
            "method": "none",
            "horizon_min": horizon_min,
            "points_used": 0,
            "projected": [],
            "direction": "unknown",
            "p_up": 0.5,
            "horizons": {},
        }

    n = len(ys)
    last = ys[-1]
    anchor = live if live is not None else last

    # Task 1: recency-weighted averages (short / med / long)
    def _wavg(arr, exp=4.0):
        m = len(arr)
        if m == 1:
            return arr[0]
        w = [math.exp(exp * (i / max(m - 1, 1))) for i in range(m)]
        s = sum(w) or 1.0
        return sum(arr[i] * w[i] for i in range(m)) / s

    wavg = _wavg(ys, 4.5 if realtime else 2.5)
    ultra = ys_short[-min(8, len(ys_short)) :] if ys_short else ys[-min(6, n) :]
    ultra_avg = sum(ultra) / len(ultra)
    recent = ys_med[-min(20, len(ys_med)) :] if ys_med else ys[-min(15, n) :]
    recent_avg = sum(recent) / len(recent)

    # Task 2: dual EWMA (fast + slow)
    alpha_f = 0.62 if realtime else 0.35
    alpha_s = 0.22 if realtime else 0.12
    ewma_fast = ys[0]
    ewma_slow = ys[0]
    for v in ys[1:]:
        ewma_fast = alpha_f * v + (1 - alpha_f) * ewma_fast
        ewma_slow = alpha_s * v + (1 - alpha_s) * ewma_slow

    # Task 3: slopes (short + medium)
    tail = ys[-min(12, n) :]
    slope_t, _ = _linear_regression(list(range(len(tail))), tail)
    slope_m, _ = _linear_regression(list(range(len(recent))), recent)

    # Task 4: volatility + jump detection
    try:
        std = statistics.pstdev(ys) if n > 1 else 0.0
        std_recent = statistics.pstdev(recent) if len(recent) > 1 else std
    except statistics.StatisticsError:
        std = std_recent = 0.0
    jump = 0.0
    if len(ys) >= 3:
        jump = (ys[-1] - ys[-3]) / (abs(ys[-3]) + 1e-6)

    poll = max(3, float(SETTINGS.get("poll_seconds", 6)))

    # Task 5: multi-horizon targets (anchored to live, mild trend only)
    # Target stays near live — never mean-revert to old session averages
    trend_boost = slope_t * (8 if realtime else 4) + slope_m * 2
    # Clamp trend so one noisy sample doesn't launch rockets
    trend_boost = max(-anchor * 0.08, min(anchor * 0.08, trend_boost))
    base_target = (
        0.55 * anchor
        + 0.25 * ultra_avg
        + 0.12 * ewma_fast
        + 0.08 * (anchor + trend_boost)
    )
    if realtime and live is not None:
        base_target = 0.70 * live + 0.30 * base_target

    def horizon_avg(minutes):
        steps = max(1, int((minutes * 60) / poll))
        # longer horizon → slightly more room for trend, still live-centric
        decay = min(1.0, minutes / 60.0)
        target = base_target + trend_boost * (0.15 + 0.35 * decay)
        vals = []
        x = anchor
        for i in range(1, steps + 1):
            pull = 0.42 if realtime else 0.22
            x = (1 - pull) * x + pull * target + slope_t * 0.08
            lo = anchor * (0.88 if realtime else 0.75)
            hi = anchor * (1.12 if realtime else 1.25) + abs(slope_t) * 3
            x = max(lo, min(hi, x))
            vals.append(max(0.0, x))
        return sum(vals) / len(vals), vals

    predicted_avg, _ = horizon_avg(horizon_min)
    h5, _ = horizon_avg(5)
    h30, _ = horizon_avg(30)
    h60, _ = horizon_avg(60)
    h480, _ = horizon_avg(480)

    # Final predicted: LIVE-FIRST so UI never crawls from a sticky old value
    if realtime and live is not None:
        predicted_avg = (
            0.58 * live
            + 0.18 * ultra_avg
            + 0.12 * h5
            + 0.08 * predicted_avg
            + 0.04 * ewma_fast
        )
    else:
        predicted_avg = 0.40 * anchor + 0.35 * ultra_avg + 0.25 * predicted_avg

    # Task 6: projection path for chart (starts at live, eases to target)
    steps = max(1, min(180, int((horizon_min * 60) / poll)))
    chart_target = 0.65 * predicted_avg + 0.35 * (anchor + trend_boost * 0.5)
    future_vals = []
    x = anchor
    for i in range(1, steps + 1):
        pull = 0.38 if realtime else 0.18
        x = (1 - pull) * x + pull * chart_target + slope_t * 0.1
        lo = anchor * 0.85
        hi = anchor * 1.18 + abs(slope_t) * 4
        x = max(lo, min(hi, x))
        future_vals.append(max(0.0, x))

    # Session-relative current avg (not whole-history drag)
    current_avg = 0.55 * ultra_avg + 0.45 * recent_avg if realtime else wavg
    if live is not None:
        current_avg = 0.45 * live + 0.55 * current_avg

    trend_pct = ((predicted_avg - anchor) / anchor) * 100.0 if anchor else 0.0
    # Task 7: direction ensemble
    mom = (ultra_avg - recent_avg) / (recent_avg + 1e-6)
    mom2 = slope_t / (std_recent + 1e-6)
    live_delta = ((live or last) - recent_avg) / (recent_avg + 1e-6)
    ewma_spread = (ewma_fast - ewma_slow) / (ewma_slow + 1e-6)
    p_up = _sigmoid(
        mom * 9 + mom2 * 2.2 + live_delta * 7 + ewma_spread * 5 + jump * 3
    )
    direction = "up" if p_up > 0.58 else ("down" if p_up < 0.42 else "flat")

    conf = min(
        0.97,
        max(
            0.25,
            (1 - min(std_recent / (ultra_avg + 1e-6), 1.0))
            * min(1.0, n / 20)
            * (0.88 + 0.12 * (1 if live else 0)),
        ),
    )
    band = 1.15 * std_recent * (1.0 + 0.08 * math.sqrt(steps / max(n, 1)))
    # tighter band when realtime-anchored
    if realtime and live is not None:
        band = min(band, live * 0.12 + std_recent * 0.5)

    # Dense enough points for a clear dashed forecast line on the chart
    n_pts = 24
    base_time = datetime.now()
    step_sec = max(poll, (horizon_min * 60) / n_pts)
    projected = []
    for i in range(n_pts):
        # sample along future_vals (or ease live→predicted)
        if future_vals:
            fi = int((i + 1) / n_pts * (len(future_vals) - 1))
            fi = max(0, min(len(future_vals) - 1, fi))
            v = future_vals[fi]
        else:
            t = (i + 1) / n_pts
            v = anchor + (predicted_avg - anchor) * (1.0 - (1.0 - t) ** 1.5)
        if live is not None and i == 0:
            v = 0.9 * live + 0.1 * v
        projected.append(
            {
                "time": (base_time + timedelta(seconds=step_sec * (i + 1))).isoformat(),
                "hs": round(max(0.0, v), 2),
            }
        )

    return {
        "ok": True,
        "predicted_avg_hs": round(predicted_avg, 2),
        "current_avg_hs": round(current_avg, 2),
        "ewma_hs": round(ewma_fast, 2),
        "recent_avg_hs": round(ultra_avg, 2),
        "live_hs": round(live, 2) if live is not None else round(last, 2),
        "trend_pct": round(trend_pct, 2),
        "confidence": round(conf, 3),
        "band_low": round(max(0.0, predicted_avg - band), 2),
        "band_high": round(predicted_avg + band, 2),
        "std_hs": round(std_recent, 2),
        "method": "classic-realtime-multi" if realtime else "classic-ewma",
        "horizon_min": horizon_min,
        "points_used": n,
        "projected": projected,
        "direction": direction,
        "p_up": round(p_up, 3),
        "horizons": {
            "5m": round(h5, 2),
            "30m": round(h30, 2),
            "60m": round(h60, 2),
            "8h": round(h480, 2),
        },
        "tasks": {
            "momentum": round(mom, 4),
            "slope": round(slope_t, 4),
            "slope_med": round(slope_m, 4),
            "volatility": round(std_recent, 2),
            "jump": round(jump, 4),
            "ewma_spread": round(ewma_spread, 4),
            "live_anchor": live is not None,
            "regime_n": n,
        },
        "summary": (
            f"Realtime forecast {predicted_avg:,.0f} H/s ({horizon_min}m) · "
            f"live {anchor:,.0f} · 5m {h5:,.0f} · 60m {h60:,.0f} · "
            f"{trend_pct:+.1f}% · {direction} p↑{p_up * 100:.0f}% · n={n}"
        ),
    }


def predict_hashrate_neural(history=None, lookback=None, horizon_min=None, live_hs=None):
    """
    Tiny pure-Python MLP + classic blend.
    Always anchors to active (non-zero) hashrate so it can't stick at 0.
    """
    global _nn_state
    hist = history if history is not None else HISTORY
    lookback = int(lookback or SETTINGS.get("predict_lookback", 120))
    horizon_min = int(horizon_min or SETTINGS.get("predict_horizon_min", 60))
    # Apply mode presets unless custom
    nn_mode = str(SETTINGS.get("nn_mode") or "balanced").lower()
    if nn_mode != "custom" and nn_mode in NN_MODE_PRESETS and NN_MODE_PRESETS[nn_mode]:
        h0, w0, ep0, lr0, blend0, pairs0, clip0 = NN_MODE_PRESETS[nn_mode]
        window = max(6, min(48, w0))
        hidden = max(4, min(32, h0))
        lr = max(0.001, min(0.2, lr0))
        epochs = max(5, min(200, ep0))
        classic_blend = max(0.05, min(0.95, blend0))
        train_pairs = max(20, min(400, pairs0))
        nn_clip = max(1.0, min(4.0, clip0))
    else:
        window = max(6, min(48, int(SETTINGS.get("nn_window", 16))))
        hidden = max(4, min(32, int(SETTINGS.get("nn_hidden", 10))))
        lr = max(0.001, min(0.2, float(SETTINGS.get("nn_lr", 0.025))))
        epochs = max(5, min(200, int(SETTINGS.get("nn_epochs", 50))))
        try:
            classic_blend = max(0.05, min(0.95, float(SETTINGS.get("nn_classic_blend", 0.55))))
        except (TypeError, ValueError):
            classic_blend = 0.55
        train_pairs = max(20, min(400, int(SETTINGS.get("nn_train_pairs", 120))))
        try:
            nn_clip = max(1.0, min(4.0, float(SETTINGS.get("nn_clip", 2.5))))
        except (TypeError, ValueError):
            nn_clip = 2.5
    # fewer epochs when realtime for lower latency
    if SETTINGS.get("ai_realtime", True):
        epochs = min(epochs, 60 if nn_mode == "deep" else 40)

    classic = predict_hashrate_classic(hist, lookback, horizon_min, live_hs=live_hs)
    samples = _active_hash_samples(hist, lookback, live_hs=live_hs)
    if live_hs is not None:
        try:
            lv = float(live_hs)
            if lv > 1:
                samples = (samples + [lv])[-lookback:]
        except (TypeError, ValueError):
            pass
    if len(samples) < window + 4:
        classic["method"] = "neural-fallback-classic"
        classic["reason"] = f"Need ≥{window + 4} active samples for neural net (have {len(samples)})"
        return classic

    mean = sum(samples) / len(samples)
    try:
        std = statistics.pstdev(samples) if len(samples) > 1 else 1.0
    except statistics.StatisticsError:
        std = 1.0
    std = std if std > 1e-6 else 1.0
    norm = [(v - mean) / std for v in samples]

    X, Y = [], []
    for i in range(window, len(norm)):
        X.append(norm[i - window : i])
        Y.append(norm[i])

    # fresh small init each call if shape mismatch; otherwise reuse
    need_init = (
        not _nn_state
        or _nn_state.get("window") != window
        or _nn_state.get("hidden") != hidden
    )
    if need_init:
        # Xavier-ish small weights
        scale = 0.35 / math.sqrt(window)
        w1 = [
            [((i * 31 + j * 17) % 1000 / 1000.0 - 0.5) * 2 * scale for j in range(hidden)]
            for i in range(window)
        ]
        b1 = [0.0] * hidden
        w2 = [((j * 13) % 1000 / 1000.0 - 0.5) * 0.3 for j in range(hidden)]
        b2 = 0.0
        w3 = [((j * 19) % 1000 / 1000.0 - 0.5) * 0.3 for j in range(hidden)]
        b3 = 0.0
        _nn_state = {
            "w1": w1,
            "b1": b1,
            "w2": w2,
            "b2": b2,
            "w3": w3,
            "b3": b3,
            "window": window,
            "hidden": hidden,
        }
    else:
        w1, b1 = _nn_state["w1"], _nn_state["b1"]
        w2, b2 = _nn_state["w2"], _nn_state["b2"]
        w3, b3 = _nn_state["w3"], _nn_state["b3"]

    def forward(x):
        hvals = []
        for j in range(hidden):
            s = b1[j]
            for i in range(window):
                s += x[i] * w1[i][j]
            hvals.append(_relu(s))
        y = b2 + sum(hvals[j] * w2[j] for j in range(hidden))
        logit = b3 + sum(hvals[j] * w3[j] for j in range(hidden))
        return hvals, y, _sigmoid(logit)

    # train on last N pairs only (speed + recency) — tunable
    pairs = list(zip(X, Y))[-train_pairs:]
    for _ep in range(epochs):
        for xi, yi in pairs:
            hvals, yhat, p_hat = forward(xi)
            err = yhat - yi
            label_up = 1.0 if yi > xi[-1] else 0.0
            d_p = p_hat - label_up
            for j in range(hidden):
                w2[j] -= lr * err * hvals[j]
                w3[j] -= lr * d_p * hvals[j]
            b2 -= lr * err
            b3 -= lr * d_p
            for j in range(hidden):
                if hvals[j] <= 0:
                    continue
                g = err * w2[j] + d_p * w3[j]
                b1[j] -= lr * g
                for i in range(window):
                    w1[i][j] -= lr * g * xi[i]

    _nn_state.update({"w1": w1, "b1": b1, "w2": w2, "b2": b2, "w3": w3, "b3": b3})

    cur = norm[-window:]
    poll = max(3, float(SETTINGS.get("poll_seconds", 6)))
    steps = max(1, min(200, int((horizon_min * 60) / poll)))
    future_norm = []
    p_ups = []
    for _ in range(steps):
        _h, yhat, p_hat = forward(cur)
        # clip normalized forecast — prevent runaway to -inf / 0 after denorm
        yhat = max(-nn_clip, min(nn_clip, yhat))
        future_norm.append(yhat)
        p_ups.append(p_hat)
        cur = cur[1:] + [yhat]

    nn_future = [max(0.0, v * std + mean) for v in future_norm]
    nn_avg = sum(nn_future) / len(nn_future)

    # Blend NN with classic (classic_blend is weight of classic)
    classic_avg = float(classic.get("predicted_avg_hs") or mean)
    recent_avg = sum(samples[-min(20, len(samples)) :]) / min(20, len(samples))
    live_v = None
    try:
        if live_hs is not None and float(live_hs) > 1:
            live_v = float(live_hs)
    except (TypeError, ValueError):
        live_v = None
    nn_w = 1.0 - classic_blend
    predicted_avg = nn_w * nn_avg + classic_blend * classic_avg
    if live_v is not None:
        predicted_avg = 0.50 * live_v + 0.50 * predicted_avg
        predicted_avg = max(live_v * 0.8, min(live_v * 1.25, predicted_avg))
    else:
        predicted_avg = max(recent_avg * 0.55, min(recent_avg * 1.45, predicted_avg))

    # blend projected series similarly
    c_proj = classic.get("projected") or []
    future_vals = []
    anchor = live_v if live_v is not None else recent_avg
    for i in range(len(nn_future)):
        c_hs = c_proj[min(i, len(c_proj) - 1)]["hs"] if c_proj else classic_avg
        v = nn_w * nn_future[i] + classic_blend * c_hs
        v = max(anchor * 0.75, min(anchor * 1.3, v))
        future_vals.append(v)

    current_avg = 0.5 * recent_avg + 0.5 * (live_v or mean)
    try:
        std_raw = statistics.pstdev(samples) if len(samples) > 1 else 0.0
    except statistics.StatisticsError:
        std_raw = 0.0
    trend_base = live_v or current_avg
    trend_pct = ((predicted_avg - trend_base) / trend_base) * 100.0 if trend_base else 0.0
    p_up = sum(p_ups) / len(p_ups) if p_ups else float(classic.get("p_up") or 0.5)
    p_up = 0.5 * p_up + 0.5 * float(classic.get("p_up") or 0.5)
    if predicted_avg > recent_avg * 1.02:
        p_up = min(0.98, p_up + 0.08)
    elif predicted_avg < recent_avg * 0.98:
        p_up = max(0.02, p_up - 0.08)
    direction = "up" if p_up > 0.55 else ("down" if p_up < 0.45 else "flat")
    conf = min(
        0.96,
        max(
            0.25,
            (1 - min(std_raw / (current_avg + 1e-6), 1.0))
            * min(1.0, len(samples) / 50),
        ),
    )
    band = 1.5 * std_raw * (1.0 + 0.12 * math.sqrt(steps / max(len(samples), 1)))
    stride = max(1, len(future_vals) // 24)
    base_time = datetime.now()
    projected = [
        {
            "time": (base_time + timedelta(seconds=poll * (i + 1))).isoformat(),
            "hs": round(future_vals[i], 2),
        }
        for i in range(0, len(future_vals), stride)
    ]
    if projected and live_v is not None:
        projected[0]["hs"] = round(0.88 * live_v + 0.12 * projected[0]["hs"], 2)
    result = {
        "ok": True,
        "predicted_avg_hs": round(predicted_avg, 2),
        "current_avg_hs": round(current_avg, 2),
        "ewma_hs": round(samples[-1], 2),
        "recent_avg_hs": round(recent_avg, 2),
        "live_hs": round(live_v, 2) if live_v is not None else round(samples[-1], 2),
        "trend_pct": round(trend_pct, 2),
        "confidence": round(conf, 3),
        "band_low": round(max(0.0, predicted_avg - band), 2),
        "band_high": round(predicted_avg + band, 2),
        "std_hs": round(std_raw, 2),
        "method": "local-neural-mlp+classic",
        "horizon_min": horizon_min,
        "points_used": len(samples),
        "projected": projected,
        "direction": direction,
        "p_up": round(p_up, 3),
        "horizons": classic.get("horizons") or {},
        "nn": {
            "mode": nn_mode,
            "hidden": hidden,
            "window": window,
            "epochs": epochs,
            "lr": lr,
            "classic_blend": round(classic_blend, 3),
            "train_pairs": train_pairs,
            "clip": nn_clip,
            "raw_nn_avg": round(nn_avg, 2),
            "classic_avg": round(classic_avg, 2),
        },
        "summary": (
            f"Neural ({nn_mode}) forecast {predicted_avg:,.0f} H/s next {horizon_min}m "
            f"(nn {nn_avg:,.0f} · classic {classic_avg:,.0f} · blend {classic_blend:.0%}) · "
            f"{trend_pct:+.1f}% · dir {direction} p↑{p_up * 100:.0f}% · {len(samples)} samples"
        ),
    }
    if live_v is not None:
        result = _reanchor_prediction(result, live_v)
        result["method"] = "local-neural-mlp+classic"
    return result


def predict_hashrate(
    history=None, lookback=None, horizon_min=None, force_offline=False, live_hs=None
):
    hist = history if history is not None else HISTORY
    # Live poll wins: if we have live hash, never force offline
    try:
        live_v = float(live_hs) if live_hs is not None else None
    except (TypeError, ValueError):
        live_v = None
    if live_v is not None and live_v > 1.0:
        force_offline = False
    # If nothing hashed recently and no live, idle at 0
    if force_offline or (
        (live_v is None or live_v <= 1.0)
        and not _active_hash_samples(hist, lookback=8, max_age_sec=180)
    ):
        return {
            "ok": False,
            "reason": "Miner offline / no hashrate in last 3 minutes",
            "predicted_avg_hs": 0,
            "current_avg_hs": 0,
            "ewma_hs": 0,
            "recent_avg_hs": 0,
            "trend_pct": 0,
            "confidence": 0,
            "band_low": 0,
            "band_high": 0,
            "method": "offline",
            "horizon_min": int(horizon_min or SETTINGS.get("predict_horizon_min", 60)),
            "points_used": 0,
            "projected": [],
            "direction": "flat",
            "p_up": 0.5,
            "horizons": {},
            "summary": "No live hashrate — forecast idle at 0 H/s until mining resumes",
        }
    ai_mode = str(SETTINGS.get("ai_mode", "classic")).lower()
    use_nn = bool(SETTINGS.get("neural_net_enabled")) or ai_mode in (
        "neural",
        "hybrid",
    )
    if use_nn:
        try:
            pred = predict_hashrate_neural(
                hist, lookback, horizon_min, live_hs=live_v
            )
            if live_v and live_v > 1 and pred.get("ok"):
                pred = _reanchor_prediction(pred, live_v)
                pred["method"] = pred.get("method") or "local-neural-mlp+classic"
            return pred
        except Exception as e:
            base = predict_hashrate_classic(
                hist, lookback, horizon_min, live_hs=live_v
            )
            base["method"] = "neural-error-classic"
            base["summary"] = (base.get("summary") or "") + f" · NN error fallback ({e})"
            return base
    return predict_hashrate_classic(hist, lookback, horizon_min, live_hs=live_v)


# ── hardware sensors / Windows (optional) ────────────────────────────────────

def _ps(cmd, timeout=6):
    """Run PowerShell, return stdout text or ''."""
    try:
        import subprocess

        r = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                cmd,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return (r.stdout or "").strip()
    except Exception:
        return ""


def detect_pc_vendor():
    """Return manufacturer string + normalized vendor key."""
    raw = _ps(
        "(Get-CimInstance Win32_ComputerSystem).Manufacturer; "
        "(Get-CimInstance Win32_ComputerSystem).Model"
    )
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    mfg = lines[0] if lines else "Unknown"
    model = lines[1] if len(lines) > 1 else ""
    low = (mfg + " " + model).lower()
    if "dell" in low:
        key = "dell"
    elif "hewlett" in low or "hp" in low:
        key = "hp"
    elif "lenovo" in low or "thinkpad" in low:
        key = "lenovo"
    elif "asus" in low:
        key = "asus"
    elif "msi" in low or "micro-star" in low:
        key = "msi"
    elif "acer" in low:
        key = "acer"
    elif "apple" in low:
        key = "apple"
    else:
        key = "generic"
    return {"manufacturer": mfg, "model": model, "vendor_key": key}


def find_lenovo_fan_control(auto_save=True):
    """
    Locate LenovoFanControl-x64.exe (jiarandiana0307/Lenovo-Fan-Control).
    Checks settings path, app folder, Downloads, Desktop, Program Files, etc.
    Optionally saves path into SETTINGS when found.
    """
    global SETTINGS
    configured = (SETTINGS.get("lenovo_fan_control_path") or "").strip().strip('"')
    if configured and os.path.isfile(configured):
        return configured

    home = os.path.expanduser("~")
    names = (
        "LenovoFanControl-x64.exe",
        "LenovoFanControl.exe",
        "Lenovo-Fan-Control-x64.exe",
    )
    roots = [
        BASE_DIR,
        os.path.join(BASE_DIR, "tools"),
        os.path.join(BASE_DIR, "bin"),
        os.path.join(home, "Downloads"),
        os.path.join(home, "Desktop"),
        os.path.join(home, "Documents"),
        os.environ.get("LOCALAPPDATA", ""),
        os.environ.get("USERPROFILE", ""),
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        r"C:\Tools",
        r"C:\Apps",
    ]
    # Direct file guesses
    for root in roots:
        if not root:
            continue
        for name in names:
            p = os.path.join(root, name)
            if os.path.isfile(p):
                if auto_save:
                    SETTINGS["lenovo_fan_control_path"] = p
                    save_settings()
                return p
            p2 = os.path.join(root, "LenovoFanControl", name)
            if os.path.isfile(p2):
                if auto_save:
                    SETTINGS["lenovo_fan_control_path"] = p2
                    save_settings()
                return p2

    # Shallow scan Downloads / Desktop (1 level of folders)
    for folder in (
        os.path.join(home, "Downloads"),
        os.path.join(home, "Desktop"),
    ):
        if not os.path.isdir(folder):
            continue
        try:
            for entry in os.listdir(folder):
                full = os.path.join(folder, entry)
                if os.path.isfile(full) and entry.lower().startswith("lenovofancontrol") and entry.lower().endswith(".exe"):
                    if auto_save:
                        SETTINGS["lenovo_fan_control_path"] = full
                        save_settings()
                    return full
                if os.path.isdir(full):
                    for name in names:
                        p = os.path.join(full, name)
                        if os.path.isfile(p):
                            if auto_save:
                                SETTINGS["lenovo_fan_control_path"] = p
                                save_settings()
                            return p
        except OSError:
            pass
    return ""


def read_hw_sensors():
    """
    Best-effort CPU temp + fan read on Windows.
    Uses ThermalZone, Win32_Fan, LibreHardwareMonitor, and Lenovo Fan Control presence.
    """
    global _last_hw, _last_hw_ts
    import time as _time
    import platform as _platform

    now = _time.time()
    if _last_hw and (now - _last_hw_ts) < 8:
        return _last_hw

    out = {
        "ok": False,
        "platform": _platform.system(),
        "cpu_temp_c": None,
        "temps": [],
        "fans": [],
        "fan_rpm": None,
        "fan_pct": None,
        "cpu_load_pct": None,
        "vendor": detect_pc_vendor(),
        "sensor_source": None,
        "fan_readable": False,
        "fan_controllable": False,
        "lenovo_fan_control": {
            "found": False,
            "path": None,
            "levels": ["--low-speed", "--normal-speed", "--high-speed"],
        },
        "control_notes": [],
        "error": None,
        "admin": is_windows_admin(),
        "fetched_at": datetime.now().isoformat(),
    }

    if out["platform"] != "Windows":
        out["error"] = "Hardware sensors optimized for Windows"
        _last_hw, _last_hw_ts = out, now
        return out

    # CPU load
    load = _ps(
        "try { (Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average } catch { '' }"
    )
    try:
        if load:
            out["cpu_load_pct"] = float(load)
    except ValueError:
        pass

    # Thermal zones (often package-ish / system)
    tz = _ps(
        r"""
        try {
          Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature -ErrorAction SilentlyContinue |
            ForEach-Object { [math]::Round(($_.CurrentTemperature / 10) - 273.15, 1) }
        } catch {}
        """
    )
    temps = []
    for ln in tz.splitlines():
        try:
            t = float(ln.strip())
            if 0 < t < 120:
                temps.append(t)
        except ValueError:
            pass
    if temps:
        out["temps"] = temps
        out["cpu_temp_c"] = max(temps)
        out["sensor_source"] = "MSAcpi_ThermalZoneTemperature"
        out["ok"] = True

    # Win32_Fan (rarely populated)
    fans_raw = _ps(
        r"""
        try {
          Get-CimInstance Win32_Fan -ErrorAction SilentlyContinue |
            ForEach-Object { "$($_.Name)|$($_.DesiredSpeed)|$($_.Status)" }
        } catch {}
        """
    )
    for ln in fans_raw.splitlines():
        parts = ln.split("|")
        if len(parts) >= 2:
            try:
                rpm = float(parts[1]) if parts[1] not in ("", "0") else None
            except ValueError:
                rpm = None
            out["fans"].append({"name": parts[0], "rpm": rpm, "status": parts[2] if len(parts) > 2 else ""})
            if rpm:
                out["fan_rpm"] = rpm
                out["fan_readable"] = True
                out["ok"] = True
                out["sensor_source"] = (out["sensor_source"] or "") + "+Win32_Fan"

    # LibreHardwareMonitor / OpenHardwareMonitor WMI (if running)
    lhm = _ps(
        r"""
        try {
          Get-CimInstance -Namespace root/LibreHardwareMonitor -ClassName Sensor -ErrorAction SilentlyContinue |
            Where-Object { $_.SensorType -in @('Temperature','Fan','Control') } |
            Select-Object -First 40 Name, SensorType, Value |
            ForEach-Object { "$($_.SensorType)|$($_.Name)|$($_.Value)" }
        } catch {}
        try {
          Get-CimInstance -Namespace root/OpenHardwareMonitor -ClassName Sensor -ErrorAction SilentlyContinue |
            Where-Object { $_.SensorType -in @('Temperature','Fan','Control') } |
            Select-Object -First 40 Name, SensorType, Value |
            ForEach-Object { "$($_.SensorType)|$($_.Name)|$($_.Value)" }
        } catch {}
        """
    )
    cpu_temps = []
    for ln in lhm.splitlines():
        parts = ln.split("|")
        if len(parts) < 3:
            continue
        stype, name, val = parts[0], parts[1], parts[2]
        try:
            v = float(val)
        except ValueError:
            continue
        if stype == "Temperature" and ("cpu" in name.lower() or "package" in name.lower() or "core" in name.lower()):
            cpu_temps.append(v)
            out["temps"].append(v)
        elif stype == "Temperature" and v > 0:
            out["temps"].append(v)
        elif stype == "Fan" and v > 0:
            out["fans"].append({"name": name, "rpm": v})
            out["fan_rpm"] = v if out["fan_rpm"] is None else max(out["fan_rpm"], v)
            out["fan_readable"] = True
        elif stype == "Control" and 0 <= v <= 100:
            out["fan_pct"] = v
            out["fan_readable"] = True
    if cpu_temps:
        out["cpu_temp_c"] = max(cpu_temps)
        out["sensor_source"] = "Libre/OpenHardwareMonitor"
        out["ok"] = True
    elif out["temps"] and out["cpu_temp_c"] is None:
        out["cpu_temp_c"] = max(out["temps"])
        out["ok"] = True

    # Lenovo Fan Control tool (control without RPM sensors)
    lfc_path = find_lenovo_fan_control(auto_save=True)
    vk = out["vendor"]["vendor_key"]
    notes = []
    controllable = False

    # Direct EnergyDrv (preferred) + optional GUI path
    edrv = energy_drv_available()
    if lfc_path or edrv or vk == "lenovo":
        out["lenovo_fan_control"] = {
            "found": bool(lfc_path or edrv),
            "path": lfc_path or None,
            "energy_drv": edrv,
            "direct_control": edrv,
            "active_mode": _lfc_worker_mode,
            "levels": ["low", "normal", "high"],
            "maps": {
                "eco": "low",
                "balanced": "normal",
                "performance": "high",
                "max_hash": "high",
            },
            "protocol": "\\\\.\\EnergyDrv IOCTL 0x831020C0 (Lenovo-Fan-Control fanctrl.c)",
        }
        if edrv:
            controllable = True
            out["ok"] = True
            notes.append("EnergyDrv ONLINE — direct fan control (no GUI spam)")
            if _lfc_worker_mode:
                notes.append(f"Active fan mode: {_lfc_worker_mode}")
        elif lfc_path:
            controllable = True
            out["ok"] = True
            notes.append(f"Lenovo Fan Control exe: {lfc_path}")
            notes.append(
                "EnergyDrv not open yet — run as admin for direct control; exe only launched once as fallback"
            )
        if not out["fan_readable"]:
            notes.append(
                "RPM not exposed by Windows (normal on Lenovo). Control uses EnergyDrv levels."
            )
        if not is_windows_admin():
            notes.append("Tip: Request administrator privileges if EnergyDrv fails to open")
    else:
        out["lenovo_fan_control"] = {
            "found": False,
            "path": None,
            "energy_drv": False,
            "levels": ["low", "normal", "high"],
            "hint": "Lenovo EnergyDrv / Fan Control not found",
        }

    if out["fan_readable"]:
        notes.append("Fan sensors readable (WMI/LHM)")
        controllable = True
    elif not lfc_path:
        notes.append(
            "No fan RPM via WMI — optional: LibreHardwareMonitor for RPM; Lenovo Fan Control for control"
        )

    if out["cpu_temp_c"] is None:
        notes.append("CPU temp unavailable via WMI")
    else:
        notes.append(f"CPU temp OK ({out['cpu_temp_c']}°C)")

    if vk in ("dell", "hp", "lenovo", "asus", "msi", "acer"):
        notes.append(f"Vendor profile: {vk.upper()}")

    # Power-plan control always possible on Windows when mode enabled
    if SETTINGS.get("windows_fan_control_enabled") or SETTINGS.get("ai_fan_control_enabled"):
        controllable = True
        notes.append("Windows power-plan control available")

    out["fan_controllable"] = controllable
    out["control_notes"] = notes
    if not out["ok"] and not out["error"]:
        out["error"] = "No thermal/fan sensors detected"
    _last_hw, _last_hw_ts = out, now
    return out


def is_windows_admin():
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def elevate_if_requested():
    """
    If settings.request_admin and not elevated, re-launch with UAC prompt.
    Returns True if this process should exit (child elevated started).
    """
    if not SETTINGS.get("request_admin"):
        return False
    if os.name != "nt":
        return False
    if is_windows_admin():
        return False
    try:
        import ctypes
        import sys

        script = os.path.abspath(__file__)
        params = f'"{script}"'
        # Also pass along if running as module
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, params, os.path.dirname(script), 1
        )
        # ShellExecute returns >32 on success
        return rc > 32
    except Exception as e:
        print(f"Admin elevation failed: {e}")
        return False


def _lenovo_mode_from_profile(profile):
    """Map dashboard profile → low | normal | high (EnergyDrv / LFC semantics)."""
    profile = (profile or "balanced").lower()
    if profile in ("eco",):
        return "low"
    if profile in ("balanced",):
        return "normal"
    return "high"  # performance / max_hash


def _lenovo_fan_args(profile):
    """CLI args for optional tray app (we prefer direct driver now)."""
    m = _lenovo_mode_from_profile(profile)
    return {
        "low": "--low-speed",
        "normal": "--normal-speed",
        "high": "--high-speed",
    }.get(m, "--normal-speed")


# ── Direct EnergyDrv (same protocol as Lenovo-Fan-Control fanctrl.c) ─────────
# Source: https://github.com/jiarandiana0307/Lenovo-Fan-Control
# Device: \\.\EnergyDrv  IOCTL write 0x831020C0  buffer [6, 1, mode]
# mode: NORMAL=0, FAST=1

_ENERGY_IOCTL_WRITE = 0x831020C0
_ENERGY_IOCTL_READ = 0x831020C4
_FAN_NORMAL = 0
_FAN_FAST = 1


def energy_drv_available():
    """True if Lenovo ACPI Virtual Power Controller device opens."""
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        GENERIC_READ = 0x80000000
        OPEN_EXISTING = 3
        FILE_ATTRIBUTE_NORMAL = 0x80
        INVALID = ctypes.c_void_p(-1).value
        h = k32.CreateFileW(
            "\\\\.\\EnergyDrv",
            GENERIC_READ,
            0,
            None,
            OPEN_EXISTING,
            FILE_ATTRIBUTE_NORMAL,
            None,
        )
        if h == INVALID or h is None or int(h) == -1:
            return False
        k32.CloseHandle(h)
        return True
    except Exception:
        return False


def energy_drv_fan_control(mode):
    """
    Write fan mode to EnergyDrv.
    mode: 0 = NORMAL, 1 = FAST (max). Returns True on success.
    """
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        GENERIC_WRITE = 0x40000000
        OPEN_EXISTING = 3
        FILE_ATTRIBUTE_NORMAL = 0x80
        INVALID = ctypes.c_void_p(-1).value

        k32.CreateFileW.restype = wintypes.HANDLE
        h = k32.CreateFileW(
            "\\\\.\\EnergyDrv",
            GENERIC_WRITE,
            0,
            None,
            OPEN_EXISTING,
            FILE_ATTRIBUTE_NORMAL,
            None,
        )
        if h == INVALID or h is None or int(h) == -1:
            return False

        in_buf = (ctypes.c_uint32 * 3)(6, 1, int(mode))
        returned = wintypes.DWORD(0)
        ok = k32.DeviceIoControl(
            h,
            _ENERGY_IOCTL_WRITE,
            ctypes.byref(in_buf),
            ctypes.sizeof(in_buf),
            None,
            0,
            ctypes.byref(returned),
            None,
        )
        k32.CloseHandle(h)
        return bool(ok)
    except Exception:
        return False


def energy_drv_read_state():
    """Read fan state; returns 0/1-ish raw or -1 on failure (best-effort)."""
    if os.name != "nt":
        return -1
    try:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        GENERIC_READ = 0x80000000
        OPEN_EXISTING = 3
        FILE_ATTRIBUTE_NORMAL = 0x80
        INVALID = ctypes.c_void_p(-1).value
        h = k32.CreateFileW(
            "\\\\.\\EnergyDrv",
            GENERIC_READ,
            0,
            None,
            OPEN_EXISTING,
            FILE_ATTRIBUTE_NORMAL,
            None,
        )
        if h == INVALID or h is None or int(h) == -1:
            return -1
        in_buf = (ctypes.c_uint32 * 1)(14)
        out_buf = (ctypes.c_uint32 * 1)(0)
        returned = wintypes.DWORD(0)
        ok = k32.DeviceIoControl(
            h,
            _ENERGY_IOCTL_READ,
            ctypes.byref(in_buf),
            ctypes.sizeof(in_buf),
            ctypes.byref(out_buf),
            ctypes.sizeof(out_buf),
            ctypes.byref(returned),
            None,
        )
        k32.CloseHandle(h)
        return int(out_buf[0]) if ok else -1
    except Exception:
        return -1


def _lfc_worker_loop(mode):
    """
    Background keep-alive matching Lenovo-Fan-Control fanctrl.c:
    - high: re-assert FAST only (never cycle NORMAL — that causes low↔high thrash)
    - low:  periodically force NORMAL
    - normal: single NORMAL then exit
    """
    global _lfc_worker_mode
    try:
        if mode == "normal":
            energy_drv_fan_control(_FAN_NORMAL)
            return
        if mode == "low":
            while not _lfc_worker_stop.is_set():
                energy_drv_fan_control(_FAN_NORMAL)
                if _lfc_worker_stop.wait(8.0):
                    break
            return
        if mode == "high":
            # Stable high only — do NOT drop to NORMAL on stop (prevents thrash)
            while not _lfc_worker_stop.is_set():
                energy_drv_fan_control(_FAN_FAST)
                if _lfc_worker_stop.wait(10.0):
                    break
            # leave fan as-is on exit; next worker/mode decides
    finally:
        if _lfc_worker_mode == mode:
            pass


def stop_lenovo_energy_worker(reset_to_normal=False):
    """Stop worker. Only force NORMAL if explicitly requested (manual stop)."""
    global _lfc_worker_thread, _lfc_worker_mode
    _lfc_worker_stop.set()
    t = _lfc_worker_thread
    if t and t.is_alive():
        t.join(timeout=2.0)
    _lfc_worker_thread = None
    _lfc_worker_mode = None
    if reset_to_normal:
        try:
            energy_drv_fan_control(_FAN_NORMAL)
        except Exception:
            pass


def start_lenovo_energy_worker(mode):
    """Start/replace single background EnergyDrv worker. mode: low|normal|high"""
    global _lfc_worker_thread, _lfc_worker_mode
    mode = (mode or "normal").lower()
    if mode not in ("low", "normal", "high"):
        mode = "normal"
    # Already running desired mode — do nothing (prevents spam/thrash)
    if (
        _lfc_worker_mode == mode
        and _lfc_worker_thread is not None
        and _lfc_worker_thread.is_alive()
    ):
        return {
            "ok": True,
            "method": "energy-drv",
            "mode": mode,
            "skipped": True,
            "detail": "already active",
        }
    # Same high mode without live thread? just restart high without NORMAL blip
    prev = _lfc_worker_mode
    stop_lenovo_energy_worker(reset_to_normal=False)
    if not energy_drv_available():
        return {
            "ok": False,
            "method": "energy-drv",
            "error": "\\\\.\\EnergyDrv not available (Lenovo ACPI driver missing?)",
        }
    _lfc_worker_stop.clear()
    _lfc_worker_mode = mode
    if mode == "normal":
        ok = energy_drv_fan_control(_FAN_NORMAL)
        return {
            "ok": ok,
            "method": "energy-drv",
            "mode": mode,
            "detail": "set NORMAL once",
            "admin": is_windows_admin(),
            "prev_mode": prev,
        }
    # Apply target mode immediately before worker loop (no intermediate NORMAL)
    if mode == "high":
        energy_drv_fan_control(_FAN_FAST)
    elif mode == "low":
        energy_drv_fan_control(_FAN_NORMAL)
    _lfc_worker_thread = threading.Thread(
        target=_lfc_worker_loop, args=(mode,), daemon=True, name="lenovo-energy-fan"
    )
    _lfc_worker_thread.start()
    return {
        "ok": True,
        "method": "energy-drv",
        "mode": mode,
        "detail": f"worker started ({mode})",
        "admin": is_windows_admin(),
        "prev_mode": prev,
        "warning": (
            "Low mode can overheat hardware — use carefully."
            if mode == "low"
            else None
        ),
    }


def apply_lenovo_fan_control(profile=None, force=False):
    """
    Direct EnergyDrv control (wired from Lenovo-Fan-Control source).
    Does NOT spam the GUI exe. Only changes mode when profile changes.
    Optional: launch tray app once if energy-drv fails and exe exists.
    """
    global _lfc_last_applied_profile, _lfc_last_apply_ts
    import time as _time

    profile = (profile or SETTINGS.get("fan_profile") or "balanced").lower()
    mode = _lenovo_mode_from_profile(profile)
    now = _time.time()

    # Debounce: same profile within 15s and worker alive → skip
    if (
        not force
        and _lfc_last_applied_profile == profile
        and (now - _lfc_last_apply_ts) < 15
    ):
        return {
            "ok": True,
            "method": "energy-drv",
            "profile": profile,
            "mode": mode,
            "skipped": True,
            "detail": "same profile recently applied",
        }

    # Prefer direct driver (no GUI process spam)
    if energy_drv_available():
        res = start_lenovo_energy_worker(mode)
        res["profile"] = profile
        if res.get("ok"):
            _lfc_last_applied_profile = profile
            _lfc_last_apply_ts = now
            res["path"] = find_lenovo_fan_control(auto_save=False) or None
            res["note"] = (
                "Direct \\\\.\\EnergyDrv control (same as Lenovo-Fan-Control source). "
                "GUI exe is NOT launched."
            )
        return res

    # Fallback: launch tray app ONCE if driver open failed (e.g. needs admin)
    path = find_lenovo_fan_control(auto_save=True)
    if not path:
        return {
            "ok": False,
            "error": (
                "EnergyDrv unavailable and LenovoFanControl exe not found. "
                "Install Lenovo ACPI driver / run as admin / set exe path."
            ),
            "method": "energy-drv",
        }

    # Only spawn GUI if not already running
    already = _ps(
        "Get-Process -Name 'LenovoFanControl*','LenovoFanControl-x64' -ErrorAction SilentlyContinue | "
        "Select-Object -First 1 -ExpandProperty Id"
    )
    if already.strip():
        _lfc_last_applied_profile = profile
        _lfc_last_apply_ts = now
        return {
            "ok": True,
            "method": "lenovo-gui-already-running",
            "profile": profile,
            "mode": mode,
            "pid": already.strip(),
            "skipped": True,
            "detail": "Lenovo Fan Control already running — not reopening",
            "hint": "Change speed from tray menu, or run dashboard as admin for direct EnergyDrv",
        }

    arg = _lenovo_fan_args(profile)
    try:
        import subprocess

        subprocess.Popen(
            [path, arg],
            cwd=os.path.dirname(path) or BASE_DIR,
        )
        _lfc_last_applied_profile = profile
        _lfc_last_apply_ts = now
        return {
            "ok": True,
            "method": "lenovo-gui-once",
            "profile": profile,
            "arg": arg,
            "path": path,
            "admin": is_windows_admin(),
            "warning": (
                "Launched Lenovo Fan Control GUI once (EnergyDrv open failed). "
                "Prefer Request admin so we can talk to EnergyDrv directly."
            ),
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "method": "lenovo-gui-once", "path": path}


def apply_windows_fan_profile(profile=None, force=False):
    """
    Optional Windows optimization:
    1) powercfg plan (all PCs) — only when profile changes
    2) Lenovo direct EnergyDrv (no exe spam)
    """
    global _lfc_last_applied_profile, _lfc_last_apply_ts
    import time as _time

    profile = (profile or SETTINGS.get("fan_profile") or "balanced").lower()
    if not SETTINGS.get("windows_fan_control_enabled") and not SETTINGS.get(
        "ai_fan_control_enabled"
    ):
        return {"ok": False, "error": "Fan/power control disabled in Settings"}
    if not SETTINGS.get("windows_mode_enabled"):
        return {"ok": False, "error": "Windows mode disabled in Settings"}

    # Global debounce for auto AI loops
    if (
        not force
        and _lfc_last_applied_profile == profile
        and (_time.time() - _lfc_last_apply_ts) < 20
    ):
        return {
            "ok": True,
            "profile": profile,
            "skipped": True,
            "detail": "profile unchanged — not re-applying",
        }

    results = {"ok": True, "profile": profile, "steps": [], "admin": is_windows_admin()}

    plans = {
        "eco": "a1841308-3541-4fab-bc81-f71556f20b4a",
        "balanced": "381b4222-f694-41f0-9685-ff5bb260df2e",
        "performance": "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",
        "max_hash": "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",
    }
    guid = plans.get(profile, plans["balanced"])
    out = _ps(f"powercfg /setactive {guid}; powercfg /getactivescheme")
    if profile == "max_hash":
        _ps(
            "powercfg -duplicatescheme e9a42b02-d5df-448d-aa00-03f14749eb61 2>$null; "
            "$u = powercfg /list | Select-String 'Ultimate'; "
            "if ($u) { $id = ($u -split '\\s+')[3]; if ($id) { powercfg /setactive $id } }"
        )
        out = _ps("powercfg /getactivescheme")
    results["steps"].append({"method": "powercfg", "detail": (out or "")[:240]})

    vendor = (SETTINGS.get("pc_vendor") or "auto").lower()
    hw_vendor = None
    try:
        hw_vendor = (detect_pc_vendor() or {}).get("vendor_key")
    except Exception:
        pass
    if (
        vendor == "lenovo"
        or hw_vendor == "lenovo"
        or SETTINGS.get("lenovo_fan_control_path")
        or energy_drv_available()
    ):
        lv = apply_lenovo_fan_control(profile, force=force)
        results["steps"].append(lv)
        if lv.get("ok"):
            results["lenovo"] = lv
        else:
            results["lenovo_error"] = lv.get("error")
            # still ok overall if powercfg worked
    else:
        _lfc_last_applied_profile = profile
        _lfc_last_apply_ts = _time.time()

    results["warning"] = (
        "Applied via EnergyDrv direct control (no GUI spam)"
        if results.get("lenovo", {}).get("method") == "energy-drv"
        else "Power plan updated"
    )
    return results


def maybe_auto_optimize_fans(hw, hashrate, pred):
    """
    Locked fan policy: stick to user-selected profile.
    Mining heat alone must NOT bounce performance↔balanced (that thrash is audible).
    Only near-critical temps may override, with wide hysteresis + long cooldown.
    """
    global _lfc_pending_profile, _lfc_pending_count, _lfc_last_applied_profile
    global _lfc_last_apply_ts, _lfc_thermal_hold_until
    if not SETTINGS.get("windows_mode_enabled"):
        return None
    if not (
        SETTINGS.get("windows_fan_control_enabled")
        or SETTINGS.get("ai_fan_control_enabled")
    ):
        return None

    temp = hw.get("cpu_temp_c") if hw else None
    user_profile = (SETTINGS.get("fan_profile") or "balanced").lower()
    target = user_profile
    now = time.time()
    in_thermal_hold = now < _lfc_thermal_hold_until

    # HARD LOCK: performance / max_hash stay put unless near-critical
    locked_profiles = ("performance", "max_hash")

    if temp is not None and temp >= _lfc_thermal_enter_c:
        # Emergency only — step ONE profile cooler, hold for 8 minutes
        if user_profile == "max_hash":
            target = "performance"
        elif user_profile == "performance":
            target = "performance"  # stay high fans (EnergyDrv high) for cooling
        elif user_profile == "balanced":
            target = "balanced"
        else:
            target = "eco"
        # For thermal emergency we actually want MORE fans not less.
        # Map to high fan when overheating, never flip low↔high on soft temps.
        if temp >= _lfc_thermal_enter_c:
            target = "performance" if user_profile != "eco" else "balanced"
        _lfc_thermal_hold_until = now + 480
        in_thermal_hold = True
    elif in_thermal_hold:
        # Hold last emergency choice until cool AND timer ends
        if temp is not None and temp > _lfc_thermal_exit_c:
            target = _lfc_last_applied_profile or user_profile
        else:
            # cooled enough — return to user profile after hold
            if temp is None or temp <= _lfc_thermal_exit_c:
                target = user_profile
            else:
                target = _lfc_last_applied_profile or user_profile
    else:
        # AI may ONLY mild-boost eco/balanced upward — never oscillate
        if (
            SETTINGS.get("ai_fan_control_enabled")
            and user_profile in ("eco", "balanced")
            and user_profile not in locked_profiles
        ):
            p_up = float((pred or {}).get("p_up") or 0.5)
            direction = (pred or {}).get("direction") or "flat"
            if (
                direction == "up"
                and p_up >= 0.88
                and (temp is None or temp < 75)
                and (hashrate or 0) > 1000
            ):
                target = "performance"
            else:
                target = user_profile
        else:
            # performance/max_hash/locked — always user profile
            target = user_profile

    # Need many consecutive votes + long cooldown
    votes_needed = 12
    if target == _lfc_pending_profile:
        _lfc_pending_count += 1
    else:
        _lfc_pending_profile = target
        _lfc_pending_count = 1

    if target == _lfc_last_applied_profile:
        return {
            "ok": True,
            "skipped": True,
            "profile": target,
            "detail": "locked/unchanged",
        }

    # Never auto-change away from user profile unless thermal emergency
    if target != user_profile and not in_thermal_hold and temp is not None:
        if temp < _lfc_thermal_enter_c:
            target = user_profile
            if target == _lfc_last_applied_profile:
                return {
                    "ok": True,
                    "skipped": True,
                    "profile": target,
                    "detail": "user profile lock",
                }

    if _lfc_pending_count < votes_needed:
        return {
            "ok": True,
            "skipped": True,
            "profile": target,
            "detail": f"pending {_lfc_pending_count}/{votes_needed} for {target}",
        }

    if _lfc_last_apply_ts and (now - _lfc_last_apply_ts) < _lfc_min_change_sec:
        return {
            "ok": True,
            "skipped": True,
            "profile": target,
            "detail": f"cooldown {int(_lfc_min_change_sec - (now - _lfc_last_apply_ts))}s",
        }

    try:
        return apply_windows_fan_profile(target, force=False)
    except Exception as e:
        return {"ok": False, "error": str(e)}


def compute_stats(history, live_hs=None):
    """Stats from active mining samples only (offline zeros excluded)."""
    ys = []
    for h in history:
        if h.get("offline"):
            continue
        try:
            v = float(h.get("hs"))
        except (TypeError, ValueError):
            continue
        if v > 1.0:
            ys.append(v)
    if not ys:
        return {
            "avg": 0,
            "min": 0,
            "max": 0,
            "median": 0,
            "std": 0,
            "count": 0,
            "live": live_hs or 0,
        }
    # Prefer recent window for avg so old sessions don't drag
    recent = ys[-min(80, len(ys)) :]
    return {
        "avg": round(sum(recent) / len(recent), 2),
        "min": round(min(recent), 2),
        "max": round(max(ys), 2),
        "median": round(statistics.median(recent), 2),
        "std": round(statistics.pstdev(recent) if len(recent) > 1 else 0.0, 2),
        "count": len(ys),
        "live": live_hs if live_hs is not None else ys[-1],
    }


def _ohlc_update(slot, key, val):
    """Update nested OHLC dict under slot[key]."""
    if val is None:
        return
    val = float(val)
    o = slot.get(key)
    if not o:
        slot[key] = {"open": val, "high": val, "low": val, "close": val, "sum": val, "n": 1}
    else:
        o["high"] = max(o["high"], val)
        o["low"] = min(o["low"], val)
        o["close"] = val
        o["sum"] += val
        o["n"] += 1


def build_candles(history, interval_sec=60, metric="hashrate"):
    """
    Rich OHLC candles per time bucket for hover tooltips + overlay lines.
    Primary candle body uses metric (hashrate or cumulative XMR).
    Each candle also carries price, est daily XMR/USD, pool due when present.
    Offline / zero-hash samples are skipped for hashrate candles (scale accuracy).
    """
    if metric == "hashrate":
        history = [
            h
            for h in history
            if not h.get("offline")
            and h.get("hs") is not None
            and float(h.get("hs") or 0) > 1.0
        ]
    if not history:
        return []
    interval_sec = max(30, int(interval_sec))
    buckets = {}
    sorted_h = sorted(history, key=lambda h: h.get("time") or "")
    cum_xmr = 0.0
    prev_t = None

    for h in sorted_h:
        try:
            t = datetime.fromisoformat(h["time"])
        except Exception:
            continue
        ts = int(t.timestamp())
        bucket = ts - (ts % interval_sec)

        hs = float(h.get("hs") or 0)
        price = h.get("price")
        xmr_daily = h.get("xmr_daily")
        usd_daily = h.get("usd_daily")
        pool_due = h.get("pool_due_xmr")
        pool_paid = h.get("pool_paid_xmr")
        pool_hs = h.get("pool_hs")

        if pool_due is not None:
            cum_val = float(pool_due)
        else:
            if prev_t is not None:
                dt = max(0, (t - prev_t).total_seconds())
                cum_xmr += float(xmr_daily or 0) * (dt / 86400.0)
            cum_val = cum_xmr
        prev_t = t

        primary = cum_val if metric == "xmr" else hs

        b = buckets.get(bucket)
        if not b:
            b = {
                "time": bucket,
                "n": 0,
                "hs": None,
                "price": None,
                "xmr_daily": None,
                "usd_daily": None,
                "cum_xmr": None,
                "pool_due": None,
                "pool_paid": None,
                "pool_hs": None,
                "primary": None,
            }
            buckets[bucket] = b

        b["n"] += 1
        _ohlc_update(b, "primary", primary)
        _ohlc_update(b, "hs", hs)
        if price is not None:
            _ohlc_update(b, "price", price)
        if xmr_daily is not None:
            _ohlc_update(b, "xmr_daily", xmr_daily)
        if usd_daily is not None:
            _ohlc_update(b, "usd_daily", usd_daily)
        _ohlc_update(b, "cum_xmr", cum_val)
        if pool_due is not None:
            _ohlc_update(b, "pool_due", pool_due)
        if pool_paid is not None:
            _ohlc_update(b, "pool_paid", pool_paid)
        if pool_hs is not None:
            _ohlc_update(b, "pool_hs", pool_hs)

    def pack(o, decimals=2):
        if not o:
            return None
        avg = o["sum"] / o["n"] if o["n"] else o["close"]
        return {
            "open": round(o["open"], decimals),
            "high": round(o["high"], decimals),
            "low": round(o["low"], decimals),
            "close": round(o["close"], decimals),
            "avg": round(avg, decimals),
        }

    candles = []
    for bucket in sorted(buckets.keys()):
        b = buckets[bucket]
        prim = b.get("primary") or {"open": 0, "high": 0, "low": 0, "close": 0, "sum": 0, "n": 1}
        dec = 6 if metric == "xmr" else 2
        p = pack(prim, dec)
        hs_p = pack(b.get("hs"), 2)
        price_p = pack(b.get("price"), 2)
        xmr_d = pack(b.get("xmr_daily"), 5)
        usd_d = pack(b.get("usd_daily"), 3)
        candles.append(
            {
                "time": datetime.fromtimestamp(bucket).isoformat(),
                "ts": bucket,
                "open": p["open"],
                "high": p["high"],
                "low": p["low"],
                "close": p["close"],
                "avg": p["avg"],
                "up": p["close"] >= p["open"],
                "samples": b["n"],
                "metric": metric,
                # rich series for tooltips + overlay lines
                "hs": hs_p,
                "price": price_p,
                "xmr_daily": xmr_d,
                "usd_daily": usd_d,
                "cum_xmr": pack(b.get("cum_xmr"), 8),
                "pool_due": pack(b.get("pool_due"), 8),
                "pool_paid": pack(b.get("pool_paid"), 8),
                "pool_hs": pack(b.get("pool_hs"), 2),
                # convenient flat closes for drawing lines
                "line_hs": hs_p["close"] if hs_p else None,
                "line_price": price_p["close"] if price_p else None,
                "line_usd_daily": usd_d["close"] if usd_d else None,
                "line_xmr_daily": xmr_d["close"] if xmr_d else None,
            }
        )
    return candles[-200:]


# ── background poller ────────────────────────────────────────────────────────

def background_updater():
    global _last_miners, _last_price, _last_pool, _last_pool_fetch
    global _last_hw, _last_hw_ts, _last_hw_bg_ts, _cached_pred, _cached_pred_ts
    while not _updater_stop.is_set():
        try:
            snaps = poll_all_miners()
            online = [s for s in snaps if s.get("online")]
            total_hs = sum(s.get("hashrate", 0) or 0 for s in online)
            # Lightweight price only (intel cached separately if enabled)
            price = None
            try:
                price = fetch_xmr_price()
            except Exception:
                pass

            now = time.time()
            pool_data = None
            pool_interval = max(15, float(SETTINGS.get("pool_poll_seconds", 30)))
            if SETTINGS.get("pool_enabled") and SETTINGS.get("pool_wallet"):
                if now - _last_pool_fetch >= pool_interval or _last_pool is None:
                    try:
                        pool_data = fetch_moneroocean_wallet(SETTINGS.get("pool_wallet"))
                    except Exception:
                        pool_data = _last_pool
                    _last_pool_fetch = now
                else:
                    pool_data = _last_pool

            # HW sensors + fan auto (slow) — background only, every 20s
            if SETTINGS.get("hw_sensors_enabled", True) and (
                now - _last_hw_bg_ts >= 20 or _last_hw is None
            ):
                try:
                    hw = read_hw_sensors()
                    _last_hw = hw
                    _last_hw_ts = now
                    _last_hw_bg_ts = now
                    # fan auto only in background, not on /data
                    if SETTINGS.get("windows_mode_enabled"):
                        with _lock:
                            hist_snap = list(HISTORY[-200:])
                        try:
                            pred_bg = (
                                predict_hashrate(hist_snap)
                                if SETTINGS.get("ai_forecast_enabled", True)
                                else {}
                            )
                        except Exception:
                            pred_bg = {}
                        maybe_auto_optimize_fans(hw, total_hs, pred_bg)
                except Exception as e:
                    print(f"hw bg error: {e}")
                    _last_hw_bg_ts = now

            # Cache forecast in background; refresh often so AI tracks live hash
            need_pred = SETTINGS.get("ai_forecast_enabled", True) and (
                now - _cached_pred_ts >= 4
                or _cached_pred_live_hs is None
                or abs(total_hs - float(_cached_pred_live_hs or 0))
                > max(25, 0.04 * max(total_hs, 1))
            )
            if need_pred:
                try:
                    with _lock:
                        hist_snap = list(HISTORY[-800:])
                    pred_new = predict_hashrate(
                        hist_snap,
                        force_offline=(total_hs <= 1),
                        live_hs=total_hs if total_hs > 1 else None,
                    )
                    if total_hs > 1 and pred_new.get("ok"):
                        pred_new = _reanchor_prediction(pred_new, total_hs)
                    _cached_pred = pred_new
                    _cached_pred_ts = now
                    _cached_pred_live_hs = total_hs
                except Exception as e:
                    print(f"pred bg error: {e}")
            if SETTINGS.get("ai_price_intel_enabled") and (
                now - _last_price_intel_ts >= 120 or not _last_price_intel
            ):
                try:
                    fetch_xmr_price_intel(force=False)
                except Exception as e:
                    print(f"price intel bg error: {e}")

            with _lock:
                _last_miners = snaps
                if price is None:
                    price = (
                        HISTORY[-1]["price"]
                        if HISTORY
                        else float(SETTINGS.get("price_fallback", 165.0))
                    )
                _last_price = price
                if pool_data is not None:
                    _last_pool = pool_data

                if online or (pool_data and pool_data.get("ok")):
                    # prefer fleet local hs; fall back to pool hs for history if no local
                    hs_for_hist = total_hs if online else float(
                        (pool_data or {}).get("hashrate") or 0
                    )
                    # Do NOT pollute history with offline zeros (breaks AI/neural forecasts)
                    if hs_for_hist <= 1.0 and not (
                        pool_data and pool_data.get("ok") and pool_data.get("amt_due_xmr") is not None
                    ):
                        pass  # skip dead sample
                    else:
                        xmr_daily = estimate_earnings(hs_for_hist) if hs_for_hist > 0 else 0.0
                        fee = float(SETTINGS.get("pool_fee_factor", 0.91))
                        usd_daily = xmr_daily * price * fee
                        row = {
                            "time": datetime.now().isoformat(),
                            "hs": round(hs_for_hist, 2),
                            "price": round(price, 2),
                            "xmr_daily": round(xmr_daily, 5),
                            "usd_daily": round(usd_daily, 3),
                            "by_miner": {
                                s["id"]: round(s.get("hashrate", 0) or 0, 2)
                                for s in online
                            },
                            "online_count": len(online),
                        }
                        if pool_data and pool_data.get("ok"):
                            row["pool_due_xmr"] = pool_data.get("amt_due_xmr")
                            row["pool_paid_xmr"] = pool_data.get("amt_paid_xmr")
                            row["pool_hs"] = pool_data.get("hashrate")
                        # Only record real hashrate. Never carry forward last-known HS when offline
                        # (that bug made the dashboard stick at e.g. 750 after miner stop).
                        if hs_for_hist > 1.0:
                            append_history(row)
                        elif online or (pool_data and pool_data.get("ok")):
                            # Explicit offline sample so charts/live drop to 0 (not used for AI training)
                            row["hs"] = 0.0
                            row["offline"] = True
                            row["xmr_daily"] = 0.0
                            row["usd_daily"] = 0.0
                            append_history(row)
        except Exception as e:
            print(f"poll error: {e}")
        sleep_s = max(3, float(SETTINGS.get("poll_seconds", 6)))
        _updater_stop.wait(sleep_s)


# ── API routes ───────────────────────────────────────────────────────────────

@app.route("/")
def dashboard():
    return render_template_string(HTML_TEMPLATE)


@app.route("/data")
def get_data():
    with _lock:
        hist = list(HISTORY[-600:])
        miners = list(_last_miners)
        price = _last_price
        pool = dict(_last_pool) if _last_pool else None

    if price is None:
        price = (
            hist[-1]["price"]
            if hist
            else float(SETTINGS.get("price_fallback", 165.0))
        )

    online_miners = [m for m in miners if m.get("online")]
    enabled_miners = [m for m in miners if m.get("enabled", True)]
    any_online = len(online_miners) > 0
    total_hs_raw = sum(m.get("hashrate", 0) or 0 for m in online_miners)
    pool_hs = float((pool or {}).get("hashrate") or 0) if pool else 0.0
    pool_workers_on = int((pool or {}).get("workers_online") or 0) if pool else 0
    # Live fleet hashrate — never sticky last-known when everything is idle
    total_hs = live_display_hashrate(any_online, total_hs_raw, pool)
    # Strict: only "live" when current poll shows hash (not history grace)
    mining_live = total_hs > 1.0
    shares_good = sum(m.get("shares_good", 0) or 0 for m in online_miners)
    shares_total = sum(m.get("shares_total", 0) or 0 for m in online_miners)
    uptime = max((m.get("uptime", 0) or 0 for m in online_miners), default=0)

    if len(online_miners) == 1:
        algo = online_miners[0]["algo"]
        worker = online_miners[0].get("worker") or "—"
        pool_str = online_miners[0].get("pool") or "—"
    elif online_miners:
        algo = f"{len(set(m.get('algo') for m in online_miners))} algos"
        worker = f"{len(online_miners)} workers"
        pools = {
            m.get("pool")
            for m in online_miners
            if m.get("pool") and m.get("pool") != "—"
        }
        pool_str = next(iter(pools)) if len(pools) == 1 else f"{len(pools)} pools"
    else:
        algo = worker = pool_str = "—"

    xmr_daily = estimate_earnings(total_hs) if total_hs > 1.0 else 0.0
    fee = float(SETTINGS.get("pool_fee_factor", 0.91))
    usd_daily = xmr_daily * price * fee
    stats = compute_stats(hist, total_hs if total_hs > 1.0 else 0.0)

    ai_on = bool(SETTINGS.get("ai_forecast_enabled", True))
    price_intel_on = bool(SETTINGS.get("ai_price_intel_enabled", False))
    price_intel = None
    pred = {
        "ok": False,
        "disabled": not ai_on,
        "reason": "AI forecast is turned off in Settings",
        "predicted_avg_hs": 0,
        "projected": [],
        "horizon_min": SETTINGS.get("predict_horizon_min", 60),
        "direction": "unknown",
        "p_up": 0.5,
    }
    pred_xmr = pred_usd = 0.0
    # Use background-cached HW only — never block /data on PowerShell
    hw = _last_hw
    fan_action = None

    try:
        if price_intel_on:
            # Prefer cached intel only on request path (cold fetch is slow → refresh lag)
            if (
                _last_price_intel
                and _last_price_intel.get("ok")
                and (time.time() - _last_price_intel_ts) < 600
            ):
                price_intel = _last_price_intel
            else:
                # Don't block UI; return stale/none and let background refresh later
                price_intel = _last_price_intel or {
                    "ok": False,
                    "error": "warming price intel…",
                }
            if price_intel and price_intel.get("ok") and price_intel.get("price"):
                price = float(price_intel["price"])
                usd_daily = xmr_daily * price * fee
    except Exception:
        price_intel = {"ok": False, "error": "price intel failed"}

    try:
        if ai_on:
            if not mining_live:
                pred = predict_hashrate(hist, force_offline=True, live_hs=0)
            elif (
                _cached_pred
                and (time.time() - _cached_pred_ts) < 8
                and _cached_pred.get("method") != "offline"
                and float(_cached_pred.get("predicted_avg_hs") or 0) > 1
            ):
                # Always re-anchor full forecast (avg + projected chart) to live
                pred = _reanchor_prediction(dict(_cached_pred), total_hs)
            else:
                pred = predict_hashrate(
                    hist, force_offline=False, live_hs=total_hs if total_hs > 1 else None
                )
                if total_hs > 1 and pred.get("ok"):
                    pred = _reanchor_prediction(pred, total_hs)
            pred_xmr = (
                estimate_earnings(pred["predicted_avg_hs"]) if pred.get("ok") else 0.0
            )
            use_price = price
            if price_intel and price_intel.get("ok") and price_intel.get("price"):
                use_price = float(price_intel["price"])
                ch24 = price_intel.get("change_24h_pct") or 0
                pred["price_intel"] = {
                    "price": use_price,
                    "change_24h_pct": price_intel.get("change_24h_pct"),
                    "change_7d_pct": price_intel.get("change_7d_pct"),
                    "trend": price_intel.get("trend"),
                    "high_24h": price_intel.get("high_24h"),
                    "low_24h": price_intel.get("low_24h"),
                    "provider": price_intel.get("provider"),
                }
                if pred.get("ok"):
                    extra = ""
                    if ch24:
                        extra = f" · XMR {float(ch24):+.2f}% (24h, {price_intel.get('trend')})"
                    pred["summary"] = (pred.get("summary") or "") + extra
                    pred["summary"] += f" · spot ${use_price:.2f}"
            pred_usd = pred_xmr * use_price * fee
    except Exception as e:
        pred = {
            "ok": False,
            "reason": f"Forecast error: {e}",
            "predicted_avg_hs": 0,
            "projected": [],
            "horizon_min": SETTINGS.get("predict_horizon_min", 60),
            "direction": "unknown",
            "p_up": 0.5,
        }

    # Prefer live hashrate for display earnings when actually hashing
    if total_hs > 1.0:
        xmr_daily = estimate_earnings(total_hs)
        usd_daily = xmr_daily * price * fee
    else:
        xmr_daily = 0.0
        usd_daily = 0.0
        pred_xmr = 0.0
        pred_usd = 0.0

    try:
        interval = int(SETTINGS.get("candle_interval_sec", 60))
        # lighter candle build for UI speed
        candles_hs = build_candles(hist[-400:], interval, "hashrate")
        candles_xmr = build_candles(hist[-400:], interval, "xmr")
    except Exception:
        interval = 60
        candles_hs, candles_xmr = [], []

    nn_on = bool(SETTINGS.get("neural_net_enabled")) or (
        str(SETTINGS.get("ai_mode", "classic")).lower() == "neural"
    )

    return jsonify(
        {
            "success": True,  # API itself is healthy
            "online": any_online and total_hs_raw > 0,
            "mining_live": mining_live,
            "hashrate": total_hs,
            "hashrate_local": total_hs_raw,
            "hashrate_pool": pool_hs,
            "price": price,
            "usd_daily": usd_daily,
            "xmr_daily": xmr_daily,
            "history": hist,
            "uptime": uptime,
            "shares_good": shares_good,
            "shares_total": shares_total,
            "algo": algo,
            "worker": worker,
            "pool": pool_str,
            "stats": stats,
            "prediction": pred,
            "pred_usd_daily": pred_usd,
            "pred_xmr_daily": pred_xmr,
            "price_intel": price_intel,
            "hardware": hw,
            "fan_action": fan_action,
            "miners": miners,
            "miners_online": len(online_miners),
            "miners_enabled": len(enabled_miners),
            "miners_total": len(miners),
            "pool_stats": pool,
            "candles": {"hashrate": candles_hs, "xmr": candles_xmr, "interval_sec": interval},
            "server_time": datetime.now().isoformat(),
            "settings_public": {
                "refresh_ui_ms": SETTINGS.get("refresh_ui_ms", 6500),
                "theme_accent": SETTINGS.get("theme_accent", "#12B76A"),
                "theme_accent2": SETTINGS.get("theme_accent2", "#4E7CFF"),
                "chart_hs_color": SETTINGS.get("chart_hs_color", "#12B76A"),
                "chart_price_color": SETTINGS.get("chart_price_color", "#F79009"),
                "chart_forecast_color": SETTINGS.get("chart_forecast_color", "#4E7CFF"),
                "dashboard_title": SETTINGS.get("dashboard_title", APP_NAME),
                "brand_name": SETTINGS.get("brand_name", APP_NAME),
                "brand_tagline": SETTINGS.get("brand_tagline", ""),
                "logo_letters": SETTINGS.get("logo_letters", "DC"),
                "portfolio_label": SETTINGS.get("portfolio_label", "Fleet portfolio · hashrate"),
                "theme_mode": SETTINGS.get("theme_mode", "dark"),
                "color_preset": SETTINGS.get("color_preset", "stockie"),
                "density": SETTINGS.get("density", "comfortable"),
                "font_scale": SETTINGS.get("font_scale", 100),
                "card_radius": SETTINGS.get("card_radius", 20),
                "background_style": SETTINGS.get("background_style", "soft_glow"),
                "chart_fill": SETTINGS.get("chart_fill", True),
                "chart_smooth": SETTINGS.get("chart_smooth", True),
                "reduced_motion": SETTINGS.get("reduced_motion", False),
                "show_watchlist": SETTINGS.get("show_watchlist", True),
                "show_holdings": SETTINGS.get("show_holdings", True),
                "show_details": SETTINGS.get("show_details", True),
                "show_footer": SETTINGS.get("show_footer", True),
                "show_portfolio_hero": SETTINGS.get("show_portfolio_hero", True),
                "number_compact": SETTINGS.get("number_compact", False),
                "currency_symbol": SETTINGS.get("currency_symbol", "$"),
                "show_price_chart": SETTINGS.get("show_price_chart", True),
                "show_earnings_card": SETTINGS.get("show_earnings_card", True),
                "ai_forecast_enabled": ai_on,
                "ai_mode": SETTINGS.get("ai_mode", "classic"),
                "neural_net_enabled": nn_on,
                "nn_mode": SETTINGS.get("nn_mode", "balanced"),
                "nn_hidden": SETTINGS.get("nn_hidden", 10),
                "nn_window": SETTINGS.get("nn_window", 16),
                "nn_epochs": SETTINGS.get("nn_epochs", 50),
                "nn_lr": SETTINGS.get("nn_lr", 0.025),
                "nn_classic_blend": SETTINGS.get("nn_classic_blend", 0.55),
                "ai_realtime": bool(SETTINGS.get("ai_realtime", True)),
                "history_backend": SETTINGS.get("history_backend", "json"),
                "ai_price_intel_enabled": price_intel_on,
                "price_provider": SETTINGS.get("price_provider", "auto"),
                "ui_mode": SETTINGS.get("ui_mode", "default"),
                "predict_horizon_min": SETTINGS.get("predict_horizon_min", 60),
                "bind_host": SETTINGS.get("bind_host", "127.0.0.1"),
                "bind_port": SETTINGS.get("bind_port", 5000),
                "pool_enabled": bool(SETTINGS.get("pool_enabled")),
                "chart_mode": SETTINGS.get("chart_mode", "line"),
                "candle_interval_sec": interval,
                "candle_metric": SETTINGS.get("candle_metric", "hashrate"),
                "hw_sensors_enabled": bool(SETTINGS.get("hw_sensors_enabled", True)),
                "windows_mode_enabled": bool(SETTINGS.get("windows_mode_enabled")),
                "windows_fan_control_enabled": bool(
                    SETTINGS.get("windows_fan_control_enabled")
                ),
                "pc_vendor": SETTINGS.get("pc_vendor", "auto"),
                "fan_profile": SETTINGS.get("fan_profile", "balanced"),
                "app_version": APP_VERSION,
            },
        }
    )


@app.route("/api/predict")
def api_predict():
    if not SETTINGS.get("ai_forecast_enabled", True):
        return jsonify({"ok": False, "disabled": True, "reason": "AI forecast disabled"})
    horizon = request.args.get("horizon", type=int)
    lookback = request.args.get("lookback", type=int)
    with _lock:
        hist = list(HISTORY)
    return jsonify(predict_hashrate(hist, lookback=lookback, horizon_min=horizon))


@app.route("/api/hardware")
def api_hardware():
    try:
        return jsonify(read_hw_sensors())
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/hardware/detect", methods=["POST"])
def api_hardware_detect():
    global _last_hw, _last_hw_ts
    try:
        # Force fresh scan (bypass cache) + rediscover LFC
        _last_hw = None
        _last_hw_ts = 0.0
        lfc = find_lenovo_fan_control(auto_save=True)
        hw = read_hw_sensors()
        # If Lenovo machine and LFC found, prefer vendor key lenovo for UI
        if hw.get("vendor", {}).get("vendor_key") == "lenovo" or lfc:
            if not SETTINGS.get("pc_vendor") or SETTINGS.get("pc_vendor") == "auto":
                pass  # keep auto; path is enough
        return jsonify(
            {
                "ok": True,
                "hardware": hw,
                "vendor": hw.get("vendor"),
                "lenovo_fan_control_path": lfc
                or (hw.get("lenovo_fan_control") or {}).get("path")
                or SETTINGS.get("lenovo_fan_control_path")
                or "",
                "settings": {
                    "lenovo_fan_control_path": SETTINGS.get("lenovo_fan_control_path") or "",
                },
            }
        )
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/hardware/fan", methods=["POST"])
def api_hardware_fan():
    body = request.get_json(silent=True) or {}
    profile = body.get("profile") or SETTINGS.get("fan_profile")
    force = bool(body.get("force", True))  # manual Apply = force once
    try:
        result = apply_windows_fan_profile(profile, force=force)
        return jsonify(result)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/hardware/fan/stop", methods=["POST"])
def api_hardware_fan_stop():
    try:
        stop_lenovo_energy_worker(reset_to_normal=True)
        return jsonify({"ok": True, "detail": "Lenovo EnergyDrv worker stopped · fan set NORMAL"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/pool/refresh", methods=["POST"])
def api_pool_refresh():
    global _last_pool, _last_pool_fetch
    if not SETTINGS.get("pool_wallet"):
        return jsonify({"ok": False, "error": "No wallet configured"})
    data = fetch_moneroocean_wallet(SETTINGS.get("pool_wallet"))
    import time as _time

    with _lock:
        _last_pool = data
        _last_pool_fetch = _time.time()
    return jsonify(data)


@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    global SETTINGS, _last_pool_fetch, _last_price_intel_ts, _cached_pred, _cached_pred_ts
    if request.method == "GET":
        return jsonify({"settings": SETTINGS, "defaults": DEFAULT_SETTINGS})

    body = request.get_json(silent=True) or {}
    incoming = body.get("settings", body)
    if not isinstance(incoming, dict):
        return jsonify({"ok": False, "error": "Invalid body"}), 400

    new = dict(SETTINGS)
    for key, default in DEFAULT_SETTINGS.items():
        if key not in incoming or key == "miners":
            continue
        val = incoming[key]
        try:
            if isinstance(default, bool):
                new[key] = (
                    bool(val)
                    if not isinstance(val, str)
                    else val.lower() in ("1", "true", "yes", "on")
                )
            elif isinstance(default, int) and not isinstance(default, bool):
                new[key] = int(val)
            elif isinstance(default, float):
                new[key] = float(val)
            elif isinstance(default, list):
                continue
            else:
                new[key] = str(val)
        except (TypeError, ValueError):
            continue

    if "miners" in incoming:
        new["miners"] = _normalize_miners(incoming["miners"])
        enabled = [m for m in new["miners"] if m.get("enabled")]
        if enabled:
            new["xmrig_api_url"] = enabled[0]["url"]

    new["poll_seconds"] = max(3, min(120, int(new["poll_seconds"])))
    new["pool_poll_seconds"] = max(15, min(300, int(new.get("pool_poll_seconds", 30))))
    new["bind_port"] = max(1, min(65535, int(new["bind_port"])))
    if new.get("history_backend") not in ("json", "sqlite"):
        new["history_backend"] = "json"
    max_keep = 20000 if str(new.get("history_backend")) == "sqlite" else 5000
    new["history_keep"] = max(50, min(max_keep, int(new["history_keep"])))
    new["refresh_ui_ms"] = max(2000, min(60000, int(new["refresh_ui_ms"])))
    new["predict_horizon_min"] = max(5, min(1440, int(new["predict_horizon_min"])))
    new["predict_lookback"] = max(10, min(2000, int(new["predict_lookback"])))
    new["candle_interval_sec"] = max(30, min(3600, int(new.get("candle_interval_sec", 60))))
    if new.get("chart_mode") not in ("line", "candle"):
        new["chart_mode"] = "line"
    if new.get("candle_metric") not in ("hashrate", "xmr"):
        new["candle_metric"] = "hashrate"
    if new.get("price_provider") not in PRICE_PROVIDERS:
        new["price_provider"] = "auto"
    if new.get("ui_mode") not in ("default", "pro", "minimal"):
        new["ui_mode"] = "default"
    if new.get("theme_mode") not in ("dark", "light"):
        new["theme_mode"] = "dark"
    if new.get("color_preset") not in COLOR_PRESETS:
        new["color_preset"] = "stockie"
    if new.get("density") not in ("comfortable", "compact", "spacious"):
        new["density"] = "comfortable"
    if new.get("background_style") not in ("solid", "soft_glow"):
        new["background_style"] = "soft_glow"
    try:
        new["font_scale"] = max(90, min(130, int(new.get("font_scale", 100))))
    except (TypeError, ValueError):
        new["font_scale"] = 100
    try:
        new["card_radius"] = max(8, min(28, int(new.get("card_radius", 20))))
    except (TypeError, ValueError):
        new["card_radius"] = 20
    new["logo_letters"] = str(new.get("logo_letters") or "DC")[:3].upper() or "DC"
    new["brand_name"] = str(new.get("brand_name") or APP_NAME)[:64]
    new["brand_tagline"] = str(new.get("brand_tagline") or "")[:80]
    new["portfolio_label"] = str(new.get("portfolio_label") or "Fleet portfolio · hashrate")[:64]
    new["currency_symbol"] = str(new.get("currency_symbol") or "$")[:3]
    new["dashboard_title"] = str(new.get("dashboard_title") or new.get("brand_name") or APP_NAME)[:64]
    # Normalize hex colors
    def _hex(v, fallback):
        s = str(v or "").strip()
        if len(s) == 7 and s.startswith("#"):
            return s
        return fallback
    new["theme_accent"] = _hex(new.get("theme_accent"), "#12B76A")
    new["theme_accent2"] = _hex(new.get("theme_accent2"), "#4E7CFF")
    new["chart_hs_color"] = _hex(new.get("chart_hs_color"), new["theme_accent"])
    new["chart_price_color"] = _hex(new.get("chart_price_color"), "#F79009")
    new["chart_forecast_color"] = _hex(new.get("chart_forecast_color"), new["theme_accent2"])
    # Apply UI preset colors unless custom (does NOT touch chart_* colors)
    preset = str(new.get("color_preset") or "stockie").lower()
    if preset != "custom" and preset in COLOR_PRESETS and COLOR_PRESETS[preset]:
        new["theme_accent"], new["theme_accent2"] = COLOR_PRESETS[preset]
    new["ai_realtime"] = bool(new.get("ai_realtime", True))
    if new.get("ai_mode") not in ("classic", "neural", "hybrid"):
        new["ai_mode"] = "classic"
    if new.get("ai_mode") in ("neural", "hybrid"):
        new["neural_net_enabled"] = True
    else:
        new["neural_net_enabled"] = False
    if new.get("nn_mode") not in NN_MODE_PRESETS:
        new["nn_mode"] = "balanced"
    # Apply NN mode presets unless custom
    if new.get("nn_mode") != "custom" and NN_MODE_PRESETS.get(new.get("nn_mode")):
        h, w, ep, lr, blend, pairs, clip = NN_MODE_PRESETS[new["nn_mode"]]
        new["nn_hidden"] = h
        new["nn_window"] = w
        new["nn_epochs"] = ep
        new["nn_lr"] = lr
        new["nn_classic_blend"] = blend
        new["nn_train_pairs"] = pairs
        new["nn_clip"] = clip
    else:
        new["nn_hidden"] = max(4, min(32, int(new.get("nn_hidden", 10))))
        new["nn_epochs"] = max(5, min(200, int(new.get("nn_epochs", 50))))
        new["nn_window"] = max(6, min(48, int(new.get("nn_window", 16))))
        try:
            new["nn_lr"] = max(0.001, min(0.2, float(new.get("nn_lr", 0.025))))
        except (TypeError, ValueError):
            new["nn_lr"] = 0.025
        try:
            new["nn_classic_blend"] = max(0.05, min(0.95, float(new.get("nn_classic_blend", 0.55))))
        except (TypeError, ValueError):
            new["nn_classic_blend"] = 0.55
        new["nn_train_pairs"] = max(20, min(400, int(new.get("nn_train_pairs", 120))))
        try:
            new["nn_clip"] = max(1.0, min(4.0, float(new.get("nn_clip", 2.5))))
        except (TypeError, ValueError):
            new["nn_clip"] = 2.5
    if new.get("pc_vendor") not in (
        "auto",
        "dell",
        "hp",
        "lenovo",
        "asus",
        "msi",
        "acer",
        "generic",
    ):
        new["pc_vendor"] = "auto"
    if new.get("fan_profile") not in ("eco", "balanced", "performance", "max_hash"):
        new["fan_profile"] = "balanced"
    # safety: fan control requires windows mode
    if (
        new.get("windows_fan_control_enabled") or new.get("ai_fan_control_enabled")
    ) and not new.get("windows_mode_enabled"):
        new["windows_mode_enabled"] = True
    if "lenovo_fan_control_path" in new:
        new["lenovo_fan_control_path"] = str(new.get("lenovo_fan_control_path") or "").strip()
    new["pool_wallet"] = str(new.get("pool_wallet") or "").strip()
    new["pool_enabled"] = bool(new.get("pool_enabled")) and bool(new["pool_wallet"])
    new["pool_provider"] = "moneroocean"
    host = str(new.get("bind_host", "127.0.0.1")).strip()
    if host not in ("127.0.0.1", "0.0.0.0", "localhost"):
        parts = host.split(".")
        if not (
            len(parts) == 4
            and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)
        ):
            host = "127.0.0.1"
    new["bind_host"] = host

    needs_restart = (
        new.get("bind_host") != SETTINGS.get("bind_host")
        or int(new.get("bind_port", 5000)) != int(SETTINGS.get("bind_port", 5000))
    )
    wallet_changed = new.get("pool_wallet") != SETTINGS.get("pool_wallet")
    price_cfg_changed = (
        new.get("price_provider") != SETTINGS.get("price_provider")
        or bool(new.get("ai_price_intel_enabled")) != bool(SETTINGS.get("ai_price_intel_enabled"))
    )
    prev_backend = str(SETTINGS.get("history_backend") or "json").lower()
    backend_changed = str(new.get("history_backend") or "json").lower() != prev_backend
    hist_status = None

    with _lock:
        # Flush JSON before switching storage
        if backend_changed and prev_backend == "json":
            try:
                save_history()
            except Exception:
                pass
        SETTINGS = new
        save_settings()
        if wallet_changed:
            _last_pool_fetch = 0  # force refresh
        if price_cfg_changed:
            _last_price_intel_ts = 0  # force fresh provider fetch
        # Invalidate AI cache so new settings apply immediately
        _cached_pred = None
        _cached_pred_ts = 0.0
        if backend_changed:
            try:
                # pass through true previous backend for correct migrate
                SETTINGS["history_backend"] = prev_backend
                hist_status = switch_history_backend(new.get("history_backend"))
                SETTINGS["history_backend"] = str(new.get("history_backend") or "json")
            except Exception as e:
                SETTINGS["history_backend"] = str(new.get("history_backend") or "json")
                hist_status = {"ok": False, "error": str(e)}
        # Windows login start (best-effort)
        try:
            apply_start_with_windows(bool(SETTINGS.get("start_with_windows")))
        except Exception:
            pass

    msg = "Settings saved."
    if needs_restart:
        msg = "Saved. Restart the app for host/port bind changes to take effect."
    elif backend_changed and hist_status:
        if hist_status.get("ok"):
            mig = hist_status.get("migrated") or 0
            msg = (
                f"History backend → {hist_status.get('backend')} "
                f"({hist_status.get('samples', 0)} samples"
                + (f", migrated {mig} from JSON" if mig else "")
                + "). "
                + (hist_status.get("warning") or "")
            )
        else:
            msg = f"Saved, but history switch failed: {hist_status.get('error')}"

    return jsonify(
        {
            "ok": True,
            "settings": SETTINGS,
            "needs_restart": needs_restart,
            "history_switch": hist_status,
            "message": msg,
        }
    )


@app.route("/api/settings/reset", methods=["POST"])
def api_settings_reset():
    global SETTINGS
    with _lock:
        SETTINGS = dict(DEFAULT_SETTINGS)
        SETTINGS["miners"] = [dict(DEFAULT_MINER)]
        save_settings()
    return jsonify({"ok": True, "settings": SETTINGS})


def apply_start_with_windows(enabled):
    """Create/remove HKCU Run entry so Deer Crypto Monitor starts at login."""
    if os.name != "nt":
        return False
    try:
        import winreg

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        name = APP_SLUG
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                if getattr(sys, "frozen", False):
                    cmd = f'"{sys.executable}"'
                else:
                    script = os.path.abspath(__file__)
                    cmd = f'"{sys.executable}" "{script}"'
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(key, name)
                except FileNotFoundError:
                    pass
        return True
    except Exception as e:
        print(f"start_with_windows: {e}")
        return False


# ── UI ───────────────────────────────────────────────────────────────────────

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0B0D12">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<title>Deer Crypto Monitor</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>

<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
:root{
  --bg0:#0B0D12;
  --bg1:#12151C;
  --bg2:#1A1E28;
  --bg3:#232836;
  --card:#141820;
  --line:rgba(255,255,255,.06);
  --line2:rgba(255,255,255,.1);
  --text:#F4F6FA;
  --muted:#8B93A7;
  --muted2:#6B7389;
  --accent:#12B76A;
  --accent2:#4E7CFF;
  --warn:#F79009;
  --danger:#F04438;
  --ok:#12B76A;
  --up-bg:rgba(18,183,106,.12);
  --dn-bg:rgba(240,68,56,.12);
  --radius:20px;
  --radius-sm:14px;
  --shadow:0 8px 32px rgba(0,0,0,.28);
  --shadow-sm:0 2px 12px rgba(0,0,0,.18);
  --font:'Inter',ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  --mono:ui-monospace,"Cascadia Code","SF Mono",Menlo,Consolas,monospace;
  --safe-b:env(safe-area-inset-bottom,0px);
  --safe-t:env(safe-area-inset-top,0px);
  --pad:20px;
  --pro-green:#12B76A; --pro-amber:#F79009; --pro-red:#F04438; --pro-cyan:#4E7CFF;
}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;padding:0;background:var(--bg0);color:var(--text);font-family:var(--font);-webkit-font-smoothing:antialiased}
body{
  min-height:100vh;min-height:100dvh;
  background:var(--bg0);
  padding-bottom:calc(80px + var(--safe-b));
}
button,input,select{font:inherit}
.app{max-width:1240px;margin:0 auto;padding:var(--pad);padding-top:calc(var(--pad) + var(--safe-t))}

/* ── Top bar (Stockie app bar) ── */
.topbar{
  display:flex;align-items:center;justify-content:space-between;gap:12px;
  padding:10px 4px 16px;margin-bottom:4px;
  background:transparent;border:none;box-shadow:none;
  position:sticky;top:0;z-index:20;
  backdrop-filter:blur(12px);
  background:linear-gradient(180deg,rgba(11,13,18,.96),rgba(11,13,18,.88) 70%,transparent);
}
.brand{display:flex;align-items:center;gap:12px;min-width:0}
.logo{
  width:40px;height:40px;border-radius:12px;display:grid;place-items:center;
  background:linear-gradient(145deg,var(--accent),var(--accent-dark, #0E9F5A));
  color:#fff;font-weight:800;font-size:14px;flex:0 0 auto;
  box-shadow:0 6px 16px var(--accent-glow, rgba(18,183,106,.28));
}
.brand h1{margin:0;font-size:1.05rem;font-weight:700;letter-spacing:-.02em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.brand p{margin:2px 0 0;color:var(--muted);font-size:.75rem;font-weight:500}
.top-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap;justify-content:flex-end}
.pill{
  display:inline-flex;align-items:center;gap:7px;padding:7px 12px;border-radius:999px;
  background:var(--bg2);border:1px solid var(--line);color:var(--muted);font-size:.78rem;font-weight:500;white-space:nowrap;
}
.dot{width:8px;height:8px;border-radius:50%;background:var(--danger);box-shadow:0 0 0 3px rgba(240,68,56,.15);flex:0 0 auto}
.dot.on{background:var(--ok);box-shadow:0 0 0 3px rgba(18,183,106,.18);animation:pulse 2.4s infinite}
.dot.partial{background:var(--warn);box-shadow:0 0 0 3px rgba(247,144,9,.18)}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.55}}

.btn{
  border:1px solid var(--line);background:var(--bg2);color:var(--text);
  border-radius:12px;padding:9px 14px;cursor:pointer;transition:.15s ease;min-height:40px;font-weight:500;font-size:.88rem;
}
.btn:hover{border-color:var(--line2);background:var(--bg3)}
.btn.primary{
  background:var(--accent);border-color:transparent;color:#fff;font-weight:600;
  box-shadow:0 6px 18px var(--accent-glow, rgba(18,183,106,.28));
}
.btn.primary:hover{filter:brightness(1.06)}
.btn.ghost{background:transparent}
.btn.danger{border-color:rgba(240,68,56,.35);color:#ff8f88}
.btn.sm{padding:7px 12px;font-size:.8rem;border-radius:10px;min-height:34px}
.btn.active{border-color:rgba(18,183,106,.4);background:var(--up-bg);color:var(--text)}

/* ── Portfolio hero (Stockie portfolio card) ── */
.portfolio-hero{
  background:var(--card);
  border:1px solid var(--line);
  border-radius:24px;
  padding:22px 22px 18px;
  margin-bottom:14px;
  box-shadow:var(--shadow-sm);
  position:relative;overflow:hidden;
}
.portfolio-hero::before{
  content:"";position:absolute;right:-40px;top:-40px;width:180px;height:180px;border-radius:50%;
  background:radial-gradient(circle,rgba(18,183,106,.16),transparent 70%);pointer-events:none;
}
.ph-top{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:6px}
.ph-label{font-size:.8rem;font-weight:500;color:var(--muted);letter-spacing:.01em}
.ph-badge{
  display:inline-flex;align-items:center;gap:4px;padding:5px 10px;border-radius:999px;
  font-size:.75rem;font-weight:600;background:var(--up-bg);color:var(--ok);
}
.ph-badge.down{background:var(--dn-bg);color:var(--danger)}
.ph-badge.flat{background:var(--bg2);color:var(--muted)}
.ph-value{
  font-size:clamp(2rem,5vw,2.75rem);font-weight:800;letter-spacing:-.04em;
  line-height:1.05;font-variant-numeric:tabular-nums;margin:4px 0 6px;
}
.ph-value .unit{font-size:.45em;font-weight:600;color:var(--muted);margin-left:6px;letter-spacing:0}
.ph-sub{font-size:.85rem;color:var(--muted);font-weight:500}
.ph-chips{display:flex;flex-wrap:wrap;gap:8px;margin-top:16px}
.ph-chip{
  flex:1;min-width:100px;padding:12px 14px;border-radius:14px;
  background:var(--bg2);border:1px solid var(--line);
}
.ph-chip .l{font-size:.7rem;color:var(--muted);font-weight:500;margin-bottom:4px}
.ph-chip .v{font-size:1rem;font-weight:700;font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.ph-chip .v.g{color:var(--ok)} .ph-chip .v.b{color:var(--accent2)} .ph-chip .v.w{color:var(--warn)}

/* ── Grids ── */
.grid-stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:14px}
.grid-pool{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px;margin-bottom:14px}
.grid-main{display:grid;grid-template-columns:1.65fr 1fr;gap:14px}
.grid-main.ai-off{grid-template-columns:1fr}
.grid-bottom{display:grid;grid-template-columns:1.4fr 1fr;gap:14px;margin-top:14px}
.grid-3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px;margin-top:14px}
.sec-title{
  font-size:.78rem;font-weight:600;color:var(--muted);letter-spacing:.04em;
  text-transform:uppercase;margin:4px 0 10px;padding:0 2px;
}

/* ── Cards ── */
.card{
  background:var(--card);
  border:1px solid var(--line);
  border-radius:var(--radius);
  padding:16px 16px 14px;
  box-shadow:var(--shadow-sm);
  min-width:0;
}
.card h2{
  margin:0 0 12px;font-size:.8rem;font-weight:600;letter-spacing:.02em;
  color:var(--muted);display:flex;align-items:center;justify-content:space-between;gap:8px;
  text-transform:none;
}
.card h2 .tag{
  font-size:.72rem;font-weight:600;padding:3px 8px;border-radius:999px;
  background:var(--bg2);color:var(--accent2);letter-spacing:0;
}
.stat-label{color:var(--muted);font-size:.75rem;font-weight:500;margin-bottom:6px}
.stat-value{font-size:1.35rem;font-weight:700;letter-spacing:-.03em;line-height:1.15;font-variant-numeric:tabular-nums}
.stat-value.accent{color:var(--accent)}
.stat-value.blue{color:var(--accent2)}
.stat-value.warn{color:var(--warn)}
.stat-sub{margin-top:6px;color:var(--muted2);font-size:.72rem;font-weight:500}
.delta{font-size:.8rem;font-weight:600}
.delta.up{color:var(--ok)} .delta.down{color:var(--danger)} .delta.flat{color:var(--muted)}

/* ── Mini metric cards (watchlist style) ── */
.metric-card{
  background:var(--card);border:1px solid var(--line);border-radius:16px;
  padding:14px;min-width:0;box-shadow:var(--shadow-sm);
  transition:border-color .15s ease, transform .15s ease;
}
.metric-card:hover{border-color:var(--line2)}
.metric-card .ico{
  width:32px;height:32px;border-radius:10px;display:grid;place-items:center;
  font-size:.9rem;margin-bottom:10px;background:var(--bg2);color:var(--muted);
}
.metric-card .ico.g{background:var(--up-bg);color:var(--ok)}
.metric-card .ico.b{background:rgba(78,124,255,.12);color:var(--accent2)}
.metric-card .ico.w{background:rgba(247,144,9,.12);color:var(--warn)}

/* ── Charts ── */
.chart-wrap{position:relative;height:340px}
.chart-wrap.sm{height:170px}
.chart-wrap.candle{height:360px;position:relative;cursor:crosshair}
.chart-wrap.tall{height:min(62vh,520px)}
#candleCanvas,#mainChart{width:100%;height:100%;display:block;touch-action:none}
.chart-toolbar{
  display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;
  margin-bottom:10px;
}
.zoom-bar{display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.zoom-bar .btn.icon{
  min-width:40px;min-height:40px;padding:0 10px;font-weight:700;font-size:1rem;
  display:inline-flex;align-items:center;justify-content:center;border-radius:12px;
}
.zoom-label{
  font-size:.72rem;color:var(--muted);font-family:var(--mono);font-weight:500;
  padding:6px 10px;border-radius:999px;border:1px solid var(--line);background:var(--bg2);
  min-width:64px;text-align:center;
}
.chart-hint-mob{display:none;font-size:.7rem;color:var(--muted);margin-top:8px}

/* ── Tabs / chips (Stockie time ranges) ── */
.tabs,.seg{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px}
.tab,.seg button{
  padding:8px 14px;border-radius:999px;border:1px solid transparent;
  background:var(--bg2);color:var(--muted);cursor:pointer;font-size:.8rem;font-weight:500;min-height:36px;
  transition:.12s ease;
}
.tab:hover,.seg button:hover{color:var(--text)}
.tab.active,.seg button.active{
  background:var(--text);color:var(--bg0);font-weight:600;border-color:transparent;
}

/* ── Mobile hero (kept for JS) ── */
.mob-hero{display:none;gap:8px;margin-bottom:12px}
.mob-hero .mh{
  flex:1;min-width:0;padding:14px;border-radius:16px;border:1px solid var(--line);
  background:var(--card);
}
.mob-hero .mh .l{font-size:.7rem;color:var(--muted);margin-bottom:4px;font-weight:500}
.mob-hero .mh .v{font-size:1.1rem;font-weight:700;font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.mob-hero .mh .v.a{color:var(--accent)} .mob-hero .mh .v.b{color:var(--accent2)} .mob-hero .mh .v.w{color:var(--warn)}
.mob-sheet-handle{
  display:none;width:40px;height:4px;border-radius:99px;background:var(--bg3);margin:0 auto 10px;
}

/* ── Candle tip ── */
.candle-tip{
  position:absolute;z-index:5;pointer-events:none;min-width:200px;max-width:min(280px,86vw);
  padding:12px 14px;border-radius:14px;font-size:.78rem;line-height:1.45;
  background:rgba(20,24,32,.96);border:1px solid var(--line2);box-shadow:var(--shadow);
  color:var(--text);opacity:0;transform:translateY(4px);transition:opacity .12s ease;
  backdrop-filter:blur(10px);
}
.candle-tip.show{opacity:1;transform:translateY(0)}
.candle-tip .t-title{font-weight:700;margin-bottom:6px;font-size:.82rem}
.candle-tip .t-row{display:flex;justify-content:space-between;gap:12px;margin:2px 0}
.candle-tip .t-row span:first-child{color:var(--muted)}
.candle-tip .t-row span:last-child{font-family:var(--mono);font-size:.74rem;text-align:right}
.candle-tip .t-up{color:var(--ok)} .candle-tip .t-down{color:var(--danger)}
.candle-tip .t-sep{height:1px;background:var(--line);margin:7px 0}
.candle-legend-row{display:flex;flex-wrap:wrap;gap:10px 14px;margin-top:10px;font-size:.72rem;color:var(--muted);font-weight:500}
.candle-legend-row i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:5px;vertical-align:-1px}

.warn-box{
  margin:8px 0 12px;padding:12px 14px;border-radius:14px;font-size:.78rem;line-height:1.45;
  background:rgba(247,144,9,.1);border:1px solid rgba(247,144,9,.28);color:#ffd699;
}
.warn-box strong{color:var(--warn)}
.intel-chip{
  display:inline-flex;align-items:center;gap:6px;padding:5px 11px;border-radius:999px;
  font-size:.74rem;font-weight:500;border:1px solid var(--line);background:var(--bg2);color:var(--muted);margin-top:10px;
}
.intel-chip.up{color:var(--ok);border-color:rgba(18,183,106,.3);background:var(--up-bg)}
.intel-chip.down{color:var(--danger);border-color:rgba(240,68,56,.3);background:var(--dn-bg)}
#candleCanvas.panning, #mainChart.panning{cursor:grabbing !important}
#candleCanvas{cursor:crosshair}
#mainChart{cursor:grab}

.kv{display:grid;grid-template-columns:1fr auto;gap:10px 14px;font-size:.86rem}
.kv span:first-child{color:var(--muted);font-weight:500}
.kv span:last-child{font-family:var(--mono);font-size:.8rem;text-align:right;word-break:break-all;font-weight:500}
.meter{height:6px;background:var(--bg2);border-radius:99px;overflow:hidden;margin:12px 0 6px}
.meter > i{display:block;height:100%;width:0;background:linear-gradient(90deg,var(--accent),#34D399);border-radius:99px;transition:width .5s ease}
.pred-box{
  margin-top:12px;padding:14px;border-radius:14px;
  background:rgba(78,124,255,.08);border:1px solid rgba(78,124,255,.16);
}
.pred-box p{margin:0;color:var(--muted);font-size:.84rem;line-height:1.5;font-weight:500}
.big-pred{font-size:1.7rem;font-weight:800;color:var(--text);margin:4px 0 2px;font-variant-numeric:tabular-nums;letter-spacing:-.03em}
.hidden{display:none !important}
.pool-banner{
  display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;
  padding:12px 14px;margin-bottom:14px;border-radius:16px;
  background:rgba(78,124,255,.08);border:1px solid rgba(78,124,255,.16);
  font-size:.84rem;color:var(--muted);font-weight:500;
}
.pool-banner strong{color:var(--text)}

/* ── Tables as holdings list ── */
.miner-table,.worker-table{width:100%;border-collapse:collapse;font-size:.86rem}
.miner-table th,.worker-table th{
  text-align:left;color:var(--muted);font-weight:600;font-size:.7rem;
  letter-spacing:.04em;text-transform:uppercase;padding:0 8px 10px 0;border-bottom:1px solid var(--line);
}
.miner-table td,.worker-table td{
  padding:12px 8px 12px 0;border-bottom:1px solid var(--line);vertical-align:middle;font-weight:500;
}
.miner-table tr:last-child td,.worker-table tr:last-child td{border-bottom:none}
.badge{
  display:inline-flex;align-items:center;gap:5px;padding:4px 9px;border-radius:999px;
  font-size:.72rem;font-weight:600;border:1px solid var(--line);background:var(--bg2);color:var(--muted);
}
.badge.on{color:var(--ok);border-color:transparent;background:var(--up-bg)}
.badge.off{color:var(--danger);border-color:transparent;background:var(--dn-bg)}
.mono{font-family:var(--mono);font-size:.78rem}
.hs-cell{font-weight:700;color:var(--accent);font-variant-numeric:tabular-nums}
.scroll-x{overflow-x:auto;-webkit-overflow-scrolling:touch}

/* ── Drawer ── */
.overlay{position:fixed;inset:0;background:rgba(0,0,0,.55);backdrop-filter:blur(6px);opacity:0;pointer-events:none;transition:.2s ease;z-index:40}
.overlay.open{opacity:1;pointer-events:auto}
.drawer{
  position:fixed;top:0;right:0;height:100%;width:min(460px,100%);
  background:var(--bg1);border-left:1px solid var(--line);box-shadow:var(--shadow);
  transform:translateX(105%);transition:transform .22s ease;z-index:50;display:flex;flex-direction:column;
  padding-top:var(--safe-t);
}
.drawer.open{transform:translateX(0)}
.drawer header{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:16px 18px;border-bottom:1px solid var(--line)}
.drawer header h3{margin:0;font-size:1.05rem;font-weight:700;letter-spacing:-.02em}
.drawer .body{padding:14px 18px 24px;overflow:auto;flex:1;-webkit-overflow-scrolling:touch}
.field{margin-bottom:14px}
.field label{display:block;font-size:.78rem;color:var(--muted);margin-bottom:7px;font-weight:500}
.field input,.field select{
  width:100%;padding:12px 13px;border-radius:12px;border:1px solid var(--line);
  background:var(--bg2);color:var(--text);outline:none;min-height:44px;font-size:16px;font-weight:500;
}
.field input:focus,.field select:focus{border-color:rgba(18,183,106,.45);box-shadow:0 0 0 3px rgba(18,183,106,.12)}
.field .hint{margin-top:6px;font-size:.72rem;color:var(--muted2);line-height:1.4}
.row2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.section-label{margin:18px 0 12px;font-size:.72rem;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);font-weight:600}
.drawer footer{
  padding:12px 16px calc(12px + var(--safe-b));border-top:1px solid var(--line);
  display:flex;gap:8px;flex-wrap:wrap;background:var(--bg1);
}
.miner-edit{border:1px solid var(--line);border-radius:14px;padding:14px;margin-bottom:10px;background:var(--bg2)}
.miner-edit .top{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:8px}
.toggle-row{
  display:flex;align-items:center;justify-content:space-between;gap:10px;
  padding:12px 14px;border:1px solid var(--line);border-radius:14px;background:var(--bg2);margin-bottom:10px;
}
.switch{position:relative;width:46px;height:26px;flex:0 0 auto}
.switch input{opacity:0;width:0;height:0}
.switch i{position:absolute;inset:0;background:#2a3140;border-radius:99px;cursor:pointer;transition:.15s}
.switch i:before{content:"";position:absolute;width:20px;height:20px;left:3px;top:3px;background:#fff;border-radius:50%;transition:.15s;box-shadow:0 1px 3px rgba(0,0,0,.2)}
.switch input:checked + i{background:var(--accent)}
.switch input:checked + i:before{transform:translateX(20px)}
.toast{
  position:fixed;bottom:calc(88px + var(--safe-b));left:50%;transform:translateX(-50%) translateY(12px);
  background:var(--bg3);border:1px solid var(--line2);color:var(--text);
  padding:12px 18px;border-radius:999px;font-size:.86rem;font-weight:500;opacity:0;pointer-events:none;transition:.2s ease;z-index:60;box-shadow:var(--shadow);
  max-width:90vw;text-align:center;
}
.toast.show{opacity:1;transform:translateX(-50%) translateY(0)}
.footer-note{margin-top:20px;text-align:center;color:var(--muted2);font-size:.74rem;padding-bottom:8px;font-weight:500}

/* ── Mobile nav ── */
.mob-nav{
  display:none;position:fixed;left:12px;right:12px;bottom:calc(10px + var(--safe-b));z-index:30;
  padding:8px;
  background:rgba(20,24,32,.94);border:1px solid var(--line);backdrop-filter:blur(18px);
  grid-template-columns:repeat(5,1fr);gap:2px;
  border-radius:20px;box-shadow:0 12px 40px rgba(0,0,0,.4);
}
.mob-nav button{
  background:transparent;border:none;color:var(--muted);padding:8px 2px;border-radius:14px;
  font-size:.62rem;font-weight:600;letter-spacing:.01em;
  display:flex;flex-direction:column;align-items:center;gap:3px;cursor:pointer;min-height:52px;
}
.mob-nav button .ic{
  width:30px;height:30px;border-radius:10px;display:grid;place-items:center;
  font-size:.95rem;line-height:1;background:transparent;transition:.15s ease;
}
.mob-nav button.active{color:var(--accent)}
.mob-nav button.active .ic{background:var(--up-bg)}

/* ── Pro tape (clean ticker, not terminal) ── */
.pro-tape{
  display:none;align-items:center;gap:0;overflow:hidden;
  margin-bottom:14px;border:1px solid var(--line);border-radius:14px;
  background:var(--card);font-size:.78rem;font-weight:500;
}
.pro-tape .pt-label{
  flex:0 0 auto;padding:9px 12px;background:var(--up-bg);color:var(--ok);
  letter-spacing:.06em;text-transform:uppercase;font-weight:700;font-size:.68rem;
  border-right:1px solid var(--line);
}
.pro-tape .pt-scroll{
  flex:1;overflow:hidden;white-space:nowrap;mask-image:linear-gradient(90deg,transparent,#000 8%,#000 92%,transparent);
}
.pro-tape .pt-track{display:inline-block;padding:9px 0;animation:tapeScroll 32s linear infinite;color:var(--muted)}
.pro-tape .pt-track b{color:var(--text);font-weight:600;margin:0 2px}
.pro-tape .pt-track .up{color:var(--ok)}
.pro-tape .pt-track .dn{color:var(--danger)}
.pro-tape .pt-track .sep{color:var(--line2);margin:0 14px}
@keyframes tapeScroll{0%{transform:translateX(0)}100%{transform:translateX(-50%)}}

/* ── MOBILE ── */
@media (max-width:900px){
  :root{--pad:14px}
  body{padding-bottom:calc(96px + var(--safe-b))}
  .mob-nav{display:grid}
  .mob-hero{display:none} /* portfolio hero covers this */
  .mob-sheet-handle{display:block}
  .chart-hint-mob{display:block}
  .topbar{padding:8px 2px 12px}
  .brand p,.pill#clockPill,.desk-only{display:none !important}
  .portfolio-hero{padding:18px;border-radius:20px}
  .ph-value{font-size:2rem}
  .grid-stats{grid-template-columns:repeat(2,1fr);gap:10px}
  .grid-stats .metric-card:nth-child(n+5){display:none}
  .grid-pool{grid-template-columns:repeat(2,1fr);gap:10px}
  .grid-pool .card:last-child{grid-column:1 / -1}
  .grid-main,.grid-main.ai-off,.grid-bottom,.grid-3{grid-template-columns:1fr;gap:12px}
  .stat-value{font-size:1.2rem}
  .big-pred{font-size:1.4rem}
  .chart-wrap{height:280px}
  .chart-wrap.candle,.chart-wrap.tall{height:min(52vh,400px)}
  .chart-wrap.sm{height:140px}
  .card{padding:14px;border-radius:18px}
  .tabs,.seg,.zoom-bar{flex-wrap:nowrap;overflow-x:auto;-webkit-overflow-scrolling:touch;padding-bottom:2px;scrollbar-width:none}
  .tabs::-webkit-scrollbar,.seg::-webkit-scrollbar,.zoom-bar::-webkit-scrollbar{display:none}
  .tab,.seg button{flex:0 0 auto;min-height:38px}
  .zoom-bar .btn.icon{min-width:44px;min-height:44px;flex:0 0 auto}
  .drawer{width:100%;border-radius:22px 22px 0 0;top:auto;height:min(92dvh,100%);bottom:0;transform:translateY(105%);left:0;right:0;border-left:none;border-top:1px solid var(--line)}
  .drawer.open{transform:translateY(0)}
  .row2{grid-template-columns:1fr}
  .section-panel{scroll-margin-top:72px}
  .ph-chips{gap:8px}
  .ph-chip{min-width:calc(50% - 4px)}
}
@media (max-width:400px){
  .stat-value{font-size:1.08rem}
  .ph-value{font-size:1.75rem}
}

/* ── PROFESSIONAL MODE (Stockie clean pro — not terminal) ── */
body.mode-pro{
  --bg0:#080A0F;
  --bg1:#0E1118;
  --bg2:#161B26;
  --bg3:#1E2433;
  --card:#10141C;
  --line:rgba(255,255,255,.07);
  --line2:rgba(255,255,255,.12);
  --text:#EEF1F6;
  --muted:#8E96A8;
  --muted2:#6A7286;
  --accent:#12B76A;
  --accent2:#5B8CFF;
  --warn:#F79009;
  --danger:#F04438;
  --ok:#12B76A;
  --radius:18px;
  --shadow:0 10px 36px rgba(0,0,0,.35);
  background:var(--bg0) !important;
}
body.mode-pro .pro-tape{display:flex !important}
body.mode-pro .logo{
  background:linear-gradient(145deg,var(--accent),var(--accent-dark,#0B8F52));
  box-shadow:0 6px 18px var(--accent-glow,rgba(18,183,106,.3));
}
body.mode-pro .portfolio-hero{
  border-color:rgba(18,183,106,.15);
  background:linear-gradient(160deg,#121820 0%,#0E131A 100%);
}
body.mode-pro .card,.mode-pro .metric-card{
  background:var(--card);
  border-color:var(--line);
}
body.mode-pro .tab.active,.mode-pro .seg button.active{
  background:var(--accent);color:#fff;
}
body.mode-pro .btn.primary{
  background:var(--accent);color:#fff;
}
body.mode-pro .ph-value{color:var(--text)}
body.mode-pro .footer-note{color:var(--muted2)}
body.mode-pro .stat-value.accent{color:var(--accent)}
@media (max-width:900px){
  body.mode-pro .chart-wrap, body.mode-pro .chart-wrap.candle{height:min(52vh,400px)}
}

/* ── Density / light theme / customization hooks ── */
body.density-compact{--pad:14px}
body.density-compact .card{padding:12px}
body.density-compact .portfolio-hero{padding:16px}
body.density-compact .stat-value{font-size:1.15rem}
body.density-compact .ph-value{font-size:clamp(1.6rem,4vw,2.2rem)}
body.density-spacious{--pad:24px}
body.density-spacious .card{padding:20px}
body.density-spacious .portfolio-hero{padding:28px}
body.theme-light{
  --bg0:#F4F6FA; --bg1:#FFFFFF; --bg2:#EEF1F6; --bg3:#E4E8F0;
  --card:#FFFFFF; --line:rgba(15,23,42,.08); --line2:rgba(15,23,42,.12);
  --text:#0F172A; --muted:#64748B; --muted2:#94A3B8;
  --shadow:0 8px 28px rgba(15,23,42,.08);
  --shadow-sm:0 2px 10px rgba(15,23,42,.06);
  background:var(--bg0) !important;
}
body.theme-light .logo{color:#fff}
body.theme-light .tab.active,body.theme-light .seg button.active{background:var(--text);color:#fff}
body.theme-light .btn.primary{color:#fff}
body.theme-light .mob-nav{background:rgba(255,255,255,.94);border-color:var(--line)}
body.theme-light .drawer{background:#fff}
body.theme-light .pill{background:var(--bg2)}
body.bg-solid{background:var(--bg0) !important}
body.bg-solid::before{display:none !important}
body.reduce-motion *,body.reduce-motion *::before,body.reduce-motion *::after{
  animation-duration:.01ms !important; animation-iteration-count:1 !important; transition-duration:.01ms !important;
}
.brand-logo-text{font-weight:800;letter-spacing:-.02em}

/* ── Minimalist UI mode (features stay; chrome simplifies) ── */
body.mode-minimal{
  --radius:10px; --radius-sm:8px; --shadow:none; --shadow-sm:none;
  --pad:14px;
  letter-spacing:0;
}
body.mode-minimal .topbar{
  background:transparent; backdrop-filter:none; border:none; padding:6px 0 10px;
}
body.mode-minimal .logo{
  border-radius:8px; box-shadow:none; width:34px; height:34px; font-size:12px;
}
body.mode-minimal .portfolio-hero,
body.mode-minimal .card,
body.mode-minimal .metric-card{
  border-radius:10px; box-shadow:none; border-color:var(--line2);
  background:var(--bg1);
}
body.mode-minimal .portfolio-hero::before{display:none}
body.mode-minimal .ph-value{font-size:clamp(1.6rem,4vw,2.2rem); font-weight:700}
body.mode-minimal .sec-title{
  text-transform:none; letter-spacing:0; font-size:.85rem; font-weight:600; color:var(--muted);
}
body.mode-minimal .pro-tape{display:none !important}
body.mode-minimal .metric-card .ico{display:none}
body.mode-minimal .ph-chip{border-radius:8px; background:var(--bg2)}
body.mode-minimal .tab,.mode-minimal .seg button{
  border-radius:8px; background:transparent; border:1px solid var(--line);
}
body.mode-minimal .tab.active,.mode-minimal .seg button.active{
  background:var(--accent); color:#fff; border-color:transparent;
}
body.mode-minimal .btn{border-radius:8px; box-shadow:none}
body.mode-minimal .btn.primary{box-shadow:none}
body.mode-minimal .mob-nav{border-radius:12px; box-shadow:none}
body.mode-minimal .candle-legend-row{display:none}
body.mode-minimal .footer-note{opacity:.7}
body.mode-minimal .stat-label{font-size:.72rem}
body.mode-minimal .drawer{border-radius:0}
</style>
</head>
<body>
<div class="app">
  <div class="topbar">
    <div class="brand">
      <div class="logo brand-logo-text" id="logoLetters">DC</div>
      <div>
        <h1 id="dashTitle">Deer Crypto Monitor</h1>
        <p id="brandTagline">Crypto mining portfolio monitor</p>
      </div>
    </div>
    <div class="top-actions">
      <div class="pill"><span class="dot" id="statusDot"></span><span id="statusText">…</span></div>
      <div class="pill desk-only" id="fleetPill">0 miners</div>
      <div class="pill desk-only" id="clockPill">—</div>
      <button class="btn primary" id="btnSettings" type="button">Settings</button>
    </div>
  </div>

  <div class="pro-tape" id="proTape" aria-hidden="true">
    <div class="pt-label">Live</div>
    <div class="pt-scroll"><div class="pt-track" id="proTapeTrack">Loading market tape…</div></div>
  </div>

  <!-- Portfolio hero -->
  <div class="portfolio-hero section-panel" id="sec-overview">
    <div class="ph-top">
      <div class="ph-label" id="portfolioLabel">Fleet portfolio · hashrate</div>
      <span class="ph-badge flat" id="phTrendBadge">—</span>
    </div>
    <div class="ph-value"><span id="hs">—</span><span class="unit">H/s</span></div>
    <div class="ph-sub">Peak <span id="hsPeak">—</span> · avg <span id="hsAvg">—</span> · med <span id="hsMed">—</span> · min <span id="hsMin">—</span></div>
    <div class="ph-chips">
      <div class="ph-chip">
        <div class="l">Est. daily</div>
        <div class="v b" id="earn">—</div>
      </div>
      <div class="ph-chip">
        <div class="l">XMR / day</div>
        <div class="v" id="xmr">—</div>
      </div>
      <div class="ph-chip">
        <div class="l">XMR price</div>
        <div class="v w" id="price">—</div>
      </div>
      <div class="ph-chip">
        <div class="l">Shares</div>
        <div class="v g" id="shares">—</div>
      </div>
    </div>
  </div>

  <!-- hidden mobile hero still updated by JS -->
  <div class="mob-hero" id="mobHero" aria-hidden="true" style="display:none">
    <div class="mh"><div class="l">Fleet H/s</div><div class="v a" id="mhHs">—</div></div>
    <div class="mh"><div class="l">Est $/day</div><div class="v b" id="mhEarn">—</div></div>
    <div class="mh"><div class="l">XMR due</div><div class="v w" id="mhDue">—</div></div>
  </div>

  <div id="poolBanner" class="pool-banner hidden">
    <div>Pool: <strong>MoneroOcean</strong> · wallet <strong id="poolWalletShort">—</strong></div>
    <button class="btn sm" id="btnPoolRefresh" type="button">Refresh pool</button>
  </div>

  <div class="sec-title" id="watchTitle">Watchlist · session</div>
  <div class="grid-stats" id="watchGrid">
    <div class="metric-card">
      <div class="ico g">↑</div>
      <div class="stat-label">Uptime</div>
      <div class="stat-value" id="uptime">—</div>
      <div class="stat-sub" id="algoLine">algo —</div>
    </div>
    <div class="metric-card">
      <div class="ico b">%</div>
      <div class="stat-label">Accept rate</div>
      <div class="stat-value" id="shareRate">—</div>
      <div class="stat-sub">local shares</div>
    </div>
    <div class="metric-card">
      <div class="ico w">℃</div>
      <div class="stat-label">CPU temp</div>
      <div class="stat-value warn" id="cpuTemp">—</div>
      <div class="stat-sub" id="cpuTempSub">sensors</div>
    </div>
    <div class="metric-card">
      <div class="ico">◎</div>
      <div class="stat-label">Hash direction</div>
      <div class="stat-value accent" id="hashDir">—</div>
      <div class="stat-sub" id="hashDirSub">AI guess</div>
    </div>
    <div class="metric-card desk-only">
      <div class="ico">↻</div>
      <div class="stat-label">Fan</div>
      <div class="stat-value" id="fanRpm">—</div>
      <div class="stat-sub" id="fanSub">RPM / %</div>
    </div>
    <div class="metric-card desk-only">
      <div class="ico b">▣</div>
      <div class="stat-label">CPU load</div>
      <div class="stat-value" id="cpuLoad">—</div>
      <div class="stat-sub" id="hwVendor">vendor —</div>
    </div>
  </div>

  <!-- earnCard id kept for JS show/hide -->
  <div id="earnCard" class="hidden" aria-hidden="true"></div>

<div id="poolGrid" class="grid-pool section-panel hidden">
    <div class="card">
      <div class="stat-label">XMR Due (pool)</div>
      <div class="stat-value accent" id="poolDue">—</div>
      <div class="stat-sub">unpaid balance</div>
    </div>
    <div class="card">
      <div class="stat-label">XMR Paid (total)</div>
      <div class="stat-value blue" id="poolPaid">—</div>
      <div class="stat-sub">lifetime payouts</div>
    </div>
    <div class="card">
      <div class="stat-label">Pool Hashrate</div>
      <div class="stat-value" id="poolHs">—</div>
      <div class="stat-sub">wallet reported H/s</div>
    </div>
    <div class="card">
      <div class="stat-label">Workers</div>
      <div class="stat-value" id="poolWorkers">—</div>
      <div class="stat-sub" id="poolWorkersSub">online / total</div>
    </div>
    <div class="card">
      <div class="stat-label">Valid Shares</div>
      <div class="stat-value" id="poolShares">—</div>
      <div class="stat-sub" id="poolInvalid">invalid —</div>
    </div>
  </div>

  <div class="sec-title">Markets &amp; insights</div>
  <div class="grid-main section-panel" id="mainGrid">
    <div class="card chart-card" id="sec-charts">
      <h2>
        <span>Markets</span>
        <span class="tag" id="chartHint">Performance</span>
      </h2>
      <div class="chart-toolbar">
        <div class="seg" id="chartModeSeg">
          <button type="button" data-mode="line" class="active">Line</button>
          <button type="button" data-mode="candle">Candles</button>
        </div>
        <div class="zoom-bar" id="zoomBar">
          <button class="btn sm icon" id="btnZoomOut" type="button" title="Zoom out">−</button>
          <button class="btn sm icon" id="btnZoomIn" type="button" title="Zoom in">+</button>
          <button class="btn sm" id="btnZoomReset" type="button" title="Reset zoom">Reset</button>
          <button class="btn sm" id="btnChartTall" type="button" title="Taller chart">Tall</button>
          <span class="zoom-label" id="zoomLabel">100%</span>
        </div>
      </div>
      <div class="tabs" id="rangeTabs">
        <button class="tab active" data-mode="live" type="button">Live</button>
        <button class="tab" data-mode="0.5" type="button">30m</button>
        <button class="tab" data-mode="2" type="button">2h</button>
        <button class="tab" data-mode="8" type="button">8h</button>
        <button class="tab" data-mode="all" type="button">All</button>
      </div>
      <div class="seg hidden" id="candleOpts">
        <button type="button" data-metric="hashrate" class="active">Hashrate OHLC</button>
        <button type="button" data-metric="xmr">XMR earned</button>
        <button type="button" data-iv="60">1m</button>
        <button type="button" data-iv="300">5m</button>
        <button type="button" data-iv="900">15m</button>
      </div>
      <div class="chart-wrap" id="lineWrap"><canvas id="mainChart"></canvas></div>
      <div class="chart-wrap candle hidden" id="candleWrap">
        <canvas id="candleCanvas"></canvas>
        <div class="candle-tip" id="candleTip"></div>
      </div>
      <div class="chart-hint-mob">Pinch/use +/− to zoom · drag empty space to pan · tap a candle for details</div>
      <div class="candle-legend-row" id="candleLegend">
        <span><i style="background:#00e5a0"></i>Candles (primary)</span>
        <span><i style="background:#5b8cff"></i>Est. $/day line</span>
        <span><i style="background:#ffb020"></i>XMR price line</span>
        <span>Hover / tap for OHLC · wheel / pinch zoom</span>
      </div>
    </div>

    <div class="card" id="aiCard">
      <h2><span>AI Insights</span><span class="tag">Local</span></h2>
      <div class="stat-label">Predicted average hashrate</div>
      <div class="big-pred" id="predHs">—</div>
      <div class="stat-sub">Horizon <span id="predHorizon">60</span> min · <span class="delta flat" id="predTrend">—</span></div>
      <div class="meter"><i id="confBar"></i></div>
      <div class="stat-sub">Confidence <span id="predConf">—</span> · band <span id="predBand">—</span></div>
      <div class="pred-box"><p id="predSummary">…</p></div>
      <div id="priceIntelChip" class="intel-chip hidden">Price intel off</div>
      <div id="nnChip" class="intel-chip hidden">Classic AI</div>
      <div style="margin-top:12px" class="kv">
        <span>Session avg</span><span id="predCurAvg">—</span>
        <span>EWMA / last</span><span id="predEwma">—</span>
        <span>Samples</span><span id="predPoints">—</span>
        <span>Pred. daily</span><span id="predEarn">—</span>
        <span>Live anchor</span><span id="predLive">—</span>
        <span>Direction</span><span id="predDir">—</span>
        <span>P(up)</span><span id="predPUp">—</span>
        <span>5m / 60m / 8h</span><span id="predHorizons">—</span>
        <span>Engine</span><span id="predEngine">—</span>
        <span>XMR spot (intel)</span><span id="predSpot">—</span>
        <span>24h / 7d</span><span id="predChg">—</span>
      </div>
      <div class="chart-wrap sm" style="margin-top:12px"><canvas id="predChart"></canvas></div>
    </div>
  </div>

  <div class="sec-title">Holdings</div>
  <div class="grid-bottom section-panel" id="sec-miners">
    <div class="card">
      <h2><span>Holdings · miners</span><span class="tag" id="minerCountLabel">—</span></h2>
      <div class="scroll-x">
        <table class="miner-table">
          <thead><tr><th>Name</th><th>Status</th><th>H/s</th><th>Shares</th><th>Uptime</th><th>Pool</th></tr></thead>
          <tbody id="minerBody"><tr><td colspan="6" style="color:var(--muted)">…</td></tr></tbody>
        </table>
      </div>
    </div>
    <div class="card" id="poolWorkersCard">
      <h2><span>Pool workers</span><span class="tag" id="pwLabel">MoneroOcean</span></h2>
      <div class="scroll-x">
        <table class="worker-table">
          <thead><tr><th>Worker</th><th>Status</th><th>H/s</th><th>Shares</th><th>Algo</th></tr></thead>
          <tbody id="workerBody"><tr><td colspan="5" style="color:var(--muted)">Enable pool wallet in Settings</td></tr></tbody>
        </table>
      </div>
    </div>
  </div>

  <div class="sec-title">Details</div>
  <div class="grid-3 section-panel" id="sec-more">
    <div class="card">
      <h2>Stability</h2>
      <div class="kv">
        <span>Std dev</span><span id="hsStd">—</span>
        <span>Variability</span><span id="hsCv">—</span>
        <span>History</span><span id="histCount">—</span>
        <span>Updated</span><span id="lastUpdate">—</span>
      </div>
    </div>
    <div class="card">
      <h2>Network</h2>
      <div class="kv">
        <span>Bind</span><span id="bindMode">localhost</span>
        <span>Port</span><span id="bindPort">5000</span>
        <span>Page</span><span id="pageUrl">—</span>
        <span>AI</span><span id="aiState">on</span>
      </div>
    </div>
    <div class="card">
      <h2>Connection</h2>
      <div class="kv">
        <span>Pool str</span><span id="pool">—</span>
        <span>Worker</span><span id="worker">—</span>
        <span>Algo</span><span id="algo">—</span>
        <span>Chart</span><span id="chartModeLabel">line</span>
      </div>
    </div>
  </div>

  <p class="footer-note" id="footerNote">Deer Crypto Monitor · local portfolio UI · estimates only · not financial advice</p>
</div>

<nav class="mob-nav" id="mobNav" aria-label="Mobile">
  <button type="button" data-sec="sec-overview" class="active"><span class="ic">⌂</span>Home</button>
  <button type="button" data-sec="sec-charts"><span class="ic">▤</span>Markets</button>
  <button type="button" data-sec="poolGrid"><span class="ic">◈</span>Pool</button>
  <button type="button" data-sec="sec-miners"><span class="ic">☰</span>Holdings</button>
  <button type="button" id="mobSettings"><span class="ic">⚙</span>More</button>
</nav>

<div class="overlay" id="overlay"></div>
<aside class="drawer" id="drawer" aria-hidden="true">
  <div class="mob-sheet-handle" aria-hidden="true"></div>
  <header>
    <h3>Settings</h3>
    <button class="btn ghost" id="btnClose" type="button">Close</button>
  </header>
  <div class="body">
    <div class="section-label">MoneroOcean pool wallet</div>
    <div class="toggle-row">
      <div>
        <span>Pull pool stats</span>
        <div class="hint" style="margin-top:4px">Due XMR, paid, workers, pool hashrate via api.moneroocean.stream</div>
      </div>
      <label class="switch"><input type="checkbox" id="s_pool_enabled"><i></i></label>
    </div>
    <div class="field">
      <label for="s_pool_wallet">Payout wallet address</label>
      <input id="s_pool_wallet" type="text" spellcheck="false" autocomplete="off" placeholder="4… your Monero address">
      <div class="hint">Same address you use on moneroocean.stream/#/dashboard</div>
    </div>
    <div class="field">
      <label for="s_pool_poll_seconds">Pool poll interval (sec)</label>
      <input id="s_pool_poll_seconds" type="number" min="15" max="300">
    </div>

    <div class="section-label">Charts</div>
    <div class="row2">
      <div class="field">
        <label for="s_chart_mode">Default chart mode</label>
        <select id="s_chart_mode">
          <option value="line">Line</option>
          <option value="candle">Candlestick</option>
        </select>
      </div>
      <div class="field">
        <label for="s_candle_metric">Candle metric</label>
        <select id="s_candle_metric">
          <option value="hashrate">Hashrate OHLC</option>
          <option value="xmr">XMR earned / due</option>
        </select>
      </div>
    </div>
    <div class="field">
      <label for="s_candle_interval_sec">Candle interval (seconds)</label>
      <input id="s_candle_interval_sec" type="number" min="30" max="3600" step="30">
      <div class="hint">Hashrate candles use open/high/low/close of samples in each bucket. XMR candles track pool due (if available) or accrued estimate — green when balance/earn goes up.</div>
    </div>

    <div class="section-label">AI forecast</div>
    <div class="toggle-row">
      <div><span>Enable AI hashrate forecast</span></div>
      <label class="switch"><input type="checkbox" id="s_ai_forecast_enabled"><i></i></label>
    </div>
    <div class="field">
      <label for="s_ai_mode">Forecast engine</label>
      <select id="s_ai_mode">
        <option value="classic">Classic realtime multi-task (recommended)</option>
        <option value="neural">Neural net (local MLP)</option>
        <option value="hybrid">Hybrid (neural + classic blend)</option>
      </select>
      <div class="hint">Classic anchors to live hashrate. Neural / Hybrid use a local MLP and blend with classic.</div>
    </div>
    <div class="toggle-row">
      <div>
        <span>Realtime AI accuracy</span>
        <div class="hint" style="margin-top:4px">Tracks live hash, momentum, volatility every poll for faster/more accurate forecasts.</div>
      </div>
      <label class="switch"><input type="checkbox" id="s_ai_realtime" checked><i></i></label>
    </div>

    <div class="section-label">Neural net modes</div>
    <div class="field">
      <label for="s_nn_mode">Neural profile</label>
      <select id="s_nn_mode">
        <option value="balanced">Balanced — default</option>
        <option value="aggressive">Aggressive — faster, more reactive</option>
        <option value="conservative">Conservative — smoother, more classic weight</option>
        <option value="deep">Deep — larger net, more training</option>
        <option value="custom">Custom — use sliders below</option>
      </select>
      <div class="hint">Profiles set hidden size, window, epochs, LR, and classic blend. Choose Custom to edit each value.</div>
    </div>
    <div class="row2" id="nnOptions">
      <div class="field">
        <label for="s_nn_hidden">Hidden units</label>
        <input id="s_nn_hidden" type="number" min="4" max="32">
      </div>
      <div class="field">
        <label for="s_nn_window">Window</label>
        <input id="s_nn_window" type="number" min="6" max="48">
      </div>
    </div>
    <div class="row2">
      <div class="field">
        <label for="s_nn_epochs">Train epochs</label>
        <input id="s_nn_epochs" type="number" min="5" max="200">
      </div>
      <div class="field">
        <label for="s_nn_lr">Learning rate</label>
        <input id="s_nn_lr" type="number" min="0.001" max="0.2" step="0.001">
      </div>
    </div>
    <div class="row2">
      <div class="field">
        <label for="s_nn_classic_blend">Classic blend (0–1)</label>
        <input id="s_nn_classic_blend" type="number" min="0.05" max="0.95" step="0.05">
        <div class="hint">Higher = more classic / less pure neural.</div>
      </div>
      <div class="field">
        <label for="s_nn_train_pairs">Train pairs</label>
        <input id="s_nn_train_pairs" type="number" min="20" max="400" step="10">
      </div>
    </div>
    <div class="field">
      <label for="s_nn_clip">Normalized clip</label>
      <input id="s_nn_clip" type="number" min="1" max="4" step="0.1">
      <div class="hint">Limits runaway NN outputs (typically 2–3).</div>
    </div>

    <div class="section-label">History database</div>
    <div class="field">
      <label for="s_history_backend">Storage backend</label>
      <select id="s_history_backend">
        <option value="json">Default JSON (simple, portable)</option>
        <option value="sqlite">Improved SQLite (indexed, longer history, better charts)</option>
      </select>
      <div class="hint">SQLite is faster for long sessions, supports more samples (up to 20k), and improves chart/AI accuracy. Applies on Save (no restart needed).</div>
    </div>
    <div class="warn-box">
      <strong>Warning — read before switching:</strong>
      <ul style="margin:8px 0 0 18px;padding:0;line-height:1.45">
        <li>JSON → SQLite: one-time import into <code>mining_history.db</code> (JSON file kept as backup).</li>
        <li>SQLite → JSON: does <strong>not</strong> auto-export. New samples go to JSON; old SQLite rows stay only in the .db file.</li>
        <li>Copy/backup <code>mining_history.json</code> (and <code>mining_history.db</code> if present) before changing.</li>
        <li>SQLite is local-only; do not put the .db on a network share while the dashboard is running.</li>
      </ul>
    </div>
    <div class="row2" id="aiOptions">
      <div class="field">
        <label for="s_predict_horizon_min">Horizon (min)</label>
        <input id="s_predict_horizon_min" type="number" min="5" max="1440">
      </div>
      <div class="field">
        <label for="s_predict_lookback">Lookback samples</label>
        <input id="s_predict_lookback" type="number" min="10" max="2000">
      </div>
    </div>
    <div class="section-label">Hardware / Windows</div>
    <div class="toggle-row">
      <div>
        <span>Show CPU temp &amp; fans</span>
        <div class="hint" style="margin-top:4px">Reads sensors via Windows WMI. LibreHardwareMonitor improves accuracy.</div>
      </div>
      <label class="switch"><input type="checkbox" id="s_hw_sensors_enabled" checked><i></i></label>
    </div>
    <div class="field">
      <label for="s_pc_vendor">PC / laptop brand</label>
      <select id="s_pc_vendor">
        <option value="auto">Auto-detect</option>
        <option value="dell">Dell</option>
        <option value="hp">HP</option>
        <option value="lenovo">Lenovo</option>
        <option value="asus">ASUS</option>
        <option value="msi">MSI</option>
        <option value="acer">Acer</option>
        <option value="generic">Generic / other</option>
      </select>
      <div class="hint">Used for capability checks. Click Detect hardware to scan sensors.</div>
    </div>
    <button class="btn sm" id="btnHwDetect" type="button">Detect hardware</button>
    <div class="hint" id="hwDetectOut" style="margin:8px 0 12px"></div>
    <div class="toggle-row">
      <div>
        <span>Windows mode</span>
        <div class="hint" style="margin-top:4px">Plug into Windows 11 power / thermal policies for mining efficiency hints.</div>
      </div>
      <label class="switch"><input type="checkbox" id="s_windows_mode_enabled"><i></i></label>
    </div>
    <div class="toggle-row">
      <div>
        <span>Allow fan / power optimization</span>
        <div class="hint" style="margin-top:4px">Optional. Power plans + Lenovo Fan Control if configured. Opt-in required.</div>
      </div>
      <label class="switch"><input type="checkbox" id="s_windows_fan_control_enabled"><i></i></label>
    </div>
    <div class="toggle-row">
      <div>
        <span>AI may control fans (classic or neural)</span>
        <div class="hint" style="margin-top:4px">Optional mild boost only (eco/balanced → performance). Your selected profile stays locked; soft temps will not thrash low↔high. Emergency uses near-critical temps only.</div>
      </div>
      <label class="switch"><input type="checkbox" id="s_ai_fan_control_enabled"><i></i></label>
    </div>
    <div class="toggle-row">
      <div>
        <span>Request administrator privileges</span>
        <div class="hint" style="margin-top:4px">On next start, UAC prompt elevates the app so CPU temp / Lenovo fan tools work better.</div>
      </div>
      <label class="switch"><input type="checkbox" id="s_request_admin"><i></i></label>
    </div>
    <div class="warn-box">
      <strong>Warning:</strong> Fan/power control can affect thermals, noise, and stability. Direct RPM on Lenovo uses <strong>Lenovo Fan Control</strong> (3rd-party). Wrong settings can reduce hashrate or increase heat. Keep off unless you understand the risk. Prefer running elevated when using fan tools.
    </div>
    <div class="field">
      <label for="s_fan_profile">Fan / power profile</label>
      <select id="s_fan_profile">
        <option value="eco">Eco (cooler, quieter) · Lenovo --low-speed</option>
        <option value="balanced">Balanced · Lenovo --normal-speed</option>
        <option value="performance">Performance · Lenovo --high-speed</option>
        <option value="max_hash">Max hash · Lenovo --high-speed + high power plan</option>
      </select>
    </div>
    <div class="field">
      <label for="s_lenovo_fan_control_path">Lenovo Fan Control .exe path</label>
      <input id="s_lenovo_fan_control_path" type="text" spellcheck="false" placeholder="C:\...\LenovoFanControl-x64.exe">
      <div class="hint">Optional. Dashboard talks to <code>\\.\EnergyDrv</code> directly (same as <a href="https://github.com/jiarandiana0307/Lenovo-Fan-Control" target="_blank" rel="noopener">Lenovo-Fan-Control source</a>). GUI exe is only a fallback and will not be re-opened in a loop.</div>
    </div>
    <button class="btn sm" id="btnFanApply" type="button">Apply profile now</button>
    <button class="btn sm" id="btnFanStop" type="button">Stop Lenovo fan worker</button>
    <div class="toggle-row">
      <div>
        <span>AI price intel (XMR market)</span>
        <div class="hint" style="margin-top:4px">Live XMR price + trends for better USD estimates. Multi-provider (avoids CoinGecko 429 when possible).</div>
      </div>
      <label class="switch"><input type="checkbox" id="s_ai_price_intel_enabled"><i></i></label>
    </div>
    <div class="warn-box" id="aiPriceWarn">
      <strong>Warning:</strong> Extra network calls. Can slow the dashboard or fail offline. Prefer <strong>Auto</strong> or <strong>CryptoCompare / CoinPaprika / Kraken</strong> if CoinGecko rate-limits (HTTP 429).
    </div>
    <div class="field">
      <label for="s_price_provider">Price data provider</label>
      <select id="s_price_provider">
        <option value="auto">Auto (best available — recommended)</option>
        <option value="coinpaprika">CoinPaprika (free, reliable)</option>
        <option value="kraken">Kraken exchange ticker</option>
        <option value="binance">Binance (XMRUSDT)</option>
        <option value="coincap">CoinCap</option>
        <option value="cryptocompare">CryptoCompare (may need API key)</option>
        <option value="coingecko">CoinGecko (often rate-limits 429)</option>
      </select>
      <div class="hint">Auto tries CoinPaprika → Kraken → Binance → CoinCap → CryptoCompare → CoinGecko. Caches 10 min; serves last good data if all fail.</div>
    </div>

    <div class="section-label">UI mode</div>
    <div class="field">
      <label for="s_ui_mode">Interface style</label>
      <select id="s_ui_mode">
        <option value="default">Stockie portfolio (default)</option>
        <option value="pro">Pro — live tape + deeper contrast</option>
        <option value="minimal">Minimalist — clean / basic chrome</option>
      </select>
      <div class="hint">Minimalist simplifies shadows, icons, and chrome but keeps all features. Instant switch — no restart.</div>
    </div>

    <div class="section-label">Miners (multi)</div>
    <div id="minerList"></div>
    <button class="btn sm" id="btnAddMiner" type="button">+ Add miner</button>

    <div class="section-label">Network / server</div>
    <div class="field">
      <label for="s_bind_mode">Web UI access</label>
      <select id="s_bind_mode">
        <option value="127.0.0.1">This PC only</option>
        <option value="0.0.0.0">Local network / LAN</option>
      </select>
    </div>
    <div class="row2">
      <div class="field">
        <label for="s_bind_port">Port</label>
        <input id="s_bind_port" type="number" min="1" max="65535">
      </div>
      <div class="field">
        <label for="s_poll_seconds">Miner poll (sec)</label>
        <input id="s_poll_seconds" type="number" min="3" max="120">
      </div>
    </div>

    <div class="section-label">Branding</div>
    <div class="field">
      <label for="s_dashboard_title">Window / page title</label>
      <input id="s_dashboard_title" type="text" placeholder="Deer Crypto Monitor">
    </div>
    <div class="row2">
      <div class="field">
        <label for="s_brand_name">Brand name</label>
        <input id="s_brand_name" type="text" placeholder="Deer Crypto Monitor">
      </div>
      <div class="field">
        <label for="s_logo_letters">Logo letters</label>
        <input id="s_logo_letters" type="text" maxlength="3" placeholder="DC">
      </div>
    </div>
    <div class="field">
      <label for="s_brand_tagline">Tagline</label>
      <input id="s_brand_tagline" type="text" placeholder="Crypto mining portfolio monitor">
    </div>
    <div class="field">
      <label for="s_portfolio_label">Portfolio hero label</label>
      <input id="s_portfolio_label" type="text" placeholder="Fleet portfolio · hashrate">
    </div>

    <div class="section-label">Look &amp; feel</div>
    <div class="row2">
      <div class="field">
        <label for="s_theme_mode">Theme</label>
        <select id="s_theme_mode">
          <option value="dark">Dark</option>
          <option value="light">Light</option>
        </select>
      </div>
      <div class="field">
        <label for="s_color_preset">Color preset</label>
        <select id="s_color_preset">
          <option value="stockie">Stockie green/blue</option>
          <option value="monero">Monero orange</option>
          <option value="ocean">Ocean</option>
          <option value="sunset">Sunset</option>
          <option value="violet">Violet</option>
          <option value="custom">Custom colors</option>
        </select>
      </div>
    </div>
    <div class="row2">
      <div class="field">
        <label for="s_theme_accent">UI accent (buttons / logo)</label>
        <input id="s_theme_accent" type="color">
      </div>
      <div class="field">
        <label for="s_theme_accent2">UI secondary</label>
        <input id="s_theme_accent2" type="color">
      </div>
    </div>
    <div class="hint" style="margin:-4px 0 12px">These change the app chrome (logo, primary buttons, badges). Chart colors are separate below.</div>

    <div class="section-label">Chart colors</div>
    <div class="row2">
      <div class="field">
        <label for="s_chart_hs_color">Hashrate line</label>
        <input id="s_chart_hs_color" type="color">
      </div>
      <div class="field">
        <label for="s_chart_price_color">Price line</label>
        <input id="s_chart_price_color" type="color">
      </div>
    </div>
    <div class="field">
      <label for="s_chart_forecast_color">AI forecast line</label>
      <input id="s_chart_forecast_color" type="color">
    </div>
    <div class="hint" style="margin:-4px 0 12px">Only the line/candle chart series. Independent of UI accent.</div>

    <div class="row2">
      <div class="field">
        <label for="s_density">Density</label>
        <select id="s_density">
          <option value="compact">Compact</option>
          <option value="comfortable">Comfortable</option>
          <option value="spacious">Spacious</option>
        </select>
      </div>
      <div class="field">
        <label for="s_font_scale">Font scale %</label>
        <input id="s_font_scale" type="number" min="90" max="130" step="5">
      </div>
    </div>
    <div class="row2">
      <div class="field">
        <label for="s_card_radius">Card radius</label>
        <input id="s_card_radius" type="number" min="8" max="28" step="1">
      </div>
      <div class="field">
        <label for="s_background_style">Background</label>
        <select id="s_background_style">
          <option value="soft_glow">Soft glow</option>
          <option value="solid">Solid</option>
        </select>
      </div>
    </div>
    <div class="row2">
      <div class="field">
        <label for="s_currency_symbol">Currency symbol</label>
        <input id="s_currency_symbol" type="text" maxlength="3" placeholder="$">
      </div>
      <div class="field">
        <label for="s_refresh_ui_ms">UI refresh (ms)</label>
        <input id="s_refresh_ui_ms" type="number" min="2000" max="60000" step="500">
      </div>
    </div>
    <div class="field">
      <label for="s_history_keep">History samples to keep</label>
      <input id="s_history_keep" type="number" min="50" max="20000">
      <div class="hint">SQLite allows higher values (up to 20k).</div>
    </div>

    <div class="section-label">Layout visibility</div>
    <div class="toggle-row">
      <div><span>Portfolio hero</span></div>
      <label class="switch"><input type="checkbox" id="s_show_portfolio_hero" checked><i></i></label>
    </div>
    <div class="toggle-row">
      <div><span>Watchlist cards</span></div>
      <label class="switch"><input type="checkbox" id="s_show_watchlist" checked><i></i></label>
    </div>
    <div class="toggle-row">
      <div><span>Holdings (miners)</span></div>
      <label class="switch"><input type="checkbox" id="s_show_holdings" checked><i></i></label>
    </div>
    <div class="toggle-row">
      <div><span>Details panels</span></div>
      <label class="switch"><input type="checkbox" id="s_show_details" checked><i></i></label>
    </div>
    <div class="toggle-row">
      <div><span>Footer note</span></div>
      <label class="switch"><input type="checkbox" id="s_show_footer" checked><i></i></label>
    </div>
    <div class="row2">
      <div class="field">
        <label for="s_show_price_chart">Price on line chart</label>
        <select id="s_show_price_chart"><option value="true">On</option><option value="false">Off</option></select>
      </div>
      <div class="field">
        <label for="s_show_earnings_card">Earnings chips</label>
        <select id="s_show_earnings_card"><option value="true">On</option><option value="false">Off</option></select>
      </div>
    </div>
    <div class="toggle-row">
      <div><span>Chart area fill</span></div>
      <label class="switch"><input type="checkbox" id="s_chart_fill" checked><i></i></label>
    </div>
    <div class="toggle-row">
      <div><span>Smooth chart curves</span></div>
      <label class="switch"><input type="checkbox" id="s_chart_smooth" checked><i></i></label>
    </div>
    <div class="toggle-row">
      <div><span>Compact numbers</span><div class="hint" style="margin-top:4px">e.g. 1.8k H/s</div></div>
      <label class="switch"><input type="checkbox" id="s_number_compact"><i></i></label>
    </div>
    <div class="toggle-row">
      <div><span>Reduce motion</span></div>
      <label class="switch"><input type="checkbox" id="s_reduced_motion"><i></i></label>
    </div>

    <div class="section-label">App behavior</div>
    <div class="toggle-row">
      <div>
        <span>Open browser on start</span>
        <div class="hint" style="margin-top:4px">When launched as installed app, open the dashboard URL.</div>
      </div>
      <label class="switch"><input type="checkbox" id="s_open_browser_on_start" checked><i></i></label>
    </div>
    <div class="toggle-row">
      <div>
        <span>Start with Windows</span>
        <div class="hint" style="margin-top:4px">Adds a login startup entry (this user only).</div>
      </div>
      <label class="switch"><input type="checkbox" id="s_start_with_windows"><i></i></label>
    </div>

    <div class="section-label">Earnings model</div>
    <div class="row2">
      <div class="field">
        <label for="s_pool_fee_factor">Net factor</label>
        <input id="s_pool_fee_factor" type="number" min="0.5" max="1" step="0.01">
      </div>
      <div class="field">
        <label for="s_earnings_factor">Difficulty factor</label>
        <input id="s_earnings_factor" type="number" min="0.1" max="2" step="0.01">
      </div>
    </div>
    <div class="row2">
      <div class="field">
        <label for="s_fallback_xmr_per_kh">Fallback XMR/kH</label>
        <input id="s_fallback_xmr_per_kh" type="number" min="0" step="0.00001">
      </div>
      <div class="field">
        <label for="s_price_fallback">Price fallback</label>
        <input id="s_price_fallback" type="number" min="1" step="0.01">
      </div>
    </div>
  </div>
  <footer>
    <button class="btn primary" id="btnSave" type="button">Save</button>
    <button class="btn" id="btnReset" type="button">Reset</button>
  </footer>
</aside>
<div class="toast" id="toast"></div>

<script>
const $ = (id) => document.getElementById(id);
let fullHistory = [];
let candles = { hashrate: [], xmr: [], interval_sec: 60 };
let settings = {};
let chartMode = 'line';
let rangeMode = 'live';
let candleMetric = 'hashrate';
let candleIv = 60;
let refreshTimer = null;
let mainChart, predChart;
let editMiners = [];
let lastData = null;
let candleHit = null;      // layout cache for hover
let candleHoverIdx = -1;
let candleDrawData = [];
// zoom windows as fractions [0,1] of visible series
let candleZoom = { start: 0, end: 1 };
let lineZoom = { start: 0, end: 1 };
let panDrag = null;        // { mode, startX, z0, z1 }
let pinchState = null;     // { dist, start, end, mode }
let chartTall = false;

const isMobile = () => window.matchMedia('(max-width: 900px)').matches;

function clamp01(x) { return Math.max(0, Math.min(1, x)); }
const MIN_ZOOM_SPAN = 0.12; // prevent ultra-zoom that makes candles absurdly wide
function zoomSpan(z) { return Math.max(MIN_ZOOM_SPAN, z.end - z.start); }
function zoomPercent(z) { return Math.round(100 / Math.max(MIN_ZOOM_SPAN, z.end - z.start)); }
function updateZoomLabel() {
  const z = chartMode === 'candle' ? candleZoom : lineZoom;
  const el = $('zoomLabel');
  if (el) el.textContent = zoomPercent(z) + '%';
}
function resetZoom(mode) {
  if (mode === 'candle' || !mode) candleZoom = { start: 0, end: 1 };
  if (mode === 'line' || !mode) lineZoom = { start: 0, end: 1 };
  updateZoomLabel();
}
/** factor < 1 zooms in, > 1 zooms out. center in 0..1 of current window */
function applyZoom(z, factor, center = 0.5) {
  const span = Math.max(MIN_ZOOM_SPAN, z.end - z.start);
  let newSpan = Math.min(1, Math.max(MIN_ZOOM_SPAN, span * factor));
  const absCenter = z.start + span * center;
  let start = absCenter - newSpan * center;
  let end = start + newSpan;
  if (start < 0) { start = 0; end = newSpan; }
  if (end > 1) { end = 1; start = 1 - newSpan; }
  z.start = clamp01(start);
  z.end = clamp01(end);
  if (z.end - z.start < MIN_ZOOM_SPAN) z.end = clamp01(z.start + MIN_ZOOM_SPAN);
}
function setZoomWindow(z, start, end) {
  let s = start, e = end;
  const span = Math.max(MIN_ZOOM_SPAN, e - s);
  if (e - s < MIN_ZOOM_SPAN) e = s + MIN_ZOOM_SPAN;
  if (s < 0) { s = 0; e = span; }
  if (e > 1) { e = 1; s = 1 - span; }
  z.start = clamp01(s);
  z.end = clamp01(e);
}
function sliceByZoom(arr, z) {
  if (!arr?.length) return [];
  if (z.end - z.start >= 0.999) return arr;
  const i0 = Math.max(0, Math.floor(arr.length * z.start));
  let i1 = Math.min(arr.length, Math.ceil(arr.length * z.end));
  // keep at least ~8 bars when possible so candles don't become giant
  if (i1 - i0 < 8 && arr.length >= 8) {
    i1 = Math.min(arr.length, i0 + 8);
  }
  return arr.slice(i0, Math.max(i0 + 2, i1));
}
function activeZoom() { return chartMode === 'candle' ? candleZoom : lineZoom; }

let panRaf = null;
let panPending = false;
function refreshActiveChartSmooth() {
  panPending = true;
  if (panRaf) return;
  panRaf = requestAnimationFrame(() => {
    panRaf = null;
    if (!panPending) return;
    panPending = false;
    updateZoomLabel();
    if (chartMode === 'candle') drawCandles();
    else if (lastData) updateMainChart(lastData.prediction, lastData.settings_public?.ai_forecast_enabled !== false);
  });
}
function refreshActiveChart() {
  updateZoomLabel();
  if (chartMode === 'candle') drawCandles();
  else if (lastData) updateMainChart(lastData.prediction, lastData.settings_public?.ai_forecast_enabled !== false);
}

const chartDefaults = {
  responsive: true,
  maintainAspectRatio: false,
  interaction: { mode: 'index', intersect: false },
  plugins: {
    legend: { labels: { color: '#8B93A7', boxWidth: 10, usePointStyle: true, pointStyle: 'circle', font: { size: 11, family: 'Inter, system-ui, sans-serif' } } },
    tooltip: {
      backgroundColor: 'rgba(20,24,32,.96)', borderColor: 'rgba(255,255,255,.1)', borderWidth: 1, borderRadius: 12,
      titleColor: '#F4F6FA', bodyColor: '#C5CEE0', padding: 12,
      titleFont: { family: 'Inter, system-ui, sans-serif', weight: '600' },
      bodyFont: { family: 'Inter, system-ui, sans-serif' },
    }
  },
  scales: {
    x: { ticks: { color: '#6B7389', maxRotation: 0, autoSkipPadding: 14, font: { size: 10, family: 'Inter, system-ui, sans-serif' } }, grid: { color: 'rgba(255,255,255,.04)' }, border: { color: 'rgba(255,255,255,.06)' } },
    y: { position: 'left', ticks: { color: '#6B7389', font: { size: 10, family: 'Inter, system-ui, sans-serif' } }, grid: { color: 'rgba(255,255,255,.04)' }, border: { color: 'rgba(255,255,255,.06)' } },
    y1: { position: 'right', ticks: { color: '#6B7389', font: { size: 10, family: 'Inter, system-ui, sans-serif' } }, grid: { drawOnChartArea: false }, border: { color: 'rgba(255,255,255,.06)' } }
  }
};

function initCharts() {
  mainChart = new Chart($('mainChart').getContext('2d'), {
    type: 'line',
    data: {
      labels: [],
      datasets: [
        { label: 'Fleet H/s', data: [], borderColor: '#12B76A', backgroundColor: 'rgba(18,183,106,.12)', fill: true, tension: 0.4, borderWidth: 2.4, pointRadius: 0, yAxisID: 'y', spanGaps: false },
        { label: 'XMR price', data: [], borderColor: '#F79009', tension: 0.35, borderWidth: 1.6, pointRadius: 0, yAxisID: 'y1', spanGaps: false },
        { label: 'AI forecast', data: [], borderColor: '#4E7CFF', backgroundColor: 'rgba(78,124,255,.08)', fill: false, borderDash: [6, 4], tension: 0.35, borderWidth: 2.6, pointRadius: 2, pointHoverRadius: 5, yAxisID: 'y', spanGaps: true }
      ]
    },
    options: chartDefaults
  });
  predChart = new Chart($('predChart').getContext('2d'), {
    type: 'line',
    data: { labels: [], datasets: [{ label: 'Projected', data: [], borderColor: '#4E7CFF', backgroundColor: 'rgba(78,124,255,.12)', fill: true, tension: 0.4, borderWidth: 2.2, pointRadius: 0 }] },
    options: {
      ...chartDefaults,
      plugins: { ...chartDefaults.plugins, legend: { display: false } },
      scales: { x: chartDefaults.scales.x, y: { ...chartDefaults.scales.y } }
    }
  });
}

function hexToRgb(hex) {
  const h = String(hex || '').replace('#','');
  if (h.length !== 6) return null;
  return {
    r: parseInt(h.slice(0,2), 16),
    g: parseInt(h.slice(2,4), 16),
    b: parseInt(h.slice(4,6), 16),
  };
}
function darkenHex(hex, amount) {
  const rgb = hexToRgb(hex);
  if (!rgb) return hex || '#0E9F5A';
  const f = Math.max(0, Math.min(1, 1 - amount));
  const to = (n) => Math.round(n * f).toString(16).padStart(2, '0');
  return '#' + to(rgb.r) + to(rgb.g) + to(rgb.b);
}
function rgbaFromHex(hex, a) {
  const rgb = hexToRgb(hex);
  if (!rgb) return `rgba(18,183,106,${a})`;
  return `rgba(${rgb.r},${rgb.g},${rgb.b},${a})`;
}

function applyTheme(s) {
  const mode = s.ui_mode || 'default';
  const pro = mode === 'pro';
  const minimal = mode === 'minimal';
  const light = s.theme_mode === 'light';
  document.body.classList.toggle('mode-pro', pro);
  document.body.classList.toggle('mode-minimal', minimal);
  document.body.classList.toggle('theme-light', light);
  document.body.classList.toggle('theme-dark', !light);
  document.body.classList.remove('density-compact', 'density-comfortable', 'density-spacious');
  document.body.classList.add('density-' + (s.density || 'comfortable'));
  document.body.classList.toggle('bg-solid', s.background_style === 'solid' || minimal);
  document.body.classList.toggle('reduce-motion', !!s.reduced_motion || minimal);
  document.documentElement.setAttribute('data-ui', mode);

  // ── UI theme colors (logo, buttons, badges, dots) ──
  const uiA = s.theme_accent || '#12B76A';
  const uiB = s.theme_accent2 || '#4E7CFF';
  const root = document.documentElement.style;
  root.setProperty('--accent', uiA);
  root.setProperty('--accent2', uiB);
  root.setProperty('--ok', uiA);
  root.setProperty('--accent-dark', darkenHex(uiA, 0.18));
  root.setProperty('--accent-glow', rgbaFromHex(uiA, 0.28));
  root.setProperty('--up-bg', rgbaFromHex(uiA, 0.12));
  // meta theme-color for mobile chrome
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute('content', light ? '#F4F6FA' : '#0B0D12');

  const scale = Math.max(90, Math.min(130, Number(s.font_scale) || 100)) / 100;
  document.documentElement.style.fontSize = (16 * scale) + 'px';
  let rad = Math.max(8, Math.min(28, Number(s.card_radius) || 20));
  if (minimal) rad = Math.min(rad, 10);
  root.setProperty('--radius', rad + 'px');
  root.setProperty('--radius-sm', Math.max(6, rad - 6) + 'px');

  const title = s.dashboard_title || s.brand_name || 'Deer Crypto Monitor';
  if ($('dashTitle')) $('dashTitle').textContent = title;
  document.title = title + (pro ? ' · Pro' : minimal ? ' · Minimal' : '');
  if ($('logoLetters')) $('logoLetters').textContent = (s.logo_letters || 'DC').toString().slice(0, 3).toUpperCase();
  if ($('brandTagline')) $('brandTagline').textContent = s.brand_tagline || 'Crypto mining portfolio monitor';
  if ($('portfolioLabel')) $('portfolioLabel').textContent = s.portfolio_label || 'Fleet portfolio · hashrate';
  if ($('footerNote')) {
    $('footerNote').textContent = (s.brand_name || 'Deer Crypto Monitor') + ' · local portfolio UI · estimates only';
    $('footerNote').classList.toggle('hidden', s.show_footer === false);
  }
  if ($('sec-overview')) $('sec-overview').classList.toggle('hidden', s.show_portfolio_hero === false);
  if ($('watchGrid')) {
    $('watchGrid').classList.toggle('hidden', s.show_watchlist === false);
    if ($('watchTitle')) $('watchTitle').classList.toggle('hidden', s.show_watchlist === false);
  }
  if ($('sec-miners')) $('sec-miners').classList.toggle('hidden', s.show_holdings === false);
  if ($('sec-more')) $('sec-more').classList.toggle('hidden', s.show_details === false);
  if ($('proTape')) {
    $('proTape').setAttribute('aria-hidden', pro && !minimal ? 'false' : 'true');
    if (minimal) $('proTape').style.display = 'none';
    else $('proTape').style.display = '';
  }
  const hideEarn = (s.show_earnings_card === false || s.show_earnings_card === 'false');
  if ($('earnCard')) $('earnCard').style.display = hideEarn ? 'none' : '';
  if ($('earn')?.closest) {
    const chip = $('earn').closest('.ph-chip');
    if (chip) chip.style.display = hideEarn ? 'none' : '';
  }
  if ($('xmr')?.closest) {
    const chip = $('xmr').closest('.ph-chip');
    if (chip) chip.style.display = hideEarn ? 'none' : '';
  }
  const aiOn = !(s.ai_forecast_enabled === false || s.ai_forecast_enabled === 'false');
  if ($('aiCard')) $('aiCard').classList.toggle('hidden', !aiOn);
  if ($('mainGrid')) $('mainGrid').classList.toggle('ai-off', !aiOn);
  if ($('aiState')) $('aiState').textContent = aiOn ? (s.ai_mode || 'on') : 'off';
  window._currencySym = s.currency_symbol || '$';
  window._numberCompact = !!s.number_compact;

  // ── Chart colors ONLY (separate from UI theme) ──
  const cHs = s.chart_hs_color || uiA;
  const cPrice = s.chart_price_color || '#F79009';
  const cFc = s.chart_forecast_color || uiB;
  const fillOn = s.chart_fill !== false;
  const smooth = s.chart_smooth !== false;
  if (mainChart) {
    mainChart.data.datasets[0].borderColor = cHs;
    mainChart.data.datasets[0].backgroundColor = fillOn ? rgbaFromHex(cHs, 0.12) : 'transparent';
    mainChart.data.datasets[0].fill = fillOn;
    mainChart.data.datasets[0].tension = smooth ? 0.4 : 0.05;
    mainChart.data.datasets[1].borderColor = cPrice;
    mainChart.data.datasets[1].hidden = s.show_price_chart === false || s.show_price_chart === 'false';
    mainChart.data.datasets[2].borderColor = cFc;
    mainChart.data.datasets[2].hidden = !aiOn;
    mainChart.data.datasets[2].tension = smooth ? 0.35 : 0.05;
    const tick = light ? '#64748B' : '#6B7389';
    const grid = light ? 'rgba(15,23,42,.06)' : 'rgba(255,255,255,.04)';
    if (mainChart.options?.plugins?.legend?.labels) {
      mainChart.options.plugins.legend.labels.color = tick;
    }
    if (mainChart.options?.scales) {
      ['y','y1','x'].forEach(k => {
        const sc = mainChart.options.scales[k];
        if (!sc) return;
        if (sc.ticks) sc.ticks.color = tick;
        if (sc.grid && k !== 'y1') sc.grid.color = grid;
      });
    }
    try { mainChart.update('none'); } catch (_) {}
  }
  if (predChart) {
    predChart.data.datasets[0].borderColor = cFc;
    predChart.data.datasets[0].backgroundColor = fillOn ? rgbaFromHex(cFc, 0.12) : 'transparent';
    predChart.data.datasets[0].fill = fillOn;
    predChart.data.datasets[0].tension = smooth ? 0.4 : 0.05;
    try { predChart.update('none'); } catch (_) {}
  }
}

function updateProTape(d) {
  const track = $('proTapeTrack');
  if (!track) return;
  const hs = (d.mining_live === false) ? 0 : Number(d.hashrate || 0);
  const price = d.price;
  const intel = d.price_intel;
  const ch = intel?.change_24h_pct;
  const chCls = ch > 0 ? 'up' : ch < 0 ? 'dn' : '';
  const chStr = ch != null ? ((ch > 0 ? '+' : '') + Number(ch).toFixed(2) + '%') : 'n/a';
  const due = d.pool_stats?.ok ? Number(d.pool_stats.amt_due_xmr).toFixed(6) : '—';
  const on = d.miners_online || 0, en = d.miners_enabled || 0;
  const prov = intel?.provider || d.settings_public?.price_provider || '—';
  const stale = intel?.stale ? ' · STALE CACHE' : '';
  const seg =
    `XMR <b>$${price != null ? Number(price).toFixed(2) : '—'}</b> <span class="${chCls}">${chStr}</span> 24H` +
    `<span class="sep">|</span>FLEET <b>${Number(hs||0).toLocaleString(undefined,{maximumFractionDigits:0})}</b> H/S` +
    `<span class="sep">|</span>EST <b>$${Number(d.usd_daily||0).toFixed(3)}</b>/DAY` +
    `<span class="sep">|</span>MINERS <b>${on}/${en}</b>` +
    `<span class="sep">|</span>DUE <b>${due}</b> XMR` +
    `<span class="sep">|</span>FEED <b>${String(prov).toUpperCase()}</b>${stale}` +
    `<span class="sep">|</span>SHARES <b>${Number(d.shares_good||0).toLocaleString()}</b>`;
  // duplicate for seamless marquee
  track.innerHTML = seg + `<span class="sep">|</span>` + seg;
}

function fmt(n, d=0) {
  if (n == null || Number.isNaN(Number(n))) return '—';
  return Number(n).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d });
}
function fmtHs(n) {
  if (n == null || Number.isNaN(Number(n))) return '—';
  const v = Number(n);
  if (window._numberCompact) {
    if (Math.abs(v) >= 1e6) return (v / 1e6).toFixed(2) + 'M';
    if (Math.abs(v) >= 1000) return (v / 1000).toFixed(1) + 'k';
  }
  return fmt(v, 0);
}
function fmtXmr(n) {
  if (n == null || Number.isNaN(Number(n))) return '—';
  const x = Number(n);
  if (x >= 1) return x.toFixed(4);
  if (x >= 0.01) return x.toFixed(5);
  return x.toFixed(8);
}
function fmtDur(sec) {
  sec = Number(sec) || 0;
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = Math.floor(sec % 60);
  if (h > 48) return Math.floor(h/24) + 'd ' + (h%24) + 'h';
  if (h > 0) return h + 'h ' + m + 'm';
  if (m > 0) return m + 'm ' + s + 's';
  return s + 's';
}
function toast(msg) {
  const t = $('toast'); t.textContent = msg; t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 2800);
}
function uid() { return 'm-' + Math.random().toString(36).slice(2, 9); }
function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function shortUrl(u) { return String(u || '').replace(/^https?:\/\//, ''); }

function filterHistory(mode) {
  if (!fullHistory.length) return [];
  // Prefer accurate series: drop offline zeros from line chart (keep for candles)
  let base = fullHistory;
  if (chartMode === 'line') {
    base = fullHistory.filter(h => !h.offline && Number(h.hs) > 0);
    if (!base.length) base = fullHistory; // fallback
  }
  if (mode === 'all') return base;
  if (mode === 'live') return base.slice(-100);
  const hours = parseFloat(mode);
  const cutoff = Date.now() - hours * 3600 * 1000;
  return base.filter(h => new Date(h.time).getTime() > cutoff);
}

function setChartMode(mode) {
  chartMode = mode;
  $('lineWrap').classList.toggle('hidden', mode !== 'line');
  $('candleWrap').classList.toggle('hidden', mode !== 'candle');
  $('candleOpts').classList.toggle('hidden', mode !== 'candle');
  $('rangeTabs').classList.toggle('hidden', mode === 'candle');
  $('chartModeLabel').textContent = mode;
  document.querySelectorAll('#chartModeSeg button').forEach(b => {
    b.classList.toggle('active', b.getAttribute('data-mode') === mode);
  });
  updateZoomLabel();
  if (mode === 'candle') drawCandles();
  else if (lastData) updateMainChart(lastData.prediction, lastData.settings_public?.ai_forecast_enabled !== false);
}

function updateMainChart(pred, aiOn) {
  if (chartMode !== 'line' || !mainChart) return;
  let filtered = filterHistory(rangeMode);
  // denser accurate points for live view
  if (rangeMode === 'live' && filtered.length > 120) filtered = filtered.slice(-120);
  // Zoom history first — then ALWAYS append forecast after (so zoom never hides AI path)
  let histPack = filtered.map(h => ({
    lb: new Date(h.time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    hs: Number(h.hs),
    price: h.price,
    fc: null,
  }));
  histPack = sliceByZoom(histPack, lineZoom);

  const labels = histPack.map(p => p.lb);
  const hs = histPack.map(p => p.hs);
  const price = histPack.map(p => p.price);
  const forecast = histPack.map(() => null);

  // AI forecast extension = dashed blue path of where hashrate is headed
  if (aiOn && pred?.ok && pred?.projected?.length) {
    const liveN = pred.live_hs != null ? Number(pred.live_hs) : null;
    const lastReal = (hs.length && hs[hs.length - 1] != null && isFinite(hs[hs.length - 1]))
      ? Number(hs[hs.length - 1])
      : (liveN != null && isFinite(liveN) ? liveN : Number(pred.predicted_avg_hs) || null);
    const join = (liveN != null && isFinite(liveN) && liveN > 1) ? liveN : lastReal;
    // Bridge: last real sample is also the first forecast point so the line connects
    if (join != null && forecast.length) {
      forecast[forecast.length - 1] = join;
    }
    // If no history on chart, start with a "now" anchor
    if (!forecast.length && join != null) {
      labels.push('now');
      hs.push(join);
      price.push(null);
      forecast.push(join);
    }
    const target = Number(pred.predicted_avg_hs) || join;
    pred.projected.forEach((p, idx) => {
      let v = Number(p.hs);
      if (!isFinite(v)) return;
      // ease from live → target so path is obvious (not a flat stuck line)
      if (join != null && isFinite(join)) {
        const t = (idx + 1) / Math.max(1, pred.projected.length);
        // blend model path with smooth ease toward predicted avg
        v = (1 - t * 0.35) * v + (t * 0.35) * target;
        if (idx === 0) v = 0.92 * join + 0.08 * v;
      }
      const tLabel = p.time
        ? new Date(p.time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        : ('+' + (idx + 1));
      labels.push(tLabel);
      hs.push(null);       // green history stops
      price.push(null);
      forecast.push(v);    // blue dashed continues
    });
  }

  mainChart.data.labels = labels;
  mainChart.data.datasets[0].data = hs;
  mainChart.data.datasets[1].data = price;
  mainChart.data.datasets[2].data = aiOn ? forecast : [];
  mainChart.data.datasets[2].hidden = !aiOn;
  mainChart.data.datasets[2].spanGaps = true;
  mainChart.data.datasets[2].borderWidth = 2.6;
  mainChart.data.datasets[2].borderDash = [6, 4];
  mainChart.data.datasets[2].pointRadius = (ctx) => {
    const v = ctx.raw;
    return (v != null && isFinite(v)) ? 2 : 0;
  };
  mainChart.data.datasets[2].pointHoverRadius = 5;
  mainChart.update('none');

  if (aiOn && pred?.ok && pred?.projected && predChart) {
    const live0 = pred.live_hs != null ? Number(pred.live_hs) : null;
    const labs = [];
    const data = [];
    if (live0 != null && isFinite(live0)) {
      labs.push('now');
      data.push(live0);
    }
    pred.projected.forEach(p => {
      labs.push(new Date(p.time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
      data.push(Number(p.hs));
    });
    predChart.data.labels = labs;
    predChart.data.datasets[0].data = data;
    predChart.update('none');
  }
  updateZoomLabel();
}

function lineVals(data, key) {
  return data.map(c => {
    if (c[key] != null && typeof c[key] === 'number') return c[key];
    if (c[key] && typeof c[key] === 'object' && c[key].close != null) return c[key].close;
    return null;
  });
}

/** Canvas candlesticks + overlay lines + hover highlight */
function drawCandles() {
  const canvas = $('candleCanvas');
  const tip = $('candleTip');
  if (!canvas) return;
  const parent = canvas.parentElement;
  const dpr = window.devicePixelRatio || 1;
  const w = parent.clientWidth;
  const h = parent.clientHeight;
  canvas.width = Math.floor(w * dpr);
  canvas.height = Math.floor(h * dpr);
  canvas.style.width = w + 'px';
  canvas.style.height = h + 'px';
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);

  let full = (candles[candleMetric] || []).slice();
  if (!full.length) {
    candleHit = null;
    candleDrawData = [];
    if (tip) tip.classList.remove('show');
    ctx.fillStyle = '#8b97b0';
    ctx.font = '13px system-ui';
    ctx.fillText('Collecting samples for candlesticks…', 16, h / 2);
    return;
  }

  // Keep a reasonable base series, then apply zoom window
  const maxBase = isMobile() ? 160 : 220;
  if (full.length > maxBase) full = full.slice(-maxBase);
  let data = sliceByZoom(full, candleZoom);
  // guarantee at least a few bars
  if (data.length < 2 && full.length >= 2) data = full.slice(-Math.min(12, full.length));
  candleDrawData = data;

  const pad = {
    l: isMobile() ? 46 : 58,
    r: isMobile() ? 42 : 54,
    t: 22,
    b: 30,
  };
  const plotW = w - pad.l - pad.r;
  const plotH = h - pad.t - pad.b;

  // primary scale (candles)
  let minV = Math.min(...data.map(c => c.low));
  let maxV = Math.max(...data.map(c => c.high));
  if (minV === maxV) {
    minV = minV * 0.98;
    maxV = maxV * 1.02 || 1;
  }
  // pad a bit so wicks aren't clipped
  const padP = (maxV - minV) * 0.06 || 1;
  minV -= padP;
  maxV += padP;
  const span = maxV - minV || 1;
  const yOf = (v) => pad.t + (1 - (v - minV) / span) * plotH;

  // right axis: blend price + usd_daily into separate normalized lines drawn on right scale
  // We draw price on right axis; est $/day is normalized onto same right axis using its own min/max mapped to plot — actually user asked for 2 lines:
  // 1) amount they could make (usd_daily or xmr_daily)  2) XMR price
  // Use dual mapping: both lines share right axis via independent normalize then map to plot height - NO that collapses meaning.
  // Better: right axis = XMR price; left-ish overlay for earn uses a third scale visually as line only (normalize earn 0-1 to plot).
  // Clean approach: right axis = price USD; second line (est $/day) also on right after scaling to price-like? Bad.
  // Best for trading UI: left = primary candles (H/s or XMR), right = price, and est earn as dashed line scaled independently (show values in tooltip only).
  // Draw est earn on left as thin blue line if metric is hashrate (earn correlates with hs), and price always on right.

  const prices = data.map(c => c.line_price ?? c.price?.close ?? null).filter(v => v != null);
  let minPrice = prices.length ? Math.min(...prices) : 0;
  let maxPrice = prices.length ? Math.max(...prices) : 1;
  if (minPrice === maxPrice) {
    minPrice *= 0.995;
    maxPrice *= 1.005;
    if (minPrice === maxPrice) { minPrice = 0; maxPrice = 1; }
  }
  const priceSpan = maxPrice - minPrice || 1;
  const yPrice = (v) => pad.t + (1 - (v - minPrice) / priceSpan) * plotH;

  const earns = data.map(c => c.line_usd_daily ?? c.usd_daily?.close ?? null).filter(v => v != null);
  let minEarn = earns.length ? Math.min(...earns) : 0;
  let maxEarn = earns.length ? Math.max(...earns) : 1;
  if (minEarn === maxEarn) {
    minEarn = Math.max(0, minEarn - 0.01);
    maxEarn = maxEarn + 0.01;
  }
  const earnSpan = maxEarn - minEarn || 1;
  const yEarn = (v) => pad.t + (1 - (v - minEarn) / earnSpan) * plotH;

  const slot = plotW / data.length;
  // Cap body width so deep zoom doesn't make candles huge slabs
  const bodyW = Math.max(2.5, Math.min(8.5, slot * 0.38));
  const hitHalf = Math.max(bodyW / 2 + 2, Math.min(7, slot * 0.28));

  const candleRects = [];
  candleHit = {
    pad, plotW, plotH, slot, bodyW, hitHalf, w, h,
    minV, maxV, minPrice, maxPrice, minEarn, maxEarn,
    yOf, candleRects,
  };

  // background grid
  ctx.strokeStyle = 'rgba(36,48,73,.5)';
  ctx.lineWidth = 1;
  ctx.font = '10px ui-monospace, monospace';
  for (let i = 0; i <= 4; i++) {
    const v = minV + (span * i) / 4;
    const y = yOf(v);
    ctx.beginPath();
    ctx.moveTo(pad.l, y);
    ctx.lineTo(w - pad.r, y);
    ctx.stroke();
    ctx.fillStyle = '#8b97b0';
    const label = candleMetric === 'xmr' ? v.toFixed(4) : Math.round(v).toLocaleString();
    ctx.fillText(label, 3, y + 3);
    // right price ticks
    if (prices.length) {
      const pv = minPrice + (priceSpan * i) / 4;
      ctx.fillStyle = '#ffb020aa';
      ctx.textAlign = 'left';
      ctx.fillText('$' + pv.toFixed(1), w - pad.r + 4, y + 3);
    }
  }
  ctx.textAlign = 'left';

  // axis titles
  ctx.fillStyle = '#8b97b0';
  ctx.font = '9px system-ui';
  ctx.fillText(candleMetric === 'xmr' ? 'XMR' : 'H/s', 4, 12);
  ctx.fillStyle = '#ffb020';
  ctx.fillText('Price', w - pad.r + 4, 12);

  // --- overlay line: est USD/day (blue) ---
  ctx.beginPath();
  let started = false;
  data.forEach((c, i) => {
    const val = c.line_usd_daily ?? c.usd_daily?.close;
    if (val == null) { started = false; return; }
    const x = pad.l + slot * i + slot / 2;
    const y = yEarn(val);
    if (!started) { ctx.moveTo(x, y); started = true; }
    else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = '#5b8cff';
  ctx.lineWidth = 1.8;
  ctx.setLineDash([5, 4]);
  ctx.stroke();
  ctx.setLineDash([]);

  // --- overlay line: XMR price (gold) ---
  ctx.beginPath();
  started = false;
  data.forEach((c, i) => {
    const val = c.line_price ?? c.price?.close;
    if (val == null) { started = false; return; }
    const x = pad.l + slot * i + slot / 2;
    const y = yPrice(val);
    if (!started) { ctx.moveTo(x, y); started = true; }
    else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = '#ffb020';
  ctx.lineWidth = 2;
  ctx.stroke();

  // --- candles ---
  data.forEach((c, i) => {
    const x = pad.l + slot * i + slot / 2;
    const up = c.close >= c.open;
    const col = up ? '#00e5a0' : '#ff5d6c';
    const yO = yOf(c.open), yC = yOf(c.close), yH = yOf(c.high), yL = yOf(c.low);
    const top = Math.min(yO, yC);
    const bh = Math.max(1.5, Math.abs(yC - yO));
    const bw = bodyW;

    candleRects.push({
      i, x,
      left: x - hitHalf,
      right: x + hitHalf,
      top: Math.min(yH, yL) - 2,
      bottom: Math.max(yH, yL) + 2,
    });

    // subtle highlight only on the candle itself (not full column)
    if (i === candleHoverIdx) {
      ctx.fillStyle = 'rgba(91,140,255,0.16)';
      ctx.beginPath();
      ctx.roundRect
        ? ctx.roundRect(x - bw / 2 - 3, Math.min(yH, yL) - 3, bw + 6, Math.abs(yH - yL) + 6, 4)
        : ctx.rect(x - bw / 2 - 3, Math.min(yH, yL) - 3, bw + 6, Math.abs(yH - yL) + 6);
      ctx.fill();
    }

    ctx.strokeStyle = col;
    ctx.lineWidth = i === candleHoverIdx ? 2 : 1.15;
    ctx.beginPath();
    ctx.moveTo(x, yH);
    ctx.lineTo(x, yL);
    ctx.stroke();

    ctx.fillStyle = col;
    ctx.globalAlpha = i === candleHoverIdx ? 1 : (up ? 0.88 : 0.78);
    ctx.fillRect(x - bw / 2, top, bw, bh);
    if (i === candleHoverIdx) {
      ctx.strokeStyle = '#e8edf7';
      ctx.lineWidth = 1;
      ctx.strokeRect(x - bw / 2, top, bw, bh);
    }
    ctx.globalAlpha = 1;
  });

  // soft crosshair only when hovering a real candle
  if (candleHoverIdx >= 0 && candleHoverIdx < data.length) {
    const c = data[candleHoverIdx];
    const x = pad.l + slot * candleHoverIdx + slot / 2;
    ctx.strokeStyle = 'rgba(232,237,247,0.18)';
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(x, pad.t);
    ctx.lineTo(x, pad.t + plotH);
    ctx.stroke();
    const yC = yOf(c.close);
    ctx.beginPath();
    ctx.moveTo(pad.l, yC);
    ctx.lineTo(w - pad.r, yC);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  // x labels
  ctx.fillStyle = '#8b97b0';
  ctx.font = '10px system-ui';
  const step = Math.max(1, Math.floor(data.length / (isMobile() ? 4 : 7)));
  for (let i = 0; i < data.length; i += step) {
    const x = pad.l + slot * i + slot / 2;
    const t = new Date(data[i].time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    ctx.fillText(t, x - 14, h - 8);
  }

  const last = data[data.length - 1];
  const unit = candleMetric === 'xmr' ? 'XMR' : 'H/s';
  const legend = $('candleLegend');
  if (legend) {
    legend.innerHTML = `
      <span><i style="background:#00e5a0"></i>Candles ${unit} (${candleIv}s)</span>
      <span><i style="background:#5b8cff"></i>Est. $/day</span>
      <span><i style="background:#ffb020"></i>XMR price</span>
      <span>Last C ${last.close} ${unit} · zoom ${zoomPercent(candleZoom)}% · ${data.length} bars</span>`;
  }
  updateZoomLabel();
}

function showCandleTip(idx, clientX, clientY) {
  const tip = $('candleTip');
  const wrap = $('candleWrap');
  if (!tip || !wrap || idx < 0 || idx >= candleDrawData.length) {
    if (tip) tip.classList.remove('show');
    return;
  }
  const c = candleDrawData[idx];
  const up = c.close >= c.open;
  const unit = candleMetric === 'xmr' ? 'XMR' : 'H/s';
  const chg = c.open ? (((c.close - c.open) / Math.abs(c.open || 1)) * 100) : 0;
  const hs = c.hs || {};
  const price = c.price || {};
  const xmrD = c.xmr_daily || {};
  const usdD = c.usd_daily || {};
  const tStr = new Date(c.time).toLocaleString([], {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit'
  });

  const row = (k, v, cls='') =>
    `<div class="t-row"><span>${k}</span><span class="${cls}">${v}</span></div>`;

  tip.innerHTML = `
    <div class="t-title">${tStr}</div>
    <div class="t-row"><span>Primary (${unit})</span><span class="${up ? 't-up' : 't-down'}">${up ? '▲ UP' : '▼ DOWN'} ${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%</span></div>
    ${row('Open', c.open + ' ' + unit)}
    ${row('High', c.high + ' ' + unit, 't-up')}
    ${row('Low', c.low + ' ' + unit, 't-down')}
    ${row('Close', c.close + ' ' + unit)}
    ${row('Avg', (c.avg != null ? c.avg : '—') + ' ' + unit)}
    ${row('Samples', c.samples != null ? c.samples : '—')}
    <div class="t-sep"></div>
    ${row('Hashrate O/H/L/C', hs.open != null ? `${fmtHs(hs.open)} / ${fmtHs(hs.high)} / ${fmtHs(hs.low)} / ${fmtHs(hs.close)}` : '—')}
    ${row('HS avg', hs.avg != null ? fmtHs(hs.avg) + ' H/s' : '—')}
    <div class="t-sep"></div>
    ${row('XMR price close', price.close != null ? '$' + Number(price.close).toFixed(2) : '—')}
    ${row('Price O→C', price.open != null ? '$' + Number(price.open).toFixed(2) + ' → $' + Number(price.close).toFixed(2) : '—')}
    ${row('Price high/low', price.high != null ? '$' + Number(price.high).toFixed(2) + ' / $' + Number(price.low).toFixed(2) : '—')}
    <div class="t-sep"></div>
    ${row('Est. XMR/day', xmrD.close != null ? Number(xmrD.close).toFixed(5) : '—')}
    ${row('Est. $/day', usdD.close != null ? '$' + Number(usdD.close).toFixed(3) : '—')}
    ${row('Earn O→C', usdD.open != null ? '$' + Number(usdD.open).toFixed(3) + ' → $' + Number(usdD.close).toFixed(3) : '—')}
    ${c.pool_due?.close != null ? row('Pool due XMR', Number(c.pool_due.close).toFixed(8)) : ''}
    ${c.pool_hs?.close != null ? row('Pool H/s', fmtHs(c.pool_hs.close)) : ''}
  `;

  tip.classList.add('show');
  // position inside wrap
  const rect = wrap.getBoundingClientRect();
  const tipW = tip.offsetWidth || 220;
  const tipH = tip.offsetHeight || 220;
  let left = clientX - rect.left + 14;
  let top = clientY - rect.top + 14;
  if (left + tipW > rect.width - 8) left = clientX - rect.left - tipW - 14;
  if (top + tipH > rect.height - 8) top = clientY - rect.top - tipH - 10;
  if (left < 6) left = 6;
  if (top < 6) top = 6;
  tip.style.left = left + 'px';
  tip.style.top = top + 'px';
}

function eventClientXY(ev) {
  if (ev.touches && ev.touches[0]) return { x: ev.touches[0].clientX, y: ev.touches[0].clientY };
  if (ev.changedTouches && ev.changedTouches[0]) return { x: ev.changedTouches[0].clientX, y: ev.changedTouches[0].clientY };
  return { x: ev.clientX, y: ev.clientY };
}

/** Only hits when pointer is on the candle body/wick — not empty chart space */
function candleIndexFromEvent(ev) {
  if (!candleHit || !candleDrawData.length) return -1;
  const canvas = $('candleCanvas');
  const rect = canvas.getBoundingClientRect();
  const { x: cx, y: cy } = eventClientXY(ev);
  const x = cx - rect.left;
  const y = cy - rect.top;
  const rects = candleHit.candleRects || [];
  for (let i = 0; i < rects.length; i++) {
    const r = rects[i];
    if (x >= r.left && x <= r.right && y >= r.top && y <= r.bottom) return r.i;
  }
  return -1;
}

function setCandleHover(idx, clientX, clientY) {
  if (idx !== candleHoverIdx) {
    candleHoverIdx = idx;
    drawCandles();
  }
  if (idx >= 0 && clientX != null) showCandleTip(idx, clientX, clientY);
  else {
    const tip = $('candleTip');
    if (tip) tip.classList.remove('show');
  }
}

function onCandlePointer(ev) {
  if (chartMode !== 'candle') return;
  if (panDrag && panDrag.moved) return;
  const { x, y } = eventClientXY(ev);
  const idx = candleIndexFromEvent(ev);
  setCandleHover(idx, x, y);
}

function onCandleLeave() {
  candleHoverIdx = -1;
  const tip = $('candleTip');
  if (tip) tip.classList.remove('show');
  if (chartMode === 'candle') drawCandles();
}

function setTrendEl(el, pct) {
  if (pct == null || Number.isNaN(pct)) { el.textContent = '—'; el.className = 'delta flat'; return; }
  const sign = pct > 0.15 ? 'up' : pct < -0.15 ? 'down' : 'flat';
  el.className = 'delta ' + sign;
  el.textContent = (pct > 0 ? '▲ ' : pct < 0 ? '▼ ' : '● ') + Math.abs(pct).toFixed(1) + '% vs avg';
}

function renderMinerTable(miners) {
  const body = $('minerBody');
  if (!miners?.length) {
    body.innerHTML = '<tr><td colspan="6" style="color:var(--muted)">No miners — open Settings</td></tr>';
    return;
  }
  body.innerHTML = miners.map(m => {
    let badge = '<span class="badge">disabled</span>';
    if (m.enabled === false) badge = '<span class="badge">disabled</span>';
    else if (m.online) badge = '<span class="badge on">online</span>';
    else badge = '<span class="badge off">offline</span>';
    const err = (!m.online && m.error) ? `<div class="mono" style="color:var(--danger);margin-top:4px;font-size:.7rem">${escapeHtml(m.error)}</div>` : '';
    return `<tr>
      <td><strong>${escapeHtml(m.name||'Miner')}</strong><div class="mono" style="color:var(--muted);margin-top:2px">${escapeHtml(shortUrl(m.url))}</div>${err}</td>
      <td>${badge}</td>
      <td class="hs-cell">${m.online ? fmtHs(m.hashrate) : '—'}</td>
      <td class="mono">${m.online ? fmt(m.shares_good) : '—'}</td>
      <td class="mono">${m.online ? fmtDur(m.uptime) : '—'}</td>
      <td class="mono">${escapeHtml(m.pool||'—')}</td>
    </tr>`;
  }).join('');
}

function renderWorkers(pool) {
  const body = $('workerBody');
  if (!pool || !pool.ok) {
    body.innerHTML = `<tr><td colspan="5" style="color:var(--muted)">${escapeHtml(pool?.error || 'Enable MoneroOcean wallet in Settings')}</td></tr>`;
    return;
  }
  const workers = pool.workers || [];
  if (!workers.length) {
    body.innerHTML = '<tr><td colspan="5" style="color:var(--muted)">No named workers (pool may show only global)</td></tr>';
    return;
  }
  body.innerHTML = workers.map(w => {
    const badge = w.online ? '<span class="badge on">online</span>' : '<span class="badge off">idle</span>';
    return `<tr>
      <td><strong>${escapeHtml(w.name)}</strong></td>
      <td>${badge}</td>
      <td class="hs-cell">${fmtHs(w.hashrate)}</td>
      <td class="mono">${fmt(w.valid_shares)}</td>
      <td class="mono">${escapeHtml(w.algo||'—')}</td>
    </tr>`;
  }).join('');
}

function renderMinerEditors() {
  const box = $('minerList');
  if (!editMiners.length) { box.innerHTML = '<div class="hint">No miners. Click Add miner.</div>'; return; }
  box.innerHTML = editMiners.map((m, i) => `
    <div class="miner-edit" data-i="${i}">
      <div class="top">
        <strong>#${i+1}</strong>
        <div style="display:flex;gap:6px;align-items:center">
          <label class="switch"><input type="checkbox" class="m-en" ${m.enabled !== false ? 'checked' : ''}><i></i></label>
          <button class="btn sm danger m-del" type="button" data-i="${i}">Remove</button>
        </div>
      </div>
      <div class="field" style="margin-bottom:8px"><label>Name</label><input class="m-name" type="text" value="${escapeHtml(m.name||'')}"></div>
      <div class="field" style="margin-bottom:0"><label>XMRig API URL</label><input class="m-url" type="text" value="${escapeHtml(m.url||'')}" spellcheck="false"></div>
    </div>`).join('');
  box.querySelectorAll('.m-del').forEach(btn => {
    btn.onclick = () => { editMiners.splice(Number(btn.dataset.i), 1); renderMinerEditors(); };
  });
}

function collectMinersFromForm() {
  const nodes = $('minerList').querySelectorAll('.miner-edit');
  const out = [];
  nodes.forEach((node, i) => {
    const prev = editMiners[i] || {};
    out.push({
      id: prev.id || uid(),
      name: node.querySelector('.m-name').value.trim() || `Miner ${i+1}`,
      url: node.querySelector('.m-url').value.trim(),
      enabled: node.querySelector('.m-en').checked,
    });
  });
  return out.filter(m => m.url);
}

async function loadSettingsForm() {
  const r = await fetch('/api/settings');
  const d = await r.json();
  settings = d.settings || {};
  applyTheme(settings);
  const map = {
    s_poll_seconds:'poll_seconds', s_bind_port:'bind_port', s_dashboard_title:'dashboard_title',
    s_theme_accent:'theme_accent', s_theme_accent2:'theme_accent2', s_refresh_ui_ms:'refresh_ui_ms',
    s_history_keep:'history_keep', s_predict_horizon_min:'predict_horizon_min', s_predict_lookback:'predict_lookback',
    s_pool_fee_factor:'pool_fee_factor', s_earnings_factor:'earnings_factor',
    s_fallback_xmr_per_kh:'fallback_xmr_per_kh', s_price_fallback:'price_fallback',
    s_pool_wallet:'pool_wallet', s_pool_poll_seconds:'pool_poll_seconds',
    s_chart_mode:'chart_mode', s_candle_metric:'candle_metric', s_candle_interval_sec:'candle_interval_sec',
    s_price_provider:'price_provider', s_ui_mode:'ui_mode',
    s_ai_mode:'ai_mode', s_nn_hidden:'nn_hidden', s_nn_window:'nn_window',
    s_nn_epochs:'nn_epochs', s_nn_lr:'nn_lr', s_pc_vendor:'pc_vendor', s_fan_profile:'fan_profile',
    s_history_backend:'history_backend',
    s_brand_name:'brand_name', s_logo_letters:'logo_letters', s_brand_tagline:'brand_tagline',
    s_portfolio_label:'portfolio_label', s_theme_mode:'theme_mode', s_color_preset:'color_preset',
    s_density:'density', s_font_scale:'font_scale', s_card_radius:'card_radius',
    s_background_style:'background_style', s_currency_symbol:'currency_symbol',
    s_chart_hs_color:'chart_hs_color', s_chart_price_color:'chart_price_color',
    s_chart_forecast_color:'chart_forecast_color', s_nn_mode:'nn_mode',
    s_nn_classic_blend:'nn_classic_blend', s_nn_train_pairs:'nn_train_pairs', s_nn_clip:'nn_clip',
  };
  Object.entries(map).forEach(([id, key]) => { if ($(id) && settings[key] != null) $(id).value = settings[key]; });
  $('s_bind_mode').value = settings.bind_host === '0.0.0.0' ? '0.0.0.0' : '127.0.0.1';
  $('s_show_price_chart').value = String(settings.show_price_chart !== false);
  $('s_show_earnings_card').value = String(settings.show_earnings_card !== false);
  $('s_ai_forecast_enabled').checked = settings.ai_forecast_enabled !== false;
  if ($('s_ai_price_intel_enabled')) {
    $('s_ai_price_intel_enabled').checked = !!settings.ai_price_intel_enabled;
  }
  if ($('s_price_provider')) $('s_price_provider').value = settings.price_provider || 'auto';
  if ($('s_ui_mode')) $('s_ui_mode').value = settings.ui_mode || 'default';
  if ($('s_ai_mode')) {
    const am = settings.ai_mode || (settings.neural_net_enabled ? 'neural' : 'classic');
    $('s_ai_mode').value = am;
  }
  if ($('s_nn_mode')) $('s_nn_mode').value = settings.nn_mode || 'balanced';
  if ($('s_hw_sensors_enabled')) $('s_hw_sensors_enabled').checked = settings.hw_sensors_enabled !== false;
  if ($('s_windows_mode_enabled')) $('s_windows_mode_enabled').checked = !!settings.windows_mode_enabled;
  if ($('s_windows_fan_control_enabled')) $('s_windows_fan_control_enabled').checked = !!settings.windows_fan_control_enabled;
  if ($('s_ai_fan_control_enabled')) $('s_ai_fan_control_enabled').checked = !!settings.ai_fan_control_enabled;
  if ($('s_request_admin')) $('s_request_admin').checked = !!settings.request_admin;
  if ($('s_lenovo_fan_control_path')) $('s_lenovo_fan_control_path').value = settings.lenovo_fan_control_path || '';
  if ($('s_ai_realtime')) $('s_ai_realtime').checked = settings.ai_realtime !== false;
  if ($('s_history_backend')) $('s_history_backend').value = settings.history_backend || 'json';
  if ($('s_show_portfolio_hero')) $('s_show_portfolio_hero').checked = settings.show_portfolio_hero !== false;
  if ($('s_show_watchlist')) $('s_show_watchlist').checked = settings.show_watchlist !== false;
  if ($('s_show_holdings')) $('s_show_holdings').checked = settings.show_holdings !== false;
  if ($('s_show_details')) $('s_show_details').checked = settings.show_details !== false;
  if ($('s_show_footer')) $('s_show_footer').checked = settings.show_footer !== false;
  if ($('s_chart_fill')) $('s_chart_fill').checked = settings.chart_fill !== false;
  if ($('s_chart_smooth')) $('s_chart_smooth').checked = settings.chart_smooth !== false;
  if ($('s_number_compact')) $('s_number_compact').checked = !!settings.number_compact;
  if ($('s_reduced_motion')) $('s_reduced_motion').checked = !!settings.reduced_motion;
  if ($('s_open_browser_on_start')) $('s_open_browser_on_start').checked = settings.open_browser_on_start !== false;
  if ($('s_start_with_windows')) $('s_start_with_windows').checked = !!settings.start_with_windows;
  $('s_pool_enabled').checked = !!settings.pool_enabled && !!settings.pool_wallet;
  editMiners = (settings.miners?.length)
    ? settings.miners.map(m => ({...m}))
    : [{ id: uid(), name: 'Local XMRig', url: 'http://127.0.0.1:8080/1/summary', enabled: true }];
  renderMinerEditors();
  chartMode = settings.chart_mode || 'line';
  candleMetric = settings.candle_metric || 'hashrate';
  candleIv = settings.candle_interval_sec || 60;
  setChartMode(chartMode);
  scheduleRefresh(settings.refresh_ui_ms || 6500);
}

// warn when enabling price intel
if ($('s_ai_price_intel_enabled')) {
  $('s_ai_price_intel_enabled').addEventListener('change', (e) => {
    if (e.target.checked) {
      const ok = window.confirm(
        'Enable AI price intel?\n\n' +
        'Fetches live XMR price + trends from market APIs.\n' +
        '• Can slow the dashboard\n' +
        '• May hit rate limits\n' +
        '• Can fail if offline / API down\n\n' +
        'Turn on anyway?'
      );
      if (!ok) e.target.checked = false;
    }
  });
}
if ($('s_windows_fan_control_enabled')) {
  $('s_windows_fan_control_enabled').addEventListener('change', (e) => {
    if (e.target.checked) {
      const ok = window.confirm(
        'Allow Windows power/fan optimization?\n\n' +
        'WARNING:\n' +
        '• Changes Windows power plans (eco/balanced/performance)\n' +
        '• Lenovo: can launch Lenovo Fan Control with speed flags\n' +
        '• Can increase heat, noise, or lower hashrate if misused\n' +
        '• Prefer administrator mode for sensors/tools\n' +
        '• Use at your own risk\n\n' +
        'Enable anyway?'
      );
      if (!ok) e.target.checked = false;
      else if ($('s_windows_mode_enabled')) $('s_windows_mode_enabled').checked = true;
    }
  });
}
if ($('s_ai_fan_control_enabled')) {
  $('s_ai_fan_control_enabled').addEventListener('change', (e) => {
    if (e.target.checked) {
      const ok = window.confirm(
        'Let AI (classic or neural) adjust fan/power profiles?\n\n' +
        'Uses hashrate direction + CPU temp to pick eco/balanced/performance.\n' +
        'Requires Windows mode. Same thermal risks as manual fan control.\n\n' +
        'Enable?'
      );
      if (!ok) e.target.checked = false;
      else {
        if ($('s_windows_mode_enabled')) $('s_windows_mode_enabled').checked = true;
        if ($('s_windows_fan_control_enabled')) $('s_windows_fan_control_enabled').checked = true;
      }
    }
  });
}
if ($('s_request_admin')) {
  $('s_request_admin').addEventListener('change', (e) => {
    if (e.target.checked) {
      toast('Save settings, then restart the app for UAC elevation');
    }
  });
}
if ($('btnHwDetect')) {
  $('btnHwDetect').onclick = async () => {
    const out = $('hwDetectOut');
    if (out) out.textContent = 'Scanning sensors + Lenovo Fan Control…';
    try {
      const r = await fetch('/api/hardware/detect', { method: 'POST' });
      const d = await r.json();
      const hw = d.hardware || d;
      const v = hw.vendor || {};
      const lfc = hw.lenovo_fan_control || {};
      const lfcPath = d.lenovo_fan_control_path || lfc.path || '';
      // Auto-fill path in settings form
      if (lfcPath && $('s_lenovo_fan_control_path')) {
        $('s_lenovo_fan_control_path').value = lfcPath;
      }
      if ($('s_pc_vendor') && v.vendor_key === 'lenovo') {
        // keep auto is fine; show clear status
      }
      const fanLine = lfc.found
        ? `Fan control: YES via Lenovo Fan Control`
        : (hw.fan_rpm != null
            ? `Fan: ${hw.fan_rpm} RPM`
            : (hw.fan_pct != null ? `Fan: ${hw.fan_pct}%` : 'Fan RPM: not exposed by Windows (normal on Lenovo)'));
      const lines = [
        `Vendor: ${v.manufacturer || '—'} · ${v.model || ''}`,
        `Key: ${v.vendor_key || '—'}`,
        `CPU temp: ${hw.cpu_temp_c != null ? hw.cpu_temp_c + '°C' : 'not found'}`,
        fanLine,
        `Controllable: ${hw.fan_controllable ? (lfc.found ? 'YES (Lenovo Fan Control)' : 'limited') : 'no'}`,
        `Admin: ${hw.admin ? 'yes' : 'no'}`,
        lfc.found ? `LFC: ${lfcPath}` : 'LFC: not found — put LenovoFanControl-x64.exe in Downloads or set path',
        `Source: ${hw.sensor_source || '—'}`,
        ...(hw.control_notes || []).slice(0, 4),
      ];
      if (out) out.textContent = lines.join(' · ');
      if (lfc.found) toast('Lenovo Fan Control found — path filled');
      else if (hw.ok) toast('Hardware scanned — set LFC path if needed');
      else toast('Limited sensors');
    } catch (err) {
      if (out) out.textContent = 'Detect failed: ' + err;
    }
  };
}
if ($('btnFanApply')) {
  $('btnFanApply').onclick = async () => {
    const winOn = $('s_windows_fan_control_enabled')?.checked;
    const aiOn = $('s_ai_fan_control_enabled')?.checked;
    if (!winOn && !aiOn) {
      toast('Enable fan/power optimization (or AI fan control) first');
      return;
    }
    if ($('s_windows_mode_enabled') && !$('s_windows_mode_enabled').checked) {
      $('s_windows_mode_enabled').checked = true;
    }
    // Save path from form first so backend sees it
    const path = $('s_lenovo_fan_control_path')?.value?.trim();
    if (path) {
      try {
        await fetch('/api/settings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            settings: {
              lenovo_fan_control_path: path,
              windows_mode_enabled: true,
              windows_fan_control_enabled: true,
              fan_profile: $('s_fan_profile')?.value || 'balanced',
              pc_vendor: $('s_pc_vendor')?.value || 'lenovo',
            },
          }),
        });
      } catch (_) {}
    }
    const profile = $('s_fan_profile')?.value || 'balanced';
    try {
      const r = await fetch('/api/hardware/fan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ profile, force: true }),
      });
      const d = await r.json();
      if (d.ok) {
        if (d.skipped) toast('Already on ' + profile);
        else {
          const lv = d.lenovo || (d.steps || []).find(s => s.method === 'energy-drv' || s.method === 'lenovo-gui-once');
          toast(lv && lv.mode ? ('Fan mode: ' + lv.mode + ' (EnergyDrv)') : ('Applied ' + profile));
        }
      } else {
        toast(d.error || 'Failed');
      }
    } catch (e) {
      toast('Apply failed');
    }
  };
}
if ($('btnFanStop')) {
  $('btnFanStop').onclick = async () => {
    try {
      const r = await fetch('/api/hardware/fan/stop', { method: 'POST' });
      const d = await r.json();
      toast(d.ok ? 'Fan worker stopped' : (d.error || 'Stop failed'));
    } catch (e) {
      toast('Stop failed');
    }
  };
}

function scheduleRefresh(ms) {
  if (refreshTimer) clearInterval(refreshTimer);
  refreshTimer = setInterval(updateDashboard, Math.max(2000, Number(ms) || 6500));
}

async function saveSettings() {
  const miners = collectMinersFromForm();
  if (!miners.length) { toast('Add at least one miner URL'); return; }
  const body = {
    settings: {
      poll_seconds: Number($('s_poll_seconds').value),
      bind_host: $('s_bind_mode').value,
      bind_port: Number($('s_bind_port').value),
      dashboard_title: $('s_dashboard_title').value.trim() || 'Deer Crypto Monitor',
      brand_name: $('s_brand_name') ? $('s_brand_name').value.trim() || 'Deer Crypto Monitor' : 'Deer Crypto Monitor',
      logo_letters: $('s_logo_letters') ? $('s_logo_letters').value.trim() || 'DC' : 'DC',
      brand_tagline: $('s_brand_tagline') ? $('s_brand_tagline').value.trim() : '',
      portfolio_label: $('s_portfolio_label') ? $('s_portfolio_label').value.trim() : '',
      theme_mode: $('s_theme_mode') ? $('s_theme_mode').value : 'dark',
      color_preset: $('s_color_preset') ? $('s_color_preset').value : 'stockie',
      density: $('s_density') ? $('s_density').value : 'comfortable',
      font_scale: $('s_font_scale') ? Number($('s_font_scale').value) : 100,
      card_radius: $('s_card_radius') ? Number($('s_card_radius').value) : 20,
      background_style: $('s_background_style') ? $('s_background_style').value : 'soft_glow',
      currency_symbol: $('s_currency_symbol') ? $('s_currency_symbol').value.trim() || '$' : '$',
      theme_accent: $('s_theme_accent').value,
      theme_accent2: $('s_theme_accent2').value,
      chart_hs_color: $('s_chart_hs_color') ? $('s_chart_hs_color').value : '#12B76A',
      chart_price_color: $('s_chart_price_color') ? $('s_chart_price_color').value : '#F79009',
      chart_forecast_color: $('s_chart_forecast_color') ? $('s_chart_forecast_color').value : '#4E7CFF',
      refresh_ui_ms: Number($('s_refresh_ui_ms').value),
      history_keep: Number($('s_history_keep').value),
      show_price_chart: $('s_show_price_chart').value === 'true',
      show_earnings_card: $('s_show_earnings_card').value === 'true',
      show_portfolio_hero: $('s_show_portfolio_hero') ? $('s_show_portfolio_hero').checked : true,
      show_watchlist: $('s_show_watchlist') ? $('s_show_watchlist').checked : true,
      show_holdings: $('s_show_holdings') ? $('s_show_holdings').checked : true,
      show_details: $('s_show_details') ? $('s_show_details').checked : true,
      show_footer: $('s_show_footer') ? $('s_show_footer').checked : true,
      chart_fill: $('s_chart_fill') ? $('s_chart_fill').checked : true,
      chart_smooth: $('s_chart_smooth') ? $('s_chart_smooth').checked : true,
      number_compact: $('s_number_compact') ? $('s_number_compact').checked : false,
      reduced_motion: $('s_reduced_motion') ? $('s_reduced_motion').checked : false,
      open_browser_on_start: $('s_open_browser_on_start') ? $('s_open_browser_on_start').checked : true,
      start_with_windows: $('s_start_with_windows') ? $('s_start_with_windows').checked : false,
      ai_forecast_enabled: $('s_ai_forecast_enabled').checked,
      ai_mode: $('s_ai_mode') ? $('s_ai_mode').value : 'classic',
      neural_net_enabled: $('s_ai_mode') ? ['neural','hybrid'].includes($('s_ai_mode').value) : false,
      nn_mode: $('s_nn_mode') ? $('s_nn_mode').value : 'balanced',
      nn_hidden: $('s_nn_hidden') ? Number($('s_nn_hidden').value) : 10,
      nn_window: $('s_nn_window') ? Number($('s_nn_window').value) : 16,
      nn_epochs: $('s_nn_epochs') ? Number($('s_nn_epochs').value) : 50,
      nn_lr: $('s_nn_lr') ? Number($('s_nn_lr').value) : 0.025,
      nn_classic_blend: $('s_nn_classic_blend') ? Number($('s_nn_classic_blend').value) : 0.55,
      nn_train_pairs: $('s_nn_train_pairs') ? Number($('s_nn_train_pairs').value) : 120,
      nn_clip: $('s_nn_clip') ? Number($('s_nn_clip').value) : 2.5,
      ai_price_intel_enabled: $('s_ai_price_intel_enabled').checked,
      price_provider: $('s_price_provider') ? $('s_price_provider').value : 'auto',
      ui_mode: $('s_ui_mode') ? $('s_ui_mode').value : 'default',
      hw_sensors_enabled: $('s_hw_sensors_enabled') ? $('s_hw_sensors_enabled').checked : true,
      windows_mode_enabled: $('s_windows_mode_enabled') ? $('s_windows_mode_enabled').checked : false,
      windows_fan_control_enabled: $('s_windows_fan_control_enabled') ? $('s_windows_fan_control_enabled').checked : false,
      ai_fan_control_enabled: $('s_ai_fan_control_enabled') ? $('s_ai_fan_control_enabled').checked : false,
      request_admin: $('s_request_admin') ? $('s_request_admin').checked : false,
      pc_vendor: $('s_pc_vendor') ? $('s_pc_vendor').value : 'auto',
      fan_profile: $('s_fan_profile') ? $('s_fan_profile').value : 'balanced',
      lenovo_fan_control_path: $('s_lenovo_fan_control_path') ? $('s_lenovo_fan_control_path').value.trim() : '',
      ai_realtime: $('s_ai_realtime') ? $('s_ai_realtime').checked : true,
      history_backend: $('s_history_backend') ? $('s_history_backend').value : 'json',
      predict_horizon_min: Number($('s_predict_horizon_min').value),
      predict_lookback: Number($('s_predict_lookback').value),
      pool_fee_factor: Number($('s_pool_fee_factor').value),
      earnings_factor: Number($('s_earnings_factor').value),
      fallback_xmr_per_kh: Number($('s_fallback_xmr_per_kh').value),
      price_fallback: Number($('s_price_fallback').value),
      pool_enabled: $('s_pool_enabled').checked,
      pool_wallet: $('s_pool_wallet').value.trim(),
      pool_poll_seconds: Number($('s_pool_poll_seconds').value),
      chart_mode: $('s_chart_mode').value,
      candle_metric: $('s_candle_metric').value,
      candle_interval_sec: Number($('s_candle_interval_sec').value),
      miners,
    }
  };
  const r = await fetch('/api/settings', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body) });
  const d = await r.json();
  if (d.ok) {
    settings = d.settings;
    applyTheme(settings);
    chartMode = settings.chart_mode || chartMode;
    candleMetric = settings.candle_metric || candleMetric;
    candleIv = settings.candle_interval_sec || candleIv;
    setChartMode(chartMode);
    scheduleRefresh(settings.refresh_ui_ms);
    toast(d.message || 'Saved');
    if (d.needs_restart) toast('Restart app for host/port');
    updateDashboard();
  } else toast(d.error || 'Save failed');
}

async function resetSettings() {
  const r = await fetch('/api/settings/reset', { method: 'POST' });
  const d = await r.json();
  if (d.ok) { settings = d.settings; await loadSettingsForm(); toast('Defaults restored'); }
}

function openDrawer(open) {
  $('drawer').classList.toggle('open', open);
  $('overlay').classList.toggle('open', open);
  $('drawer').setAttribute('aria-hidden', open ? 'false' : 'true');
}

let _failStreak = 0;
async function updateDashboard() {
  try {
    const ctrl = new AbortController();
    const to = setTimeout(() => ctrl.abort(), 20000);
    const r = await fetch('/data', { cache: 'no-store', signal: ctrl.signal });
    clearTimeout(to);
    if (!r.ok) {
      _failStreak++;
      $('statusText').textContent = 'Server ' + r.status;
      $('statusDot').classList.remove('on');
      $('statusDot').classList.add('partial');
      return;
    }
    let d;
    try {
      d = await r.json();
    } catch (parseErr) {
      _failStreak++;
      $('statusText').textContent = 'Bad response';
      return;
    }
    _failStreak = 0;
    lastData = d;
    fullHistory = d.history || [];
    candles = d.candles || candles;
    const pub = d.settings_public || {};
    try { applyTheme({ ...settings, ...pub }); } catch (_) {}
    const aiOn = pub.ai_forecast_enabled !== false;

    const on = d.miners_online || 0, en = d.miners_enabled || 0, tot = d.miners_total || 0;
    if ($('fleetPill')) $('fleetPill').textContent = `${on}/${en} miners`;
    if ($('minerCountLabel')) $('minerCountLabel').textContent = `${on}/${en} online`;
    const allOnline = on > 0 && on >= en && en > 0;
    const partial = on > 0 && on < en;
    const poolOk = !!(d.pool_stats && d.pool_stats.ok);
    const dashOk = d.success !== false; // API healthy
    $('statusDot').classList.toggle('on', allOnline || (dashOk && (on > 0 || poolOk)));
    $('statusDot').classList.toggle('partial', partial || (dashOk && !allOnline && (on > 0 || poolOk)));
    if (!on && !poolOk) {
      // dashboard still online even if miner offline
      if (dashOk) {
        $('statusDot').classList.remove('on');
        // keep partial off — idle
      }
    }
    // Status = miner fleet state, never "UI offline" when /data works
    if (!en) $('statusText').textContent = dashOk ? 'No miners' : 'API error';
    else if (allOnline) $('statusText').textContent = 'Fleet online';
    else if (partial) $('statusText').textContent = 'Partial fleet';
    else if (poolOk) $('statusText').textContent = 'Pool only';
    else if (dashOk) $('statusText').textContent = 'Miners offline';
    else $('statusText').textContent = 'API error';
    if ($('clockPill')) $('clockPill').textContent = new Date().toLocaleTimeString();

    // Live hashrate only — never fall back to sticky last-known when idle
    const liveHs = (d.mining_live === false)
      ? 0
      : Number(d.hashrate || 0);
    const mining = liveHs > 1;
    $('hs').textContent = fmtHs(liveHs);
    if ($('phTrendBadge') && !mining) { const tb=$('phTrendBadge'); tb.textContent='Idle'; tb.classList.add('flat'); tb.classList.remove('down'); }
    const st = d.stats || {};
    $('hsAvg').textContent = st.avg ? fmtHs(st.avg) : '—';
    $('hsMin').textContent = st.min != null ? fmtHs(st.min) : '—';
    $('hsMed').textContent = st.median != null ? fmtHs(st.median) : '—';
    $('hsPeak').textContent = st.max != null ? fmtHs(st.max) : '—';
    $('price').textContent = d.price != null ? ('$' + Number(d.price).toFixed(2)) : '—';
    const cur = window._currencySym || '$';
    $('earn').textContent = mining ? (cur + Number(d.usd_daily||0).toFixed(3)) : (cur + '0.000');
    $('xmr').textContent = mining ? Number(d.xmr_daily||0).toFixed(5) : '0.00000';
    // mobile hero
    if ($('mhHs')) $('mhHs').textContent = fmtHs(liveHs);
    if ($('mhEarn')) $('mhEarn').textContent = mining ? (cur + Number(d.usd_daily||0).toFixed(2)) : (cur + '0.00');
    if ($('mhDue')) $('mhDue').textContent = d.pool_stats?.ok ? fmtXmr(d.pool_stats.amt_due_xmr) : '—';
    $('shares').textContent = d.shares_good != null ? fmt(d.shares_good) : '—';
    const totS = d.shares_total || d.shares_good || 0, good = d.shares_good || 0;
    if ($('shareRate')) $('shareRate').textContent = totS > 0 ? ((good/totS)*100).toFixed(1)+'%' : '—';
    $('uptime').textContent = fmtDur(d.uptime);
    $('algoLine').textContent = 'algo ' + (d.algo || '—');
    $('pool').textContent = d.pool || '—';
    $('worker').textContent = d.worker || '—';
    $('algo').textContent = d.algo || '—';
    $('hsStd').textContent = st.std != null ? fmtHs(st.std)+' H/s' : '—';
    const cv = st.avg > 0 ? (st.std/st.avg*100) : 0;
    $('hsCv').textContent = st.avg ? cv.toFixed(1)+'% CV' : '—';
    $('histCount').textContent = st.count != null ? fmt(st.count) : '—';
    $('lastUpdate').textContent = d.server_time ? new Date(d.server_time).toLocaleTimeString() : '—';
    $('bindMode').textContent = pub.bind_host === '0.0.0.0' ? 'LAN' : 'localhost';
    $('bindPort').textContent = pub.bind_port || 5000;
    $('pageUrl').textContent = location.host;

    // pool panel
    const ps = d.pool_stats;
    const poolOn = !!(pub.pool_enabled && ps);
    $('poolBanner').classList.toggle('hidden', !poolOn);
    $('poolGrid').classList.toggle('hidden', !poolOn);
    if (poolOn && ps) {
      $('poolWalletShort').textContent = ps.wallet_short || '—';
      if (ps.ok) {
        $('poolDue').textContent = fmtXmr(ps.amt_due_xmr);
        $('poolPaid').textContent = fmtXmr(ps.amt_paid_xmr);
        $('poolHs').textContent = fmtHs(ps.hashrate);
        $('poolWorkers').textContent = `${ps.workers_online||0}/${ps.workers_total||0}`;
        $('poolWorkersSub').textContent = 'online / total';
        $('poolShares').textContent = fmt(ps.valid_shares);
        $('poolInvalid').textContent = 'invalid ' + fmt(ps.invalid_shares);
      } else {
        $('poolDue').textContent = '—';
        $('poolWorkersSub').textContent = ps.error || 'error';
      }
      renderWorkers(ps);
    } else {
      renderWorkers(null);
    }

    renderMinerTable(d.miners || []);
    // Surface local miner connection errors clearly
    try {
      const offline = (d.miners || []).filter(m => m.enabled !== false && !m.online);
      if (offline.length && $('minerCountLabel')) {
        const err = offline.map(m => (m.name || 'miner') + ': ' + (m.error || 'offline')).join(' · ');
        if (err) $('minerCountLabel').title = err;
      }
    } catch (_) {}

    const p = d.prediction || {};
    if (aiOn) {
      if ($('predHorizon')) $('predHorizon').textContent = p.horizon_min || pub.predict_horizon_min || 60;
      if (p.ok) {
        if ($('predHs')) $('predHs').textContent = fmtHs(p.predicted_avg_hs) + ' H/s';
        if ($('predTrend')) setTrendEl($('predTrend'), p.trend_pct);
        if ($('phTrendBadge')) {
          const tb = $('phTrendBadge');
          const tp = Number(p.trend_pct || 0);
          tb.classList.remove('down','flat');
          if (tp > 0.4) { tb.textContent = (tp>0?'+':'') + tp.toFixed(1) + '% · AI'; tb.classList.remove('down','flat'); }
          else if (tp < -0.4) { tb.textContent = tp.toFixed(1) + '% · AI'; tb.classList.add('down'); }
          else { tb.textContent = 'Stable · AI'; tb.classList.add('flat'); }
        }
        if ($('predConf')) $('predConf').textContent = Math.round((p.confidence||0)*100) + '%';
        if ($('confBar')) $('confBar').style.width = Math.round((p.confidence||0)*100) + '%';
        if ($('predBand')) $('predBand').textContent = fmtHs(p.band_low)+' – '+fmtHs(p.band_high);
        if ($('predSummary')) $('predSummary').textContent = p.summary || '';
        if ($('predCurAvg')) $('predCurAvg').textContent = fmtHs(p.current_avg_hs)+' H/s';
        if ($('predEwma')) $('predEwma').textContent = fmtHs(p.ewma_hs)+' H/s';
        if ($('predPoints')) $('predPoints').textContent = p.points_used;
        if ($('predEarn')) $('predEarn').textContent = '$'+Number(d.pred_usd_daily||0).toFixed(3);
        if ($('predLive')) $('predLive').textContent = p.live_hs != null ? fmtHs(p.live_hs) + ' H/s' : (mining ? fmtHs(liveHs) + ' H/s' : '—');
        if ($('predDir')) $('predDir').textContent = (p.direction || '—') + (p.direction === 'up' ? ' ▲' : p.direction === 'down' ? ' ▼' : '');
        if ($('predPUp')) $('predPUp').textContent = p.p_up != null ? Math.round(p.p_up * 100) + '%' : '—';
        if ($('predHorizons') && p.horizons) {
          const h = p.horizons;
          $('predHorizons').textContent = [h['5m'], h['60m'], h['8h']].map(v => v != null ? fmtHs(v) : '—').join(' / ');
        }
        if ($('predEngine')) $('predEngine').textContent = p.method || pub.ai_mode || 'classic';
        if ($('hashDir')) $('hashDir').textContent = (p.direction || '—').toUpperCase();
        if ($('hashDirSub')) $('hashDirSub').textContent = p.p_up != null ? ('p↑ ' + Math.round(p.p_up * 100) + '% · ' + (p.method || '')) : 'AI guess';
      } else {
        if ($('predHs')) $('predHs').textContent = '0';
        if ($('predSummary')) $('predSummary').textContent = p.reason || 'Waiting…';
        if ($('predLive')) $('predLive').textContent = mining ? fmtHs(liveHs) : '0';
        if ($('predHorizons')) $('predHorizons').textContent = '—';
      }
      const nnChip = $('nnChip');
      if (nnChip) {
        nnChip.classList.remove('hidden');
        const nn = pub.neural_net_enabled || pub.ai_mode === 'neural';
        nnChip.textContent = nn ? ('Neural net · ' + (p.method || 'mlp')) : 'Classic AI';
        nnChip.classList.toggle('up', !!nn);
      }
    }
    // hardware cards
    try {
      const hw = d.hardware || {};
      const lfc = hw.lenovo_fan_control || {};
      if ($('cpuTemp')) $('cpuTemp').textContent = hw.cpu_temp_c != null ? (Number(hw.cpu_temp_c).toFixed(0) + '°') : '—';
      if ($('cpuTempSub')) $('cpuTempSub').textContent = hw.sensor_source || (hw.error || 'no sensor');
      if ($('fanRpm')) {
        if (hw.fan_rpm != null) $('fanRpm').textContent = fmt(hw.fan_rpm, 0);
        else if (hw.fan_pct != null) $('fanRpm').textContent = Number(hw.fan_pct).toFixed(0) + '%';
        else if (lfc.found) $('fanRpm').textContent = 'LFC';
        else $('fanRpm').textContent = '—';
      }
      if ($('fanSub')) {
        if (lfc.direct_control || lfc.energy_drv) {
          $('fanSub').textContent = 'EnergyDrv · ' + (lfc.active_mode || 'idle');
        } else if (lfc.found) {
          $('fanSub').textContent = 'LFC ready (prefer admin)';
        } else if (hw.fan_readable) {
          $('fanSub').textContent = hw.fan_controllable ? 'readable · control ok' : 'readable';
        } else {
          $('fanSub').textContent = 'no RPM sensor (normal)';
        }
      }
      if ($('fanRpm') && (lfc.direct_control || lfc.energy_drv) && hw.fan_rpm == null) {
        $('fanRpm').textContent = (lfc.active_mode || 'drv').toString().toUpperCase();
      }
      if ($('cpuLoad')) $('cpuLoad').textContent = hw.cpu_load_pct != null ? (Number(hw.cpu_load_pct).toFixed(0) + '%') : '—';
      const v = hw.vendor || {};
      if ($('hwVendor')) {
        let t = (v.vendor_key || pub.pc_vendor || '—');
        if (v.model) t += ' · ' + v.model;
        if (lfc.found) t += ' · LFC';
        if (hw.admin) t += ' · admin';
        $('hwVendor').textContent = t;
      }
    } catch (_) {}
    // price intel chip
    const chip = $('priceIntelChip');
    const intel = d.price_intel || p.price_intel;
    if (chip) {
      if (pub.ai_price_intel_enabled && intel && intel.ok) {
        chip.classList.remove('hidden', 'up', 'down');
        chip.classList.add(intel.trend === 'up' ? 'up' : intel.trend === 'down' ? 'down' : '');
        const c24 = intel.change_24h_pct != null ? (intel.change_24h_pct > 0 ? '+' : '') + Number(intel.change_24h_pct).toFixed(2) + '%' : '—';
        const src = (intel.provider || pub.price_provider || 'auto').toUpperCase();
        const staleTag = intel.stale ? ' · cached' : '';
        chip.textContent = `Intel · ${src} · $${Number(intel.price).toFixed(2)} · 24h ${c24}${staleTag}`;
        if ($('predSpot')) $('predSpot').textContent = '$' + Number(intel.price).toFixed(2) + ' (' + src + ')';
        if ($('predChg')) {
          const c7 = intel.change_7d_pct != null ? (Number(intel.change_7d_pct) > 0 ? '+' : '') + Number(intel.change_7d_pct).toFixed(2) + '%' : '—';
          $('predChg').textContent = c24 + ' / ' + c7;
        }
      } else if (pub.ai_price_intel_enabled && intel && !intel.ok) {
        chip.classList.remove('hidden', 'up');
        chip.classList.add('down');
        chip.textContent = 'Price intel error: ' + (intel.error || 'failed') + ' — try another provider in Settings';
        if ($('predSpot')) $('predSpot').textContent = '—';
        if ($('predChg')) $('predChg').textContent = '—';
      } else {
        chip.classList.add('hidden');
        if ($('predSpot')) $('predSpot').textContent = 'off';
        if ($('predChg')) $('predChg').textContent = '—';
      }
    }

    if (pub.candle_interval_sec) candleIv = pub.candle_interval_sec;
    try {
      if (chartMode === 'candle') drawCandles();
      else updateMainChart(p, aiOn);
    } catch (chartErr) {
      console.warn('chart update', chartErr);
    }
    try { updateProTape(d); } catch (_) {}
  } catch (e) {
    // Network / abort — keep last good data; only nag after 3 fails
    console.warn('dashboard refresh', e);
    _failStreak++;
    if (!lastData) {
      $('statusText').textContent = 'Connecting…';
      $('statusDot').classList.remove('on', 'partial');
    } else if (_failStreak >= 3) {
      $('statusText').textContent = 'Slow refresh';
      $('statusDot').classList.add('partial');
    }
    // else keep previous status text (fleet online etc.)
  }
}

// events
$('btnSettings').onclick = async () => { await loadSettingsForm(); openDrawer(true); };
$('mobSettings').onclick = async () => { await loadSettingsForm(); openDrawer(true); };
$('btnClose').onclick = () => openDrawer(false);
$('overlay').onclick = () => openDrawer(false);
$('btnSave').onclick = saveSettings;
$('btnReset').onclick = resetSettings;
$('btnAddMiner').onclick = () => {
  editMiners = collectMinersFromForm();
  editMiners.push({ id: uid(), name: 'New miner', url: 'http://127.0.0.1:8080/1/summary', enabled: true });
  renderMinerEditors();
};
$('btnPoolRefresh').onclick = async () => {
  toast('Refreshing pool…');
  await fetch('/api/pool/refresh', { method: 'POST' });
  updateDashboard();
};
document.querySelectorAll('#rangeTabs .tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('#rangeTabs .tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    rangeMode = tab.getAttribute('data-mode');
    resetZoom('line');
    updateDashboard();
  });
});
document.querySelectorAll('#chartModeSeg button').forEach(btn => {
  btn.addEventListener('click', () => {
    setChartMode(btn.getAttribute('data-mode'));
    updateZoomLabel();
  });
});
document.querySelectorAll('#candleOpts button').forEach(btn => {
  btn.addEventListener('click', () => {
    if (btn.dataset.metric) {
      candleMetric = btn.dataset.metric;
      document.querySelectorAll('#candleOpts button[data-metric]').forEach(b => b.classList.toggle('active', b === btn));
    }
    if (btn.dataset.iv) {
      candleIv = Number(btn.dataset.iv);
      document.querySelectorAll('#candleOpts button[data-iv]').forEach(b => b.classList.toggle('active', b === btn));
      candles.hashrate = clientCandles(fullHistory, candleIv, 'hashrate');
      candles.xmr = clientCandles(fullHistory, candleIv, 'xmr');
    }
    candleHoverIdx = -1;
    drawCandles();
  });
});

function ohlcPush(slot, key, val) {
  if (val == null || Number.isNaN(Number(val))) return;
  val = Number(val);
  if (!slot[key]) slot[key] = { open: val, high: val, low: val, close: val, sum: val, n: 1 };
  else {
    const o = slot[key];
    o.high = Math.max(o.high, val); o.low = Math.min(o.low, val); o.close = val;
    o.sum += val; o.n += 1;
  }
}
function packO(o, d=2) {
  if (!o) return null;
  const avg = o.n ? o.sum / o.n : o.close;
  const r = (x) => Number(Number(x).toFixed(d));
  return { open: r(o.open), high: r(o.high), low: r(o.low), close: r(o.close), avg: r(avg) };
}

function clientCandles(history, intervalSec, metric) {
  if (!history?.length) return [];
  const buckets = {};
  let cum = 0, prev = null;
  const sorted = [...history].sort((a,b) => new Date(a.time) - new Date(b.time));
  for (const h of sorted) {
    const t = new Date(h.time);
    if (Number.isNaN(+t)) continue;
    const ts = Math.floor(t.getTime()/1000);
    const bucket = ts - (ts % intervalSec);
    const hs = Number(h.hs || 0);
    let cumVal;
    if (h.pool_due_xmr != null) cumVal = Number(h.pool_due_xmr);
    else {
      if (prev) cum += Number(h.xmr_daily || 0) * ((t - prev) / 1000 / 86400);
      cumVal = cum; prev = t;
    }
    const primary = metric === 'xmr' ? cumVal : hs;
    if (!buckets[bucket]) buckets[bucket] = { n: 0 };
    const b = buckets[bucket];
    b.n += 1;
    ohlcPush(b, 'primary', primary);
    ohlcPush(b, 'hs', hs);
    ohlcPush(b, 'price', h.price);
    ohlcPush(b, 'xmr_daily', h.xmr_daily);
    ohlcPush(b, 'usd_daily', h.usd_daily);
    ohlcPush(b, 'pool_due', h.pool_due_xmr);
    ohlcPush(b, 'pool_hs', h.pool_hs);
  }
  return Object.keys(buckets).sort((a,b) => a - b).map(k => {
    const b = buckets[k];
    const p = packO(b.primary, metric === 'xmr' ? 6 : 2);
    const hs = packO(b.hs, 2);
    const price = packO(b.price, 2);
    const xmrD = packO(b.xmr_daily, 5);
    const usdD = packO(b.usd_daily, 3);
    return {
      time: new Date(Number(k) * 1000).toISOString(),
      ts: Number(k),
      open: p.open, high: p.high, low: p.low, close: p.close, avg: p.avg,
      up: p.close >= p.open, samples: b.n, metric,
      hs, price, xmr_daily: xmrD, usd_daily: usdD,
      pool_due: packO(b.pool_due, 8), pool_hs: packO(b.pool_hs, 2),
      line_hs: hs?.close, line_price: price?.close,
      line_usd_daily: usdD?.close, line_xmr_daily: xmrD?.close,
    };
  });
}

// zoom buttons
$('btnZoomIn').onclick = () => { applyZoom(activeZoom(), 0.75, 0.5); refreshActiveChart(); };
$('btnZoomOut').onclick = () => { applyZoom(activeZoom(), 1.35, 0.5); refreshActiveChart(); };
$('btnZoomReset').onclick = () => { resetZoom(chartMode); refreshActiveChart(); toast('Zoom reset'); };
$('btnChartTall').onclick = () => {
  chartTall = !chartTall;
  $('lineWrap').classList.toggle('tall', chartTall);
  $('candleWrap').classList.toggle('tall', chartTall);
  $('btnChartTall').classList.toggle('active', chartTall);
  refreshActiveChart();
  if (mainChart) mainChart.resize();
};

function clearCandleSelection() {
  candleHoverIdx = -1;
  const tip = $('candleTip');
  if (tip) tip.classList.remove('show');
}

function wireChartZoom(canvas, mode) {
  if (!canvas) return;
  const getZ = () => (mode === 'candle' ? candleZoom : lineZoom);

  canvas.addEventListener('wheel', (e) => {
    e.preventDefault();
    const rect = canvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const frac = clamp01(x / Math.max(1, rect.width));
    // smoother wheel steps
    applyZoom(getZ(), e.deltaY > 0 ? 1.12 : 0.9, frac);
    clearCandleSelection();
    refreshActiveChartSmooth();
  }, { passive: false });

  canvas.addEventListener('mousedown', (e) => {
    if (e.button !== 0) return;
    panDrag = {
      mode, startX: e.clientX, z0: getZ().start, z1: getZ().end,
      moved: false, select: false
    };
    canvas.classList.add('panning');
  });

  window.addEventListener('mousemove', (e) => {
    if (!panDrag || panDrag.mode !== mode) return;
    const rect = canvas.getBoundingClientRect();
    const dx = e.clientX - panDrag.startX;
    if (Math.abs(dx) > 4) {
      if (!panDrag.moved) {
        panDrag.moved = true;
        clearCandleSelection();
      }
    }
    // slightly dampened pan for smoother feel
    const s = Math.max(MIN_ZOOM_SPAN, panDrag.z1 - panDrag.z0);
    const delta = -(dx / Math.max(1, rect.width)) * s * 0.92;
    setZoomWindow(getZ(), panDrag.z0 + delta, panDrag.z0 + delta + s);
    refreshActiveChartSmooth();
  });

  window.addEventListener('mouseup', (e) => {
    if (!panDrag || panDrag.mode !== mode) return;
    const wasPan = panDrag.moved;
    canvas.classList.remove('panning');
    // click (no pan) on candle → select
    if (mode === 'candle' && !wasPan) {
      const idx = candleIndexFromEvent(e);
      setCandleHover(idx, e.clientX, e.clientY);
    }
    panDrag = null;
  });

  canvas.addEventListener('touchstart', (e) => {
    if (e.touches.length === 2) {
      const d = Math.hypot(
        e.touches[0].clientX - e.touches[1].clientX,
        e.touches[0].clientY - e.touches[1].clientY
      );
      pinchState = { dist: d, start: getZ().start, end: getZ().end, mode };
      panDrag = null;
      clearCandleSelection();
      canvas.classList.add('panning');
    } else if (e.touches.length === 1) {
      panDrag = {
        mode,
        startX: e.touches[0].clientX,
        z0: getZ().start,
        z1: getZ().end,
        moved: false,
      };
      // do NOT open tip on touchstart — only on clean tap end
    }
  }, { passive: true });

  canvas.addEventListener('touchmove', (e) => {
    if (pinchState && pinchState.mode === mode && e.touches.length === 2) {
      e.preventDefault();
      const d = Math.hypot(
        e.touches[0].clientX - e.touches[1].clientX,
        e.touches[0].clientY - e.touches[1].clientY
      );
      const factor = pinchState.dist / Math.max(1, d);
      const span0 = Math.max(MIN_ZOOM_SPAN, pinchState.end - pinchState.start);
      const newSpan = Math.min(1, Math.max(MIN_ZOOM_SPAN, span0 * factor));
      const mid = (pinchState.start + pinchState.end) / 2;
      setZoomWindow(getZ(), mid - newSpan / 2, mid + newSpan / 2);
      refreshActiveChartSmooth();
      return;
    }
    if (panDrag && panDrag.mode === mode && e.touches.length === 1) {
      e.preventDefault();
      const rect = canvas.getBoundingClientRect();
      const dx = e.touches[0].clientX - panDrag.startX;
      if (Math.abs(dx) > 6) {
        if (!panDrag.moved) {
          panDrag.moved = true;
          clearCandleSelection();
          canvas.classList.add('panning');
        }
      }
      if (!panDrag.moved) return; // still a potential tap
      const s = Math.max(MIN_ZOOM_SPAN, panDrag.z1 - panDrag.z0);
      const delta = -(dx / Math.max(1, rect.width)) * s * 0.9;
      setZoomWindow(getZ(), panDrag.z0 + delta, panDrag.z0 + delta + s);
      refreshActiveChartSmooth();
    }
  }, { passive: false });

  canvas.addEventListener('touchend', (e) => {
    if (e.touches.length < 2) pinchState = null;
    if (e.touches.length === 0) {
      canvas.classList.remove('panning');
      // one-tap only (no pan/pinch) → show candle info
      if (mode === 'candle' && panDrag && !panDrag.moved && e.changedTouches[0]) {
        const fake = {
          clientX: e.changedTouches[0].clientX,
          clientY: e.changedTouches[0].clientY,
        };
        const idx = candleIndexFromEvent(fake);
        setCandleHover(idx, fake.clientX, fake.clientY);
      }
      panDrag = null;
    }
  });
}

// desktop hover: only when directly over a candle body/wick
(function wireCandleHover() {
  const canvas = $('candleCanvas');
  if (!canvas) return;
  canvas.addEventListener('mousemove', (e) => {
    if (panDrag) return; // panning owns the pointer
    onCandlePointer(e);
  });
  canvas.addEventListener('mouseleave', onCandleLeave);
  wireChartZoom(canvas, 'candle');
  wireChartZoom($('mainChart'), 'line');
})();

// mobile nav
document.querySelectorAll('#mobNav button[data-sec]').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('#mobNav button[data-sec]').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    let id = btn.dataset.sec;
    if (id === 'poolGrid') {
      const grid = $('poolGrid');
      const ban = $('poolBanner');
      if (grid && !grid.classList.contains('hidden')) id = 'poolGrid';
      else if (ban && !ban.classList.contains('hidden')) id = 'poolBanner';
      else { toast('Enable pool wallet in Settings'); id = 'sec-charts'; }
    }
    const el = document.getElementById(id);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
});

// scroll-spy for mobile nav
let spyTick = null;
window.addEventListener('scroll', () => {
  if (!isMobile()) return;
  if (spyTick) return;
  spyTick = requestAnimationFrame(() => {
    spyTick = null;
    const ids = ['sec-overview', 'sec-charts', 'poolGrid', 'sec-miners'];
    let best = 'sec-overview', bestDist = Infinity;
    ids.forEach(id => {
      const el = document.getElementById(id);
      if (!el || el.classList.contains('hidden')) return;
      const d = Math.abs(el.getBoundingClientRect().top - 90);
      if (d < bestDist) { bestDist = d; best = id; }
    });
    document.querySelectorAll('#mobNav button[data-sec]').forEach(b => {
      const sec = b.dataset.sec;
      b.classList.toggle('active', sec === best || (sec === 'poolGrid' && best === 'poolBanner'));
    });
  });
}, { passive: true });

document.addEventListener('keydown', (e) => { if (e.key === 'Escape') openDrawer(false); });
window.addEventListener('resize', () => { if (chartMode === 'candle') drawCandles(); });

// UI color pickers → custom preset (does not change chart colors)
['s_theme_accent','s_theme_accent2'].forEach(id => {
  if ($(id)) $(id).addEventListener('input', () => {
    if ($('s_color_preset')) $('s_color_preset').value = 'custom';
    // live preview of UI chrome
    if (lastData || settings) applyTheme({ ...(settings||{}), ...(lastData?.settings_public||{}), theme_accent: $('s_theme_accent')?.value, theme_accent2: $('s_theme_accent2')?.value, color_preset: 'custom' });
  });
});
// Chart color pickers live-preview charts only
['s_chart_hs_color','s_chart_price_color','s_chart_forecast_color'].forEach(id => {
  if ($(id)) $(id).addEventListener('input', () => {
    if (lastData || settings) applyTheme({
      ...(settings||{}), ...(lastData?.settings_public||{}),
      chart_hs_color: $('s_chart_hs_color')?.value,
      chart_price_color: $('s_chart_price_color')?.value,
      chart_forecast_color: $('s_chart_forecast_color')?.value,
    });
  });
});
if ($('s_color_preset')) {
  $('s_color_preset').addEventListener('change', () => {
    const p = $('s_color_preset').value;
    const map = {
      stockie: ['#12B76A','#4E7CFF'], monero: ['#FF6600','#F2A900'],
      ocean: ['#0EA5E9','#6366F1'], sunset: ['#F97316','#EC4899'],
      violet: ['#A855F7','#22D3EE'],
    };
    if (map[p] && $('s_theme_accent') && $('s_theme_accent2')) {
      $('s_theme_accent').value = map[p][0];
      $('s_theme_accent2').value = map[p][1];
      applyTheme({ ...(settings||{}), theme_accent: map[p][0], theme_accent2: map[p][1], color_preset: p });
    }
  });
}
// NN mode → fill custom fields for visibility
if ($('s_nn_mode')) {
  const nnMap = {
    balanced: { h:10, w:16, ep:50, lr:0.025, blend:0.55, pairs:120, clip:2.5 },
    aggressive: { h:16, w:12, ep:80, lr:0.04, blend:0.35, pairs:160, clip:3.0 },
    conservative: { h:8, w:20, ep:30, lr:0.015, blend:0.75, pairs:80, clip:2.0 },
    deep: { h:24, w:24, ep:100, lr:0.02, blend:0.45, pairs:200, clip:2.8 },
  };
  $('s_nn_mode').addEventListener('change', () => {
    const m = nnMap[$('s_nn_mode').value];
    if (!m) return;
    if ($('s_nn_hidden')) $('s_nn_hidden').value = m.h;
    if ($('s_nn_window')) $('s_nn_window').value = m.w;
    if ($('s_nn_epochs')) $('s_nn_epochs').value = m.ep;
    if ($('s_nn_lr')) $('s_nn_lr').value = m.lr;
    if ($('s_nn_classic_blend')) $('s_nn_classic_blend').value = m.blend;
    if ($('s_nn_train_pairs')) $('s_nn_train_pairs').value = m.pairs;
    if ($('s_nn_clip')) $('s_nn_clip').value = m.clip;
  });
  ['s_nn_hidden','s_nn_window','s_nn_epochs','s_nn_lr','s_nn_classic_blend','s_nn_train_pairs','s_nn_clip'].forEach(id => {
    if ($(id)) $(id).addEventListener('input', () => { if ($('s_nn_mode')) $('s_nn_mode').value = 'custom'; });
  });
}
if ($('s_ui_mode')) {
  $('s_ui_mode').addEventListener('change', () => {
    applyTheme({ ...(settings||{}), ...(lastData?.settings_public||{}), ui_mode: $('s_ui_mode').value });
  });
}

initCharts();
loadSettingsForm().then(updateDashboard);
</script>
</body>
</html>
"""


def _set_windows_app_id():
    """Register as a real Win32 app (taskbar grouping, jump lists, Start)."""
    if os.name != "nt":
        return
    try:
        import ctypes
        # Explicit AppUserModelID so Windows treats us as a proper application
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            f"DeerCrypto.{APP_SLUG}.{APP_VERSION}"
        )
    except Exception:
        pass


if __name__ == "__main__":
    _set_windows_app_id()
    load_settings()
    # Optional UAC elevation for sensors / Lenovo fan tools
    if elevate_if_requested():
        print("Restarting elevated (UAC)… close this window if a new one opened.")
        raise SystemExit(0)
    # Auto-discover Lenovo Fan Control on startup
    try:
        lfc = find_lenovo_fan_control(auto_save=True)
        if lfc:
            print(f"  Lenovo Fan Control: {lfc}")
        else:
            print("  Lenovo Fan Control: not found (optional)")
    except Exception:
        pass
    load_history()
    host = SETTINGS.get("bind_host", "127.0.0.1")
    port = int(SETTINGS.get("bind_port", 5000))
    n_miners = len([m for m in SETTINGS.get("miners", []) if m.get("enabled")])
    threading.Thread(target=background_updater, daemon=True).start()
    ai_mode = "neural" if (
        SETTINGS.get("neural_net_enabled")
        or str(SETTINGS.get("ai_mode", "")).lower() == "neural"
    ) else "classic"
    url = f"http://127.0.0.1:{port}" if host in ("0.0.0.0", "127.0.0.1", "localhost") else f"http://{host}:{port}"
    print("=" * 56)
    print(f"  {APP_NAME}  v{APP_VERSION}")
    print("  Mining portfolio · MoneroOcean · AI · candles")
    print("=" * 56)
    print(f"  Bind   : {host}:{port}")
    print(f"  Miners : {n_miners} enabled")
    print(f"  Pool   : {'ON' if SETTINGS.get('pool_enabled') else 'OFF'} (MoneroOcean)")
    print(f"  AI     : {'ON' if SETTINGS.get('ai_forecast_enabled', True) else 'OFF'} ({ai_mode}"
          f"{'+rt' if SETTINGS.get('ai_realtime', True) else ''})")
    print(f"  History: {SETTINGS.get('history_backend', 'json')}")
    print(f"  Theme  : {SETTINGS.get('theme_mode', 'dark')} / {SETTINGS.get('color_preset', 'stockie')}")
    print(f"  Admin  : {'YES' if is_windows_admin() else 'no'}")
    print(f"  Frozen : {'yes' if getattr(sys, 'frozen', False) else 'no'}")
    if host == "0.0.0.0":
        print(f"  LAN    : http://<this-pc-ip>:{port}")
    print(f"  Open   : {url}")
    print("=" * 56)
    if SETTINGS.get("open_browser_on_start", True):
        def _open_browser():
            time.sleep(1.2)
            try:
                import webbrowser
                webbrowser.open(url)
            except Exception:
                pass
        threading.Thread(target=_open_browser, daemon=True).start()
    # Flask quieter in packaged builds
    app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)
