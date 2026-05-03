# Traffic API Cost & Caching Report

**Project:** traffic-intel (Wadi Saqra PoC, Phase 3)
**Date:** 2026-05-03
**Scope:** Compare Google Maps Platform vs Mapbox for live traffic ingestion, model cost across polling intervals, design a caching strategy that keeps the bill near $0 as we scale corridors.

---

## 1. Executive summary

- **Today the project pays $0** for traffic data. `phase3-fullstack/.../poc_wadi_saqra/fusion.py` loads a pre-fetched Google Maps CSV (`load_gmaps`) — there is no live API call in the running stack. Any live polling we add is **net new spend**.
- At realistic intervals (≥5 min) for a single corridor, **both Mapbox and Google fit inside their free tiers**. The choice is about scale and switching cost, not steady-state $.
- **Mapbox is ~3× cheaper at heavy poll rates and has a 20× larger free tier** (100k vs ~5k requests/month).
- **Sub-minute polling is wasted spend.** Mapbox refreshes live speed every ~5 min; Google's traffic engine updates on a similar cadence. 1-Hz polling is 60–300× more cost for the same data.
- **A two-layer cache (in-process LRU + Redis) with a 60–120 s TTL plus request coalescing reduces upstream API calls by 95–99 %** for typical web workloads. That's the lever that keeps cost near zero as corridors and concurrent users grow.

---

## 2. Current state

| Component | Reality |
|---|---|
| `fusion.py:load_gmaps` | Loads pre-saved `gmaps_*.csv` from disk. Static. |
| `forecast_ml_artifacts.md` (memory) | LightGBM trained on Google-anchored history. No runtime calls. |
| `signal_plan_field_observation.md` (memory) | 3-phase NS/E/W timing is a fixed plan. Doesn't depend on API. |
| Live API keys in code | None for traffic providers. Only Anthropic key for the optional LLM advisor. |

**Implication:** every cost figure below is for a *new* live-polling capability we'd add (e.g., a "Live signal advisor" that re-tunes phase timing every N minutes against current Mapbox/Google congestion).

---

## 3. Pricing reference (May 2026)

### Mapbox — Directions API (`profile=driving-traffic`, `annotations=congestion_numeric`)

| Volume / month | $ per 1,000 calls |
|---|---|
| 0 – 100,000 | **free** |
| 100,001 – 500,000 | $2.00 |
| 500,001 – 1,000,000 | $1.60 |
| 1,000,001 – 5,000,000 | $1.20 |
| 5M+ | sales |

Returns: per-segment `congestion` class (low/moderate/heavy/severe) **or** `congestion_numeric` 0–100.
Rate limit: 300 req/min on the public token (higher with enterprise).

### Google — Routes API, Compute Routes Pro, `routingPreference=TRAFFIC_AWARE_OPTIMAL`

| Volume / month | $ per 1,000 calls |
|---|---|
| 0 – ~5,000 (Pro free SKU credit) | **free** |
| up to 100,000 | $10.00 |
| 100,001 – 500,000 | $8.00 |
| 500,001 – 1,000,000 | $6.00 |
| 1,000,001 – 5,000,000 | $3.00 |
| 5M+ | $0.75 |

Returns: ETA + `trafficUnaware` vs `trafficAware` duration delta (we derive congestion ratio from this).
Rate limit: project-default 600 req/min, increasable on request.

> Free-tier note: Google replaced the old $200/mo credit with per-SKU free monthly caps in March 2025. Pro SKUs (which include traffic-aware) currently get ~5,000 free events/month per project. The exact figure shifts; treat as "small" not "100k".

---

## 4. Polling-interval usage model

Single endpoint, 30-day month:

| Interval | Calls / month |
|---|---|
| 1 sec | 2,592,000 |
| 1 min | 43,200 |
| 5 min | 8,640 |
| 10 min | 4,320 |
| 30 min | 1,440 |

For *N* corridors polled at the same interval, multiply by *N*.

---

## 5. Cost matrix

### 5.1 Single endpoint (one corridor)

| Interval | Mapbox / mo | Google / mo | Δ |
|---|---|---|---|
| 1 sec | **~$3,510** | **~$11,930** | Google 3.4× |
| 1 min | **$0** (in free) | **~$382** | — |
| 5 min | **$0** | **~$36** | — |
| 10 min | **$0** | **$0** (in free) | — |
| 30 min | **$0** | **$0** | — |

### 5.2 Five corridors (Wadi Saqra + 4 future intersections)

| Interval | Calls/mo (5×) | Mapbox / mo | Google / mo |
|---|---|---|---|
| 1 sec | 12.96M | ~$13,150 | ~$50,700 |
| 1 min | 216,000 | ~$232 | ~$1,838 |
| 5 min | 43,200 | $0 | ~$382 |
| 10 min | 21,600 | $0 | ~$166 |
| 30 min | 7,200 | $0 | ~$22 |

