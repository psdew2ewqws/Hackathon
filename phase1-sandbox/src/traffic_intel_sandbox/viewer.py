"""Tiny local HTTP dashboard for the Phase 1 sandbox.

Serves a single HTML page at http://localhost:8000/ showing:
    • Live RTSP thumbnail (auto-refreshes every 2 s)
    • Hourly detector-count chart for the most recent day
    • The last 10 signal-log events
    • Handles to everything else (RTSP URL, HLS URL, MediaMTX API, CVAT)

This is NOT the Phase 3 dashboard — it's a lightweight sandbox preview so you
can see the system running without extra tooling. No external JS/CSS deps.

Usage:
    python -m traffic_intel_sandbox.viewer               # :8000
    python -m traffic_intel_sandbox.viewer --port 8123
"""

from __future__ import annotations

import argparse
import gzip as _gz
import hashlib as _hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time as _time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Sequence

import pyarrow.parquet as pq

# ── mtime+TTL cache for file-derived endpoints ───────────────────────────
#
# Several /api/* handlers read the same ndjson/parquet on every request.
# `_mtime_cached` short-circuits those reads when none of the source files
# have changed since the last compute. When a file IS mutating (phase2.ndjson
# during a live run), an optional `min_ttl_s` floor caps recompute QPS.
_MTIME_CACHE: dict[str, tuple[tuple, Any, float]] = {}
_MTIME_CACHE_LOCK = threading.Lock()


def _stat_sig(p: Path) -> tuple[int, int]:
    try:
        st = p.stat()
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return (0, 0)


def _mtime_cached(key: str, paths: Sequence[Path], fn: Callable[[], Any],
                  *, min_ttl_s: float = 0.0) -> Any:
    sig = tuple((str(p), _stat_sig(p)) for p in paths)
    now = _time.monotonic()
    with _MTIME_CACHE_LOCK:
        hit = _MTIME_CACHE.get(key)
    if hit is not None:
        old_sig, value, stamp = hit
        if old_sig == sig:
            return value
        if min_ttl_s and (now - stamp) < min_ttl_s:
            return value
    value = fn()
    with _MTIME_CACHE_LOCK:
        _MTIME_CACHE[key] = (sig, value, now)
    return value


def _etag_for(paths: Sequence[Path], extra: str = "") -> str:
    """Weak ETag derived from file mtimes + sizes. Cheap to compute, changes
    iff any source file mutates."""
    h = _hashlib.blake2b(digest_size=12)
    for p in paths:
        mt, sz = _stat_sig(p)
        h.update(f"{p.name}:{mt}:{sz};".encode())
    if extra:
        h.update(extra.encode())
    return f'W/"{h.hexdigest()}"'


def _tail_lines(path: Path, n: int, max_bytes: int = 128 * 1024) -> list[str]:
    """Return the last n lines of a text file without reading the whole file."""
    try:
        size = path.stat().st_size
    except OSError:
        return []
    if size == 0:
        return []
    read_sz = min(size, max_bytes)
    with path.open("rb") as fh:
        fh.seek(size - read_sz)
        tail = fh.read()
    lines = tail.splitlines()
    # If we didn't read the whole file, drop the first (possibly partial) line.
    if read_sz < size and len(lines) > n:
        lines = lines[1:]
    return [b.decode("utf-8", errors="replace") for b in lines[-n:]]

# parents[3] = .../traffic-intel (repo root)
#   parents[0] = .../traffic_intel_sandbox
#   parents[1] = .../src
#   parents[2] = .../phase1-sandbox
#   parents[3] = .../traffic-intel
REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = Path(os.environ.get("DATA_DIR", REPO_ROOT / "data"))
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"
THUMB_PATH = Path("/tmp/traffic-intel-thumb.jpg")

# §7.7 audit + auth. DASHBOARD_TOKEN is read lazily at request time so the
# operator can rotate it without restarting the process. If unset, write
# endpoints are disabled entirely (there are none today — this is
# forward-compat for Phase 3).
AUDIT_LOG_PATH = DATA_DIR / "audit.log"
AUDIT_MAX_BYTES = 50 * 1024 * 1024

# MIME map for the handful of file types Vite emits
_STATIC_MIME = {
    ".html": "text/html; charset=utf-8",
    ".js":   "application/javascript; charset=utf-8",
    ".mjs":  "application/javascript; charset=utf-8",
    ".css":  "text/css; charset=utf-8",
    ".map":  "application/json; charset=utf-8",
    ".svg":  "image/svg+xml",
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".ico":  "image/x-icon",
    ".json": "application/json; charset=utf-8",
    ".woff": "font/woff",
    ".woff2":"font/woff2",
}
THUMB_REFRESH_S = 2.0

