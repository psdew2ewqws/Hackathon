# Taregak (طريقك)

> **When should you leave?** A mobile app for Amman that recommends the optimal departure time to arrive on time, plus BRT bus arrival predictions.

The full plan lives at `~/.claude/plans/i-want-to-build-swirling-glade.md` (12-week solo build).

## Project layout

```
.
├── server/      # Fastify + TS backend (Node 20+)
├── mobile/      # React Native (Expo SDK 52)
├── scripts/    # one-off tools (Week 1 validation, etc.)
├── data/       # generated training log + experiment outputs (gitignored)
└── .env         # local secrets — copy from .env.example
```

## Prerequisites

- Node 20+ (you're on 24, fine)
- npm 9+
- A Google Cloud project with **Routes API** enabled and an API key
- A Mapbox account (free) with a public token (only needed when we wire maps in Week 3)
- Expo Go app on your phone OR an Android emulator / iOS simulator

Get a Google Maps API key at https://console.cloud.google.com → APIs & Services → Credentials. Restrict it by HTTP referer + IP for safety.

## Setup

```bash
cp .env.example .env
# then edit .env and paste your GOOGLE_MAPS_API_KEY

npm install                  # installs all workspaces
```

## Run the backend (Week 1)

```bash
npm run dev:server
# server listens on http://localhost:4000
# health: GET /v1/health
# predict: POST /v1/predict-departure  (see body below)
```

Try it:

```bash
curl -X POST http://localhost:4000/v1/predict-departure \
  -H 'content-type: application/json' \
  -H 'x-device-id: dev-test' \
  -d '{
    "origin": {"lat": 31.945, "lng": 35.880},
    "dest":   {"lat": 31.987, "lng": 35.872},
    "arriveBy": "2026-04-30T09:00:00.000Z",
    "windowMinutes": 90,
    "budget": 5
  }' | jq .
```

(Adjust `arriveBy` to a future time. The Routes API only does future predictions.)

## Run the mobile app (Week 1)

```bash
npm run dev:mobile
# scan the QR with Expo Go on your phone
# OR press `a` for Android emulator, `i` for iOS simulator
```

The home screen has lat/lng inputs — Week 3 swaps these for a real map picker.

If you're testing on a physical device, set `EXPO_PUBLIC_API_BASE` in `.env` to your LAN IP (e.g. `http://192.168.1.50:4000`) so the phone can reach the server.

## Week 1 validation experiment

Run the night before:

```bash
npm run validate:week1
```

This queries Routes API for 3 known Amman corridors (Abdoun↔UJ, 7th Circle↔Sweifieh, Tabarbour↔Downtown) at 7:00, 7:30, 8:00 tomorrow and writes predictions to `data/week1/YYYY-MM-DD_predictions.csv` plus a blank `_actuals.csv` template.

Then **drive each corridor at the queried time** the next morning and fill in actual durations. Repeat for 5 days. Pass criterion: mean absolute error < 25%, max < 40%. If you fail, the whole product needs reframing — see plan §Top 5 risks.

## Useful commands

```bash
npm run typecheck       # all workspaces
npm run lint            # all workspaces (when configured)
npm -w server run test  # server unit tests
```

## Cost watch

Every Routes API call costs ~$1 per 100 calls (Advanced w/ traffic). Two safeguards are wired in already:

- **Per-device rate limit**: 30 calls/hour, by `X-Device-Id` header
- **Hard budget cap per request**: `budget` parameter (default 8, max 10)

Daily budget kill-switch lands in Week 4 (BullMQ + cost alerts).

## What's next

See `~/.claude/plans/i-want-to-build-swirling-glade.md` Build Sequence table. Week 2 = Postgres + caching.