### 5.3 Twenty corridors (full Amman pilot scope)

| Interval | Calls/mo (20×) | Mapbox / mo | Google / mo |
|---|---|---|---|
| 1 min | 864,000 | ~$1,824 | ~$8,162 |
| 5 min | 172,800 | ~$146 | ~$1,678 |
| 10 min | 86,400 | $0 | ~$814 |
| 30 min | 28,800 | $0 | ~$238 |

**Free tiers are per *account*, not per corridor.** That's why "5 corridors @ 1 min" lands at $232 on Mapbox even though "1 corridor @ 1 min" is $0 — the combined 216k req/mo blows past the 100k free band.

---

## 6. Caching strategy — the actual cost-reduction lever

### 6.1 Why traffic data caches very well

- **Upstream refresh cadence** is ~5 minutes on both platforms. A query at *t* and *t+30 s* return statistically identical congestion values. Sub-5-min polling buys nothing.
- **Spatial reuse:** any user looking at the Wadi Saqra dashboard hits the same corridor query. *N* concurrent SPA users → 1 upstream call if cached.
- **Idempotent inputs:** corridor `(origin, destination, mode)` is a stable cache key. No personalization, no auth scope.

### 6.2 Two-layer cache architecture

```
[FastAPI handler]
       │
       ▼
[L1: in-process LRU]   ← per-worker, ~10 ms hit, 30–60 s TTL
       │ miss
       ▼
[L2: Redis / SQLite]   ← shared across workers, 60–300 s TTL
       │ miss
       ▼
[Single-flight gate]   ← coalesces concurrent misses into ONE upstream call
       │
       ▼
[Mapbox / Google API]  ← billable
       │
       ▼
[Long-tail store]      ← every successful response also archived for ML retraining
```

### 6.3 TTL design — match the upstream refresh

| Data type | Recommended TTL | Justification |
|---|---|---|
| Live congestion class | **90 s** | Below upstream 5-min refresh; covers brief network blips. |
| Live ETA / numeric ratio | **60 s** | A bit fresher; the advisor's Webster timing is sensitive to ratio. |
| "Typical" baseline (Mapbox `driving-traffic` no-departure) | **24 h** | Day-of-week × time-of-day lookup; rebuilds nightly. |
| Stale-while-revalidate window | TTL × 2 | Serve old value, refresh async — protects against latency spikes and quota errors. |

A 90 s TTL on a 1-min poller means **~33% of polls hit upstream**, the rest serve from cache. Combined with single-flight, real upstream rate is bounded to ⌈60/TTL⌉ ≈ 40/hour per corridor regardless of how many users are watching.

### 6.4 Request coalescing (single-flight)

Without it: 50 concurrent dashboard tabs at TTL expiry → 50 simultaneous upstream calls.
With it: the first miss locks a per-key future, the other 49 await it → **1 upstream call**.

Rough Python sketch (asyncio):

```python
_inflight: dict[str, asyncio.Future] = {}

async def get_congestion(key: str) -> Congestion:
    if (cached := await cache.get(key)) is not None:
        return cached
    if key in _inflight:
        return await _inflight[key]
    fut = asyncio.get_event_loop().create_future()
    _inflight[key] = fut
    try:
        value = await upstream_fetch(key)
        await cache.set(key, value, ttl=90)
        fut.set_result(value)
        return value
    finally:
        _inflight.pop(key, None)
```

### 6.5 Long-tail historical cache → free baseline

Every successful upstream response is **also** archived (Parquet/SQLite) keyed by `(corridor, iso_minute_of_week)`. After ~1 week of polling 5 corridors at 5 min, you have ~10k congestion samples — enough to:

- Serve a **"typical Tuesday 3pm" lookup** from local disk (zero API cost) for the dashboard's historical charts.
- **Retrain the LightGBM forecaster** (`forecast_ml_artifacts.md`) on the broader sample, which is what the project already does.
- Detect "now vs typical" anomalies without paying for both — only the live call is billed; "typical" is free from your own archive.

This is the same pattern Mapbox sells as their Enterprise "Typical Traffic" product; you can synthesize a project-specific version for the corridors you actually care about.

### 6.6 Negative caching

When upstream returns 429 / 5xx, cache the failure for 30 s with a short TTL. Without this, a quota burst causes a thundering-herd retry storm that 10× the bill on the recovery minute.

---

## 7. Cost reduction projection — caching applied