HTML = r"""<!doctype html>
<html lang="en" dir="ltr"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=1280">
<title>Traffic Ops · SITE-001</title>
<style>
  :root {
    color-scheme: dark;
    /* ── Surface ─────────────────────────────── */
    --bg:         #0B0D11;
    --surface:    #14171D;
    --surface-2:  #181C24;
    --hover:      #1B1F28;
    --border:     #23272F;
    --border-soft:#1A1D23;
    /* ── Text ───────────────────────────────── */
    --fg:         #E7E9EC;
    --fg-dim:     #9097A0;
    --fg-faint:   #5A616B;
    --fg-mute:    #3E444D;
    /* ── Accent (use sparingly) ─────────────── */
    --accent:     #E8B464;   /* warm amber — live / active only */
    --accent-dim: #8B6A3A;
    --accent-ghost:rgba(232,180,100,0.10);
    --good:       #7FA889;   /* sage, for positive deltas */
    --warn:       #D68F6B;   /* muted terracotta, rarely */
    /* ── Type ───────────────────────────────── */
    --sans: system-ui, -apple-system, 'Segoe UI', 'Helvetica Neue', 'DejaVu Sans', 'Ubuntu', sans-serif;
    --mono: ui-monospace, 'JetBrains Mono', 'Fira Mono', 'DejaVu Sans Mono', 'Ubuntu Mono', monospace;
    /* ── Rhythm ────────────────────────────── */
    --r-sm: 6px;
    --r-md: 10px;
    --r-lg: 14px;
  }
  *,*::before,*::after { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { height: 100%; background: var(--bg); color: var(--fg); }
  body {
    font-family: var(--sans);
    font-size: 13px; line-height: 1.55;
    font-feature-settings: 'cv11' 1, 'ss01' 1, 'tnum' 1;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
    min-height: 100vh;
  }
  ::selection { background: var(--accent-ghost); color: var(--fg); }

  /* ── Subtle atmospheric warm glow only at very top, one line deep ── */
  body::before {
    content: ""; position: fixed; inset: 0 0 auto 0; height: 320px;
    background: radial-gradient(ellipse 900px 320px at 50% 0%, rgba(232,180,100,0.025), transparent 70%);
    pointer-events: none; z-index: 0;
  }

  .page {
    position: relative; z-index: 1;
    max-width: 1480px; margin: 0 auto;
    padding: 28px 32px 56px;
  }

  /* ── HEADER ─────────────────────────────────── */
  .topbar {
    display: grid;
    grid-template-columns: auto 1fr auto;
    align-items: center;
    gap: 28px;
    padding: 6px 0 24px;
    margin-bottom: 28px;
    border-bottom: 1px solid var(--border-soft);
  }
  .brand {
    display: flex; align-items: baseline; gap: 12px;
  }
  .brand .logo {
    width: 22px; height: 22px; position: relative;
  }
  .brand .logo::before, .brand .logo::after {
    content: ""; position: absolute; background: var(--accent);
    border-radius: 2px;
  }
  .brand .logo::before { inset: 0 auto auto 0; width: 22px; height: 6px; }
  .brand .logo::after  { inset: 9px 0 9px auto; width: 6px; height: 4px; background: var(--fg-dim); }
  .brand h1 {
    font-weight: 600; font-size: 15px; letter-spacing: -0.01em;
    color: var(--fg);
  }
  .brand h1 .sep { color: var(--fg-mute); margin: 0 8px; font-weight: 400; }
  .brand h1 .site { color: var(--fg-dim); font-weight: 400; }

  .compliance {
    display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
    justify-content: center;
  }
  .chip {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 5px 10px;
    font: 500 11px var(--mono);
    letter-spacing: 0.02em;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 999px;
    color: var(--fg-dim);
    transition: color 0.2s, border-color 0.2s, background 0.2s;
  }
  .chip .dot {
    width: 5px; height: 5px; border-radius: 50%;
    background: var(--fg-mute);
    transition: background 0.2s, box-shadow 0.2s;
  }
  .chip.ok { color: var(--fg); border-color: rgba(232,180,100,0.3); }
  .chip.ok .dot { background: var(--accent); box-shadow: 0 0 4px rgba(232,180,100,0.6); }
  .chip.bad { color: var(--fg-faint); }

  .meta-right {
    display: flex; align-items: center; gap: 20px;
    font: 500 12px var(--mono); color: var(--fg-dim);
  }
  .meta-right time { color: var(--fg); font-variant-numeric: tabular-nums; }
  .live-pill {
    display: inline-flex; align-items: center; gap: 7px;
    padding: 5px 11px; border-radius: 999px;
    background: var(--accent-ghost);
    border: 1px solid rgba(232,180,100,0.25);
    color: var(--accent); font: 600 11px var(--mono);
    letter-spacing: 0.08em;
  }
  .live-pill .pulse {
    width: 6px; height: 6px; border-radius: 50%;
    background: var(--accent);
    box-shadow: 0 0 0 0 rgba(232,180,100, 0.8);
    animation: livepulse 1.8s ease-out infinite;
  }
  @keyframes livepulse {
    0%   { box-shadow: 0 0 0 0 rgba(232,180,100, 0.6); }
    70%  { box-shadow: 0 0 0 7px rgba(232,180,100, 0); }
    100% { box-shadow: 0 0 0 0 rgba(232,180,100, 0); }
  }
  .live-pill.off { background: transparent; border-color: var(--border); color: var(--fg-faint); }
  .live-pill.off .pulse { background: var(--fg-mute); box-shadow: none; animation: none; }
  .nav-link {
    font: 500 12px var(--mono); letter-spacing: 0.03em;
    padding: 6px 12px; border-radius: var(--r-sm);
    border: 1px solid rgba(232,180,100,0.35);
    background: var(--accent-ghost);
    color: var(--accent); text-decoration: none;
    transition: background 0.15s;
  }
  .nav-link:hover { background: rgba(232,180,100,0.18); }

  /* ── PANEL BASE ─────────────────────────────── */
  .panel {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--r-md);
    padding: 20px 22px;
  }
  .panel-title {
    display: flex; justify-content: space-between; align-items: baseline;
    margin-bottom: 18px;
  }
  .panel-title h2 {
    font-weight: 500; font-size: 13px; color: var(--fg);
    letter-spacing: -0.005em;
  }
  .panel-title .hint {
    font: 500 11px var(--mono);
    color: var(--fg-faint); letter-spacing: 0.02em;
  }

  /* ── HERO METRICS ──────────────────────────── */
  .metrics {
    display: grid; grid-template-columns: repeat(5, 1fr);
    gap: 0;
    margin-bottom: 24px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--r-md);
    overflow: hidden;
  }
  .metric {
    padding: 20px 22px;
    border-right: 1px solid var(--border-soft);
    position: relative;
  }
  .metric:last-child { border-right: none; }
  .metric .label {
    font: 500 10px var(--mono);
    letter-spacing: 0.12em; text-transform: uppercase;
    color: var(--fg-faint);
    margin-bottom: 10px;
  }
  .metric .value {
    font-weight: 600; font-size: 28px; line-height: 1.1;
    color: var(--fg); letter-spacing: -0.02em;
    font-variant-numeric: tabular-nums lining-nums;
  }
  .metric .sub {
    font: 400 11px var(--mono);
    color: var(--fg-dim); margin-top: 6px;
    letter-spacing: 0.01em;
  }
  .metric.accent .value { color: var(--accent); }
  .metric.accent .label { color: var(--accent-dim); }

  /* ── FEED (mini strip + main stage) ────────── */
  .feed {
    margin-bottom: 24px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--r-md);
    overflow: hidden;
  }
  .mini-strip {
    display: grid; grid-template-columns: repeat(5, 1fr); gap: 1px;
    background: var(--border-soft);
    padding: 1px;
  }
  .mini {
    all: unset; cursor: pointer;
    position: relative; display: block;
    aspect-ratio: 16 / 9;
    background: #000;
    overflow: hidden;
    transition: filter 0.25s ease;
  }
  .mini:hover .mini-media { filter: saturate(1); }
  .mini[aria-pressed="true"]::after {
    content: ""; position: absolute; inset: 0;
    box-shadow: inset 0 0 0 2px var(--accent);
    pointer-events: none;
  }
  .mini-media {
    width: 100%; height: 100%;
    object-fit: cover; display: block;
    filter: saturate(0.6) brightness(0.85);
    transition: filter 0.25s ease;
  }
  .mini[aria-pressed="true"] .mini-media { filter: none; }
  .mini-label {
    position: absolute; left: 10px; bottom: 10px; z-index: 2;
    padding: 3px 8px; border-radius: var(--r-sm);
    font: 600 10px var(--mono);
    letter-spacing: 0.04em;
    color: var(--fg);
    background: rgba(11,13,17,0.78);
    backdrop-filter: blur(6px);
    display: inline-flex; align-items: center; gap: 6px;
  }
  .mini[aria-pressed="true"] .mini-label { color: var(--accent); }
  .mini-live-dot {
    width: 5px; height: 5px; border-radius: 50%;
    background: var(--accent);
    animation: minidot 1.6s ease-in-out infinite;
  }
  @keyframes minidot { 50% { opacity: 0.35; } }

  .stage {
    position: relative;
    aspect-ratio: 16 / 9; width: 100%;
    background: #000;
  }
  .stage-media {
    width: 100%; height: 100%; object-fit: contain; display: block;
    background: #000;
  }
  .stage video { pointer-events: none; }
  .stage video::-webkit-media-controls,
  .stage video::-webkit-media-controls-enclosure,
  .stage video::-webkit-media-controls-panel { display: none !important; }

  .stage-chrome {
    position: absolute; inset: 14px 14px auto 14px;
    display: flex; justify-content: space-between; align-items: center;
    pointer-events: none; z-index: 2;
  }
  .stage-tag, .stage-meta {
    padding: 5px 10px; border-radius: var(--r-sm);
    font: 500 10px var(--mono);
    background: rgba(11,13,17,0.74);
    backdrop-filter: blur(6px);
    letter-spacing: 0.04em;
  }
  .stage-tag {
    color: var(--fg); display: inline-flex; align-items: center; gap: 6px;
  }
  .stage-tag .dot {
    width: 5px; height: 5px; border-radius: 50%; background: var(--accent);
    animation: minidot 1.6s ease-in-out infinite;
  }
  .stage-meta { color: var(--fg-dim); }

  .stage-right { display: flex; align-items: center; gap: 10px; pointer-events: auto; }

  /* AI master toggle — one switch applies to every cam */
  .ai-toggle {
    all: unset; cursor: pointer;
    display: inline-flex; align-items: center; gap: 8px;
    padding: 4px 10px 4px 4px; border-radius: 999px;
    background: rgba(11,13,17,0.78); backdrop-filter: blur(6px);
    border: 1px solid var(--border);
    font: 500 10px var(--mono); letter-spacing: 0.08em;
    color: var(--fg-dim);
    transition: border-color 0.2s, color 0.2s;
  }
  .ai-toggle:hover { border-color: var(--fg-dim); color: var(--fg); }
  .ai-sw {
    width: 28px; height: 16px; border-radius: 999px;
    background: var(--fg-mute); position: relative;
    transition: background 0.2s ease;
  }
  .ai-knob {
    position: absolute; top: 2px; left: 2px;
    width: 12px; height: 12px; border-radius: 50%;
    background: var(--fg); transition: left 0.2s ease;
  }
  .ai-toggle[aria-pressed="true"] {
    color: var(--accent); border-color: rgba(232,180,100,0.35);
  }
  .ai-toggle[aria-pressed="true"] .ai-sw { background: var(--accent); }
  .ai-toggle[aria-pressed="true"] .ai-knob { left: 14px; background: #0B0D11; }
  .ai-toggle .ai-lbl b { font-weight: 600; }

  .endpoint-strip {
    display: flex; gap: 24px; flex-wrap: wrap;
    padding: 12px 22px;
    font: 500 11px var(--mono);
    color: var(--fg-faint);
    border-top: 1px solid var(--border-soft);
  }
  .endpoint-strip a {
    color: var(--fg-dim); text-decoration: none;
    border-bottom: 1px solid transparent;
    transition: color 0.2s, border-color 0.2s;
  }
  .endpoint-strip a:hover { color: var(--accent); border-color: var(--accent-dim); }

  /* ── GRID LAYOUT ───────────────────────────── */
  .grid-3 {
    display: grid; grid-template-columns: 1.5fr 1fr 1.5fr;
    gap: 16px; margin-bottom: 24px;
  }
  .grid-2 {
    display: grid; grid-template-columns: 1fr 1fr; gap: 16px;
    margin-bottom: 24px;
  }

  /* ── CHARTS ────────────────────────────────── */
  canvas { display: block; width: 100%; }
  .chart-wrap { height: 220px; margin-bottom: 16px; }
  .chart-wrap canvas { height: 100%; }
  .chart-meta {
    display: grid; grid-template-columns: repeat(3, 1fr);
    gap: 16px; padding-top: 12px;
    border-top: 1px solid var(--border-soft);
  }
  .chart-meta .k {
    font: 500 10px var(--mono); color: var(--fg-faint);
    letter-spacing: 0.08em; text-transform: uppercase;
  }
  .chart-meta .v {
    font-weight: 500; font-size: 16px; color: var(--fg);
    margin-top: 4px; font-variant-numeric: tabular-nums;
    letter-spacing: -0.01em;
  }
  .chart-meta .v.accent { color: var(--accent); }

  /* ── APPROACH LIST (horizontal bars) ──────── */
  .approach {
    display: grid; grid-template-columns: 28px 1fr auto;
    gap: 14px; align-items: center;
    padding: 8px 0;
    border-bottom: 1px solid var(--border-soft);
    font-family: var(--mono);
  }
  .approach:last-child { border-bottom: none; }
  .approach .a {
    font-weight: 600; font-size: 12px; color: var(--fg);
    letter-spacing: 0.04em;
  }
  .approach .track {
    height: 4px; border-radius: 2px;
    background: var(--border); position: relative;
  }
  .approach .fill {
    position: absolute; inset: 0 auto 0 0;
    border-radius: 2px; background: var(--fg-dim);
    transition: width 0.35s ease;
  }
  .approach.top .fill { background: var(--accent); }
  .approach .n {
    font-weight: 500; font-size: 14px; color: var(--fg);
    font-variant-numeric: tabular-nums;
    min-width: 56px; text-align: right;
    letter-spacing: -0.01em;
  }
  .approach.top .n { color: var(--accent); }

  /* ── LOG ───────────────────────────────────── */
  .log {
    max-height: 280px; overflow-y: auto;
    margin: 0 -10px; padding: 0 10px;
    scrollbar-width: thin; scrollbar-color: var(--border) transparent;
  }
  .log::-webkit-scrollbar { width: 5px; }
  .log::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }
  .log-row {
    display: grid; grid-template-columns: 72px 1fr;
    gap: 12px; align-items: baseline;
    padding: 7px 0;
    border-bottom: 1px solid var(--border-soft);
    font: 400 11.5px var(--mono);
  }
  .log-row:last-child { border-bottom: none; }
  .log-row .ts { color: var(--fg-faint); font-variant-numeric: tabular-nums; }
  .log-row .body { color: var(--fg); word-break: break-word; }
  .log-row .body .k { color: var(--accent); margin-right: 6px; }
  .log-row.x { border-left: 2px solid var(--accent); margin-left: -10px; padding-left: 10px; }
  .log:empty::before {
    content: "awaiting events"; display: block;
    padding: 14px 2px; color: var(--fg-faint);
    font: 400 12px var(--mono);
  }

  /* ── HANDLES ───────────────────────────────── */
  .handles {
    display: grid; grid-template-columns: 1fr 1fr;
    gap: 8px 20px;
    font: 500 12px var(--mono);
  }
  .handle {
    display: grid; grid-template-columns: 52px 1fr;
    gap: 10px; align-items: baseline;
    padding: 6px 0;
    border-bottom: 1px solid var(--border-soft);
  }
  .handle b {
    color: var(--fg-faint); font-weight: 500;
    font-size: 10px; letter-spacing: 0.14em;
    text-transform: uppercase;
  }
  .handle a, .handle code {
    color: var(--fg); text-decoration: none;
    font-family: var(--mono); font-size: 12px;
  }
  .handle a:hover { color: var(--accent); }
  .handle code {
    background: var(--surface-2); padding: 2px 6px; border-radius: 4px;
    border: 1px solid var(--border-soft);
    font-size: 11px; color: var(--fg-dim);
  }

  /* ── FOOTER ────────────────────────────────── */
  .foot {
    margin-top: 40px; padding-top: 18px;
    border-top: 1px solid var(--border-soft);
    display: flex; justify-content: space-between; align-items: center;
    font: 500 11px var(--mono); color: var(--fg-faint);
    letter-spacing: 0.02em;
  }
  .foot .sep { color: var(--fg-mute); margin: 0 10px; }
  .foot .right { color: var(--fg-dim); font-variant-numeric: tabular-nums; }

  /* ── MOTION (muted) ─────────────────────────── */
  .reveal { opacity: 0; transform: translateY(6px);
            animation: reveal 0.55s cubic-bezier(0.22,0.8,0.22,1) forwards; }
  .r1 { animation-delay: 0.00s; }
  .r2 { animation-delay: 0.08s; }
  .r3 { animation-delay: 0.16s; }
  .r4 { animation-delay: 0.24s; }
  .r5 { animation-delay: 0.32s; }
  .r6 { animation-delay: 0.40s; }
  .r7 { animation-delay: 0.48s; }
  @keyframes reveal { to { opacity: 1; transform: none; } }

  /* ── RESPONSIVE ─────────────────────────────── */
  @media (max-width: 1100px) {
    .metrics { grid-template-columns: repeat(2, 1fr); }
    .metric { border-right: none; border-bottom: 1px solid var(--border-soft); }
    .grid-3, .grid-2 { grid-template-columns: 1fr; }
    .mini-strip { grid-template-columns: repeat(3, 1fr); }
    .handles { grid-template-columns: 1fr; }
    .topbar { grid-template-columns: 1fr; }
    .compliance { justify-content: flex-start; }
    .meta-right { justify-content: flex-start; }
  }

  /* ── FORECAST PANEL ─────────────────────────── */
  .forecast-head {
    display: grid; grid-template-columns: 1fr auto; gap: 18px;
    align-items: baseline; margin-bottom: 18px;
  }
  .forecast-basis {
    font: 400 11px var(--mono);
    color: var(--fg-faint); letter-spacing: 0.01em;
    line-height: 1.7;
  }
  .forecast-basis b { color: var(--fg-dim); font-weight: 500; }
  .forecast-slider-wrap {
    display: flex; align-items: center; gap: 14px;
    padding: 14px 16px; margin-bottom: 18px;
    background: var(--surface-2); border: 1px solid var(--border-soft);
    border-radius: var(--r-md);
  }
  .forecast-slider-wrap label {
    font: 500 11px var(--mono);
    color: var(--fg-faint); letter-spacing: 0.08em;
    text-transform: uppercase;
  }
  .forecast-slider-wrap input[type=range] {
    flex: 1; accent-color: var(--accent);
    height: 4px;
  }
  .forecast-slider-wrap .t-now {
    font: 600 16px var(--mono);
    color: var(--accent); min-width: 60px; text-align: right;
    font-variant-numeric: tabular-nums;
  }
  .forecast-cards {
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px;
  }
  .f-card {
    position: relative;
    padding: 18px 18px 16px;
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: var(--r-md);
    transition: border-color 0.15s;
  }
  .f-card .appr {
    font: 500 10px var(--mono);
    letter-spacing: 0.12em; text-transform: uppercase;
    color: var(--fg-faint);
    margin-bottom: 10px;
  }
  .f-card .count {
    font-weight: 600; font-size: 28px; line-height: 1.0;
    color: var(--fg); letter-spacing: -0.02em;
    font-variant-numeric: tabular-nums;
  }
  .f-card .count .unit {
    font-size: 12px; color: var(--fg-faint);
    font-weight: 400; margin-left: 4px;
    letter-spacing: 0;
  }
  .f-card .ratio {
    font: 400 11px var(--mono);
    color: var(--fg-dim); margin-top: 8px;
  }
  .f-card .ratio .label {
    color: var(--fg-faint); margin-right: 6px;
  }
  .f-card .signal {
    position: absolute; top: 16px; right: 16px;
    display: flex; align-items: center; gap: 6px;
    font: 500 10px var(--mono);
    letter-spacing: 0.08em; text-transform: uppercase;
  }
  .f-card .signal .dot {
    width: 10px; height: 10px; border-radius: 50%;
    background: var(--fg-mute);
  }
  .f-card.sig-green { border-color: rgba(127, 168, 137, 0.45); }
  .f-card.sig-green .signal { color: #7FA889; }
  .f-card.sig-green .signal .dot {
    background: #7FA889;
    box-shadow: 0 0 6px rgba(127,168,137,0.6);
  }
  .f-card.sig-yellow { border-color: rgba(232, 180, 100, 0.45); }
  .f-card.sig-yellow .signal { color: var(--accent); }
  .f-card.sig-yellow .signal .dot {
    background: var(--accent);
    box-shadow: 0 0 6px rgba(232,180,100,0.7);
  }
  .f-card.sig-red { border-color: rgba(214, 143, 107, 0.55); }
  .f-card.sig-red .signal { color: #E46F6F; }
  .f-card.sig-red .signal .dot {
    background: #E46F6F;
    box-shadow: 0 0 8px rgba(228,111,111,0.7);
  }
  .f-card.sig-gray .signal { color: var(--fg-mute); }

  @media (max-width: 1100px) {
    .forecast-cards { grid-template-columns: repeat(2, 1fr); }
  }
</style></head>
<body>

<div class="page">

  <!-- ── TOPBAR ─────────────────────────────── -->
  <header class="topbar reveal r1">
    <div class="brand">
      <div class="logo" aria-hidden="true"></div>
      <h1>
        Traffic Ops
        <span class="sep">/</span>
        <span class="site">SITE-001 · Wadi Saqra · Amman</span>
      </h1>
    </div>

    <div class="compliance" aria-label="§6.1 CCTV input compliance">
      <span class="chip" id="chip-cam"><span class="dot"></span><span id="chip-cam-val">1 view · /site1</span></span>
      <span class="chip" id="chip-proto"><span class="dot"></span><span id="chip-proto-val">—</span></span>
      <span class="chip" id="chip-codec"><span class="dot"></span><span id="chip-codec-val">—</span></span>
      <span class="chip" id="chip-res"><span class="dot"></span><span id="chip-res-val">—</span></span>
      <span class="chip" id="chip-fps"><span class="dot"></span><span id="chip-fps-val">—</span></span>
    </div>

    <div class="meta-right">
      <a href="/signal-timing" class="nav-link" aria-label="Open signal-timing simulator">Signal Timing →</a>
      <span class="live-pill" id="liveBadge"><span class="pulse"></span>LIVE</span>
      <time id="masthead-date">—</time>
    </div>
  </header>

  <!-- ── HERO METRICS ───────────────────────── -->
  <section class="metrics reveal r2" aria-label="Live metrics">
    <div class="metric">
      <div class="label">Active tracks</div>
      <div class="value" id="hActive">—</div>
      <div class="sub">Vehicles observed</div>
    </div>
    <div class="metric accent">
      <div class="label">Volume · 24h</div>
      <div class="value" id="hTotal">—</div>
      <div class="sub">Aggregated count</div>
    </div>
    <div class="metric">
      <div class="label">Peak hour</div>
      <div class="value" id="hPeak">—</div>
      <div class="sub">at <span id="hPeakHour">—</span> local</div>
    </div>
    <div class="metric">
      <div class="label">Crossings · live</div>
      <div class="value" id="hCross">0</div>
      <div class="sub">N/S/E/W combined</div>
    </div>
    <div class="metric">
      <div class="label">Inference p50</div>
      <div class="value" id="hFps">—</div>
      <div class="sub">ms per frame</div>
    </div>
  </section>

  <!-- ── FEED ───────────────────────────────── -->
  <section class="feed reveal r3" aria-label="Live feeds">
    <div class="mini-strip" id="miniStrip">
      <button class="mini" data-src="live" aria-pressed="true">
        <img id="miniLive" class="mini-media" src="/thumb.jpg?ts=0" alt="live">
        <span class="mini-label"><span class="mini-live-dot"></span>LIVE · RTSP</span>
      </button>
    </div>

    <div class="stage">
      <img id="mainImg" class="stage-media"
           src="/thumb.jpg?ts=0" alt="AI annotated live stream">
      <video id="mainVid" class="stage-media" style="display:none"
             muted loop playsinline autoplay preload="auto"
             disablepictureinpicture controlslist="nodownload noplaybackrate"></video>
      <div class="stage-chrome">
        <span class="stage-tag"><span class="dot"></span><span id="stageTag">AI · LIVE</span></span>
        <div class="stage-right">
          <button class="ai-toggle" id="aiToggle" aria-pressed="false" type="button">
            <span class="ai-sw"><span class="ai-knob"></span></span>
            <span class="ai-lbl">AI <b id="aiState">OFF</b></span>
          </button>
          <span class="stage-meta" id="streamMeta">1920×1080 · 10 fps · YOLO26 + BoT-SORT</span>
        </div>
      </div>
    </div>

    <nav class="endpoint-strip">
      <a id="rtspLink" href="#">rtsp://localhost:8554/site1</a>
      <a href="http://localhost:8888/site1/index.m3u8" target="_blank">:8888 / hls</a>
      <a href="/ai-thumb.jpg" target="_blank">:8000 / ai-thumb</a>
      <a href="/calibrate">/ calibrate</a>
    </nav>
  </section>

  <!-- ── CHARTS + ENDPOINTS ─────────────────── -->
  <section class="grid-3 reveal r4">
    <div class="panel">
      <div class="panel-title">
        <h2>Hourly throughput</h2>
        <span class="hint" id="chartMeta">—</span>
      </div>
      <div class="chart-wrap"><canvas id="chart"></canvas></div>
      <div class="chart-meta">
        <div><div class="k">Date</div><div class="v" id="chartDate">—</div></div>
        <div><div class="k">Detectors</div><div class="v" id="chartDet">—</div></div>
        <div><div class="k">Volume</div><div class="v accent" id="chartTot">—</div></div>
      </div>
    </div>

    <div class="panel">
      <div class="panel-title">
        <h2>Approach crossings</h2>
        <span class="hint" id="approachMeta">live</span>
      </div>
      <div id="approachList">
        <div class="approach" data-a="N"><span class="a">N</span><span class="track"><span class="fill" id="barN" style="width:0%"></span></span><span class="n" id="cN">0</span></div>
        <div class="approach" data-a="S"><span class="a">S</span><span class="track"><span class="fill" id="barS" style="width:0%"></span></span><span class="n" id="cS">0</span></div>
        <div class="approach" data-a="E"><span class="a">E</span><span class="track"><span class="fill" id="barE" style="width:0%"></span></span><span class="n" id="cE">0</span></div>
        <div class="approach" data-a="W"><span class="a">W</span><span class="track"><span class="fill" id="barW" style="width:0%"></span></span><span class="n" id="cW">0</span></div>
      </div>
    </div>

    <div class="panel">
      <div class="panel-title">
        <h2>Endpoints</h2>
        <span class="hint">localhost</span>
      </div>
      <div class="handles">
        <div class="handle"><b>UI</b><a href="http://localhost:8000/" target="_blank">:8000 dashboard</a></div>
        <div class="handle"><b>AI</b><a href="http://localhost:8081/" target="_blank">:8081 mjpeg</a></div>
        <div class="handle"><b>RTSP</b><a href="#" id="h-rtsp">:8554 stream</a></div>
        <div class="handle"><b>HLS</b><a href="http://localhost:8888/site1/index.m3u8" target="_blank">:8888 site1</a></div>
        <div class="handle"><b>Ctl</b><a href="http://localhost:9997/v3/paths/list" target="_blank">:9997 mediamtx</a></div>
        <div class="handle"><b>Cvat</b><a href="http://localhost:8080" target="_blank">:8080 annotate</a></div>
        <div class="handle"><b>Calib</b><a href="/calibrate">/calibrate</a></div>
        <div class="handle"><b>Verify</b><code>make sandbox-verify</code></div>
      </div>
    </div>
  </section>

  <!-- ── TRAFFIC FORECAST ───────────────────── -->
  <section class="panel reveal r5" style="margin-bottom: 24px;">
    <div class="forecast-head">
      <div>
        <h2 style="font-weight:500; font-size:13px; letter-spacing:-0.005em; margin-bottom:6px;">Traffic forecast · typical Sunday</h2>
        <div class="forecast-basis">
          Anchor observation: <b id="fAnchor">—</b>
          &nbsp;·&nbsp; Profile: Google typical-day curve at <b id="fSite">SITE-GMAPS</b>
          &nbsp;·&nbsp; Algorithm: BPR-scaled with 4× jam cap
        </div>
      </div>
      <span class="hint" style="font: 500 11px var(--mono); color: var(--fg-faint); letter-spacing: 0.02em;">/api/forecast</span>
    </div>

    <div class="forecast-slider-wrap">
      <label for="fSlider">Time</label>
      <input type="range" id="fSlider" min="0" max="47" value="34" step="1">
      <span class="t-now" id="fTime">17:00</span>
    </div>

    <div class="forecast-cards" id="fCards">
      <div class="f-card sig-gray" data-approach="N">
        <div class="appr">North</div>
        <div class="count"><span class="num" id="fN">—</span><span class="unit">veh</span></div>
        <div class="ratio"><span class="label">ratio</span><span id="fRatioN">—</span></div>
        <div class="signal"><span class="dot"></span><span id="fLabelN">—</span></div>
      </div>
      <div class="f-card sig-gray" data-approach="S">
        <div class="appr">South</div>
        <div class="count"><span class="num" id="fS">—</span><span class="unit">veh</span></div>
        <div class="ratio"><span class="label">ratio</span><span id="fRatioS">—</span></div>
        <div class="signal"><span class="dot"></span><span id="fLabelS">—</span></div>
      </div>
      <div class="f-card sig-gray" data-approach="E">
        <div class="appr">East</div>
        <div class="count"><span class="num" id="fE">—</span><span class="unit">veh</span></div>
        <div class="ratio"><span class="label">ratio</span><span id="fRatioE">—</span></div>
        <div class="signal"><span class="dot"></span><span id="fLabelE">—</span></div>
      </div>
      <div class="f-card sig-gray" data-approach="W">
        <div class="appr">West</div>
        <div class="count"><span class="num" id="fW">—</span><span class="unit">veh</span></div>
        <div class="ratio"><span class="label">ratio</span><span id="fRatioW">—</span></div>
        <div class="signal"><span class="dot"></span><span id="fLabelW">—</span></div>
      </div>
    </div>
  </section>

  <!-- ── AI EVENT LOG ───────────────────────── -->
  <section class="panel reveal r6" style="margin-bottom: 24px;">
    <div class="panel-title">
      <h2>AI events</h2>
      <span class="hint">last 20 · phase2.ndjson</span>
    </div>
    <div class="log" id="logPhase2"></div>
  </section>

  <!-- ── FOOTER ─────────────────────────────── -->
  <footer class="foot reveal r7">
    <div>
      Traffic Ops
      <span class="sep">/</span>
      Phase 1 Sandbox
      <span class="sep">/</span>
      Hackathon 2026
    </div>
    <div class="right"><time id="localClock">—</time></div>
  </footer>

</div>

<script>
'use strict';
const el = id => document.getElementById(id);
const RTSP_URL = 'rtsp://localhost:8554/site1';

// ── Clock ─────────────────────────────────────
const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
function pad2(n) { return String(n).padStart(2, '0'); }
function tickClock() {
  const d = new Date();
  const time = pad2(d.getHours()) + ':' + pad2(d.getMinutes()) + ':' + pad2(d.getSeconds());
  el('masthead-date').textContent = pad2(d.getDate()) + ' ' + MONTHS[d.getMonth()] + ' ' + d.getFullYear() + '  ·  ' + time;
  el('localClock').textContent = time;
}
setInterval(tickClock, 1000); tickClock();

// ── RTSP copy ─────────────────────────────────
[el('rtspLink'), el('h-rtsp')].forEach(a => {
  if (!a) return;
  a.addEventListener('click', e => {
    e.preventDefault();
    try { navigator.clipboard.writeText(RTSP_URL); } catch(_) {}
    const orig = a.textContent;
    a.textContent = 'copied';
    a.style.color = 'var(--accent)';
    setTimeout(() => { a.textContent = orig; a.style.color = ''; }, 1100);
  });
});

// ── LIVE mini snapshot refresh ────────────────
setInterval(() => { const m = el('miniLive'); if (m) m.src = '/thumb.jpg?ts=' + Date.now(); }, 2000);

// ── Mini strip + main stage ──────────────────
const miniStrip = el('miniStrip');
const mainImg   = el('mainImg');
const mainVid   = el('mainVid');
const stageTag  = el('stageTag');
const streamMeta = el('streamMeta');
let activeSrc = 'live';

// LIVE AI via snapshot polling — MJPEG multipart breaks Chromium in this VM
let _aiPoll = null;
function stopMjpeg() {
  if (_aiPoll) { clearInterval(_aiPoll); _aiPoll = null; }
  if (mainImg.src) { mainImg.removeAttribute('src'); try { mainImg.src = ''; } catch(_) {} }
}
function startMjpeg() {
  mainImg.style.display = '';
  mainVid.style.display = 'none';
  try { mainVid.pause(); } catch(_) {}
  mainVid.removeAttribute('src'); try { mainVid.load(); } catch(_) {}
  if (_aiPoll) clearInterval(_aiPoll);
  const tick = () => { mainImg.src = '/ai-thumb.jpg?ts=' + Date.now(); };
  tick();
  _aiPoll = setInterval(tick, 400);
}
// No MP4 playback — Chrome in this VM SIGILLs on any <video> element.
// All cams render via <img>: LIVE = MJPEG (image stream), angles = hi-res poster.
function stopMp4() {
  try { mainVid.pause(); } catch(_) {}
  mainVid.removeAttribute('src'); try { mainVid.load(); } catch(_) {}
  mainVid.style.display = 'none';
}
function showPoster(url) {
  stopMp4(); stopMjpeg();
  mainImg.style.display = '';
  if (url) mainImg.src = url;
}
function showThumb() {
  stopMp4(); stopMjpeg();
  mainImg.style.display = '';
  mainImg.src = '/thumb.jpg?ts=' + Date.now();
}

// AI master toggle — affects every cam. Default OFF so MJPEG doesn't autoload
// on first paint (heavy stream can crash Chromium-in-VM tabs). User clicks to engage.
let aiOn = false;
const aiToggleBtn = el('aiToggle');
const aiStateLbl  = el('aiState');

// Cam registry: { src: {label, raw_url, ai_url, is_live} }
const cams = { live: { label: 'LIVE', is_live: true } };
let activeCamSrc = 'live';

function applyCam(src) {
  activeCamSrc = src;
  const c = cams[src] || cams.live;
  document.querySelectorAll('.mini').forEach(m => {
    m.setAttribute('aria-pressed', m.dataset.src === src ? 'true' : 'false');
  });
  if (c.is_live) {
    stageTag.textContent = (aiOn ? 'AI · LIVE' : 'LIVE · RAW');
    streamMeta.textContent = aiOn ? 'snapshot · YOLO26 · BoT-SORT · 400ms' : 'RTSP snapshot · refresh 2s';
    if (aiOn) startMjpeg(); else showThumb();
  } else {
    stageTag.textContent = (aiOn ? 'AI · ' : 'RAW · ') + (c.label || src).toUpperCase();
    streamMeta.textContent = aiOn ? 'annotated · YOLO26 + BoT-SORT · looping' : 'raw · looping';
    // AI ON: annotated WebP. AI OFF: raw WebP (no boxes).
    const url = aiOn
      ? (c.anim_url || c.poster_url)
      : (c.raw_anim_url || c.raw_poster_url || c.poster_url);
    showPoster(url);
  }
}
function selectMini(src) { applyCam(src); }

aiToggleBtn.addEventListener('click', () => {
  aiOn = !aiOn;
  aiToggleBtn.setAttribute('aria-pressed', aiOn ? 'true' : 'false');
  aiStateLbl.textContent = aiOn ? 'ON' : 'OFF';
  applyCam(activeCamSrc);
});

// Thumbnail refresher for LIVE view when AI is off
setInterval(() => {
  if (activeCamSrc === 'live' && !aiOn) mainImg.src = '/thumb.jpg?ts=' + Date.now();
}, 2000);

document.querySelector('.mini[data-src="live"]').addEventListener('click', () => selectMini('live'));

async function loadVideos() {
  try {
    const resp = await fetch('/api/videos');
    const data = await resp.json();
    const videos = (data.videos || []).filter(v => v.has_ai);
    for (const v of videos) {
      cams[v.name] = {
        label: v.label, raw_url: v.url, ai_url: v.ai_url,
        poster_url: v.poster_url, anim_url: v.anim_url,
        raw_poster_url: v.raw_poster_url, raw_anim_url: v.raw_anim_url,
        is_live: false,
      };

      const mini = document.createElement('button');
      mini.className = 'mini';
      mini.dataset.src = v.name;
      mini.setAttribute('aria-pressed', 'false');
      mini.title = v.label + '  ·  ' + (v.size / 1e6).toFixed(1) + ' MB';

      // Static poster — avoids 5 concurrent H.264 decoders in the browser tab.
      const media = document.createElement('img');
      media.className = 'mini-media';
      media.alt = v.label;
      media.loading = 'lazy';
      media.src = v.poster_url || v.ai_url;  // fallback to ai_url if poster gen failed
      media.addEventListener('error', () => { media.style.opacity = '0.2'; });

      const label = document.createElement('span');
      label.className = 'mini-label';
      label.textContent = v.label;

      mini.append(media, label);
      mini.addEventListener('click', () => selectMini(v.name));
      miniStrip.appendChild(mini);
    }
  } catch(_) {}
}
// Kick off loadVideos unconditionally — even if later setup fails it still fills the mini strip.
(async () => {
  try { await loadVideos(); } catch (_) {}
  try { applyCam('live'); } catch (_) {}
})();

mainImg.addEventListener('error', () => {
  if (activeSrc === 'live') {
    stageTag.textContent = 'LIVE · offline (run make phase2-live-bg)';
  }
});

// ── §6.1 chips ────────────────────────────────
function setChip(id, ok, valText) {
  const c = el(id); if (!c) return;
  c.classList.toggle('ok', !!ok);
  c.classList.toggle('bad', !ok);
  const v = c.querySelector('span:last-child');
  if (v && valText != null) v.textContent = valText;
}
function updateChips(s) {
  setChip('chip-cam', true, '1 view · /site1');
  if (s && !s.error) {
    const isRtsp = (s.url || '').startsWith('rtsp://');
    setChip('chip-proto', isRtsp, isRtsp ? 'rtsp · tcp' : (s.url || '—'));
    const codecOk = s.codec === 'h264' || s.codec === 'hevc';
    setChip('chip-codec', codecOk, codecOk ? (s.codec || '').toUpperCase() : (s.codec || '—'));
    const resOk = s.width === 1920 && s.height === 1080;
    setChip('chip-res', resOk, (s.width || '?') + '×' + (s.height || '?'));
    const fps = s.fps || 0;
    const fpsOk = fps >= 5 && fps <= 15;
    setChip('chip-fps', fpsOk, fps.toFixed(1) + ' fps');
  } else {
    setChip('chip-proto', false, '—');
    setChip('chip-codec', false, '—');
    setChip('chip-res', false, '—');
    setChip('chip-fps', false, '—');
  }
  const live = el('liveBadge');
  live.classList.toggle('off', !s.healthy);
  live.replaceChildren();
  const p = document.createElement('span'); p.className = 'pulse';
  live.append(p, document.createTextNode(s.healthy ? 'LIVE' : 'OFFLINE'));
}

// ── Parsing helpers ───────────────────────────
function safeJson(line) { try { return JSON.parse(line); } catch { return null; } }
function shortTs(iso) { return (iso || '').slice(11, 19); }

// ── Phase 2 event log ────────────────────────
function renderPhase2Log(lines) {
  const c = el('logPhase2'); c.replaceChildren();
  const recent = (lines || []).slice(-20).reverse();
  for (const line of recent) {
    const o = safeJson(line); if (!o) continue;
    const row = document.createElement('div');
    row.className = 'log-row' + (o.event_type === 'stop_line_crossing' ? ' x' : '');
    const ts = document.createElement('span'); ts.className = 'ts';
    ts.textContent = shortTs(o.timestamp);
    const body = document.createElement('span'); body.className = 'body';
    const k = document.createElement('span'); k.className = 'k';
    k.textContent = (o.event_type || 'event');
    body.append(k);
    let tail = '';
    if (o.event_type === 'stop_line_crossing')
      tail = ' ' + o.approach + ' Δ' + o.delta + '  in ' + o.in_count + '  out ' + o.out_count;
    else if (o.event_type === 'zone_occupancy')
      tail = ' ' + (o.name || '') + ' n=' + o.count + ' (was ' + o.prev + ')';
    else if (o.event_type === 'run_start')
      tail = ' model=' + (o.model || '') + ' dev=' + (o.device || '');
    else if (o.event_type === 'run_end')
      tail = ' frames=' + o.frames + ' fps=' + o.fps + ' tracks=' + o.unique_tracks;
    const tailNode = document.createElement('span');
    tailNode.textContent = tail;
    body.append(tailNode);
    row.append(ts, body);
    c.append(row);
  }
}

// ── Approach crossings ───────────────────────
const approachState = { N: 0, S: 0, E: 0, W: 0 };
function updateApproachCounts(p2Lines) {
  const seen = new Set();
  for (let i = p2Lines.length - 1; i >= 0 && seen.size < 4; i--) {
    const o = safeJson(p2Lines[i]);
    if (!o || o.event_type !== 'stop_line_crossing') continue;
    const a = o.approach;
    if (!a || seen.has(a)) continue;
    approachState[a] = (o.in_count || 0) + (o.out_count || 0);
    seen.add(a);
  }
  const apps = ['N','S','E','W'];
  const max = Math.max(1, ...apps.map(a => approachState[a]));
  let topA = apps[0], topV = -1;
  for (const a of apps) if (approachState[a] > topV) { topV = approachState[a]; topA = a; }
  for (const a of apps) {
    el('c' + a).textContent = approachState[a].toLocaleString();
    el('bar' + a).style.width = (approachState[a] / max * 100) + '%';
    const row = document.querySelector('.approach[data-a="' + a + '"]');
    if (row) row.classList.toggle('top', a === topA && approachState[a] > 0);
  }
  const total = approachState.N + approachState.S + approachState.E + approachState.W;
  el('hCross').textContent = total.toLocaleString();
  el('approachMeta').textContent = total ? total.toLocaleString() + ' · live' : 'live';
}

// ── Canvas chart ─────────────────────────────
function drawChart(c) {
  const cv = el('chart'); const ctx = cv.getContext('2d');
  const DPR = window.devicePixelRatio || 1;
  const W = cv.width = cv.clientWidth * DPR;
  const H = cv.height = cv.clientHeight * DPR;
  ctx.clearRect(0, 0, W, H);
  if (!c.hourly || !c.hourly.length) {
    ctx.fillStyle = '#5A616B';
    ctx.font = (12 * DPR) + 'px ui-monospace, monospace';
    ctx.fillText('awaiting data', 8 * DPR, 24 * DPR);
    return;
  }
  const PAD_L = 40 * DPR, PAD_B = 26 * DPR, PAD_T = 12 * DPR, PAD_R = 8 * DPR;
  const plotW = W - PAD_L - PAD_R;
  const plotH = H - PAD_B - PAD_T;
  const max = Math.max(...c.hourly) || 1;
  // gridlines (very quiet)
  ctx.strokeStyle = '#1A1D23'; ctx.lineWidth = 1;
  ctx.beginPath();
  for (let i = 0; i <= 4; i++) {
    const y = Math.round(PAD_T + plotH * i / 4) + 0.5;
    ctx.moveTo(PAD_L, y); ctx.lineTo(W - PAD_R, y);
  }
  ctx.stroke();
  // y axis labels
  ctx.fillStyle = '#5A616B';
  ctx.font = (10 * DPR) + 'px ui-monospace, monospace';
  ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
  for (let i = 0; i <= 4; i++) {
    const v = Math.round(max * (1 - i / 4));
    ctx.fillText(v.toLocaleString(), PAD_L - 8 * DPR, PAD_T + plotH * i / 4);
  }
  // bars — flat amber
  const bw = plotW / 24 * 0.68;
  const gap = plotW / 24 - bw;
  const peak = c.hourly.indexOf(max);
  c.hourly.forEach((v, i) => {
    const h = plotH * v / max;
    const x = PAD_L + i * (plotW / 24) + gap / 2;
    const y = PAD_T + plotH - h;
    ctx.fillStyle = (i === peak) ? '#E8B464' : '#3E444D';
    ctx.fillRect(x, y, bw, h);
  });
  // x axis
  ctx.fillStyle = '#5A616B';
  ctx.textAlign = 'center'; ctx.textBaseline = 'top';
  ctx.font = (10 * DPR) + 'px ui-monospace, monospace';
  [0, 6, 12, 18, 23].forEach(i => {
    const x = PAD_L + i * (plotW / 24) + (plotW / 24) / 2;
    ctx.fillText(pad2(i) + ':00', x, PAD_T + plotH + 6 * DPR);
  });
}

// ── Number counter animation ─────────────────
function animateNumber(node, target) {
  const start = performance.now();
  const duration = 900;
  (function step(now) {
    const t = Math.min(1, (now - start) / duration);
    const e = 1 - Math.pow(1 - t, 3);
    node.textContent = Math.round(target * e).toLocaleString();
    if (t < 1) requestAnimationFrame(step);
  })(start);
}

// ── Poll loop ────────────────────────────────
async function poll() {
  try { updateChips(await fetch('/api/status').then(r => r.json())); } catch(_) {}
  try {
    const c = await fetch('/api/counts').then(r => r.json());
    drawChart(c);
    el('chartDate').textContent = c.date || '—';
    el('chartDet').textContent  = String(c.detectors || 0);
    el('chartTot').textContent  = (c.total || 0).toLocaleString();
    el('chartMeta').textContent = (c.date || '—') + ' · 24h';

    if (!el('hTotal').dataset.done) {
      animateNumber(el('hTotal'), c.total || 0);
      el('hTotal').dataset.done = '1';
    } else {
      el('hTotal').textContent = (c.total || 0).toLocaleString();
    }
    if (c.hourly && c.hourly.length) {
      const pk = Math.max(...c.hourly);
      const pkIdx = c.hourly.indexOf(pk);
      el('hPeak').textContent = pk.toLocaleString();
      el('hPeakHour').textContent = pad2(pkIdx) + ':00';
    }
  } catch(_) {}
  try {
    const p2data = await fetch('/api/phase2').then(r => r.json());
    const p2Lines = p2data.lines || [];
    renderPhase2Log(p2Lines);
    updateApproachCounts(p2Lines);

    let tracks = null, p50 = null;
    for (let i = p2Lines.length - 1; i >= 0; i--) {
      const o = safeJson(p2Lines[i]); if (!o) continue;
      if (o.event_type === 'run_end') {
        tracks = o.unique_tracks;
        p50 = o.latency_ms && o.latency_ms.p50;
        break;
      }
    }
    if (tracks != null && !el('hActive').dataset.done) {
      animateNumber(el('hActive'), tracks); el('hActive').dataset.done = '1';
    } else if (tracks != null) {
      el('hActive').textContent = tracks.toLocaleString();
    }
    if (p50 != null) el('hFps').textContent = p50;
  } catch(_) {}
}
poll(); setInterval(poll, 4000);

// ── Forecast panel ───────────────────────────────────────────────────────
const F_APPR = ['N','S','E','W'];
let forecastRows = null;

function slotToHhmm(idx) {
  const h = String(Math.floor(idx / 2)).padStart(2, '0');
  const m = idx % 2 === 0 ? '00' : '30';
  return h + ':' + m;
}

function renderForecastAt(hhmm) {
  el('fTime').textContent = hhmm;
  if (!forecastRows) return;
  for (const a of F_APPR) {
    const row = forecastRows.find(r => r.time === hhmm && r.approach === a);
    const card = document.querySelector(`.f-card[data-approach="${a}"]`);
    card.classList.remove('sig-green','sig-yellow','sig-red','sig-gray');
    if (!row || row.count == null) {
      card.classList.add('sig-gray');
      el('f' + a).textContent = '—';
      el('fRatio' + a).textContent = '—';
      el('fLabel' + a).textContent = 'no data';
      continue;
    }
    card.classList.add('sig-' + (row.signal || 'gray'));
    el('f' + a).textContent = Math.round(row.count).toLocaleString();
    el('fRatio' + a).textContent = row.ratio.toFixed(2) + '×';
    el('fLabel' + a).textContent = row.label || row.signal;
  }
}

async function loadForecast() {
  try {
    const r = await fetch('/api/forecast');
    const j = await r.json();
    if (!j.available) {
      el('fAnchor').textContent = j.message || 'no forecast available';
      return;
    }
    forecastRows = j.rows;
    const a = j.anchor || {};
    const counts = a.per_approach_count || {};
    el('fAnchor').textContent =
      `T₀ = ${j.t0_hhmm} · ${a.duration_s}s observed · ` +
      F_APPR.map(k => `${k}=${counts[k] ?? '—'}`).join(' ');
    if (j.typical_source) {
      el('fSite').textContent = j.typical_source.split('/').pop();
    }
    const slider = el('fSlider');
    slider.oninput = () => renderForecastAt(slotToHhmm(Number(slider.value)));
    renderForecastAt(slotToHhmm(Number(slider.value)));
  } catch (e) {
    el('fAnchor').textContent = 'forecast endpoint error';
  }
}
loadForecast();
setInterval(loadForecast, 3600 * 1000);

</script>
</body></html>
"""
def _thumb_refresher(rtsp_url: str, stop: threading.Event) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return
    while not stop.is_set():
        tmp = THUMB_PATH.with_suffix(".tmp.jpg")
        try:
            subprocess.run(
                [ffmpeg, "-y", "-loglevel", "error",
                 "-rtsp_transport", "tcp",
                 "-i", rtsp_url,
                 "-vframes", "1", "-q:v", "3", str(tmp)],
                check=True, timeout=8,
            )
            tmp.replace(THUMB_PATH)
        except Exception:
            pass  # stream may be starting / not up
        stop.wait(THUMB_REFRESH_S)


