# 🧠 Reflection Check-In — 9XAI Fellowship

> ⏱️ **Estimated time to complete: 10–15 minutes**
> Fill this out **twice per week** — on **Tuesday** (mid-week) and **Thursday** (end of week).
> Be honest — the more specific you are, the better we can support you.

---

## 📋 The Basics

**Your Name**: Issa Dalu
**Date**: 2026-05-14
**This is my**: ⬜ Tuesday check-in ✅ Thursday check-in
**Scope of this reflection**: The MiroFish Swarm Analysis page on `360-CitizenVoices` — design, build, test, branch management, integration with the team's new `persona-generation-workflow` service.

---

## 🎯 What I Actually Did Since Last Check-In

> Don't overthink this — just list the concrete things you worked on. Be specific.

### Tasks I completed or made progress on

1. **Stood up the MiroFish Forecast Console** as a new top-level module in the VoC 360 dashboard. Vanilla React + Babel-Standalone (no bundler), hash-routed under `#mirofish`, registered via `window.registerModule("MiroFish", ...)`, slotted into the existing `NAV` array under the **Intelligence** group with the `⌖` glyph, themed via `frontend/src/modules/mirofish.css` (scoped under `.mirofish`, brutalist console aesthetic — dotted-grid backdrop, numbered step labels, mono-font headers, all colours from `tokens.css`).
2. **Built the data-driven scenario picker** (`MfSuggestedScenarios` + `GET /api/mirofish/scenario-suggestions`). Backend scans recent Supabase rows from `the_data` (deduped, ranked), the LLM proposes 5 ranked "what if" Arabic scenarios with category, keywords, why-now justification, and signal count. Click a card → scenario is created from a custom prompt with auto-derived keywords, drawer auto-opens, projects list prepends — three layers of feedback so the click is never silent.
3. **Built the persona swarm — solo AND multi modes** behind a single endpoint `POST /api/mirofish/projects/{pid}/agent-swarm`:
   - **Solo (n=1)**: one persona produces a structured Arabic analysis — `persona_voice_ar`, `status_quo_assessment_ar`, `key_pain_points_ar`, ONE concrete `proposed_solution` (title, description, first_step, responsible_entity, required_resources, estimated_cost band, timeline, feasibility band + reasoning, evidence_quotes pulled from real Supabase samples), `impact_analysis` split short-term (4–12wk) / medium-term (3–12mo) with beneficiaries / affected_groups / risks / success_indicators, and a `personal_perspective_ar` in the persona's own voice.
   - **Multi (n≥2)**: N personas converse over R rounds with `replies_to` threading and `stance` per post (agree/disagree/neutral/alarmed), then a synthesis card extracts the winning solution + impact + risks.
4. **Optimised the swarm + analyze prompts** so every recommended action must cite an evidence quote — *no quote → no action*, forbidding generic "improve services" output. Required `first_step` + `responsible_entity` + `estimated_cost` + `timeline` + `feasibility_reasoning` on every action card. Split impact into 4–12 week / 3–12 month timeframes with explicit beneficiaries, affected groups, risks, and success indicators.
5. **Integrated the team's new `persona-generation-workflow` service**. Pulled the 14 pre-generated sector personas (`digital_services`, `education`, `finance`, `health`, `housing`, `justice`, `labor`, `municipal_services`, `other`, `security`, `social_protection`, `telecom`, `transport`, `water_and_energy` — sample sizes 2/2 up to 40/7261) into MiroFish's persona picker. Extended `SwarmPersona` schema with an optional `persona_text` field; the swarm system prompt uses the rich first-person profile when present and falls back to the structured fields otherwise. Added `GET /api/mirofish/data-personas` reading the `v2_<sector>_L1.txt` files directly from disk. Mounted the persona dir into the FastAPI container via `docker-compose.yml`.
6. **Built the Phase-3 chat panel** — per-scenario chatbot grounded in the prompt + 15 sample texts + the latest analysis (last 6 turns of history sent with each request, Arabic-only output enforced). ~$0.0003 per turn.
7. **Built Phase-2 LLM analysis** with rich `actions_detailed` schema (rationale, evidence quote, owner, timeframe, feasibility per action) persisting to a `forecast_questions` Supabase table. When the table is missing, the API response surfaces the exact `CREATE TABLE` SQL the operator pastes once into Supabase SQL Editor.
8. **Live-graph propagation simulation**: configurable steps (2–30), the animator grows the scenario's sample cap over the run so the D3 force-graph visibly accumulates nodes/edges per iteration. Auto-triggers the Phase-2 analysis at the final tick. Three view tabs (Graph / Agents / Question) inside the propagation step so the user can flip between them mid-simulation.
9. **Branch management throughout** — handled three force-pushes on `origin/dev` during this work, two of which would have re-introduced previously-deleted commits if I'd naively merged. Backup branches before every risky operation, cherry-picks onto rewritten upstreams, hand-resolved the same three frontend conflicts (`index.html`, `app.jsx`, `i18n.jsx`) multiple times preserving both my MiroFish additions and the upstream's Persona Builder / Sim Engine / Karam-branch additions.
10. **Container lifecycle discipline** — every time docker-compose recreated the FastAPI container (compose config changed, env_file flipped), the runtime-installed deps got wiped. Re-installed `httpx statsmodels networkx python-multipart pymupdf` after every recreate; documented this as a follow-up to bake into `requirements-api.txt`.