Assume **5 corridors, 5 dashboard users concurrently, polling cycle = 1 min from the client side** (the most expensive realistic config we'd actually run).

Without caching: 5 corridors × 5 clients × 60 polls/hr × 24 h × 30 d = **1,080,000 calls/mo**.
- Mapbox: 100k free + 400k×$2 + 500k×$1.60 + 80k×$1.20 ≈ **$1,696/mo**
- Google: 5k free + 95k×$10 + 400k×$8 + 500k×$6 + 80k×$3 ≈ **$7,390/mo**

With L1 + L2 + single-flight (90 s TTL, deduped across users):
- **Effective upstream rate per corridor: 1 call per 90 s = ~29,200 calls/mo**
- 5 corridors × 29,200 = **146,000 calls/mo**
- Mapbox: 100k free + 46k×$2 = **$92/mo** (95 % cheaper)
- Google: 5k free + 95k×$10 + 46k×$8 = **$1,318/mo** (82 % cheaper)

Add the long-tail "typical" cache (replaces ~30 % of live calls with archive lookups when the user is browsing historical charts):
- Mapbox: ~**$36/mo**
- Google: ~**$870/mo**

| Stack | No cache | + L1/L2 cache | + long-tail cache | Total reduction |
|---|---|---|---|---|
| Mapbox | $1,696 | $92 | **$36** | **98 %** |
| Google | $7,390 | $1,318 | **$870** | **88 %** |

The same caching layer applied to the 1-Hz scenario brings Google from $11,930/mo down to ~$1,300/mo for a single corridor — the savings *grow* with poll rate because cache hit-rate goes up.

---

## 8. Implementation plan (incremental, low risk)

1. **Add a `traffic_provider` abstraction** in `phase3-fullstack/src/traffic_intel_phase3/poc_wadi_saqra/` — interface returns `(congestion_numeric, eta_seconds, source, fetched_at)`. Two impls: `MapboxProvider`, `GoogleProvider`. Existing `load_gmaps` stays as a third impl: `CsvProvider` (default; preserves current $0 behavior).
2. **Wrap with `CachedProvider`** — `aiocache` with in-memory backend by default; swap to Redis when we scale past one worker.
3. **Single-flight decorator** on the cache miss path.
4. **Archive sink** — every upstream success appends to `data/traffic_archive.parquet`. Roll daily, retain 90 d.
5. **Config knobs** in `configs/traffic.yaml`:
   ```yaml
   provider: csv  # csv | mapbox | google
   poll_interval_seconds: 300
   cache_ttl_seconds: 90
   stale_while_revalidate: true
   archive_enabled: true
   ```
6. **Cost guardrails** — startup check that estimates monthly call volume from config and **logs a warning** if it would exceed a configurable `max_monthly_spend_usd`. Hard-stop at 2× budget.

---

## 9. Recommendation

| Decision | Recommendation |
|---|---|
| Switch from CSV to live? | **Not yet.** The current static Google CSV gives free baseline. Add live as a feature-flagged enhancement, not a replacement. |
| Mapbox or Google for live? | **Mapbox** for any net-new live work — 3× cheaper, 20× larger free tier, exposes congestion class natively. |
| Polling interval | **5 min from client; 90 s effective upstream after caching.** Sub-minute polling is wasted spend and provides no data benefit. |
| Caching priority order | (1) L1 LRU + single-flight, (2) Redis L2 when scaling workers, (3) long-tail archive for "typical" lookups, (4) negative caching for 429/5xx. |
| Budget guardrail | Hard-cap `$50/mo` until 5+ corridors are wired up; revisit at scale. |

**Bottom line:** with caching done right, even the 20-corridor / 1-min scenario stays under **$50/mo on Mapbox** and under **$300/mo on Google**. Without caching, those same configs cost $1.8k–$8k/mo. The caching layer pays for itself in the first day of operation.

---

## Appendix A — assumptions

- 30-day month, uniform request rate.
- Free tier consumed entirely by this project (no other traffic-API workloads on the same account).
- Google Pro SKU free credit ≈ 5,000 / mo (verify at signup; Google adjusts these).
- Mapbox public-token rate limit 300 req/min — sufficient for ≤5 corridors at 1 min.
- Latency budget per dashboard frame: 250 ms p95. Both providers are ~80–150 ms; cache hits ~10 ms.

## Appendix B — sources

- [Mapbox Pricing](https://www.mapbox.com/pricing)
- [Mapbox Directions API — congestion annotations](https://docs.mapbox.com/api/navigation/directions/)
- [Google Maps Platform pricing](https://developers.google.com/maps/billing-and-pricing/pricing)
- [Routes API usage & billing](https://developers.google.com/maps/documentation/routes/usage-and-billing)
- [Google Maps Platform 2025 pricing-change FAQ](https://developers.google.com/maps/billing-and-pricing/faq)