def _latest_counts() -> dict:
    files = sorted(DATA_DIR.glob("detector_counts/counts_*.parquet"))
    if not files:
        return {"date": None, "hourly": [], "detectors": 0, "total": 0}
    latest = files[-1]

    def _compute() -> dict:
        table = pq.read_table(latest)
        df = table.to_pandas()
        df["hour"] = df["timestamp"].dt.hour
        hourly = df.groupby("hour")["vehicle_count"].sum().reindex(range(24), fill_value=0)
        return {
            "date": latest.stem.replace("counts_", ""),
            "hourly": [int(x) for x in hourly.tolist()],
            "detectors": int(df["detector_id"].nunique()),
            "total": int(df["vehicle_count"].sum()),
        }

    return _mtime_cached(f"latest_counts:{latest.name}", [latest], _compute)


def _latest_events(limit: int = 10) -> dict:
    files = sorted(DATA_DIR.glob("signal_logs/signal_*.ndjson"))
    if not files:
        return {"lines": ["(no signal logs)"]}
    latest = files[-1]
    return {"lines": [ln.rstrip() for ln in _tail_lines(latest, limit)]}


def _latest_phase2(limit: int = 10) -> dict:
    """Tail the Phase 2 detect+track ndjson event log."""
    path = DATA_DIR / "events" / "phase2.ndjson"
    if not path.exists():
        return {"lines": ["(no phase2 events yet — run `make phase2-detect`)"]}
    return {"lines": [ln.rstrip() for ln in _tail_lines(path, limit)]}