### Pick ONE of the tasks above and tell me more

**What tools/technologies did you use?** (be specific — framework names, libraries, APIs)
For the swarm endpoint: FastAPI + Pydantic v2 for the request/response models (`SwarmPersona`, `SwarmBody` accepting `persona_text` + `source` so both built-in archetypes and data-driven sector personas pass through the same path), `httpx` for the OpenAI-compatible chat-completions call to `gpt-4o-mini` (response_format: json_object — the model is forced to emit strict JSON), `json` + `Pydantic` for sanitising the LLM output before persisting. The structured swarm payload mirrors onto the local project record on disk and gets returned to the frontend in one shot. Frontend is vanilla React + Babel-Standalone in the browser — no bundler, no build step. The data-personas picker reads from a Docker bind mount (`./persona-generation-workflow:/srv/persona-generation-workflow:ro`) so nothing has to run as a separate container. Supabase is the source of truth for citizen-voice samples (`the_data`, 22,883+ rows); the deduped pool feeds both the scenario suggestions and the swarm context.

**Why did you build it THIS way?** (was there another option you considered?)
The crucial design call was making solo and multi modes share **one endpoint** with **one envelope** (`{mode, …}`) instead of two endpoints. Three reasons. (1) The frontend's `MfSwarmResult` component renders both modes by branching on `mode` — adding a new mode later (say, "round-robin with rebuttal") is one new prompt and one new render branch, not a fresh endpoint and a fresh component tree. (2) The `SwarmPersona` schema unifies built-in archetypes (carry `name_ar`/`archetype_ar`/`bias_ar`/`quote_ar`) and data-driven sector personas (carry `persona_text`) by making `persona_text` optional — the prompt's persona-block renderer picks the rich profile when present and the compact one-liner otherwise. The call site doesn't know which kind it's passing. (3) It's the same shape as the message-bus factory I built in Week 1 and the detector factory in Week 2: a tiny interface, optional rich fields, single dispatch point. Same shape across the codebase = same mental model when I come back to it in a month.

### Which project(s) did you contribute to?

