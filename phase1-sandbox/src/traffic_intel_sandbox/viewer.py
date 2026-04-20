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
<html lang="en"><head>
<meta charset="utf-8">
<title>Traffic-Intel · Phase 1 Sandbox</title>
<style>
 :root { color-scheme: dark; }
 body { font-family: -apple-system, Segoe UI, system-ui, sans-serif;
        margin: 0; background:#0b1220; color:#e5e7eb; }
 header { padding: 14px 22px; background:#0f172a; border-bottom:1px solid #1e293b;
          display:flex; gap:12px; align-items:center; }
 header h1 { margin:0; font-size:18px; letter-spacing:0.02em; }
 header .pill { font-size:12px; padding:2px 8px; border:1px solid #334155;
                border-radius:999px; color:#94a3b8; }
 main { padding: 18px 22px; max-width:1200px; margin:0 auto;
        display:grid; grid-template-columns: 1.2fr 1fr; gap:20px; }
 section { background:#111827; border:1px solid #1f2937; border-radius:10px;
           padding:16px; }
 section h2 { margin:0 0 10px 0; font-size:14px; text-transform:uppercase;
              letter-spacing:0.08em; color:#93c5fd; }
 img.stream { width:100%; border-radius:6px; background:#000; aspect-ratio:16/9; object-fit:contain; }
 .kv { display:grid; grid-template-columns:max-content 1fr; gap:4px 12px; font-size:13px; }
 .kv b { color:#9ca3af; font-weight:500; }
 a { color:#60a5fa; text-decoration:none; }
 a:hover { text-decoration:underline; }
 .links code { background:#1f2937; padding:2px 6px; border-radius:4px; font-size:12px; }
 canvas { width:100%; height:200px; }
 .events { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size:12px;
           max-height:280px; overflow:auto; background:#0f172a; border-radius:6px;
           padding:10px; white-space: pre; }
 .footer { grid-column: 1 / -1; text-align:center; color:#475569; font-size:12px;
           padding-top:6px; }
 .bad { color:#f87171; }
 .good { color:#34d399; }
</style></head>
<body>
 <header>
  <h1>Traffic-Intel · Phase 1 Sandbox</h1>
  <span class="pill" id="status">checking…</span>
  <span class="pill" id="clock"></span>
 </header>
 <main>

  <section>
   <h2>Live RTSP (auto-refresh 2 s)</h2>
   <img class="stream" id="thumb" src="/thumb.jpg?ts=0" alt="rtsp thumbnail">
   <div class="kv" style="margin-top:10px">
    <b>RTSP</b>  <a href="#" id="rtspLink"></a>
    <b>HLS</b>   <a href="http://localhost:8888/site1/index.m3u8" target="_blank">http://localhost:8888/site1/index.m3u8</a>
    <b>MediaMTX API</b> <a href="http://localhost:9997/v3/paths/list" target="_blank">http://localhost:9997/v3/paths/list</a>
   </div>
  </section>

  <section>
   <h2>Hourly detector counts (latest day)</h2>
   <canvas id="chart"></canvas>
   <div class="kv" id="countsMeta" style="margin-top:8px"></div>
  </section>

  <section style="grid-column: 1 / -1">
   <h2>Signal log — last 10 events</h2>
   <div class="events" id="events">loading…</div>
  </section>

  <section class="links" style="grid-column: 1 / -1">
   <h2>Handles</h2>
   <div class="kv">
    <b>Repo</b>       <code>/home/admin1/traffic-intel</code>
    <b>Data dict</b>  <code>phase1-sandbox/data_dictionary.md</code>
    <b>Methodology</b><code>phase1-sandbox/methodology.md</code>
    <b>Phase 1 README</b> <code>phase1-sandbox/README.md</code>
    <b>Run tests</b>  <code>make sandbox-verify</code>
    <b>CVAT (when up)</b> <a href="http://localhost:8080" target="_blank">http://localhost:8080</a>
   </div>
  </section>

  <div class="footer">Phase 1 sandbox preview · not the Phase 3 production dashboard</div>
 </main>

<script>
 const el = id => document.getElementById(id);
 setInterval(() => { el('clock').textContent = new Date().toLocaleTimeString(); }, 1000);

 // Fill the RTSP link (textContent — never innerHTML with interpolation)
 const rtspUrl = 'rtsp://localhost:8554/site1';
 const rtspA = el('rtspLink');
 rtspA.textContent = rtspUrl;
 rtspA.onclick = (e) => { e.preventDefault(); navigator.clipboard.writeText(rtspUrl); };

 // Live thumbnail refresh — src setter is safe (no HTML parsing)
 setInterval(() => {
   el('thumb').src = '/thumb.jpg?ts=' + Date.now();
 }, 2000);

 async function poll() {
   try {
    const s = await fetch('/api/status').then(r => r.json());
    const p = el('status');
    p.textContent = s.healthy ? '● stream healthy' : '● stream down';
    p.className = 'pill ' + (s.healthy ? 'good' : 'bad');
   } catch(e) {
    el('status').textContent = '● api down';
    el('status').className='pill bad';
   }
   try {
    const c = await fetch('/api/counts').then(r => r.json());
    drawChart(c);
    const meta = el('countsMeta');
    meta.replaceChildren();
    const add = (label, val) => {
      const b = document.createElement('b'); b.textContent = label;
      const s = document.createElement('span'); s.textContent = val;
      meta.append(b, s);
    };
    add('Date', c.date ?? '—');
    add('Detectors', String(c.detectors));
    add('Total vehicles', (c.total || 0).toLocaleString());
   } catch(e) {}
   try {
    const ev = await fetch('/api/events').then(r => r.json());
    el('events').textContent = ev.lines.join('\n');
   } catch(e) {}
 }
 setInterval(poll, 5000); poll();

 function drawChart(c) {
   const cv = el('chart'); const ctx = cv.getContext('2d');
   const W = cv.width = cv.clientWidth * devicePixelRatio;
   const H = cv.height = cv.clientHeight * devicePixelRatio;
   ctx.clearRect(0,0,W,H);
   ctx.strokeStyle = '#1f2937'; ctx.lineWidth = 1 * devicePixelRatio;
   const PAD = 30 * devicePixelRatio;
   ctx.beginPath(); ctx.moveTo(PAD, H-PAD); ctx.lineTo(W-PAD/2, H-PAD); ctx.stroke();
   if (!c.hourly || !c.hourly.length) return;
   const max = Math.max(...c.hourly) || 1;
   const bw = (W-PAD-PAD/2) / c.hourly.length;
   ctx.fillStyle = '#60a5fa';
   c.hourly.forEach((v,i) => {
     const h = (H - 2*PAD) * v / max;
     ctx.fillRect(PAD + i*bw + 1, H-PAD-h, bw-2, h);
   });
   ctx.fillStyle = '#94a3b8'; ctx.font = (10*devicePixelRatio)+'px sans-serif';
   ['0h','6h','12h','18h','24h'].forEach((t,i) => {
     const x = PAD + (i*6) * bw;
     ctx.fillText(t, x, H-PAD/2);
   });
 }
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