def _phase2_crossings(window_s: float = 120.0,
                      recent_limit: int = 20) -> dict:
    """Parse phase2.ndjson and return tidy per-approach + per-lane crossing
    data.

    The raw log mixes ``run_start`` / ``zone_occupancy`` / ``stop_line_crossing``
    / ``lane_crossing`` events at per-frame cadence; naive tail-N mostly
    surfaces ``zone_occupancy`` and hides the sparse crossing lines. This
    endpoint parses the whole file (cheap at our scale) and returns only what
    matters for the live dashboard counts.

    Cached on the source file's mtime+size — the dashboard polls this every
    1.5–2.5s, and re-parsing a 15 MB ndjson each hit is wasteful. During a
    live phase2-live-bg run the ndjson grows by ~1 KB/s, so a 500 ms floor
    also caps worst-case recompute QPS.
    """
    path = DATA_DIR / "events" / "phase2.ndjson"
    if not path.exists():
        return {
            "available": False,
            "message": "run `make phase2-live-bg` to generate events",
            "per_approach": {a: {"in": 0, "out": 0} for a in ("N", "S", "E", "W")},
            "recent": [],
            "window_s": window_s,
        }

    def _compute() -> dict:
        return _compute_phase2_crossings(path, window_s, recent_limit)

    return _mtime_cached(
        f"phase2_crossings:{window_s}:{recent_limit}",
        [path], _compute, min_ttl_s=0.5,
    )