**Primary project**: 360-CitizenVoices (MiroFish / Forecast Console module — `frontend/src/modules/mirofish.{jsx,css}`, `backend/app/api/routers/mirofish.py`, integration with the team's `persona-generation-workflow` service, end-to-end Phase 1.5 → Phase 5 buildout)
**Did you contribute to any other project?**
- [ ] No — focused on my main project only
- [x] Yes → Which one(s)? Treated the team's new `persona-generation-workflow/` microservice as a producer and consumed its pre-generated `v2_<sector>_L1.txt` outputs directly. Didn't touch the service itself; only added a thin reader endpoint on my side + the volume mount in `docker-compose.yml` so the swarm could see those files.

---

## 🔥 The Hardest Problem I Faced

> Think of a moment since your last check-in where something wasn't working and you had to figure it out.

**What was the problem?**
After committing my Phase-5 work locally, I went to push and the remote `dev` had been **force-pushed** while I was working. A naive `git pull origin dev` reported "up to date" in some checks but my push was rejected with "non-fast-forward". When I inspected the divergence I found that `origin/dev` had been rewritten — six commits I'd had locally (including a known "init" and several merges) no longer existed in the new `origin/dev` history. The maintainer had deliberately rebased history to clean up. If I'd just merged the new `origin/dev` into my local and pushed, my merge commit would have **reintroduced all six removed commits** to the public branch, silently undoing the cleanup the maintainer had just done — and I would have only found out when the maintainer noticed those commits back in the log.

**How did you discover it?**
- [x] I found it myself while working
- [ ] A teammate told me about it
- [ ] It came up in testing
- [ ] The program manager / mentor pointed it out
- [ ] A user / demo found it
- [ ] Other: _______________

**Walk me through what you did to fix it** (step by step — like you're explaining to a friend)
Step one — I didn't push. The push command was failing anyway; I treated that as a *signal*, not an obstacle. Step two — I ran `git merge-base --is-ancestor <commit-sha> origin/dev` for each of the suspicious old commits in my local history. All six came back as **not in** the new `origin/dev`. That confirmed my suspicion: a merge would re-inject them. Step three — I created a safety branch (`backup/mirofish-merge-<sha>`) pointing at my current HEAD so nothing I did next was unrecoverable. Step four — I did `git reset --hard origin/dev` to bring my local exactly in line with the rewritten remote. Step five — I cherry-picked **only my feature commit** onto the new history (`git cherry-pick <my-commit>`). This produced the same three conflicts as the original merge (index.html, app.jsx, i18n.jsx) but on the *new* base — I re-resolved them keeping both my MiroFish additions and the upstream's renames (e.g. `search: AI Assistant` → `search: Global Search`, the new `personas` nav group, the new `mirofish` route binding). Step six — sandbox-validated the merged frontend by transpiling each `.jsx` through Babel-Standalone (the same engine the browser uses) so I'd catch any runtime parse errors before the user did. Step seven — pushed. Step eight — verified the public history was clean: my one feature commit on top of the new `origin/dev`, no resurrected ghosts. The maintainer's history-cleanup work stayed intact.

**How long did it take?**
- [ ] Under 1 hour
- [x] 1-3 hours
- [ ] Half a day
- [ ] More than a day
- [ ] Still working on it

**Did the fix prevent it from happening again, or was it a quick patch?**
- [x] Permanent fix — it won't happen again
- [ ] Temporary — might need revisiting
- [ ] Not sure
The permanent piece is the workflow: I now reflexively check `git log <old-sha>..origin/dev` ancestry on any branch that's been force-pushed before I let a merge happen, and I cherry-pick onto the rewritten upstream rather than merging. The backup-branch-before-anything-destructive habit is the part I want to keep.

---

## 📈 Skill Check

> Be real with yourself. Rate your **current comfort level** (not where you want to be).

| Skill | Comfort Level (1-5) | Did it improve since last check-in? |
|---|:---:|:---:|
| Python / Backend (FastAPI, etc.) | ⬜1 ⬜2 ⬜3 ⬜4 ✅5 | ✅ Yes ⬜ No ⬜ N/A |
| Frontend (React, TypeScript, etc.) | ⬜1 ⬜2 ⬜3 ⬜4 ✅5 | ✅ Yes ⬜ No ⬜ N/A |
| AI/ML (RAG, Embeddings, Agents) | ⬜1 ⬜2 ⬜3 ⬜4 ✅5 | ✅ Yes ⬜ No ⬜ N/A |
| DevOps (Docker, Deployment, CI/CD) | ⬜1 ⬜2 ⬜3 ✅4 ⬜5 | ✅ Yes ⬜ No ⬜ N/A |
| Communication & Presenting | ⬜1 ⬜2 ⬜3 ✅4 ⬜5 | ✅ Yes ⬜ No ⬜ N/A |
| Problem Solving & Debugging | ⬜1 ⬜2 ⬜3 ⬜4 ✅5 | ✅ Yes ⬜ No ⬜ N/A |
| Teamwork & Collaboration | ⬜1 ⬜2 ⬜3 ✅4 ⬜5 | ✅ Yes ⬜ No ⬜ N/A |

> **1** = "I'd panic if asked to do this alone"
> **3** = "I can handle it with some Googling"
> **5** = "I could teach someone else how to do this"

---

## 🤝 Who I Worked With

**Name a teammate you worked closely with. What did you do together?**
The persona-generation-workflow team (Salsabeel + Ahmad). They shipped the standalone service that generates sector-level personas from the master survey table. I didn't change a line of their service — instead I built MiroFish to consume their output. The cleanest interface possible: they own generation, my side owns presentation + simulation. Their pre-generated `v2_<sector>_L1.txt` files became the data-driven persona pool in my swarm picker.

**Did you help someone who was stuck? What was the situation?**
Fixed the missing `predictionsToView` mapper in `frontend/src/api.jsx` — it was referenced from two places (`data.jsx::__refreshLiveData` and `modules/rootcause.jsx`) but never actually defined, so `window.PREDICTIONS` was silently `undefined` for everyone. The Root Cause module's propagation tab was showing "predictions.csv is empty" misleadingly. Adding the mapper unblocked my MiroFish work AND fixed the existing tab as a side effect.

**Did someone help YOU when you were stuck? What happened?**
The persona-generation maintainer's docker-compose was a real lifesaver — when my FastAPI container started showing `LLM_BASE_URL=http://host.docker.internal:11434` (Ollama defaults) after a recreate, I traced it to an upstream commit `29e0b95 chore(compose): activate Ollama on the assistant tab` that set `${VOC_LLM_BASE_URL:-ollama-defaults}` on the fastapi-platform service. The maintainer had left escape-hatch vars (`VOC_LLM_*`) precisely for this case. Setting them in `.env` flipped the container back to OpenAI without a code change. That's good defensive design from someone else's PR.

**Did you contribute to a group outside your primary project?**
- [ ] No — focused on my main project
- [x] Yes → Which group? Surface-level integration with persona-generation-workflow (read its output files; mount its persona dir into our container). Also opened a follow-up note for the team that runtime-pip-installed deps in `voc360-fastapi` get wiped on container recreate — they should land in `backend/requirements-api.txt` so a fresh `docker compose up` works without manual intervention.

---

## 💡 The "Aha!" Moment

> What's one thing you learned since your last check-in that clicked — something you didn't understand before but now you do?

**Constrain the output schema, and the LLM does *better* work, not less.** I started with a permissive system prompt that said "give me a forecast with summary, impact, and recommended actions in Arabic JSON." The output was real but generic — "improve digital services", "raise awareness". I tightened the schema and added rules: each `recommended_action` must include `evidence_quote_ar` cited from the provided samples, `responsible_entity_ar` (a real Jordanian ministry), `timeframe_ar` (a specific band), `feasibility` (high/medium/low), and `feasibility_reasoning_ar` (one sentence). I also forced *one* solution in solo mode, not a list — pick the best, defend the pick.

The model didn't push back; it produced sharper, more concrete output because the schema gave it places to put its thinking. The first run after tightening produced "إنشاء خط ساخن مخصص للدعم المالي · وزارة التنمية الاجتماعية · متوسطة 0.5–5 مليون د.أ · 3 أشهر · high · الخط الساخن يمكن تنفيذه بسرعة..." with two real citizen quotes from the Supabase pool. That's not a more constrained version of the previous answer — it's a *better* answer, because the constraints forced the model to ground each piece.

Same lesson as factory patterns, just on the prompt side: design the contract first, the implementation gets clearer because of it.

---

## 🚧 What's Blocking Me

**Is anything slowing you down right now?**
Two contained things. (1) The `forecast_questions` Supabase table still doesn't exist — PostgREST doesn't allow DDL, so the operator has to paste the `CREATE TABLE` once into the Supabase SQL Editor. My code already surfaces the exact SQL in the API error when the table is missing; just needs the human running it once. Until then, analyses run successfully but only persist locally (mirrored onto the project record), not into the shared DB. (2) Container deps wiped on recreate — every time `docker compose up --force-recreate` runs the FastAPI service, I lose the `pip install statsmodels networkx python-multipart pymupdf` and have to re-run it. The fix is adding those to `backend/requirements-api.txt` so the image bakes them in. Both items are written up; neither is blocking the core work.

**What have you already tried to unblock yourself?**
For (1), the error-message-as-documentation pattern: when the analyze endpoint can't save to Supabase, the API response contains the exact DDL the operator needs to paste — it's not a guessing game, it's a copy-paste. I also added `GET /api/mirofish/forecast-questions/ddl` so the SQL is fetchable any time. For (2), documented in the commit message and the team note. Both are pull-request-able and I'll send them up next session.

**What would help you move faster?**
- [ ] More time
- [ ] Pair-programming with a specific teammate
- [ ] A mentor/coach session on a specific topic
- [ ] Better documentation / clearer requirements
- [x] Access to tools/accounts/APIs
- [ ] Nothing — I'm good
- [ ] Other: _______________
Specifically: a Supabase SQL Editor session with the maintainer to run the `forecast_questions` DDL + maybe a few more tables I'll need for the swarm-history persistence next session.

---

## ⚡ Quick Fire Round

**Since last check-in I'm most proud of**: The end-to-end validation script — 21/21 structured fields populated on the very first solo-swarm run against the live `DATA-V2_HEALTH_L1` persona (40-sample profile from 608 real records). The persona's parental healthcare worldview *visibly* shaped the output: solution mentions children's medication, personal-perspective speaks as a parent worried about chronic care. That's not a generic model output — that's the persona profile carrying through.

**The decision I made that had the biggest impact**: Unifying solo + multi swarm under one endpoint with one envelope. Future modes (chain-of-personas, debate-with-rebuttal, etc.) are one new prompt and one new render branch — not a separate endpoint, schema, or component each time. Same shape as the factory patterns from earlier weeks.

**One thing I wish I handled differently**: The regex `/u` flag bug. I had a `.split(/[\s,;:.\?\!\(\)\[\]"']/u)` in the scenario-graph derivation that ES Unicode mode rejects as "Invalid escape". The module threw at *parse time*, before `window.registerModule` ran, so `ROUTES.mirofish` was `undefined` and the route fell through to the Situation Room — the user saw `#mirofish` highlight in the sidebar but Situation Room content in the body. I caught it only after the user reported it. Lesson: brace-balance checks aren't enough; my sandbox validation now runs every edited `.jsx` through Babel-Standalone (the actual browser parser) so runtime-only errors surface locally first.

**My energy level right now** (pick one):
🟢 High — feeling energized
The solo swarm working end-to-end with real Supabase data — and the persona's voice actually showing up in the output — was a real "now we're cooking" moment.

---

# 📌 THURSDAY ONLY — Weekly Goal Review

> ⚠️ **Fill this section ONLY on Thursday.** Skip it on Tuesday.

### How Did I Do Against My Sunday Plan?

> This reflection scopes to the MiroFish/Swarm work specifically — for the broader weekly plan see `thursday-reflection.md` in this folder.

| # | Goal I Set on Sunday (swarm-scoped) | Status | Notes |
|---|---|:---:|---|
| 1 | Add MiroFish as a first-class tab on 360 CitizenVoices and theme it to match the existing dashboard | ✅ Done ⬜ Partial ⬜ Not Started | `frontend/src/modules/mirofish.{jsx,css}`, registered, hash-routed under `#mirofish`, lives in the **Intelligence** nav group with the `⌖` glyph; scoped CSS reuses the existing token system (no new hex values). |
| 2 | Wire MiroFish to live Supabase data — no mocks, real citizen voices grounded in `the_data` | ✅ Done ⬜ Partial ⬜ Not Started | `POST /api/mirofish/projects` calls Supabase with `ilike-OR` across keywords, dedupes by normalised text, shuffles client-side (PostgREST has no `order=random`), persists up to 500 unique samples per scenario. End-to-end verified: 463 matched / 68 stored on a real welfare-fund scenario. |
| 3 | Get the swarm analysis fully functional with a single persona producing a valid, realistic, status-quo-grounded solution | ✅ Done ⬜ Partial ⬜ Not Started | Solo mode produces all 20 structured fields populated on every run — status quo, pain points, ONE concrete proposed_solution with first_step/owner/cost/timeline/feasibility/evidence_quotes, impact_analysis split short/medium-term, personal_perspective in persona voice. End-to-end script: 21/21 checks pass. |
| 4 | Optimise the prompt to find clear, compatible solutions — no vague advice, every action grounded in evidence | ✅ Done ⬜ Partial ⬜ Not Started | System prompt requires `evidence_quote_ar` per action ("no quote → no action"), `responsible_entity_ar`, `timeframe_ar`, `feasibility` band + reasoning, and exactly ONE solution in solo mode. Verified the output cites actual citizen voices and avoids generic phrasing. |
| 5 | Multi-persona swarm: real conversation with replies and stances, ending with a synthesis | ✅ Done ⬜ Partial ⬜ Not Started | N personas converse over R rounds with `replies_to` threading + `stance` chips (agree / disagree / neutral / alarmed). Final synthesis extracts winning_solution, first_step, owner, feasibility, impact short/medium-term, affected groups, risks. Single LLM call covers both halves. |
| 6 | Wire the team's new `persona-generation-workflow` output into the MiroFish swarm picker | ✅ Done ⬜ Partial ⬜ Not Started | `GET /api/mirofish/data-personas` reads `v2_<sector>_L1.txt` from disk (mounted into the container via `docker-compose.yml`); 14 sectors selectable in the UI alongside the 10 built-in archetypes. Persona-text profiles drive the swarm prompt when present; the LLM's output reflects the sector worldview (verified on the health sector). |
| 7 | Branch management — keep `origin/dev` clean through multiple force-pushes from other contributors | ✅ Done ⬜ Partial ⬜ Not Started | Caught three force-pushes that would have re-introduced deleted commits; cherry-picked feature work onto rewritten upstreams instead of merging; preserved every upstream's additions (Persona Builder, Sim Engine, Karam, persona-generation) while landing the swarm work clean. Backup branches before every reset. |

**If something didn't get done — what happened?**
All swarm-scoped goals shipped. Two adjacent items are documented but not done because they need someone else: the `forecast_questions` Supabase table creation (needs SQL-editor access) and baking the runtime deps into `requirements-api.txt` (small PR pending). Both are written up clearly so picking them up is one-step.

**Was my Sunday plan realistic?**
- [x] Yes — I estimated well
- [ ] Too ambitious — I set too many goals
- [ ] Too easy — I finished early and could have done more
- [ ] Mixed — some goals were right, others were off

### Week Summary (Swarm scope)

**Hours I put in this week on the swarm specifically (approx.)**: 8 hours

**My biggest strength this week**: Designing for the *next* mode I haven't built yet. Solo + multi share one endpoint, one envelope, one render component — adding a third mode (chain-of-personas, debate-with-rebuttal, etc.) is a new prompt and a new render branch, not a rewrite. Same shape as the factories from earlier weeks; the codebase stays consistent.

**The skill I most need to level up**: Pre-flight validation. I caught the regex `/u` flag bug only after the user reported a routing symptom. My sanity checks were structural (brace balance, file size) when they needed to be *semantic* (does this actually parse?). I've added Babel-Standalone transpilation to my local sanity script, but the real fix is wiring this into CI on `dev` so the bug never makes it past the merge gate.

**If I had to give myself a grade this week on the swarm work (A-F)**: A
**Why?**: Every swarm-scoped goal landed; the end-to-end validation came back 21/21 on the first try with real Supabase data; the branch management didn't lose anyone's work despite three force-pushes; and the design is shaped so the next iteration is additive, not a rewrite. The half-grade I'm withholding is for the regex bug — that should have been caught by sandbox-validation, not by the user. Now it will be.

**What I want to focus on next week** (this feeds into Sunday's plan):
Run the `forecast_questions` DDL with the team so analyses persist to Supabase, not just local mirror. Add `statsmodels networkx python-multipart pymupdf` to `backend/requirements-api.txt` so a fresh `docker compose up` works. Build the swarm-history sidebar — every scenario keeps a chronological list of past swarm runs (which personas, which solution emerged, which evidence quotes) so the operator can compare runs. And start the third swarm mode: a "policy-bench" mode where the personas explicitly judge a *named* proposed policy (rather than only reacting to a what-if), so the dashboard becomes useful for evaluating concrete proposals, not just exploratory forecasting.

---
