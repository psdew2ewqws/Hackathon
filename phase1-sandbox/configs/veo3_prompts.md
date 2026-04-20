# Veo 3 Prompts — Phase 1 CCTV Source Generation

Use these prompts with Google Veo 3 to generate fixed-CCTV style traffic footage. The output drops into `data/raw/veo3/` and is consumed by `make veo3-ingest`.

## Prompt constraints that matter

Veo 3 tends to add motion and scene changes when prompts are ambiguous. These constraints keep the output usable:

- **Camera: fixed, mounted on a pole, ~8 m elevation, tilted down 30°.** Repeat explicitly: *"The camera does NOT move or pan throughout the entire clip."*
- **Angle: elevated three-quarter view**, not first-person.
- **Aspect/resolution: 16:9, 1920×1080.**
- **No on-screen text, logos, or UI overlays.**
- **No dramatic lighting changes** (sunset/sunrise) within a single clip — Phase 1 wants stable conditions.

## Scene 1 — Daytime, light traffic

```
High-angle fixed CCTV traffic camera view of a four-approach urban
intersection with traffic signals. Camera mounted 8 meters high on a
pole, angled down 30 degrees, looking south across the intersection.
Wide field of view showing all four approaches with stop lines,
crosswalks, and the central conflict zone. Each approach has 3-5 lanes
including through, left, and right turn lanes with painted arrows.
Clear daytime weather, sunny, mid-morning. Light urban traffic:
6-10 sedans, 2 SUVs, 1 city bus, 2 motorcycles moving through with
signal cycle changes visible. Vehicles follow lane markings and obey
signals. The camera does NOT move or pan. Surveillance camera aesthetic,
slight lens distortion, sharp focus on the roadway.
```

## Scene 2 — Daytime, heavy peak traffic

Same as Scene 1 but:
- Replace light traffic with: `dense peak-hour traffic with queuing at red lights, 20-30 visible vehicles across all approaches, mix of sedans, SUVs, taxis, motorcycles`.

## Scene 3 — Night, streetlit moderate traffic

Same as Scene 1 but:
- Replace daytime with: `night time, after 10 PM, sodium and LED streetlights illuminating the intersection, dark sky, car headlights and tail lights visible`.

## Scene 4 — Rain, day

Same as Scene 1 but:
- Add: `light to moderate rain, wet asphalt reflecting signals, visible rain streaks, vehicles driving more slowly`.

## Scene 5 — Incident: stalled vehicle

Same as Scene 1 but:
- Add: `one sedan stalled in the middle of the eastbound through lane, hazard lights blinking, other vehicles swerving around it, signals cycling normally`.

## Scene 6 — Incident: queue spillback

Same as Scene 1 but:
- Add: `severe congestion on the southbound approach, queue of stopped vehicles extending far back from the stop line past the upstream camera edge, vehicles on other approaches moving normally`.

## Filename convention

Save each clip as `veo3-SS-<scene_slug>.mp4` — e.g. `veo3-01-day-light.mp4`, `veo3-05-stalled.mp4`. The slug becomes the traceable identifier in `methodology.md`.

## Target pack

- **Minimum for Phase 1 demo:** 2 scenes (day-light + day-heavy), ≥ 24 s total.
- **Recommended:** all 6 scenes, 48+ s total → gives enough variety for Phase 2 edge-case testing.
- **Bonus:** multiple clips per scene with slight prompt variations → better dataset diversity.