def _compute_phase2_crossings(path: Path, window_s: float,
                              recent_limit: int) -> dict:
    last_counters: dict = {a: {"in": 0, "out": 0} for a in ("N", "S", "E", "W")}
    per_lane_totals: dict = {}
    current_occupancy: dict[str, int] = {a: 0 for a in ("N", "S", "E", "W")}
    occupancy_latest_ts: str = ""
    recent_events: list[dict] = []
    last_ts_ns: int = 0
    import datetime as _dt

    def _ts_to_ns(ts: str) -> int | None:
        if not ts.endswith("Z"):
            return None
        try:
            return int(
                _dt.datetime.strptime(ts.replace("Z", "+0000"),
                                      "%Y-%m-%dT%H:%M:%S.%f%z").timestamp()
                * 1_000_000_000)
        except ValueError:
            return None

    for raw in path.read_text().splitlines():
        if not raw.strip():
            continue
        try:
            ev = json.loads(raw)
        except json.JSONDecodeError:
            continue
        etype = ev.get("event_type")
        if etype == "stop_line_crossing":
            a = ev.get("approach")
            if a in last_counters:
                last_counters[a] = {
                    "in":  int(ev.get("in_count",  last_counters[a]["in"])),
                    "out": int(ev.get("out_count", last_counters[a]["out"])),
                }
            recent_events.append(ev)
            ns = _ts_to_ns(ev.get("timestamp", ""))
            if ns: last_ts_ns = max(last_ts_ns, ns)
        elif etype == "lane_crossing":
            lane_id = ev.get("lane_id")
            if lane_id:
                per_lane_totals[lane_id] = {
                    "approach":  ev.get("approach"),
                    "lane_type": ev.get("lane_type"),
                    "lane_idx":  ev.get("lane_idx"),
                    "in":        int(ev.get("in_count", 0)),
                    "out":       int(ev.get("out_count", 0)),
                }
        elif etype == "approach_occupancy":
            a = ev.get("approach")
            if a in current_occupancy:
                current_occupancy[a] = int(ev.get("count", 0))
                occupancy_latest_ts = ev.get("timestamp", "")

    cutoff_ns = last_ts_ns - int(window_s * 1_000_000_000) if last_ts_ns else 0
    window_counts = {a: {"in": 0, "out": 0} for a in ("N", "S", "E", "W")}
    if cutoff_ns:
        for ev in recent_events:
            ns = _ts_to_ns(ev.get("timestamp", ""))
            if ns is None or ns < cutoff_ns:
                continue
            a = ev.get("approach")
            if a not in window_counts:
                continue
            d = int(ev.get("delta", 0))
            if d > 0: window_counts[a]["in"]  += d
            if d < 0: window_counts[a]["out"] += -d

    # Group per-lane totals by approach for the dashboard
    per_approach_lanes: dict = {a: [] for a in ("N", "S", "E", "W")}
    for lane_id, info in per_lane_totals.items():
        a = info.get("approach")
        if a in per_approach_lanes:
            per_approach_lanes[a].append({
                "lane_id":    lane_id,
                "lane_type":  info.get("lane_type"),
                "lane_idx":   info.get("lane_idx"),
                "in":         info["in"],
                "out":        info["out"],
            })
    for a in per_approach_lanes:
        per_approach_lanes[a].sort(key=lambda r: r.get("lane_idx", 0) or 0)

    return {
        "available":           True,
        "per_approach_totals": last_counters,
        "per_approach_window": window_counts,
        "per_approach_lanes":  per_approach_lanes,
        "per_approach_current_occupancy": current_occupancy,
        "occupancy_latest_ts": occupancy_latest_ts,
        "window_s":            window_s,
        "recent":              recent_events[-recent_limit:][::-1],
        "total_events_seen":   len(recent_events),
        "total_lanes_tracked": len(per_lane_totals),
    }


# ── §7.4 ML forecast endpoint ────────────────────────────────────────────
_VIEWER_STARTED_AT_NS: int = 0  # set in main()


def _ml_forecast(target_iso: str | None) -> dict:
    """Run the LightGBM forecaster for a given timestamp (or latest bin).

    Returns the per-detector + per-approach prediction grid for horizons
    +0/+15/+30/+60 min. Empty if the model artefact isn't trained yet.
    """
    bundle = REPO_ROOT / "models" / "forecast_lgb.json"
    counts_dir = DATA_DIR / "detector_counts"
    if not bundle.is_file():
        return {"available": False,
                "message": "model not trained — run `make forecast-ml-train`"}
    try:
        import pandas as pd
        from forecast_ml.predict import predict_at, _read_history
        if target_iso:
            ts = pd.Timestamp(target_iso)
            ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
        else:
            ts = _read_history(counts_dir)["timestamp"].max()
        return predict_at(ts, counts_dir, bundle)
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "message": f"ml predict failed: {exc}"}


# ── §7.6 historical performance ──────────────────────────────────────────
def _history_counts(days: int = 14) -> dict:
    """Aggregate the most recent ``days`` worth of detector counts into a
    per-approach hourly trend (averaged across days). Used by the
    HistoricalPanel on the dashboard."""
    import glob
    files = sorted(glob.glob(str(DATA_DIR / "detector_counts" / "counts_*.parquet")))
    if not files:
        return {"available": False, "message": "no counts yet — run `make synth-all`"}
    files = files[-days:]
    paths = [Path(f) for f in files]

    def _compute() -> dict:
        try:
            import pandas as pd, pyarrow.parquet as pq
            frames = [pq.read_table(f).to_pandas() for f in files]
            df = pd.concat(frames, ignore_index=True)
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
            df["hour"] = df["timestamp"].dt.hour + df["timestamp"].dt.minute / 60.0
            agg = (df.groupby(["approach", "hour"])["vehicle_count"]
                      .mean()
                      .round(2)
                      .reset_index())
            out: dict = {a: [] for a in ("N", "S", "E", "W")}
            for r in agg.itertuples(index=False):
                if r.approach in out:
                    out[r.approach].append({"hour": float(r.hour),
                                            "avg_count": float(r.vehicle_count)})
            for a in out:
                out[a].sort(key=lambda d: d["hour"])
            return {
                "available":  True,
                "days":       len(files),
                "first_date": str(df["timestamp"].min().date()),
                "last_date":  str(df["timestamp"].max().date()),
                "per_approach_hourly": out,
                "total_rows": int(len(df)),
            }
        except Exception as exc:  # noqa: BLE001
            return {"available": False, "message": f"history read failed: {exc}"}

    return _mtime_cached(f"history_counts:{days}", paths, _compute)


# ── §7.6 system health ────────────────────────────────────────────────────
def _health() -> dict:
    """Aggregate live system indicators: RTSP probe, phase2 process state,
    event-log freshness, viewer uptime, ingest rate."""
    import time
    out: dict = {}
    # Uptime
    if _VIEWER_STARTED_AT_NS:
        out["viewer_uptime_s"] = round((time.monotonic_ns() - _VIEWER_STARTED_AT_NS) / 1e9, 1)

    # Phase2 process
    pid_path = Path("/tmp/traffic-intel-phase2.pid")
    out["phase2_alive"] = False
    if pid_path.exists():
        try:
            pid = int(pid_path.read_text().strip())
            os.kill(pid, 0)  # raises if dead
            out["phase2_alive"] = True
            out["phase2_pid"] = pid
        except (OSError, ValueError):
            pass

    # Phase2 log → recent FPS
    p2_log = Path("/tmp/traffic-intel-phase2.log")
    out["phase2_fps"] = None
    if p2_log.exists():
        try:
            tail = p2_log.read_text().splitlines()[-25:]
            fps_lines = [ln for ln in tail if "fps=" in ln]
            if fps_lines:
                # Format: "[phase2] frame=X det=Y tracks=Z fps=AA.AA lines=N"
                last = fps_lines[-1]
                fps_str = last.split("fps=")[1].split()[0]
                out["phase2_fps"] = round(float(fps_str), 2)
        except Exception:  # noqa: BLE001
            pass

    # Event log freshness
    p2_events = DATA_DIR / "events" / "phase2.ndjson"
    if p2_events.exists():
        try:
            stat = p2_events.stat()
            out["events_age_s"] = round(time.time() - stat.st_mtime, 1)
            out["events_size_bytes"] = stat.st_size
        except OSError:
            pass

    # ffmpeg publisher
    ff_pid = Path("/tmp/traffic-intel-ffmpeg.pid")
    out["ffmpeg_alive"] = False
    if ff_pid.exists():
        try:
            pid = int(ff_pid.read_text().strip())
            os.kill(pid, 0)
            out["ffmpeg_alive"] = True
        except (OSError, ValueError):
            pass

    # RTSP probe (re-use existing helper)
    try:
        out["rtsp"] = _healthy("rtsp://localhost:8554/site1")
    except Exception as exc:  # noqa: BLE001
        out["rtsp"] = {"healthy": False, "error": str(exc)}

    return {"available": True, **out}


def _latest_forecast() -> dict:
    """Read the full-day traffic forecast (48 slots × 4 approaches) written by
    `make forecast-predict`. Empty response if the file is missing."""
    path = DATA_DIR / "forecast" / "forecast_day.json"
    if not path.is_file():
        return {"available": False,
                "message": "run `make forecast-all` to produce a forecast"}

    def _compute() -> dict:
        try:
            data = json.loads(path.read_text())
            data["available"] = True
            return data
        except (OSError, json.JSONDecodeError) as exc:
            return {"available": False, "message": f"forecast read failed: {exc}"}

    return _mtime_cached("latest_forecast", [path], _compute)


def _gmaps_state_now() -> dict:
    """Look up the current Amman-local 30-min slot in the Google typical-day
    curve (data/research/gmaps/typical_*.parquet) and return the congestion
    label + ratio + speed per approach N/S/E/W. This is what drives the
    free/light/heavy/jam display on the live dashboard.
    """
    import glob
    files = sorted(glob.glob(str(DATA_DIR / "research" / "gmaps" /
                                 "typical_*.parquet")))
    if not files:
        return {"available": False,
                "message": "no typical Google data — run make gmaps-typical"}
    latest = files[-1]

    # Parquet is static for the day; cache the parsed frame by mtime, but re-
    # resolve the current 30-min slot on every call since that's trivial.
    def _load_df():
        import pandas as pd
        df = pd.read_parquet(latest)

        def _to_min(s: str) -> int:
            try:
                h, m = s.split(":")
                return int(h) * 60 + int(m)
            except Exception:
                return -1

        df["time_hhmm"] = df["departure_local"].str[11:16]
        df["slot_min"] = df["time_hhmm"].map(_to_min)
        return df

    try:
        import datetime as _dt
        import pandas as pd
        df = _mtime_cached(f"gmaps_df:{latest}", [Path(latest)], _load_df)
        # Compute current Amman local HH:MM, snap to 30-min grid used by the
        # fetch (Amman is UTC+3 year-round).
        amman_now = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=3)
        mm = 0 if amman_now.minute < 30 else 30
        hhmm = f"{amman_now.hour:02d}:{mm:02d}"
        slot = df[df["time_hhmm"] == hhmm]

        def _label(r: float | None) -> str:
            if r is None or (isinstance(r, float) and r != r): return "unknown"
            if r < 1.4:  return "light" if r >= 1.0 else "free"
            if r < 2.4:  return "heavy"
            return "jam"

        target_min = amman_now.hour * 60 + mm

        out: dict = {}
        for appr in ("N", "S", "E", "W"):
            rows = df[(df["corridor"] == appr)
                      & df["congestion_ratio"].notna()]
            if rows.empty:
                out[appr] = {"ratio": None, "speed_kmh": None,
                             "label": "unknown", "street": None,
                             "slot": None}
                continue
            # Nearest slot by absolute minute distance
            rows = rows.copy()
            rows["dist"] = (rows["slot_min"] - target_min).abs()
            r = rows.sort_values("dist").iloc[0]
            ratio = float(r["congestion_ratio"])
            speed = (float(r["speed_kmh"])
                     if "speed_kmh" in r and not pd.isna(r["speed_kmh"]) else None)
            street = (str(r.get("street_name") or "") or None)
            out[appr] = {
                "ratio":     round(ratio, 3),
                "speed_kmh": round(speed, 1) if speed is not None else None,
                "label":     _label(ratio),
                "street":    street,
                "slot":      r["time_hhmm"],
            }
        return {
            "available":     True,
            "source_file":   str(Path(latest).name),
            "amman_hhmm":    hhmm,
            "per_approach":  out,
        }
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "message": f"gmaps read failed: {exc}"}


def _forecast_optimize(t_hhmm: str,
                       green_overrides: dict[int, int] | None = None) -> dict:
    """Run Webster/HCM optimizer for target slot T.
    Returns current-plan evaluation + Webster recommendation as a single JSON."""
    from traffic_intel_sandbox.forecast import optimize as opt

    forecast_path = DATA_DIR / "forecast" / "forecast_day.json"
    site_path = DATA_DIR / "forecast" / "forecast_site.json"
    if not forecast_path.is_file():
        return {"available": False,
                "message": "no forecast; run make forecast-all"}

    forecast = json.loads(forecast_path.read_text())
    lanes = (
        {a["name"]: len(a.get("lanes", []))
         for a in json.loads(site_path.read_text()).get("approaches", [])}
        if site_path.is_file() else {"N": 3, "S": 3, "E": 3, "W": 3}
    )
    inputs = opt._approach_inputs(forecast.get("rows", []), t_hhmm, lanes,
                                  opt.DEFAULT_CORRECTION)
    if not inputs:
        return {"available": False,
                "message": f"no forecast data for T={t_hhmm}"}

    current_green = green_overrides or dict(opt.DEFAULT_GREEN_S)
    current = opt.evaluate(inputs, current_green)
    rec_cycle, rec_green = opt.recommend(inputs)
    rec_eval = opt.evaluate(inputs, rec_green, cycle_s=rec_cycle)

    def _pack(res: "opt.EvalResult", green_map: dict[int, int]) -> dict:
        return {
            "green":    {str(k): v for k, v in green_map.items()},
            "cycle_s":  res.cycle_s,
            "critical_y": res.critical_y,
            "summary":  res.summary,
            "rows":     [r.__dict__ for r in res.rows],
        }

    return {
        "available": True,
        "t":          t_hhmm,
        "correction": opt.DEFAULT_CORRECTION,
        "approach_inputs": {a: {"volume_vph": i.volume_vph, "lanes": i.lanes}
                            for a, i in inputs.items()},
        "current": _pack(current, current_green),
        "webster": _pack(rec_eval, rec_green),
        "delay_reduction_pct": round(
            (current.summary["weighted_avg_delay_s"]
             - rec_eval.summary["weighted_avg_delay_s"])
            / max(1e-6, current.summary["weighted_avg_delay_s"]) * 100, 1),
    }


_HEALTHY_TTL_S = 2.0
_HEALTHY_CACHE: dict[str, tuple[float, dict]] = {}


