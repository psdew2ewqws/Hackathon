# Vendored: movsim · traffic-simulation-de

This directory is a trimmed copy of [movsim/traffic-simulation-de](https://github.com/movsim/traffic-simulation-de),
limited to the **signalised 4-way intersection** scenario. The upstream simulator
is a JavaScript implementation of the Intelligent Driver Model (IDM) with
multi-lane lane changes, signal control, and conflict-resolved intersections.

We embed it inside the Traffic-Intel React dashboard at `/app/simulation` via
a `<iframe src="/app/movsim/" />`.

## Modifications from upstream

1. **Trimmed scenarios** — only the intersection scenario is kept (no
   roundabout, on-ramp, off-ramp, ring road, golf-course, ramp-meter game,
   coffee-meter game, …). Saves ~7 MB of figs.
2. **postMessage bridge** — at the bottom of `index.html` (formerly
   `intersection.html`) we appended an IIFE that:
   - Listens for `{type: 'config', signal, demand_multiplier, lane_closures,
     time_lapse}` and writes to the upstream globals (`qIn`, `q2`,
     `cycleTL`, `greenMain`, `timewarp`).
   - Posts `{type: 'metrics', sim_time_s, avg_delay_s_per_veh,
     throughput_per_15min, queue_length, vehicles_active}` to `parent` every
     ~1 s of wall-clock time.
   - Posts `{type: 'ready'}` once after page load so the React parent knows
     when to send the initial configuration.
3. **`overrides.css`** — dark-theme overrides loaded last; matches the
   Traffic-Intel `--bg`/`--accent` palette.

## License

Upstream is **GPL-3.0**. The full original `LICENSE` is preserved verbatim
in this directory. Our modifications above are also released under GPL-3.0.

## Upstream commit

See `UPSTREAM_COMMIT.txt` for the exact SHA copied. To re-sync:

```bash
git clone --depth 1 https://github.com/movsim/traffic-simulation-de /tmp/movsim
# Compare js/, css/, figs/, intersection.html with our copies.
```
