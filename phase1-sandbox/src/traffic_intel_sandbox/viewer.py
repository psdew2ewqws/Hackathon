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
import json
import os
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pyarrow.parquet as pq

# parents[3] = .../traffic-intel (repo root)
#   parents[0] = .../traffic_intel_sandbox
#   parents[1] = .../src
#   parents[2] = .../phase1-sandbox
#   parents[3] = .../traffic-intel
REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = Path(os.environ.get("DATA_DIR", REPO_ROOT / "data"))
THUMB_PATH = Path("/tmp/traffic-intel-thumb.jpg")
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

  <!-- ── AI EVENT LOG ───────────────────────── -->
  <section class="panel reveal r5" style="margin-bottom: 24px;">
    <div class="panel-title">
      <h2>AI events</h2>
      <span class="hint">last 20 · phase2.ndjson</span>
    </div>
    <div class="log" id="logPhase2"></div>
  </section>

  <!-- ── FOOTER ─────────────────────────────── -->
  <footer class="foot reveal r6">
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


def _latest_events(limit: int = 10) -> dict:
    files = sorted(DATA_DIR.glob("signal_logs/signal_*.ndjson"))
    if not files:
        return {"lines": ["(no signal logs)"]}
    latest = files[-1]
    with latest.open() as fh:
        lines = fh.readlines()
    return {"lines": [ln.rstrip() for ln in lines[-limit:]]}


def _latest_phase2(limit: int = 10) -> dict:
    """Tail the Phase 2 detect+track ndjson event log."""
    path = DATA_DIR / "events" / "phase2.ndjson"
    if not path.exists():
        return {"lines": ["(no phase2 events yet — run `make phase2-detect`)"]}
    with path.open() as fh:
        lines = fh.readlines()
    return {"lines": [ln.rstrip() for ln in lines[-limit:]]}


def _latest_forecast() -> dict:
    """Read the full-day traffic forecast (48 slots × 4 approaches) written by
    `make forecast-predict`. Empty response if the file is missing."""
    path = DATA_DIR / "forecast" / "forecast_day.json"
    if not path.is_file():
        return {"available": False,
                "message": "run `make forecast-all` to produce a forecast"}
    try:
        data = json.loads(path.read_text())
        data["available"] = True
        return data
    except (OSError, json.JSONDecodeError) as exc:
        return {"available": False, "message": f"forecast read failed: {exc}"}


def _healthy(rtsp_url: str) -> dict:
    try:
        from traffic_intel_sandbox.rtsp_sim.healthcheck import _probe, evaluate
        info = _probe(rtsp_url)
        report, _failures = evaluate(info)
        report["url"] = rtsp_url
        return report
    except Exception as exc:  # noqa: BLE001
        return {"healthy": False, "error": str(exc)}


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
    running 5 concurrent video decoders in Chromium-on-VM)."""
    out: list[dict] = []
    seen: set[str] = set()
    search_dirs = [
        (DATA_DIR / "normalized", "archive"),
        (DATA_DIR / "normalized" / "scenarios", "angle"),
    ]
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


def _handler(rtsp_url: str):
    class H(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args): pass   # quiet access log

        def _json(self, obj: dict, code: int = 200) -> None:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(json.dumps(obj).encode())

        def do_GET(self):  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path == "/":
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(HTML.encode())
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
                self._json(_latest_counts())
            elif path == "/api/events":
                self._json(_latest_events())
            elif path == "/api/phase2":
                self._json(_latest_phase2())
            elif path == "/api/forecast":
                self._json(_latest_forecast())
            elif path == "/api/videos":
                self._json({"videos": _list_videos()})
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
            elif path.startswith("/video/"):
                self._serve_video(path[len("/video/"):], kind="raw")
            elif path.startswith("/video-ai/"):
                self._serve_video(path[len("/video-ai/"):], kind="ai")
            else:
                self.send_response(404); self.end_headers()

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