def _healthy(rtsp_url: str) -> dict:
    # ffprobe is ~55 ms and the dashboard polls this path (directly or via
    # /api/status /api/health) every few seconds. A short TTL cache removes
    # the duplicate probes without hiding a genuinely-down stream for long.
    now = _time.monotonic()
    hit = _HEALTHY_CACHE.get(rtsp_url)
    if hit and (now - hit[0]) < _HEALTHY_TTL_S:
        return hit[1]
    try:
        from traffic_intel_sandbox.rtsp_sim.healthcheck import _probe, evaluate
        info = _probe(rtsp_url)
        report, _failures = evaluate(info)
        report["url"] = rtsp_url
    except Exception as exc:  # noqa: BLE001
        report = {"healthy": False, "error": str(exc)}
    _HEALTHY_CACHE[rtsp_url] = (now, report)
    return report


_VIDEO_LABELS = {
    # Long-form archival
    "amman-wadi-saqra-gardens-brt.mp4": "Wadi Saqra · Gardens + BRT",
    "amman-wadi-saqra-tour.mp4":        "Wadi Saqra · tour",
    "amman-7th-circle-drive.mp4":       "7th Circle · dashcam",
    # Short scenario clips (Veo3 generative)
    "veo3-01-day-light.mp4":            "Veo3 · 01 day light",
    "veo3-02-cctv-request.mp4":         "Veo3 · 02 cctv",
    "veo3-03-car-view.mp4":             "Veo3 · 03 car view",
    # AI-annotated scenario angles (each = a different incident angle)
    "angle_a_gridlock_1419.mp4":           "Angle A · gridlock",
    "angle_b_gridlock_1421.mp4":           "Angle B · gridlock",
    "angle_c_suv_red_1419.mp4":            "Angle C · red runner",
    "angle_d_motorcycle_wrongway_1418.mp4":"Angle D · wrong way",
}


def _find_normalized(name: str) -> Path | None:
    """Look up a normalized MP4 by basename across known subdirs."""
    for candidate in (DATA_DIR / "normalized" / name,
                      DATA_DIR / "normalized" / "scenarios" / name):
        if candidate.is_file():
            return candidate
    return None


def _find_annotated(name: str) -> Path | None:
    """Look up an AI-annotated MP4 by basename across known subdirs."""
    for candidate in (DATA_DIR / "annotated" / "scenarios" / name,
                      DATA_DIR / "annotated" / name):
        if candidate.is_file():
            return candidate
    return None


POSTER_DIR = Path("/tmp/traffic-intel-posters")
ANIM_DIR   = Path("/tmp/traffic-intel-anim")


def _ensure_animated_webp(video_path: Path, webp_path: Path, width: int = 960, fps: int = 10) -> bool:
    """Convert an annotated MP4 to an animated WebP for browser-safe animation
    (bypasses the broken H.264 decoder path on this VM)."""
    if webp_path.exists() and webp_path.stat().st_size > 0:
        return True
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    webp_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [ffmpeg, "-y", "-loglevel", "error",
             "-i", str(video_path),
             "-vf", f"fps={fps},scale={width}:-2:flags=bilinear",
             "-loop", "0",
             "-c:v", "libwebp", "-lossless", "0", "-q:v", "60",
             "-preset", "default", "-an", "-vsync", "0",
             str(webp_path)],
            check=True, timeout=60,
        )
        return webp_path.exists() and webp_path.stat().st_size > 0
    except Exception:
        return False


def _ensure_poster(video_path: Path, poster_path: Path, width: int = 1280) -> bool:
    """Extract a JPEG frame from the middle of the video at full HD width, cache it."""
    if poster_path.exists() and poster_path.stat().st_size > 0:
        return True
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    poster_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        # ~40% into the clip; pick a frame that's likely to have detections on it
        subprocess.run(
            [ffmpeg, "-y", "-loglevel", "error",
             "-ss", "3", "-i", str(video_path),
             "-frames:v", "1", "-vf", f"scale={width}:-2",
             "-q:v", "3", str(poster_path)],
            check=True, timeout=10,
        )
        return poster_path.exists() and poster_path.stat().st_size > 0
    except Exception:
        return False


def _list_videos() -> list[dict]:
    """Only videos that have an AI-annotated counterpart are exposed to the
    dashboard. Posters are static JPEG snapshots for the mini strip (avoids
    running 5 concurrent video decoders in Chromium-on-VM).

    Cached by directory mtimes — the only dynamic bit is ffmpeg poster/webp
    generation, and those functions already short-circuit if output exists.
    """
    search_dirs = [
        (DATA_DIR / "normalized", "archive"),
        (DATA_DIR / "normalized" / "scenarios", "angle"),
    ]
    cache_paths: list[Path] = [d for d, _ in search_dirs if d.is_dir()]

    def _compute() -> list[dict]:
        return _scan_videos(search_dirs)

    if not cache_paths:
        return []
    return _mtime_cached("list_videos", cache_paths, _compute)


def _scan_videos(search_dirs: list[tuple[Path, str]]) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for root, group in search_dirs:
        if not root.is_dir():
            continue
        for p in sorted(root.glob("*.mp4")):
            name = p.name
            if name in seen:
                continue
            ai = _find_annotated(name)
            if not ai:
                continue
            seen.add(name)
            stem = Path(name).stem
            # AI (annotated) + RAW posters/anims — give AI OFF a truly box-free view.
            ai_poster  = POSTER_DIR / f"{stem}.ai.jpg"
            raw_poster = POSTER_DIR / f"{stem}.raw.jpg"
            ai_anim    = ANIM_DIR   / f"{stem}.ai.webp"
            raw_anim   = ANIM_DIR   / f"{stem}.raw.webp"
            has_ai_poster  = _ensure_poster(ai, ai_poster)
            has_raw_poster = _ensure_poster(p,  raw_poster)
            has_ai_anim    = _ensure_animated_webp(ai, ai_anim)
            has_raw_anim   = _ensure_animated_webp(p,  raw_anim)
            out.append({
                "name":            name,
                "label":           _VIDEO_LABELS.get(name, name),
                "group":           group,
                "size":            p.stat().st_size,
                "url":             f"/video/{name}",
                "ai_url":          f"/video-ai/{name}",
                "poster_url":      f"/poster/{stem}.ai.jpg"   if has_ai_poster  else None,
                "raw_poster_url":  f"/poster/{stem}.raw.jpg"  if has_raw_poster else None,
                "anim_url":        f"/animated/{stem}.ai.webp"  if has_ai_anim  else None,
                "raw_anim_url":    f"/animated/{stem}.raw.webp" if has_raw_anim else None,
                "has_ai":          True,
            })
    return out


def _audit_append(ip: str, method: str, path: str, code: int) -> None:
    """Append one request to the audit log, rotating if it exceeds the cap.

    §7.7: structured record so security review can trace every dashboard
    interaction back to source IP + outcome. Rotation is best-effort and
    failures are swallowed — the request itself must not fail because the
    audit log is full.
    """
    try:
        AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        # Simple size-based rotation: when current exceeds cap, move to .1 and restart
        if AUDIT_LOG_PATH.exists() and AUDIT_LOG_PATH.stat().st_size > AUDIT_MAX_BYTES:
            AUDIT_LOG_PATH.replace(AUDIT_LOG_PATH.with_suffix(".log.1"))
        line = json.dumps({
            "ts":     datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "ip":     ip,
            "method": method,
            "path":   path,
            "code":   code,
        })
        with AUDIT_LOG_PATH.open("a") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def _audit_tail(n: int = 200) -> dict:
    if not AUDIT_LOG_PATH.exists():
        return {"available": False, "message": "no audit log yet"}
    try:
        lines = AUDIT_LOG_PATH.read_text().splitlines()[-n:]
        records = []
        for ln in lines:
            try:
                records.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
        return {"available": True, "count": len(records), "records": records}
    except OSError as exc:
        return {"available": False, "message": f"audit read failed: {exc}"}


def _proc_status(pid_file: Path) -> dict:
    """Resolve pid → live process stats. Returns a uniform dict so the
    dashboard can render module cards without per-module branching."""
    out = {"status": "down", "pid": None, "uptime_s": None,
           "cpu_pct": None, "rss_mb": None}
    if not pid_file.is_file():
        return out
    try:
        pid = int(pid_file.read_text().strip())
    except (OSError, ValueError):
        return out
    try:
        os.kill(pid, 0)
    except OSError:
        return out
    out["status"] = "up"
    out["pid"] = pid
    try:
        res = subprocess.run(
            ["ps", "-p", str(pid), "-o", "etimes=,pcpu=,rss="],
            capture_output=True, text=True, timeout=1.5,
        )
        parts = res.stdout.strip().split()
        if len(parts) >= 3:
            out["uptime_s"] = int(parts[0])
            out["cpu_pct"] = float(parts[1])
            out["rss_mb"] = round(int(parts[2]) / 1024, 1)
    except (subprocess.SubprocessError, ValueError):
        pass
    return out


def _tail_log(path: Path, n: int = 1, pattern: str | None = None) -> str:
    """Return the last matching line (or last line) of a log file; empty on miss."""
    try:
        size = path.stat().st_size
    except OSError:
        return ""
    if size == 0:
        return ""
    read_sz = min(size, 32 * 1024)
    with path.open("rb") as fh:
        fh.seek(size - read_sz)
        lines = fh.read().splitlines()
    if pattern:
        lines = [b for b in lines if pattern.encode() in b]
    return lines[-1].decode("utf-8", errors="replace") if lines else ""


