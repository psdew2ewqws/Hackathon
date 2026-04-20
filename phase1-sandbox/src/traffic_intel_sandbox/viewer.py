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
<title>Traffic &amp; Ops Briefing · SITE-001</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=JetBrains+Mono:wght@300;400;500;700&display=swap" rel="stylesheet">
<style>
  :root {
    color-scheme: dark;
    --paper:    #0E0F0C;
    --paper-2:  #15160F;
    --ink:      #F0E8D8;
    --ink-dim:  #8A8777;
    --rule:     #2A2B26;
    --tungsten: #FF6A00;
    --phosphor: #9FE870;
    --amber:    #F1C40F;
    --stop:     #FF3D3D;
    --serif:    'Instrument Serif', 'Cormorant Garamond', Georgia, serif;
    --mono:     'JetBrains Mono', ui-monospace, 'SF Mono', monospace;
  }
  *, *::before, *::after { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  body {
    font-family: var(--mono);
    font-size: 13px; line-height: 1.5;
    color: var(--ink);
    background:
      radial-gradient(ellipse 1400px 700px at 50% -20%, rgba(255,106,0,0.07), transparent 70%),
      radial-gradient(ellipse 900px 500px at 100% 100%, rgba(159,232,112,0.04), transparent 70%),
      linear-gradient(#0E0F0C, #0A0B08);
    background-attachment: fixed;
    min-height: 100vh;
    font-feature-settings: 'tnum' 1, 'zero' 1, 'ss01' 1;
    overflow-x: hidden;
  }
  /* Film-grain overlay */
  body::before {
    content: ""; position: fixed; inset: 0; pointer-events: none; z-index: 1;
    background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 120 120'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='2.3' numOctaves='2' stitchTiles='stitch'/><feColorMatrix values='0 0 0 0 0.94  0 0 0 0 0.91  0 0 0 0 0.85  0 0 0 0.08 0'/></filter><rect width='120' height='120' filter='url(%23n)'/></svg>");
    opacity: 0.4; mix-blend-mode: overlay;
  }
  /* Thin vertical printers' rule */
  body::after {
    content: ""; position: fixed; inset: 0; pointer-events: none; z-index: 0;
    background-image: linear-gradient(to right, rgba(42,43,38,0.55) 1px, transparent 1px);
    background-size: 120px 120px; opacity: 0.6;
  }

  .page {
    position: relative; z-index: 2;
    max-width: 1480px; margin: 0 auto;
    padding: 32px 44px 64px;
  }

  /* registration marks */
  .reg { position: fixed; width: 24px; height: 24px; pointer-events: none; z-index: 3;
         color: var(--ink-dim); opacity: 0.45; }
  .reg.tl { top: 18px; left: 18px; }
  .reg.tr { top: 18px; right: 18px; transform: scaleX(-1); }
  .reg.bl { bottom: 18px; left: 18px; transform: scaleY(-1); }
  .reg.br { bottom: 18px; right: 18px; transform: scale(-1,-1); }

  /* ── MASTHEAD ─────────────────────────────── */
  .masthead {
    display: grid; grid-template-columns: 1fr auto 1fr;
    align-items: baseline; gap: 32px;
    padding-bottom: 16px; border-bottom: 2px solid var(--ink);
  }
  .masthead-side {
    font-size: 10px; letter-spacing: 0.22em; text-transform: uppercase;
    color: var(--ink-dim); display: flex; gap: 22px;
  }
  .masthead-side.right { justify-content: flex-end; }
  .masthead-title {
    font-family: var(--serif); font-weight: 400;
    font-size: 74px; line-height: 0.88;
    letter-spacing: -0.025em; text-align: center;
    font-style: italic;
  }
  .masthead-title .roman { font-style: normal; }
  .masthead-title .amp { color: var(--tungsten); font-style: normal; }

  .masthead-sub {
    padding: 10px 0 12px; border-bottom: 1px solid var(--rule);
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 24px;
    font-size: 10px; letter-spacing: 0.18em; text-transform: uppercase;
    color: var(--ink-dim); margin-bottom: 30px;
  }
  .masthead-sub b {
    color: var(--ink); font-weight: 500;
    letter-spacing: 0.04em; text-transform: none;
    font-size: 12px;
  }
  .badge-onair {
    color: var(--tungsten); display: inline-flex; align-items: center;
    gap: 8px; font-size: 11px; letter-spacing: 0.2em;
  }
  .badge-onair .dot {
    width: 9px; height: 9px; border-radius: 50%;
    background: var(--tungsten); box-shadow: 0 0 12px var(--tungsten);
    animation: blink 1.8s ease-in-out infinite;
  }
  @keyframes blink { 50% { opacity: 0.25; transform: scale(0.82); } }

  /* ── HERO METRICS ─────────────────────────── */
  .hero {
    display: grid; grid-template-columns: repeat(5, 1fr);
    border-top: 1px solid var(--rule); border-bottom: 1px solid var(--rule);
    margin-bottom: 34px;
  }
  .stat {
    padding: 20px 24px; position: relative;
    border-right: 1px solid var(--rule);
  }
  .stat:last-child { border-right: none; }
  .stat .label {
    font-size: 9px; letter-spacing: 0.26em;
    text-transform: uppercase; color: var(--ink-dim);
    display: flex; gap: 8px; align-items: center;
  }
  .stat .label::before {
    content: ''; width: 5px; height: 5px; background: var(--tungsten); border-radius: 50%;
  }
  .stat .value {
    font-family: var(--serif); font-size: 64px; line-height: 1;
    font-weight: 400; margin-top: 10px;
    letter-spacing: -0.025em; color: var(--ink);
    font-variant-numeric: tabular-nums lining-nums;
  }
  .stat.accent .value { color: var(--tungsten); }
  .stat.phosphor .value { color: var(--phosphor); }
  .stat .unit {
    font-size: 10px; color: var(--ink-dim);
    letter-spacing: 0.15em; text-transform: uppercase; margin-top: 6px;
  }

  /* ── FIGURE CARDS ─────────────────────────── */
  .grid {
    display: grid; grid-template-columns: 1.6fr 1fr;
    gap: 30px; margin-bottom: 34px;
  }
  .figure {
    border: 1px solid var(--rule);
    background: linear-gradient(180deg, rgba(21,22,15,0.85), rgba(14,15,12,0.55));
    position: relative;
  }
  .figure-head {
    display: flex; justify-content: space-between; align-items: baseline;
    padding: 14px 18px; gap: 20px;
    border-bottom: 1px solid var(--rule);
    background: var(--paper-2);
  }
  .fig-id {
    font-size: 9px; letter-spacing: 0.26em;
    text-transform: uppercase; color: var(--tungsten);
    white-space: nowrap;
  }
  .fig-title {
    font-family: var(--serif); font-style: italic;
    font-size: 18px; color: var(--ink);
    flex: 1; text-align: center;
  }
  .fig-meta {
    font-size: 10px; letter-spacing: 0.14em;
    color: var(--ink-dim); text-transform: uppercase;
    white-space: nowrap;
  }

  /* ── STREAM DUAL ─────────────────────────── */
  .dual {
    display: grid; grid-template-columns: 1fr 1fr; gap: 1px;
    background: var(--rule);
  }
  .stream-frame {
    position: relative; background: #000;
    aspect-ratio: 16/9; overflow: hidden;
  }
  .stream-frame img {
    width: 100%; height: 100%; object-fit: contain; display: block;
  }
  .stream-frame::after {
    content: ""; position: absolute; inset: 0; pointer-events: none;
    background-image: repeating-linear-gradient(
      0deg, rgba(0,0,0,0.13) 0px, rgba(0,0,0,0.13) 1px, transparent 1px, transparent 3px);
    mix-blend-mode: multiply;
  }
  .stream-frame::before {
    content: ""; position: absolute; inset: 12px; pointer-events: none;
    background:
      linear-gradient(var(--ink), var(--ink)) top    left  / 18px 1.5px no-repeat,
      linear-gradient(var(--ink), var(--ink)) top    left  / 1.5px 18px no-repeat,
      linear-gradient(var(--ink), var(--ink)) top    right / 18px 1.5px no-repeat,
      linear-gradient(var(--ink), var(--ink)) top    right / 1.5px 18px no-repeat,
      linear-gradient(var(--ink), var(--ink)) bottom left  / 18px 1.5px no-repeat,
      linear-gradient(var(--ink), var(--ink)) bottom left  / 1.5px 18px no-repeat,
      linear-gradient(var(--ink), var(--ink)) bottom right / 18px 1.5px no-repeat,
      linear-gradient(var(--ink), var(--ink)) bottom right / 1.5px 18px no-repeat;
    opacity: 0.9; z-index: 2;
  }
  .stream-badge {
    position: absolute; top: 22px; right: 22px; z-index: 3;
    padding: 5px 10px;
    background: rgba(14,15,12,0.78); border: 1px solid var(--ink);
    font-size: 10px; letter-spacing: 0.22em; color: var(--ink);
    display: flex; align-items: center; gap: 7px;
  }
  .stream-badge .rec {
    width: 7px; height: 7px; border-radius: 50%;
    background: var(--stop); box-shadow: 0 0 9px var(--stop);
    animation: blink 1.3s ease-in-out infinite;
  }
  .stream-badge.ai .rec { background: var(--phosphor); box-shadow: 0 0 9px var(--phosphor); }
  .p2-hint {
    display: none; position: absolute; inset: 0; z-index: 4;
    color: var(--ink); font-size: 11px;
    padding: 20px; background: var(--paper);
    text-align: center; align-items: center; justify-content: center;
    flex-direction: column; gap: 10px;
  }
  .p2-hint code {
    color: var(--phosphor); font-size: 12px;
    padding: 4px 8px; border: 1px solid var(--rule);
  }
  .stream-note {
    padding: 10px 18px; border-top: 1px solid var(--rule);
    font-size: 10px; letter-spacing: 0.14em;
    display: flex; justify-content: space-between; gap: 16px;
    color: var(--ink-dim); text-transform: uppercase;
  }
  .stream-note a { color: var(--ink); text-decoration: none;
                   border-bottom: 1px dotted var(--ink-dim); }
  .stream-note a:hover { color: var(--tungsten); border-bottom-color: var(--tungsten); }

  /* ── PHASE CLOCK ──────────────────────────── */
  .clock-wrap { display: flex; justify-content: center; padding: 24px 18px 10px; }
  .phase-clock { width: 260px; height: 260px; position: relative; }
  .phase-clock svg { width: 100%; height: 100%; transform: rotate(-90deg); overflow: visible; }
  .phase-clock .ring-bg { fill: none; stroke: var(--rule); stroke-width: 28; }
  .phase-clock .ring-seg { fill: none; stroke-width: 28;
                           transition: stroke 0.28s ease, filter 0.28s ease;
                           stroke-linecap: butt; }
  .phase-clock .center-text {
    position: absolute; inset: 0;
    display: flex; flex-direction: column; justify-content: center; align-items: center;
  }
  .phase-clock .phase-num {
    font-family: var(--serif); font-style: italic;
    font-size: 84px; line-height: 1; color: var(--ink);
    font-variant-numeric: tabular-nums;
  }
  .phase-clock .phase-state {
    font-size: 11px; letter-spacing: 0.32em;
    text-transform: uppercase; color: var(--tungsten);
    margin-top: 4px; font-weight: 500;
  }
  .legend {
    padding: 6px 20px 18px;
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px;
    font-size: 10px; letter-spacing: 0.1em;
  }
  .legend .chip { display: flex; align-items: center; gap: 7px; color: var(--ink-dim); }
  .legend .chip .sw { width: 11px; height: 11px; border: 1px solid; }
  .legend .chip.g .sw { background: var(--phosphor); border-color: var(--phosphor); }
  .legend .chip.y .sw { background: var(--amber); border-color: var(--amber); }
  .legend .chip.r .sw { background: var(--stop); border-color: var(--stop); }
  .legend .chip.o .sw { background: transparent; border-color: var(--rule); }

  /* ── CHART ────────────────────────────────── */
  .chart-wrap { padding: 14px 18px 10px; }
  .chart-wrap canvas { width: 100%; height: 200px; display: block; }
  .chart-meta {
    display: grid; grid-template-columns: repeat(3,1fr); gap: 22px;
    padding: 14px 18px; border-top: 1px solid var(--rule);
    font-size: 10px;
  }
  .chart-meta .m-label {
    color: var(--ink-dim); letter-spacing: 0.22em; text-transform: uppercase;
  }
  .chart-meta .m-value {
    color: var(--ink); font-size: 22px; margin-top: 4px;
    font-family: var(--serif); font-style: italic;
    font-variant-numeric: tabular-nums;
  }

  /* ── WIRE TICKER ──────────────────────────── */
  .wire {
    margin: 0 -44px 34px; padding: 13px 44px;
    border-top: 1px solid var(--rule); border-bottom: 1px solid var(--rule);
    background: linear-gradient(180deg, var(--paper-2), var(--paper));
    position: relative; overflow: hidden;
  }
  .wire-label {
    position: absolute; left: 44px; top: 50%; transform: translateY(-50%);
    font-size: 10px; letter-spacing: 0.3em; text-transform: uppercase;
    color: var(--tungsten); padding: 4px 10px;
    border: 1px solid var(--tungsten); background: var(--paper); z-index: 2;
    font-weight: 500;
  }
  .wire-track {
    padding-left: 110px; display: flex; gap: 46px;
    white-space: nowrap; font-size: 12px; color: var(--ink);
    animation: slide 78s linear infinite;
    animation-play-state: running;
  }
  .wire:hover .wire-track { animation-play-state: paused; }
  .wire-item { display: inline-flex; align-items: center; gap: 10px; }
  .wire-item .k { color: var(--phosphor); letter-spacing: 0.1em; }
  .wire-item .sep { color: var(--ink-dim); }
  @keyframes slide { to { transform: translateX(-50%); } }

  /* ── LOGS ─────────────────────────────────── */
  .twocol { display: grid; grid-template-columns: 1fr 1fr; gap: 30px; margin-bottom: 34px; }
  .log {
    font-size: 11px; max-height: 300px; overflow-y: auto;
    padding: 8px 18px 18px;
    scrollbar-color: var(--rule) transparent; scrollbar-width: thin;
  }
  .log::-webkit-scrollbar { width: 6px; }
  .log::-webkit-scrollbar-thumb { background: var(--rule); }
  .log .row {
    padding: 7px 0; border-bottom: 1px dotted var(--rule);
    display: grid; grid-template-columns: 84px 1fr;
    gap: 14px; align-items: baseline;
  }
  .log .ts { color: var(--ink-dim); letter-spacing: 0.08em; }
  .log .body { color: var(--ink); word-break: break-word; }
  .log .body .k { color: var(--phosphor); margin-right: 6px; }
  .log .body .on  { color: var(--phosphor); }
  .log .body .red { color: var(--stop); }
  .log .body .tung { color: var(--tungsten); }
  .log:empty::before {
    content: "… awaiting events"; color: var(--ink-dim);
    font-style: italic; font-family: var(--serif); font-size: 14px;
    display: block; padding: 14px 0;
  }

  /* ── HANDLES ──────────────────────────────── */
  .handles {
    display: grid; grid-template-columns: repeat(3, 1fr);
    gap: 4px 30px; padding: 18px;
    font-size: 11px;
  }
  .handles .h-row {
    display: grid; grid-template-columns: max-content 1fr; gap: 14px;
    padding: 5px 0; align-items: baseline;
  }
  .handles b {
    font-weight: 500; color: var(--ink-dim);
    text-transform: uppercase; letter-spacing: 0.18em; font-size: 9px;
  }
  .handles a {
    color: var(--ink); text-decoration: none;
    border-bottom: 1px dotted var(--rule);
  }
  .handles a:hover { color: var(--tungsten); border-bottom-color: var(--tungsten); }
  .handles code {
    color: var(--phosphor); font-size: 11px;
    background: rgba(159,232,112,0.04); padding: 1px 5px;
  }

  /* ── FOOTER ───────────────────────────────── */
  footer {
    margin-top: 48px; padding-top: 22px;
    border-top: 2px solid var(--ink);
    display: grid; grid-template-columns: 1fr auto 1fr; gap: 24px;
    font-size: 10px; letter-spacing: 0.18em;
    text-transform: uppercase; color: var(--ink-dim);
    align-items: baseline;
  }
  footer .center {
    font-family: var(--serif); font-style: italic;
    text-transform: none; letter-spacing: 0.02em;
    font-size: 15px; color: var(--ink); text-align: center;
  }
  footer .right { text-align: right; }
  footer a { color: var(--ink-dim); text-decoration: none; }
  footer a:hover { color: var(--tungsten); }

  /* ── MOTION ───────────────────────────────── */
  .reveal { opacity: 0; transform: translateY(14px);
            animation: reveal 0.9s cubic-bezier(0.22,0.8,0.22,1) forwards; }
  .r1 { animation-delay: 0.02s; }
  .r2 { animation-delay: 0.16s; }
  .r3 { animation-delay: 0.32s; }
  .r4 { animation-delay: 0.48s; }
  .r5 { animation-delay: 0.60s; }
  .r6 { animation-delay: 0.72s; }
  @keyframes reveal { to { opacity: 1; transform: none; } }

  @media (max-width: 1100px) {
    .hero { grid-template-columns: repeat(2, 1fr); }
    .stat { border-right: none; border-bottom: 1px solid var(--rule); }
    .grid, .dual, .twocol { grid-template-columns: 1fr; }
    .masthead-title { font-size: 52px; }
    .wire-track { animation-duration: 55s; }
  }
</style></head>
<body>

 <!-- registration marks -->
 <svg class="reg tl" viewBox="0 0 24 24"><path d="M0 1 H16 M1 0 V16" stroke="currentColor" stroke-width="1" fill="none"/><circle cx="19" cy="19" r="3" stroke="currentColor" stroke-width="1" fill="none"/></svg>
 <svg class="reg tr" viewBox="0 0 24 24"><path d="M0 1 H16 M1 0 V16" stroke="currentColor" stroke-width="1" fill="none"/></svg>
 <svg class="reg bl" viewBox="0 0 24 24"><path d="M0 1 H16 M1 0 V16" stroke="currentColor" stroke-width="1" fill="none"/></svg>
 <svg class="reg br" viewBox="0 0 24 24"><path d="M0 1 H16 M1 0 V16" stroke="currentColor" stroke-width="1" fill="none"/></svg>

 <div class="page">

  <!-- MASTHEAD -->
  <header class="masthead reveal r1">
    <div class="masthead-side">
      <span>No. 001</span>
      <span>Vol. Phase I</span>
    </div>
    <div class="masthead-title">
      <span class="roman">Traffic</span> <span class="amp">&amp;</span> Operations<br>
      Briefing
    </div>
    <div class="masthead-side right">
      <span id="masthead-date">—</span>
      <span>Amman · JOR</span>
    </div>
  </header>

  <div class="masthead-sub reveal r1">
    <div>Site<br><b>SITE-001 · Wadi Saqra</b></div>
    <div>Stream<br><b id="streamRes">—</b></div>
    <div>Detector<br><b>YOLO26n · BoT-SORT</b></div>
    <div style="text-align:right">Status<br><span class="badge-onair" id="streamStatus"><span class="dot"></span>BOOTING</span></div>
  </div>

  <!-- HERO METRICS -->
  <section class="hero reveal r2" aria-label="Hero metrics">
    <div class="stat">
      <div class="label">Active Tracks</div>
      <div class="value" id="hActive">—</div>
      <div class="unit">Vehicles observed</div>
    </div>
    <div class="stat accent">
      <div class="label">Today Volume</div>
      <div class="value" id="hTotal">—</div>
      <div class="unit">Aggregated count</div>
    </div>
    <div class="stat">
      <div class="label">Peak Hour</div>
      <div class="value" id="hPeak">—</div>
      <div class="unit">at <span id="hPeakHour">—</span> local</div>
    </div>
    <div class="stat phosphor">
      <div class="label">Current Phase</div>
      <div class="value" id="hPhase">—</div>
      <div class="unit" id="hPhaseState">—</div>
    </div>
    <div class="stat">
      <div class="label">Inference</div>
      <div class="value" id="hFps">—</div>
      <div class="unit">ms / frame p50</div>
    </div>
  </section>

  <!-- PRIMARY GRID -->
  <section class="grid reveal r3">
    <div class="figure">
      <div class="figure-head">
        <span class="fig-id">Fig. 01 · Live</span>
        <span class="fig-title">Intersection feed — raw versus inferred</span>
        <span class="fig-meta" id="streamMeta">RTSP · H264 · 1920×1080 · 10 fps</span>
      </div>
      <div class="dual">
        <div class="stream-frame">
          <img src="/thumb.jpg?ts=0" id="thumb" alt="raw RTSP thumbnail">
          <div class="stream-badge"><span class="rec"></span>RTSP</div>
        </div>
        <div class="stream-frame">
          <img src="http://localhost:8081/stream.mjpeg" id="p2stream" alt="annotated live stream">
          <div class="stream-badge ai"><span class="rec"></span>AI</div>
          <div class="p2-hint" id="p2hint">
            <span>ANNOTATED FEED OFFLINE</span>
            <code>make phase2-live-bg</code>
          </div>
        </div>
      </div>
      <div class="stream-note">
        <span>RTSP → <a id="rtspLink" href="#">rtsp://localhost:8554/site1</a></span>
        <span>HLS → <a href="http://localhost:8888/site1/index.m3u8" target="_blank">:8888/site1</a></span>
        <span>MJPEG → <a href="http://localhost:8081/stream.mjpeg" target="_blank">:8081/stream.mjpeg</a></span>
      </div>
    </div>

    <div class="figure">
      <div class="figure-head">
        <span class="fig-id">Fig. 02 · Signal</span>
        <span class="fig-title">NEMA phase clock</span>
        <span class="fig-meta">SITE-001</span>
      </div>
      <div class="clock-wrap">
        <div class="phase-clock">
          <svg viewBox="-20 -20 280 280" id="phaseSvg">
            <circle class="ring-bg" cx="120" cy="120" r="90"/>
          </svg>
          <div class="center-text">
            <span class="phase-num" id="pcNum">—</span>
            <span class="phase-state" id="pcState">IDLE</span>
          </div>
        </div>
      </div>
      <div class="legend">
        <span class="chip g"><span class="sw"></span>GREEN</span>
        <span class="chip y"><span class="sw"></span>AMBER</span>
        <span class="chip r"><span class="sw"></span>RED</span>
        <span class="chip o"><span class="sw"></span>INACTIVE</span>
      </div>
    </div>
  </section>

  <!-- WIRE TICKER -->
  <div class="wire reveal r4">
    <div class="wire-label">Wire</div>
    <div class="wire-track" id="wireTrack"><span>—</span></div>
  </div>

  <!-- COUNTS + HANDLES -->
  <section class="grid reveal r5">
    <div class="figure">
      <div class="figure-head">
        <span class="fig-id">Fig. 03 · Counts</span>
        <span class="fig-title">Hourly detector throughput — 24 h</span>
        <span class="fig-meta" id="chartMeta">—</span>
      </div>
      <div class="chart-wrap"><canvas id="chart"></canvas></div>
      <div class="chart-meta">
        <div><div class="m-label">Date</div><div class="m-value" id="chartDate">—</div></div>
        <div><div class="m-label">Detectors</div><div class="m-value" id="chartDet">—</div></div>
        <div><div class="m-label">Volume</div><div class="m-value" id="chartTot">—</div></div>
      </div>
    </div>

    <div class="figure">
      <div class="figure-head">
        <span class="fig-id">Fig. 04 · Handles</span>
        <span class="fig-title">Local endpoints &amp; artefacts</span>
        <span class="fig-meta">localhost</span>
      </div>
      <div class="handles">
        <div class="h-row"><b>UI</b><a href="http://localhost:8000/" target="_blank">:8000 · dashboard</a></div>
        <div class="h-row"><b>AI</b><a href="http://localhost:8081/" target="_blank">:8081 · MJPEG</a></div>
        <div class="h-row"><b>RTSP</b><a href="#" id="h-rtsp">:8554 · stream</a></div>
        <div class="h-row"><b>HLS</b><a href="http://localhost:8888/site1/index.m3u8" target="_blank">:8888 · site1</a></div>
        <div class="h-row"><b>Ctl</b><a href="http://localhost:9997/v3/paths/list" target="_blank">:9997 · mediamtx</a></div>
        <div class="h-row"><b>CVAT</b><a href="http://localhost:8080" target="_blank">:8080 · annotate</a></div>
        <div class="h-row"><b>Repo</b><code>~/traffic-intel</code></div>
        <div class="h-row"><b>Data</b><code>data/*</code></div>
        <div class="h-row"><b>Verify</b><code>make sandbox-verify</code></div>
      </div>
    </div>
  </section>

  <!-- LOGS -->
  <section class="twocol reveal r6">
    <div class="figure">
      <div class="figure-head">
        <span class="fig-id">Fig. 05 · Signal log</span>
        <span class="fig-title">NEMA phase transitions</span>
        <span class="fig-meta">last 20</span>
      </div>
      <div class="log" id="logSignal"></div>
    </div>
    <div class="figure">
      <div class="figure-head">
        <span class="fig-id">Fig. 06 · AI log</span>
        <span class="fig-title">Detect &amp; track events</span>
        <span class="fig-meta">last 20</span>
      </div>
      <div class="log" id="logPhase2"></div>
    </div>
  </section>

  <!-- FOOTER -->
  <footer>
    <div>Sources · Veo 3 · Synthetic NEMA · CVAT seed</div>
    <div class="center">Traffic &amp; Operations Briefing · Phase 1 Sandbox · Hackathon</div>
    <div class="right"><span id="localClock">—</span></div>
  </footer>

 </div>

 <script>
  'use strict';
  const el = id => document.getElementById(id);
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const RTSP_URL = 'rtsp://localhost:8554/site1';

  // ── Clock + masthead date ────────────────
  const MONTHS = ['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'];
  function pad2(n) { return String(n).padStart(2, '0'); }
  function fmtDate(d) {
    return pad2(d.getDate()) + ' ' + MONTHS[d.getMonth()] + ' ' + d.getFullYear();
  }
  function tickClock() {
    const d = new Date();
    el('masthead-date').textContent = fmtDate(d);
    el('localClock').textContent = pad2(d.getHours()) + ':' + pad2(d.getMinutes())
                                   + ':' + pad2(d.getSeconds()) + ' LOCAL';
  }
  tickClock(); setInterval(tickClock, 1000);

  // ── Copy-on-click RTSP links ─────────────
  [el('rtspLink'), el('h-rtsp')].forEach(a => {
    if (!a) return;
    a.addEventListener('click', e => {
      e.preventDefault();
      try { navigator.clipboard.writeText(RTSP_URL); } catch (_e) {}
      const orig = a.textContent;
      a.textContent = 'copied ✓'; a.style.color = 'var(--phosphor)';
      setTimeout(() => { a.textContent = orig; a.style.color = ''; }, 1200);
    });
  });

  // ── Raw thumb refresh ────────────────────
  setInterval(() => { el('thumb').src = '/thumb.jpg?ts=' + Date.now(); }, 2000);

  // If MJPEG fails to load, show the hint
  const p2 = el('p2stream');
  if (p2) p2.addEventListener('error', () => {
    const h = el('p2hint'); if (h) h.style.display = 'flex';
    p2.style.visibility = 'hidden';
  });

  // ── Phase clock (NEMA 8-segment donut) ───
  function renderPhaseRing(currentPhase, currentState) {
    const svg = el('phaseSvg');
    svg.querySelectorAll('.ring-seg, .phase-label').forEach(n => n.remove());
    const cx = 120, cy = 120, r = 90;
    const N = 8, gap = 4;
    const segDeg = 360 / N - gap;
    const C = 2 * Math.PI * r;
    const colorFor = (active, state) => {
      if (!active) return 'rgba(42,43,38,1)';
      if (state === 'GREEN_ON')  return '#9FE870';
      if (state === 'YELLOW_ON') return '#F1C40F';
      if (state === 'RED_ON')    return '#FF3D3D';
      return '#F0E8D8';
    };
    for (let i = 0; i < N; i++) {
      const phase = i + 1;
      const startDeg = i * (360 / N) + gap / 2;
      const seg = document.createElementNS(SVG_NS, 'circle');
      seg.setAttribute('class', 'ring-seg');
      seg.setAttribute('cx', cx); seg.setAttribute('cy', cy); seg.setAttribute('r', r);
      const segLen = C * segDeg / 360;
      seg.setAttribute('stroke-dasharray', segLen + ' ' + (C - segLen));
      seg.setAttribute('stroke-dashoffset', -C * startDeg / 360);
      const active = phase === currentPhase;
      seg.setAttribute('stroke', colorFor(active, currentState));
      if (active) seg.setAttribute('filter', 'drop-shadow(0 0 6px ' + colorFor(true, currentState) + ')');
      svg.appendChild(seg);

      // Phase numeral label outside the ring
      const midDeg = i * (360 / N) + (360 / N) / 2 - 90;
      const rad = midDeg * Math.PI / 180;
      const lx = cx + Math.cos(rad) * (r + 26);
      const ly = cy + Math.sin(rad) * (r + 26);
      const text = document.createElementNS(SVG_NS, 'text');
      text.setAttribute('class', 'phase-label');
      text.setAttribute('x', lx); text.setAttribute('y', ly);
      text.setAttribute('text-anchor', 'middle');
      text.setAttribute('dominant-baseline', 'central');
      text.setAttribute('transform', 'rotate(90 ' + lx + ' ' + ly + ')');
      text.setAttribute('fill', active ? '#FF6A00' : '#8A8777');
      text.setAttribute('font-family', 'JetBrains Mono, monospace');
      text.setAttribute('font-size', '11');
      text.setAttribute('font-weight', active ? '700' : '400');
      text.setAttribute('letter-spacing', '0.12em');
      text.textContent = 'φ' + phase;
      svg.appendChild(text);
    }
    el('pcNum').textContent = currentPhase != null ? String(currentPhase) : '—';
    const niceState = { GREEN_ON: 'GREEN', YELLOW_ON: 'AMBER', RED_ON: 'RED' }[currentState] || 'IDLE';
    el('pcState').textContent = niceState;
  }
  renderPhaseRing(null, null);

  // ── Parsing helpers ──────────────────────
  function safeJson(line) { try { return JSON.parse(line); } catch { return null; } }
  function shortTs(iso) { return (iso || '').slice(11, 19); }
  function stateColor(st) {
    if (st === 'GREEN_ON') return 'on';
    if (st === 'RED_ON') return 'red';
    if (st === 'YELLOW_ON') return 'tung';
    return '';
  }

  // ── Log renderers (safe DOM only) ───────
  function renderSignalLog(lines) {
    const c = el('logSignal'); c.replaceChildren();
    const recent = (lines || []).slice(-20).reverse();
    for (const line of recent) {
      const o = safeJson(line); if (!o) continue;
      const row = document.createElement('div'); row.className = 'row';
      const ts  = document.createElement('span'); ts.className = 'ts';
      ts.textContent = shortTs(o.timestamp);
      const body = document.createElement('span'); body.className = 'body';
      const k = document.createElement('span'); k.className = 'k';
      k.textContent = 'φ' + o.phase;
      const sep = document.createElement('span'); sep.textContent = ' ';
      const st  = document.createElement('span');
      st.className = stateColor(o.state);
      st.textContent = (o.state || '').replace('_ON','');
      body.append(k, sep, st);
      row.append(ts, body);
      c.append(row);
    }
  }
  function renderPhase2Log(lines) {
    const c = el('logPhase2'); c.replaceChildren();
    const recent = (lines || []).slice(-20).reverse();
    for (const line of recent) {
      const o = safeJson(line); if (!o) continue;
      const row = document.createElement('div'); row.className = 'row';
      const ts  = document.createElement('span'); ts.className = 'ts';
      ts.textContent = shortTs(o.timestamp);
      const body = document.createElement('span'); body.className = 'body';
      const k = document.createElement('span'); k.className = 'k';
      k.textContent = (o.event_type || 'event');
      body.append(k);
      let tail = '';
      if (o.event_type === 'stop_line_crossing')
        tail = ' ' + o.approach + ' Δ' + o.delta + '  in:' + o.in_count + ' out:' + o.out_count;
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

  // ── Wire ticker ─────────────────────────
  function renderWire(signalLines, p2Lines) {
    const track = el('wireTrack'); track.replaceChildren();
    const items = [];
    for (const line of (p2Lines || []).slice(-8)) {
      const o = safeJson(line); if (!o) continue;
      const t = shortTs(o.timestamp);
      let msg = (o.event_type || '');
      if (o.event_type === 'stop_line_crossing')
        msg += ' ' + o.approach + ' Δ' + o.delta;
      else if (o.event_type === 'zone_occupancy')
        msg += ' ' + (o.name || '') + ' n=' + o.count;
      items.push(['ai', t, msg]);
    }
    for (const line of (signalLines || []).slice(-6)) {
      const o = safeJson(line); if (!o) continue;
      items.push(['sig', shortTs(o.timestamp),
                  'φ' + o.phase + ' ' + (o.state || '').replace('_ON','')]);
    }
    if (!items.length) {
      const s = document.createElement('span');
      s.textContent = 'AWAITING EVENTS…';
      s.style.color = 'var(--ink-dim)';
      track.append(s);
      return;
    }
    // duplicate for seamless loop
    for (let pass = 0; pass < 2; pass++) {
      for (const [klass, t, msg] of items) {
        const item = document.createElement('span'); item.className = 'wire-item';
        const k = document.createElement('span'); k.className = 'k'; k.textContent = t;
        const sep = document.createElement('span'); sep.className = 'sep'; sep.textContent = '⋅';
        const body = document.createElement('span'); body.textContent = msg;
        if (klass === 'sig') body.style.color = 'var(--tungsten)';
        item.append(k, sep, body);
        track.append(item);
      }
    }
  }

  // ── Canvas chart ────────────────────────
  function drawChart(c) {
    const cv = el('chart'); const ctx = cv.getContext('2d');
    const DPR = window.devicePixelRatio || 1;
    const W = cv.width = cv.clientWidth * DPR;
    const H = cv.height = cv.clientHeight * DPR;
    ctx.clearRect(0, 0, W, H);

    if (!c.hourly || !c.hourly.length) {
      ctx.fillStyle = '#8A8777';
      ctx.font = 'italic ' + (14 * DPR) + 'px "Instrument Serif", serif';
      ctx.fillText('awaiting data', 8 * DPR, 24 * DPR);
      return;
    }
    const PAD_L = 44 * DPR, PAD_B = 26 * DPR, PAD_T = 12 * DPR, PAD_R = 10 * DPR;
    const plotW = W - PAD_L - PAD_R;
    const plotH = H - PAD_B - PAD_T;
    const max = Math.max(...c.hourly) || 1;

    // horizontal gridlines
    ctx.strokeStyle = '#2A2B26'; ctx.lineWidth = 1;
    ctx.beginPath();
    for (let i = 0; i <= 4; i++) {
      const y = Math.round(PAD_T + plotH * i / 4) + 0.5;
      ctx.moveTo(PAD_L, y); ctx.lineTo(W - PAD_R, y);
    }
    ctx.stroke();

    // Y axis labels
    ctx.fillStyle = '#8A8777';
    ctx.font = (9 * DPR) + 'px "JetBrains Mono", monospace';
    ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
    for (let i = 0; i <= 4; i++) {
      const v = Math.round(max * (1 - i / 4));
      ctx.fillText(v.toLocaleString(), PAD_L - 8 * DPR, PAD_T + plotH * i / 4);
    }

    // Bars
    const bw = plotW / 24 * 0.72;
    const gap = plotW / 24 - bw;
    c.hourly.forEach((v, i) => {
      const h = plotH * v / max;
      const x = PAD_L + i * (plotW / 24) + gap / 2;
      const y = PAD_T + plotH - h;
      const g = ctx.createLinearGradient(0, y, 0, PAD_T + plotH);
      g.addColorStop(0, '#FF6A00');
      g.addColorStop(1, 'rgba(255,106,0,0.18)');
      ctx.fillStyle = g; ctx.fillRect(x, y, bw, h);
      ctx.fillStyle = '#F0E8D8'; ctx.fillRect(x, y - 1.5 * DPR, bw, 1.5 * DPR);
    });

    // X axis
    ctx.fillStyle = '#8A8777';
    ctx.textAlign = 'center'; ctx.textBaseline = 'top';
    ctx.font = (9 * DPR) + 'px "JetBrains Mono", monospace';
    [0, 6, 12, 18, 23].forEach(i => {
      const x = PAD_L + i * (plotW / 24) + (plotW / 24) / 2;
      ctx.fillText(pad2(i) + ':00', x, PAD_T + plotH + 6 * DPR);
    });
  }

  // ── Number counter animation ────────────
  function animateNumber(node, target, opts) {
    opts = opts || {};
    const duration = opts.duration || 1200;
    const fmt = opts.fmt || (n => Math.round(n).toLocaleString());
    const start = performance.now();
    (function step(now) {
      const t = Math.min(1, (now - start) / duration);
      const e = 1 - Math.pow(1 - t, 3);
      node.textContent = fmt(target * e);
      if (t < 1) requestAnimationFrame(step);
    })(start);
  }

  // ── Poll loop ───────────────────────────
  async function poll() {
    // status
    try {
      const s = await fetch('/api/status').then(r => r.json());
      const st = el('streamStatus');
      st.replaceChildren();
      const dot = document.createElement('span'); dot.className = 'dot';
      const text = document.createTextNode(s.healthy ? 'ON AIR' : 'OFF AIR');
      if (!s.healthy) { dot.style.background = 'var(--stop)'; dot.style.boxShadow = '0 0 10px var(--stop)'; }
      st.append(dot, text);
      st.style.color = s.healthy ? 'var(--tungsten)' : 'var(--stop)';
      if (s.healthy) {
        el('streamRes').textContent = s.width + '×' + s.height + ' · ' + s.fps + ' fps';
        el('streamMeta').textContent = 'RTSP · ' + (s.codec || 'h264').toUpperCase()
                                       + ' · ' + s.width + '×' + s.height + ' · ' + s.fps + ' fps';
      }
    } catch (e) {}

    // counts
    try {
      const c = await fetch('/api/counts').then(r => r.json());
      drawChart(c);
      el('chartDate').textContent = c.date || '—';
      el('chartDet').textContent  = String(c.detectors || 0);
      el('chartTot').textContent  = (c.total || 0).toLocaleString();
      el('chartMeta').textContent = (c.date || '—') + ' · 24 h';

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
    } catch (e) {}

    // signal events
    let signalLines = [];
    try {
      const ev = await fetch('/api/events').then(r => r.json());
      signalLines = ev.lines || [];
      renderSignalLog(signalLines);
      let latest = null;
      for (let i = signalLines.length - 1; i >= 0; i--) {
        const o = safeJson(signalLines[i]);
        if (o && o.phase != null) { latest = o; break; }
      }
      if (latest) {
        renderPhaseRing(latest.phase, latest.state);
        el('hPhase').textContent = String(latest.phase);
        el('hPhaseState').textContent = { GREEN_ON: 'GREEN', YELLOW_ON: 'AMBER', RED_ON: 'RED' }[latest.state] || '—';
      }
    } catch (e) {}

    // phase 2 events
    let p2Lines = [];
    try {
      const p2data = await fetch('/api/phase2').then(r => r.json());
      p2Lines = p2data.lines || [];
      renderPhase2Log(p2Lines);
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
    } catch (e) {}

    renderWire(signalLines, p2Lines);
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


def _healthy(rtsp_url: str) -> dict:
    try:
        from traffic_intel_sandbox.rtsp_sim.healthcheck import _probe, evaluate
        info = _probe(rtsp_url)
        report, _failures = evaluate(info)
        report["url"] = rtsp_url
        return report
    except Exception as exc:  # noqa: BLE001
        return {"healthy": False, "error": str(exc)}


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
            elif path == "/api/status":
                self._json(_healthy(rtsp_url))
            elif path == "/api/counts":
                self._json(_latest_counts())
            elif path == "/api/events":
                self._json(_latest_events())
            elif path == "/api/phase2":
                self._json(_latest_phase2())
            else:
                self.send_response(404); self.end_headers()
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