def _analysis_throughput(window_min: int = 60, bin_min: int = 1) -> dict:
    """Per-approach stop-line crossings bucketed into 1-minute bins over the
    last `window_min` minutes. Powers the Analysis page's live chart.

    phase2.ndjson is append-only and can get large (50 MB+), so we
    tail-read from the end until we pass the cutoff timestamp.
    """
    import datetime as _dt
    path = DATA_DIR / "events" / "phase2.ndjson"
    if not path.exists():
        return {"available": False,
                "message": "no phase2 events yet — run `make phase2-live-bg`",
                "bins": [], "series": {}}

    window_min = max(1, min(240, window_min))
    bin_min = max(1, min(15, bin_min))

    def _ts_to_ns(ts: str) -> int | None:
        if not ts.endswith("Z"):
            return None
        try:
            return int(
                _dt.datetime.strptime(ts.replace("Z", "+0000"),
                                      "%Y-%m-%dT%H:%M:%S.%f%z").timestamp()
                * 1_000_000_000)
        except ValueError:
            return None

    def _compute() -> dict:
        try:
            size = path.stat().st_size
        except OSError:
            return {"available": False, "message": "stat failed",
                    "bins": [], "series": {}}

        # Find the latest timestamp by reading the very tail
        tail_size = min(size, 16 * 1024)
        with path.open("rb") as fh:
            fh.seek(size - tail_size)
            tail = fh.read().splitlines()
        latest_ns = 0
        for raw in reversed(tail):
            if not raw.strip():
                continue
            try:
                ev = json.loads(raw)
            except json.JSONDecodeError:
                continue
            ns = _ts_to_ns(ev.get("timestamp", ""))
            if ns:
                latest_ns = ns
                break
        if latest_ns == 0:
            return {"available": False, "message": "no parseable timestamps",
                    "bins": [], "series": {}}

        cutoff_ns = latest_ns - window_min * 60 * 1_000_000_000
        bin_ns = bin_min * 60 * 1_000_000_000
        # Number of bins we intend to produce
        n_bins = window_min // bin_min
        bins_edge = [latest_ns - (n_bins - i) * bin_ns for i in range(n_bins + 1)]

        counts = {a: [0] * n_bins for a in ("N", "S", "E", "W")}

        # Stream from end — stop once we pass cutoff by >20% margin
        chunk_size = 512 * 1024
        tail_read = min(size, chunk_size)
        carry = b""
        pos = size - tail_read
        stopped = False
        while not stopped and tail_read > 0:
            with path.open("rb") as fh:
                fh.seek(pos)
                buf = fh.read(tail_read)
            if pos > 0:
                # keep partial first line for next (earlier) chunk
                nl = buf.find(b"\n")
                if nl < 0:
                    carry = buf + carry
                    tail_read = min(pos, chunk_size)
                    pos -= tail_read
                    continue
                head_partial = buf[:nl]
                lines = buf[nl + 1:].split(b"\n") + carry.split(b"\n")
                carry = head_partial
            else:
                lines = buf.split(b"\n") + carry.split(b"\n")
                carry = b""
            stopped = pos == 0
            for raw in reversed(lines):
                if not raw.strip():
                    continue
                try:
                    ev = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if ev.get("event_type") != "stop_line_crossing":
                    continue
                ns = _ts_to_ns(ev.get("timestamp", ""))
                if ns is None or ns < cutoff_ns:
                    stopped = True
                    break
                appr = ev.get("approach")
                if appr not in counts:
                    continue
                bin_idx = int((ns - bins_edge[0]) // bin_ns)
                if 0 <= bin_idx < n_bins:
                    delta = int(ev.get("delta", 1))
                    counts[appr][bin_idx] += max(abs(delta), 1)
            if not stopped:
                tail_read = min(pos, chunk_size)
                pos -= tail_read

        # Bin midpoint labels (HH:MM in Amman local, UTC+3)
        def _fmt(ns: int) -> str:
            secs = ns // 1_000_000_000 + 3 * 3600
            h = (secs // 3600) % 24
            m = (secs // 60) % 60
            return f"{h:02d}:{m:02d}"
        bin_labels = [_fmt(bins_edge[i] + bin_ns // 2) for i in range(n_bins)]

        totals = {a: sum(counts[a]) for a in counts}
        return {
            "available":     True,
            "window_min":    window_min,
            "bin_min":       bin_min,
            "latest_ts":     _fmt(latest_ns),
            "bin_labels":    bin_labels,
            "series":        counts,
            "totals":        totals,
            "grand_total":   sum(totals.values()),
        }

    return _mtime_cached(
        f"analysis_throughput:{window_min}:{bin_min}",
        [path], _compute, min_ttl_s=5.0,
    )


def _incidents() -> dict:
    """Return the clip-manifest verdicts produced by classifier.py. This
    powers the /incidents page — a time-sorted list of every clip the
    classifier has analysed with its predicted tag + confidence."""
    path = DATA_DIR / "labels" / "clips_manifest.json"
    if not path.is_file():
        return {"available": False,
                "message": "no manifest yet — run `make phase2-classify`"}

    def _compute() -> dict:
        try:
            manifest = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            return {"available": False, "message": f"manifest read failed: {exc}"}

        clips = manifest.get("clips", [])
        # Slim each row to what the UI actually renders, and count per-tag.
        tag_counts: dict[str, int] = {}
        rows = []
        for c in clips:
            tag = c.get("predicted_tag") or c.get("tag") or "unknown"
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
            rows.append({
                "clip":         c.get("clip"),
                "tag":          tag,
                "confidence":   c.get("predicted_confidence"),
                "classifier":   c.get("classifier_version"),
                "pass":         c.get("pass_used"),
                "reasons":      c.get("reasons", [])[:4],
                "interpretation": (c.get("interpretation") or [""])[0],
                "line_crossings": c.get("line_crossings") or {},
                "detections":   c.get("detections"),
                "tracks":       c.get("tracks"),
                "frames":       c.get("frames"),
                "artifacts":    c.get("artifacts", {}),
            })
        # Sort: non-normal first (most attention-grabbing), then by clip name
        rows.sort(key=lambda r: (r["tag"] == "normal", r["clip"] or ""))
        return {
            "available":       True,
            "schema":          manifest.get("schema"),
            "intersection_id": manifest.get("intersection_id"),
            "total":           len(rows),
            "tag_counts":      tag_counts,
            "rows":            rows,
        }

    return _mtime_cached("incidents", [path], _compute)


def _architecture() -> dict:
    """Live §7.1 snapshot: modules, storage, data flows, faults, monitoring,
    multi-site readiness. Rendered by the /system page."""
    now = _time.time()

    def _path_stat(p: Path) -> dict:
        try:
            st = p.stat()
            # Prefer cumulative size for directories
            if p.is_dir():
                total = 0
                for child in p.rglob("*"):
                    try:
                        total += child.stat().st_size
                    except OSError:
                        continue
                size = total
            else:
                size = st.st_size
            return {"exists": True, "size_bytes": size,
                    "mtime_age_s": round(now - st.st_mtime, 1)}
        except OSError:
            return {"exists": False, "size_bytes": 0, "mtime_age_s": None}

    # ── Process + module health ───────────────────────────────────────
    pub = _proc_status(Path("/tmp/traffic-intel-ffmpeg.pid"))
    yolo = _proc_status(Path("/tmp/traffic-intel-phase2.pid"))
    gmaps = _proc_status(Path("/tmp/traffic-intel-gmaps.pid"))

    # Latest frame= line from phase2.log for live fps
    yolo_fps = None
    yolo_det = None
    last_fps = _tail_log(Path("/tmp/traffic-intel-phase2.log"),
                         pattern="frame=")
    if "fps=" in last_fps:
        try:
            yolo_fps = round(float(last_fps.split("fps=")[1].split()[0]), 2)
        except (IndexError, ValueError):
            pass
    if "det=" in last_fps:
        try:
            yolo_det = int(last_fps.split("det=")[1].split()[0])
        except (IndexError, ValueError):
            pass

    p2_ndjson = DATA_DIR / "events" / "phase2.ndjson"
    p2_stat = _path_stat(p2_ndjson)

    modules = [
        # Source layer
        {
            "id": "thevideo", "layer": "Source",
            "display": "TheVideo.mp4 (looped)",
            "path": "/home/admin1/TheVideo.mp4",
            "status": "up" if Path("/home/admin1/TheVideo.mp4").is_file() else "down",
            "detail": "H.264 1080p, looped source",
        },
        {
            "id": "counts", "layer": "Source",
            "display": "Detector counts (synth)",
            "path": "data/detector_counts/*.parquet",
            "status": "up" if any((DATA_DIR / "detector_counts").glob("*.parquet")) else "down",
            "detail": f"{len(list((DATA_DIR / 'detector_counts').glob('*.parquet')))} files",
        },
        {
            "id": "signals", "layer": "Source",
            "display": "Signal logs (synth)",
            "path": "data/signal_logs/*.ndjson",
            "status": "up" if any((DATA_DIR / "signal_logs").glob("*.ndjson")) else "down",
            "detail": f"{len(list((DATA_DIR / 'signal_logs').glob('*.ndjson')))} files",
        },
        # Ingest/AI
        {
            "id": "publisher", "layer": "Ingest+AI",
            "display": "FFmpeg → MediaMTX (RTSP)",
            "path": "phase1-sandbox/scripts/publish_loop.sh",
            "status": pub["status"],
            "pid": pub["pid"], "uptime_s": pub["uptime_s"],
            "cpu_pct": pub["cpu_pct"], "rss_mb": pub["rss_mb"],
            "detail": "NVENC · 15 fps → rtsp://localhost:8554/site1",
        },
        {
            "id": "yolo", "layer": "Ingest+AI",
            "display": "YOLO26 + ByteTrack",
            "path": "phase2-feasibility/src/traffic_intel_phase2/detect_track.py",
            "status": yolo["status"],
            "pid": yolo["pid"], "uptime_s": yolo["uptime_s"],
            "cpu_pct": yolo["cpu_pct"], "rss_mb": yolo["rss_mb"],
            "fps": yolo_fps, "detections_last_bin": yolo_det,
            "detail": f"imgsz=640 · fps={yolo_fps or '—'} · det/frame={yolo_det or '—'}",
        },
        {
            "id": "ingest_layer", "layer": "Ingest+AI",
            "display": "Unified ingest (§7.2)",
            "path": "phase2-feasibility/src/traffic_intel_phase2/ingest_layer.py",
            "status": "up" if (DATA_DIR / "ingest_unified.ndjson").is_file() else "idle",
            "detail": f"{_path_stat(DATA_DIR / 'ingest_unified.ndjson')['size_bytes']}B unified, "
                      f"{_path_stat(DATA_DIR / 'ingest_errors.ndjson')['size_bytes']}B errors",
        },
        # Analytics
        {
            "id": "classifier", "layer": "Analytics",
            "display": "Event classifier (§6.6 + §7.3)",
            "path": "phase2-feasibility/src/traffic_intel_phase2/classifier.py",
            "status": "up" if (DATA_DIR / "labels" / "clips_manifest.json").is_file() else "idle",
        },
        {
            "id": "forecast_bpr", "layer": "Analytics",
            "display": "BPR forecast (§7.4 anchor)",
            "path": "phase1-sandbox/src/traffic_intel_sandbox/forecast/predict.py",
            "status": "up" if (DATA_DIR / "forecast" / "forecast_day.json").is_file() else "idle",
        },
        {
            "id": "forecast_ml", "layer": "Analytics",
            "display": "LightGBM forecast (§7.4)",
            "path": "phase3-fullstack/src/forecast_ml/predict.py",
            "status": "up" if (REPO_ROOT / "models" / "forecast_lgb.json").is_file() else "idle",
        },
        {
            "id": "optimizer", "layer": "Analytics",
            "display": "Webster + HCM (§7.5, §8.3)",
            "path": "phase1-sandbox/src/traffic_intel_sandbox/forecast/optimize.py",
            "status": "up",
        },
        {
            "id": "gmaps", "layer": "Analytics",
            "display": "Google Routes poller",
            "path": "traffic_intel_sandbox.ingest.gmaps",
            "status": gmaps["status"] if gmaps["pid"] else "idle",
            "pid": gmaps["pid"],
            "detail": "typical-day data cached" if any(
                (DATA_DIR / "research" / "gmaps").glob("typical_*.parquet")) else "no data",
        },
        # Dashboard
        {
            "id": "viewer", "layer": "Dashboard",
            "display": "viewer.py (BaseHTTP)",
            "path": "phase1-sandbox/src/traffic_intel_sandbox/viewer.py",
            "status": "up",
            "uptime_s": round((_time.monotonic_ns() - _VIEWER_STARTED_AT_NS) / 1e9, 0)
                       if _VIEWER_STARTED_AT_NS else None,
            "detail": "12 JSON endpoints · gzip+ETag enabled",
        },
        {
            "id": "spa", "layer": "Dashboard",
            "display": "React + Vite SPA",
            "path": "frontend/dist/",
            "status": "up" if FRONTEND_DIST.is_dir() else "down",
            "detail": f"{len(list(FRONTEND_DIST.glob('assets/*')))} chunks, "
                      f"{sum(p.stat().st_size for p in FRONTEND_DIST.glob('assets/*'))} B",
        },
    ]

    # ── Storage layer rows (matches architecture.md table) ─────────────
    storage_spec = [
        ("Replay video", "/home/admin1/TheVideo.mp4", "MP4", "6.1"),
        ("Detector counts", str(DATA_DIR / "detector_counts"), "Parquet", "6.3"),
        ("Signal logs", str(DATA_DIR / "signal_logs"), "NDJSON", "6.4"),
        ("Live AI events", str(DATA_DIR / "events" / "phase2.ndjson"), "NDJSON", "7.3"),
        ("Incident snapshots", str(DATA_DIR / "incidents"), "JPEG", "7.3"),
        ("Forecast outputs", str(DATA_DIR / "forecast" / "forecast_day.json"), "JSON", "7.4"),
        ("Google typical", str(DATA_DIR / "research" / "gmaps"), "Parquet", "7.4"),
        ("Clips manifest", str(DATA_DIR / "labels" / "clips_manifest.json"), "JSON", "6.6"),
        ("Audit log", str(AUDIT_LOG_PATH), "NDJSON", "7.7"),
        ("Ingest errors", str(DATA_DIR / "ingest_errors.ndjson"), "NDJSON", "7.2"),
        ("ML model", str(REPO_ROOT / "models" / "forecast_lgb.json"), "LightGBM", "7.4"),
        ("Site metadata", "phase1-sandbox/src/traffic_intel_sandbox/metadata/site1.example.json",
         "JSON-Schema", "6.5"),
    ]
    storage = []
    for name, path, fmt, section in storage_spec:
        p = Path(path)
        stats = _path_stat(p)
        storage.append({
            "name": name, "path": path, "format": fmt, "section": section,
            **stats,
        })

    # ── Data flows (live throughput where measurable) ─────────────────
    flows = [
        {
            "id": "F1", "name": "Live AI loop",
            "from": "TheVideo.mp4", "to": "phase2.ndjson",
            "throughput": f"15 fps RTSP → {yolo_fps or '—'} fps YOLO → events.ndjson ({p2_stat['size_bytes']//1024} KB)",
            "healthy": pub["status"] == "up" and yolo["status"] == "up",
        },
        {
            "id": "F2", "name": "Forecast loop",
            "from": "detector_counts + gmaps", "to": "/api/forecast{,ml,optimize}",
            "throughput": "day JSON regenerated on `make forecast-all`",
            "healthy": (DATA_DIR / "forecast" / "forecast_day.json").is_file(),
        },
        {
            "id": "F3", "name": "Incident loop",
            "from": "phase2.ndjson", "to": "clips_manifest.json + incidents/*.jpg",
            "throughput": "rule-based + motion-check classifier",
            "healthy": (DATA_DIR / "labels" / "clips_manifest.json").is_file(),
        },
    ]

    # ── Fault-handling paths (from architecture.md) ───────────────────
    # Counter reads are derived from on-disk state — we don't yet track
    # in-process fire counts for most paths.
    ingest_errors_size = _path_stat(DATA_DIR / "ingest_errors.ndjson")["size_bytes"]
    faults = [
        {"name": "RTSP connection drop",
         "mitigation": "phase2 auto-reconnect, UI badge flips off",
         "active": pub["status"] != "up"},
        {"name": "YOLO model load fail",
         "mitigation": "process exits; operator re-runs make phase2-live-bg",
         "active": yolo["status"] != "up" and yolo["pid"] is None},
        {"name": "Malformed event in phase2.ndjson",
         "mitigation": "tolerant line-skip in _phase2_crossings()",
         "active": False},
        {"name": "Missing forecast slot",
         "mitigation": "nearest-slot fallback in _gmaps_state_now()",
         "active": False},
        {"name": "Optimiser oversaturation (Y≥1)",
         "mitigation": "webster_cycle() clamps to C_MAX=120s",
         "active": False},
        {"name": "Snapshot JPG missing",
         "mitigation": "/ai-thumb.jpg 503; SPA shows stale tag",
         "active": not Path("/tmp/traffic-intel-phase2-latest.jpg").is_file()},
        {"name": "Ingest schema violation",
         "mitigation": "divert to data/ingest_errors.ndjson",
         "active": ingest_errors_size > 0},
        {"name": "ML model file missing",
         "mitigation": "fall back to BPR forecast; UI labels source",
         "active": not (REPO_ROOT / "models" / "forecast_lgb.json").is_file()},
        {"name": "Homography lock fail",
         "mitigation": "smoothed identity H, never crashes",
         "active": False},
    ]

    # ── Monitoring paths ──────────────────────────────────────────────
    monitoring = {
        "endpoints": [
            "/api/health", "/api/status", "/api/audit",
            "/api/phase2", "/api/phase2/crossings",
        ],
        "logs": [
            {"path": "/tmp/traffic-intel-viewer.log",
             **_path_stat(Path("/tmp/traffic-intel-viewer.log"))},
            {"path": "/tmp/traffic-intel-phase2.log",
             **_path_stat(Path("/tmp/traffic-intel-phase2.log"))},
            {"path": "/tmp/traffic-intel-ffmpeg.log",
             **_path_stat(Path("/tmp/traffic-intel-ffmpeg.log"))},
            {"path": "/tmp/traffic-intel-gmaps.log",
             **_path_stat(Path("/tmp/traffic-intel-gmaps.log"))},
        ],
        "freshness": {
            "phase2_events_ndjson_age_s": p2_stat["mtime_age_s"],
            "audit_log_age_s": _path_stat(AUDIT_LOG_PATH)["mtime_age_s"],
        },
    }

    # ── Multi-site readiness ──────────────────────────────────────────
    multi_site = {
        "current_sites": ["SITE1"],
        "readiness": [
            {"dimension": "intersection_id keying",
             "ready": True, "note": "all events + parquets carry it"},
            {"dimension": "Per-site RTSP path",
             "ready": True, "note": "MediaMTX supports /site<N> paths"},
            {"dimension": "Per-site detector process",
             "ready": True, "note": "one detect_track per site"},
            {"dimension": "Per-site ML model",
             "ready": True, "note": "models/forecast_lgb_<site>.json"},
            {"dimension": "Per-site Google corridors",
             "ready": True, "note": "gmaps_routes.yml per site"},
            {"dimension": "Dashboard site selector",
             "ready": False, "note": "not yet wired — SPA pinned to SITE1"},
            {"dimension": "Storage partitioning",
             "ready": False, "note": "data/sites/<site_id>/ layout not adopted"},
        ],
    }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "site_id": "SITE1",
        "modules": modules,
        "storage": storage,
        "flows": flows,
        "faults": faults,
        "monitoring": monitoring,
        "multi_site": multi_site,
    }


def _auth_token_required() -> str | None:
    """Return the expected bearer token, or None when auth is disabled.

    We deliberately don't auto-generate a token — if ``DASHBOARD_TOKEN`` is
    not set the server behaves exactly as it did in Phase 1 (read-only GET
    endpoints, no writeable endpoints reachable). Setting the env var turns
    on auth for every future POST.
    """
    tok = os.environ.get("DASHBOARD_TOKEN")
    return tok if tok else None


def _handler(rtsp_url: str):
    class H(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args): pass   # quiet access log

        def log_request(self, code="-", size="-"):
            # §7.7 audit: every response flows through send_response(), which
            # calls log_request(code). We piggy-back the audit line here so
            # coverage is automatic — no wrapper needed per endpoint.
            try:
                code_int = int(code)
            except (TypeError, ValueError):
                code_int = 0
            _audit_append(self.client_address[0], self.command or "-", self.path, code_int)

        def _audit(self, code: int) -> None:
            _audit_append(self.client_address[0], self.command, self.path, code)

        def _json(self, obj: dict, code: int = 200, *,
                  etag: str | None = None,
                  cache_max_age: int = 0) -> None:
            # Conditional GET — short-circuit before we spend any bytes.
            if etag and self.headers.get("If-None-Match", "") == etag:
                self.send_response(304)
                self.send_header("ETag", etag)
                if cache_max_age:
                    self.send_header("Cache-Control",
                                     f"public, max-age={cache_max_age}")
                self.end_headers()
                return

            body = json.dumps(obj, separators=(",", ":")).encode()
            accept = self.headers.get("Accept-Encoding", "")
            use_gz = "gzip" in accept and len(body) >= 1024
            if use_gz:
                body = _gz.compress(body, compresslevel=6, mtime=0)

            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Vary", "Accept-Encoding")
            if use_gz:
                self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(body)))
            if etag:
                self.send_header("ETag", etag)
            if cache_max_age:
                self.send_header("Cache-Control",
                                 f"public, max-age={cache_max_age}")
            else:
                self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _handle_optimize(self) -> dict:
            """GET /api/forecast/optimize?t=HH:MM[&g2=35&g6=15&g4=22&g8=10]"""
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            t = (q.get("t", ["13:00"])[0] or "13:00").strip()
            overrides: dict[int, int] = {}
            for ph in (2, 4, 6, 8):
                raw = q.get(f"g{ph}", [None])[0]
                if raw is not None:
                    try:
                        overrides[ph] = max(5, min(80, int(raw)))
                    except ValueError:
                        pass
            return _forecast_optimize(t, overrides or None)

        def do_GET(self):  # noqa: N802
            path = self.path.split("?", 1)[0]
            # SPA-first: "/" and any path React Router owns serves the built
            # index.html; React Router decides which page to render.
            if path == "/":
                self._serve_spa_index()
            elif path == "/thumb.jpg":
                if THUMB_PATH.exists():
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(THUMB_PATH.read_bytes())
                else:
                    self.send_response(503); self.end_headers()
            elif path == "/ai-thumb.jpg":
                # Phase 2 annotated snapshot — poll-based replacement for MJPEG
                # multipart stream (which SIGILLs Chromium inside this VM).
                p = Path("/tmp/traffic-intel-phase2-latest.jpg")
                if p.is_file():
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(p.read_bytes())
                else:
                    self.send_response(503); self.end_headers()
            elif path == "/api/status":
                self._json(_healthy(rtsp_url))
            elif path == "/api/counts":
                p = DATA_DIR / "detector_counts"
                files = sorted(p.glob("counts_*.parquet"))
                etag = _etag_for(files[-1:]) if files else None
                self._json(_latest_counts(), etag=etag)
            elif path == "/api/events":
                files = sorted((DATA_DIR / "signal_logs").glob("signal_*.ndjson"))
                etag = _etag_for(files[-1:]) if files else None
                self._json(_latest_events(), etag=etag)
            elif path == "/api/phase2":
                p2 = DATA_DIR / "events" / "phase2.ndjson"
                etag = _etag_for([p2]) if p2.exists() else None
                self._json(_latest_phase2(), etag=etag)
            elif path == "/api/phase2/crossings":
                p2 = DATA_DIR / "events" / "phase2.ndjson"
                etag = _etag_for([p2]) if p2.exists() else None
                self._json(_phase2_crossings(), etag=etag)
            elif path == "/api/forecast":
                fp = DATA_DIR / "forecast" / "forecast_day.json"
                etag = _etag_for([fp]) if fp.exists() else None
                self._json(_latest_forecast(), etag=etag)
            elif path == "/api/gmaps/now":
                self._json(_gmaps_state_now())
            elif path.startswith("/api/forecast/optimize"):
                self._json(self._handle_optimize())
            elif path.startswith("/api/forecast/ml"):
                from urllib.parse import parse_qs, urlparse
                q = parse_qs(urlparse(self.path).query)
                ts = q.get("ts", [None])[0]
                self._json(_ml_forecast(ts))
            elif path.startswith("/api/history/counts"):
                from urllib.parse import parse_qs, urlparse
                q = parse_qs(urlparse(self.path).query)
                try:
                    days = max(1, min(60, int(q.get("days", ["14"])[0])))
                except ValueError:
                    days = 14
                hc_files = sorted((DATA_DIR / "detector_counts")
                                  .glob("counts_*.parquet"))[-days:]
                etag = _etag_for(hc_files, extra=f"d{days}") if hc_files else None
                self._json(_history_counts(days), etag=etag)
            elif path == "/api/health":
                self._json(_health())
            elif path == "/api/audit":
                from urllib.parse import parse_qs, urlparse
                q = parse_qs(urlparse(self.path).query)
                try:
                    n = max(1, min(1000, int(q.get("n", ["200"])[0])))
                except ValueError:
                    n = 200
                self._json(_audit_tail(n))
            elif path == "/api/videos":
                self._json({"videos": _list_videos()})
            elif path == "/api/architecture":
                self._json(_architecture())
            elif path == "/api/incidents":
                cp = DATA_DIR / "labels" / "clips_manifest.json"
                etag = _etag_for([cp]) if cp.exists() else None
                self._json(_incidents(), etag=etag)
            elif path.startswith("/api/analysis/throughput"):
                from urllib.parse import parse_qs, urlparse
                q = parse_qs(urlparse(self.path).query)
                try:
                    w = max(5, min(240, int(q.get("window", ["60"])[0])))
                except ValueError:
                    w = 60
                try:
                    b = max(1, min(15, int(q.get("bin", ["1"])[0])))
                except ValueError:
                    b = 1
                self._json(_analysis_throughput(w, b))
            elif path.startswith("/poster/"):
                name = Path(path[len("/poster/"):]).name
                p = POSTER_DIR / name
                if p.is_file() and p.suffix.lower() in (".jpg", ".jpeg"):
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Cache-Control", "public, max-age=86400")
                    self.end_headers()
                    self.wfile.write(p.read_bytes())
                else:
                    self.send_response(404); self.end_headers()
            elif path.startswith("/animated/"):
                name = Path(path[len("/animated/"):]).name
                p = ANIM_DIR / name
                if p.is_file() and p.suffix.lower() == ".webp":
                    self.send_response(200)
                    self.send_header("Content-Type", "image/webp")
                    self.send_header("Cache-Control", "public, max-age=3600")
                    self.send_header("Content-Length", str(p.stat().st_size))
                    self.end_headers()
                    self.wfile.write(p.read_bytes())
                else:
                    self.send_response(404); self.end_headers()
            elif path == "/video/thevideo":
                self._serve_anchor_video(Path("/home/admin1/TheVideo.mp4"))
            elif path == "/video/thevideo-annotated":
                self._serve_anchor_video(DATA_DIR / "forecast" / "anchor_annotated.mp4")
            elif path.startswith("/video/"):
                self._serve_video(path[len("/video/"):], kind="raw")
            elif path.startswith("/video-ai/"):
                self._serve_video(path[len("/video-ai/"):], kind="ai")
            elif path.startswith("/assets/"):
                # Vite-emitted bundle chunks (production build)
                self._serve_spa_static(path[len("/"):])
            elif path == "/favicon.svg" or path == "/vite.svg":
                self._serve_spa_static(path[len("/"):])
            elif path.startswith("/api/"):
                # Unknown /api/* = 404
                self.send_response(404); self.end_headers()
            else:
                # SPA fallback — React Router owns anything unrecognised
                self._serve_spa_index()

        def do_POST(self):  # noqa: N802
            """§7.7 bearer-token gate. There are no POST endpoints in Phase 2 —
            this method exists so the auth contract is enforced the moment a
            Phase 3 writeable endpoint is added. If ``DASHBOARD_TOKEN`` is
            unset, POST is rejected outright (fail-closed). If set, the
            request must present ``Authorization: Bearer <token>``."""
            expected = _auth_token_required()
            got = self.headers.get("Authorization", "")
            if not expected:
                self._json({"error": "POST disabled — set DASHBOARD_TOKEN to enable"},
                           code=405)
                return
            if not got.startswith("Bearer ") or got[7:].strip() != expected:
                self._json({"error": "invalid or missing bearer token"}, code=401)
                return
            # No real POST routes yet — reject unknown paths cleanly
            self._json({"error": "no such endpoint"}, code=404)

        def _serve_anchor_video(self, src: Path) -> None:
            """Range-aware server for a specific MP4 (TheVideo.mp4 or the
            YOLO-annotated sibling). Uses the same H.264 headers as the
            /video/ route so Chromium uses software decoding."""
            if not src.is_file() or src.suffix.lower() != ".mp4":
                self.send_response(404); self.end_headers(); return
            size = src.stat().st_size
            rng = self.headers.get("Range", "")
            start, end = 0, size - 1
            if rng.startswith("bytes="):
                try:
                    s, _, e = rng[6:].partition("-")
                    start = int(s) if s else 0
                    end = int(e) if e else size - 1
                    if start < 0 or end >= size or start > end:
                        raise ValueError
                except Exception:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers(); return
            length = end - start + 1
            code = 206 if rng else 200
            self.send_response(code)
            self.send_header("Content-Type", 'video/mp4; codecs="avc1.42E01F"')
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(length))
            if code == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Cache-Control", "public, max-age=3600")
            self.end_headers()
            with src.open("rb") as fh:
                fh.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = fh.read(min(1 << 20, remaining))
                    if not chunk: break
                    try:
                        self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        return
                    remaining -= len(chunk)

        def _serve_spa_index(self) -> None:
            index = FRONTEND_DIST / "index.html"
            if not index.is_file():
                self.send_response(503)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(
                    b"Signal-timing SPA not built. Run `cd frontend && npm run build`."
                )
                return
            body = index.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _serve_spa_static(self, relpath: str) -> None:
            # Strip any query string, then constrain to files under dist/
            relpath = relpath.split("?", 1)[0].split("#", 1)[0]
            # Resolve + verify the resulting path is inside FRONTEND_DIST
            target = (FRONTEND_DIST / relpath).resolve()
            try:
                target.relative_to(FRONTEND_DIST.resolve())
            except ValueError:
                self.send_response(403); self.end_headers(); return
            if not target.is_file():
                # SPA fallback: non-asset paths serve index.html
                if "/assets/" not in relpath:
                    self._serve_spa_index()
                    return
                self.send_response(404); self.end_headers(); return
            suffix = target.suffix.lower()
            mime = _STATIC_MIME.get(suffix, "application/octet-stream")
            body = target.read_bytes()

            # gzip text-like payloads when the client accepts it. Huge win for
            # the main JS chunk (~260 KB → ~82 KB).
            gz_ok = suffix in {".js", ".mjs", ".css", ".svg", ".json", ".map",
                               ".html", ".xml"}
            accept = self.headers.get("Accept-Encoding", "")
            use_gz = gz_ok and "gzip" in accept and len(body) >= 1024
            if use_gz:
                body = _gz.compress(body, compresslevel=6, mtime=0)

            # Weak ETag based on file mtime+size — cheap Conditional GET.
            etag = _etag_for([target])
            if self.headers.get("If-None-Match", "") == etag:
                self.send_response(304)
                self.send_header("ETag", etag)
                if relpath.startswith("assets/"):
                    self.send_header("Cache-Control",
                                     "public, max-age=31536000, immutable")
                self.end_headers()
                return

            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Vary", "Accept-Encoding")
            if use_gz:
                self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("ETag", etag)
            # Vite emits content-hashed filenames → safe to cache aggressively
            if relpath.startswith("assets/"):
                self.send_header("Cache-Control",
                                 "public, max-age=31536000, immutable")
            else:
                self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _serve_video(self, name: str, kind: str = "raw") -> None:
            # Sanitize — only allow plain filenames; block traversal
            safe = Path(name).name
            if not safe or safe != name:
                self.send_response(400); self.end_headers(); return
            full = _find_annotated(safe) if kind == "ai" else _find_normalized(safe)
            if not full or not full.is_file() or full.suffix.lower() != ".mp4":
                self.send_response(404); self.end_headers(); return
            size = full.stat().st_size
            rng = self.headers.get("Range", "")
            start, end = 0, size - 1
            if rng.startswith("bytes="):
                try:
                    s, _, e = rng[6:].partition("-")
                    start = int(s) if s else 0
                    end = int(e) if e else size - 1
                    if start < 0 or end >= size or start > end:
                        raise ValueError
                except Exception:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers(); return
            length = end - start + 1
            code = 206 if rng else 200
            self.send_response(code)
            # Advertise the exact AVC1 codec string for H.264 Constrained
            # Baseline, level 3.1 (avc1.42E01F). All MP4s under data/normalized
            # and data/annotated are transcoded to this profile so Chrome in
            # this VirtualBox VM takes the software-decode path unconditionally
            # and avoids the VA-API/virtio-GPU SIGILL seen with High profile
            # + B-frames (and with MPEG-4 Part 2, which Chrome cannot decode).
            self.send_header("Content-Type", 'video/mp4; codecs="avc1.42E01F"')
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(length))
            if code == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Cache-Control", "public, max-age=3600")
            self.end_headers()
            with full.open("rb") as fh:
                fh.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = fh.read(min(1 << 20, remaining))
                    if not chunk: break
                    try:
                        self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        return
                    remaining -= len(chunk)
    return H


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Tiny sandbox preview dashboard.")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--rtsp-url", default=os.environ.get("RTSP_URL", "rtsp://localhost:8554/site1"))
    args = p.parse_args(argv)

    # Stamp the start time for /api/health uptime reporting
    import time as _time
    global _VIEWER_STARTED_AT_NS
    _VIEWER_STARTED_AT_NS = _time.monotonic_ns()

    stop = threading.Event()
    t = threading.Thread(target=_thumb_refresher, args=(args.rtsp_url, stop), daemon=True)
    t.start()

    server = ThreadingHTTPServer((args.host, args.port), _handler(args.rtsp_url))
    print(f"[viewer] open  http://{args.host}:{args.port}/", file=sys.stderr)
    print(f"[viewer] RTSP  {args.rtsp_url}", file=sys.stderr)
    print("[viewer] Ctrl+C to stop", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
