# 🧠 Reflection Check-In — 9XAI Fellowship

> ⏱️ **Estimated time to complete: 10–15 minutes**  
> Fill this out **twice per week** — on **Tuesday** (mid-week) and **Thursday** (end of week).  
> Be honest — the more specific you are, the better we can support you.

---

## 📋 The Basics

**Your Name**: Issa Dalu  
**Date**: 2026-05-14  
**This is my**: ⬜ Tuesday check-in ✅ Thursday check-in

---

## 🎯 What I Actually Did Since Last Check-In

> Don't overthink this — just list the concrete things you worked on. Be specific.  
> ❌ Bad: "Worked on the project"  
> ✅ Good: "Built the JWT auth system with bcrypt + 24h token expiry"

### Tasks I completed or made progress on

1. Owned the GitHub branch model for 360 CitizenVoices and ran the integration: settled the repo on `main` (release snapshot) / `dev` (integration) / `backend` / `frontend` / `persona_service`, with everyone branching off the relevant lane and PR-ing back. Over the sprint I merged on the order of 170+ PRs and the recurring `backend → dev` / `frontend → dev` integration merges (`Merge backend branch into dev — FastAPI platform + p1/p2/p4/p5/p6 routers + frontend↔FastAPI wiring`, `Merge frontend branch into dev — bring the live-wired dashboards in`, `Merge dev into main — release snapshot of the integrated platform`), plus the long-lived contributor merges (`karam`, `yaman`, `hasasneh`, `Ali-Backend`, …).
2. Did the structural surgery: collapsed the project into a proper monorepo (`feat: monorepo structure + full-stack integration (backend ↔ frontend)`), removed the duplicated dirs at the repo root (`Clean up: remove duplicated dirs at root (kept under backend/)`), and consolidated a root-level duplicate frontend down to a single canonical `frontend/` (`refactor: consolidate to single frontend/ — remove root-level duplicate`).
3. Wired the dashboard to live data: pointed `frontend/src/api.jsx` at the Flask pipeline API (`:5050` — `/api/priority-queue`, `/api/spikes`, `/api/root-causes`, `/api/runs`) and the FastAPI services, ripped out the mock-data layer (`feat: wire dashboards to the unified FastAPI backend (live data)`), fixed router-compat breakage after the merge (`Fix merged FastAPI router compatibility`), and added the live KPI page (`feat(frontend): restore live-wired dashboard under frontend/ + new live KPI page`).
4. Wired the persona engine end-to-end: `Wire #personas page to classification_service (FastAPI :8000)` → `Wire personas to Supabase data + heuristic classifier + deep analysis`, including the `#personas` console redesign (`Redesign #personas page — refined console aesthetic`) and cache-busting `?v=` on `tokens.css` / `api.jsx` / `personas.jsx` so the browser-Babel app actually picks up changes.
5. Containerised the stack: Dockerfiles + a root `docker-compose.yml` orchestrating the frontend, the Flask pipeline API, the preprocessor, the root-cause job, the simulation microservice, and the classification service; `feat: containerise the unified FastAPI platform (:8001) + pipeline analysis doc`.
6. Hardened the runtime: vendored React / ReactDOM / Babel / Firebase locally so the frontend has **no** external CDN dependency at runtime (`fix: vendor React/ReactDOM/Babel/Firebase locally`); batched the Supabase ingest (commit every 250 rows, paginate fetches of 1000) after a per-row commit kept getting rate-limited (`ingest: paginate Supabase fetches + batch DB commits`, `feat(p1): incremental Supabase ingest with checkpoint and sync report`); reverted a bad live-data merge that blanked the app and re-landed it cleanly (`Fix blank app: revert dev/frontend/ live-data rewrite to the last working state`).
7. Documentation pass: the comprehensive top-level `README.md` (service-and-port map, branch model, quick-start, known-issues/cleanup TODO — 229 lines), `docs/unified-pipeline-runbook.md` (589 lines), `docs/pipeline-analysis.md`, the production-delivery workstream plan, and committing `classification_service/.env` non-secret config so the team had a working baseline.

### Pick ONE of the tasks above and tell me more

> This helps us understand how you think, not just what you shipped.

**What tools/technologies did you use?** (be specific — framework names, libraries, APIs)  
For the frontend↔backend wiring and the persona page: the dashboard is React 18 + Babel-standalone in the browser (no bundler), Firebase email/password auth; the backend side is FastAPI (the unified `backend/app` platform — `/api/analytics`, `/api/metrics/*`, `/api/sources`, `/api/signals`, `/api/simulations`, `/api/actions`, `/api/conversation`) plus a Flask service (`backend/scripts/api_server.py` on `:5050`) for the pipeline artifacts, and the `classification_service/` FastAPI app (`/v1/classify*`, `/v1/personas/*`, `/v1/ingest/supabase`) backed by SQLite. Data lives in Supabase (Postgres, ~27.5k citizen-voice records). Everything runs through Docker + docker-compose. Git was the actual day-job tool — branches, PRs, conflict resolution, the occasional `revert`.

**Why did you build it THIS way?** (was there another option you considered?)  
On the frontend API layer I went with a single `api.jsx` exposing `_BASE` (pipeline API) and `_CLS_BASE` (classification service) with `window.API_BASE` / `window.CLASSIFICATION_API_BASE` runtime overrides, instead of hard-coding URLs into each page module or baking them in at build time. The browser-Babel setup has no build step, so a build-time env var wasn't even an option — and with two-plus backends on different ports (and a known `:8000` collision between the FastAPI platform and the classification service), giving ops a single override point meant we could re-point the whole dashboard at a different host or port without touching twelve module files. The cost was one extra layer of indirection; the payoff was that the `:8000` collision became a config workaround instead of a code change.

### Which project(s) did you contribute to?

**Primary project**: 360 CitizenVoices — Voice-of-Citizen / Citizen-Experience Intelligence platform (DevOps / integration lead: branch model, monorepo migration, frontend↔backend wiring, containerisation, release docs)  
**Did you contribute to any other project?**  
- [x] No — focused on my main project only  
- [ ] Yes → Which one(s)? _______________

---

## 🔥 The Hardest Problem I Faced

> Think of a moment since your last check-in where something wasn't working and you had to figure it out.  
> If nothing broke — what was the most challenging thing you built?

**What was the problem?**  
After merging the `frontend` branch's live-data rewrite into `dev`, the whole dashboard went blank — white screen, no error surfaced to the user. It worked on the feature branch in isolation and broke the moment it was integrated, which is the worst failure mode because nobody who wrote the code saw it fail. On top of that, twenty people were on a handful of shared branches, so the same files (`admin.jsx`, the personas modules, the login page, the sidebar/logo) had conflicting redesigns landing on top of each other.

**How did you discover it?**
- [x] I found it myself while working
- [ ] A teammate told me about it
- [ ] It came up in testing
- [ ] The program manager / mentor pointed it out
- [ ] A user / demo found it
- [ ] Other: _______________

**Walk me through what you did to fix it** (step by step — like you're explaining to a friend)  
Step one — I bisected the merge: checked out the last known-good `dev`, confirmed it rendered, then walked forward commit by commit until the screen went white, which pinned it to the live-data rewrite of `dev/frontend/`. Step two — instead of trying to hot-patch a rewrite I didn't fully trust, I reverted `dev/frontend/` to the last working state (`Fix blank app: revert dev/frontend/ live-data rewrite to the last working state`) so the integration branch was demoable again — green branch first, fixes second. Step three — I re-landed the live-data work in smaller, reviewable pieces: wired the `#personas` page to the classification service on its own, then wired the dashboards to the FastAPI backend, then fixed the merged-router compatibility break (`Fix merged FastAPI router compatibility`), checking the app rendered after each. Step four — for the recurring frontend conflicts I stopped trying to auto-merge and started resolving them by hand with an explicit rule: keep the newest working redesign of a module (e.g. "keep Nmaa/updateDesign design for admin and personas modules") and write that decision into the merge commit so the next person — or future-me on a `git bisect` — could see *why*. Step five — added `?v=` cache-busting on `tokens.css` / `api.jsx` / `personas.jsx`, because half the "it's still broken" reports were just the browser serving a stale Babel-compiled file.

**How long did it take?**  
- [ ] Under 1 hour
- [ ] 1-3 hours  
- [x] Half a day
- [ ] More than a day
- [ ] Still working on it

**Did the fix prevent it from happening again, or was it a quick patch?**  
- [ ] Permanent fix — it won't happen again
- [x] Temporary — might need revisiting
- [ ] Not sure

> The revert + smaller re-lands fixed *this* blank-screen, and cache-busting killed the stale-asset class of false reports. The deeper fix — branch protection + required review on `dev`, smaller PRs, a CI smoke check that the app renders — is in the known-issues list, not yet enforced.

---

## 📈 Skill Check

> Be real with yourself. Rate your **current comfort level** (not where you want to be).

| Skill | Comfort Level (1-5) | Did it improve since last check-in? |
|---|:---:|:---:|
| Python / Backend (FastAPI, etc.) | ⬜1 ⬜2 ⬜3 ⬜4 ✅5 | ✅ Yes ⬜ No ⬜ N/A |
| Frontend (React, TypeScript, etc.) | ⬜1 ⬜2 ⬜3 ⬜4 ✅5 | ⬜ Yes ✅ No ⬜ N/A |
| AI/ML (RAG, Embeddings, Agents) | ⬜1 ⬜2 ⬜3 ✅4 ⬜5 | ⬜ Yes ✅ No ⬜ N/A |
| DevOps (Docker, Deployment, CI/CD) | ⬜1 ⬜2 ⬜3 ✅4 ⬜5 | ✅ Yes ⬜ No ⬜ N/A |
| Communication & Presenting | ⬜1 ⬜2 ⬜3 ✅4 ⬜5 | ✅ Yes ⬜ No ⬜ N/A |
| Problem Solving & Debugging | ⬜1 ⬜2 ⬜3 ⬜4 ✅5 | ✅ Yes ⬜ No ⬜ N/A |
| Teamwork & Collaboration | ⬜1 ⬜2 ⬜3 ⬜4 ✅5 | ✅ Yes ⬜ No ⬜ N/A |

> **1** = "I'd panic if asked to do this alone"  
> **3** = "I can handle it with some Googling"  
> **5** = "I could teach someone else how to do this"

---

## 🤝 Who I Worked With

> No one builds alone. Tell us about your team interactions.

**Name a teammate you worked closely with. What did you do together?**  
Effectively the whole team — every contributor's branch came through me. Closest were the people whose work I had to land repeatedly: Karam (backend conversation features + routers), Yaman (the p1 incremental Supabase ingest), Hasasneh (the person 2 preprocess / canonical-contract hardening), Ali (the prediction-driven Action Hub), and Ti-03 (the frontend redesign + the root-level cleanup). For each I'd review the PR, resolve the conflict against `dev`, and where the merge broke something (router compat, blank app) I'd fix it and tell them what the seam was so they could avoid it next time.

**Did you help someone who was stuck? What was the situation?**  
A lot of "it's broken on my machine" was actually environment, not code — so I wrote the top-level `README.md` (service-and-port map, quick-start, known-issues), the `docs/unified-pipeline-runbook.md`, and committed `classification_service/.env`'s non-secret config so people had a working baseline to copy. I also unblocked the ingest path by batching the Supabase commits (250-row batches, paginated fetches) so the big-table pull stopped getting rate-limited mid-run.

**Did someone help YOU when you were stuck? What happened?**  
On the frontend conflicts — when I was unsure which of two competing redesigns of `admin.jsx` / the personas modules to keep, the people who wrote them told me which one was actually the current direction, which is the only reason those merges resolved correctly instead of me silently picking the stale version.

**Did you contribute to a group outside your primary project?**  
- [x] No — focused on my main project
- [ ] Yes → Which group? _______________  
  What exactly did you do for them? _______________

---

## 💡 The "Aha!" Moment

> What's one thing you learned since your last check-in that clicked — something you didn't understand before but now you do?  
> Try to explain it like you'd explain it to a friend who's not in the program.

Integration is where everyone's *hidden assumptions* collide — and that's not a bug in the process, it's the whole point of having an integration branch. Each person's code worked on their own branch because it only had to satisfy their own mental model: which port the API is on, whether the dashboard reads live data or mock data, whether a dependency is allowed to come from a CDN. None of those assumptions are wrong in isolation; they only conflict when you put the code together. So most of "DevOps" on this project wasn't writing clever code — it was being the person who absorbs that collision: bisecting the merge that broke the app, reconciling two redesigns of the same file, turning a port clash into a config override, and *writing down* the decision in the merge commit so the next person doesn't have to rediscover it. The aha was that a clean `git` history and an honest README are infrastructure too — they're how twenty people's parallel work actually adds up to one runnable thing.

---

## 🚧 What's Blocking Me

> Be honest. If nothing is blocking you, write "Nothing — I'm clear."

**Is anything slowing you down right now?**  
Two known issues are still open: (1) the `:8000` port collision — the unified FastAPI platform (`backend/app/main.py`) and the classification/persona service both default to `:8000` on disjoint prefixes (`/api/*` vs `/v1/*`), so only one can bind it; needs one of them moved to its own port plus a compose service for `backend/app`. (2) Secrets hygiene — a Firebase admin-SDK JSON leaked into the `frontend` branch's *history* (not into `dev`'s tree, but history ≠ working tree); the proper fix is a `git filter-repo` scrub of that branch plus key rotation, which I don't want to run unilaterally on a shared repo without the team's sign-off.

**What have you already tried to unblock yourself?**  
For the port clash I shipped the `window.API_BASE` / `window.CLASSIFICATION_API_BASE` override so the dashboard works today, and documented the real fix in the README's known-issues. For the secret I confirmed it's not propagated into `dev`'s tree, gitignored the live `.env` files, and wrote the rotation/scrub plan into the README so it's a tracked task, not a forgotten one.

**What would help you move faster?**  
- [ ] More time
- [ ] Pair-programming with a specific teammate
- [ ] A mentor/coach session on a specific topic
- [x] Better documentation / clearer requirements
- [ ] Access to tools/accounts/APIs
- [ ] Nothing — I'm good
- [x] Other: team agreement to enable branch protection + required review on `dev`, and a maintenance window to run the history scrub + key rotation

---

## ⚡ Quick Fire Round

> Don't think. Just write the first thing that comes to mind.

**Since last check-in I'm most proud of**: Taking a repo with twenty contributors on a handful of shared branches and a duplicated frontend, and landing it as one runnable monorepo on `dev` with a release snapshot on `main`, live-wired dashboards, a containerised stack, and a README that tells the truth about what's still broken.

**The decision I made that had the biggest impact**: Reverting the blank-app merge to a green state *first* and re-landing the live-data work in small reviewable pieces, instead of trying to hot-patch a rewrite I didn't trust.

**One thing I wish I handled differently**: I should have pushed for branch protection + required review on `dev` and a frozen port/API contract on day one — the `:8000` collision and most of the by-hand frontend merges were predictable consequences of not agreeing on those up front.

**My energy level right now** (pick one):  
🟡 Medium — having good and bad moments  

---

# 📌 THURSDAY ONLY — Weekly Goal Review

> ⚠️ **Fill this section ONLY on Thursday.** Skip it on Tuesday.  
> Pull out your **Sunday Weekly Plan** and let's see how the week went.

### How Did I Do Against My Sunday Plan?

> Copy your goals from Sunday's plan and mark the result.

| # | Goal I Set on Sunday | Status | Notes |
|---|---|:---:|---|
| 1 | Stand up a clear branch model for 360 CitizenVoices and get all contributor branches integrated onto `dev` with a clean `main` release snapshot | ✅ Done ⬜ Partial ⬜ Not Started | `main` / `dev` / `backend` / `frontend` / `persona_service` model documented in the README; 170+ PRs and the recurring `backend→dev` / `frontend→dev` merges landed; `Merge dev into main — release snapshot of the integrated platform`. |
| 2 | Consolidate the codebase into a single monorepo and kill the duplicated frontend / root-level dirs | ✅ Done ⬜ Partial ⬜ Not Started | `feat: monorepo structure + full-stack integration`, `Clean up: remove duplicated dirs at root (kept under backend/)`, `refactor: consolidate to single frontend/ — remove root-level duplicate`. |
| 3 | Wire the React dashboard to live backend data — pipeline API + FastAPI platform + classification/persona service — and remove mock data | ✅ Done ⬜ Partial ⬜ Not Started | `feat: wire dashboards to the unified FastAPI backend (live data)`, `Wire #personas page to classification_service`, `Wire personas to Supabase data + heuristic classifier + deep analysis`; merged-router compat break fixed. Blank-app regression on the first merge attempt was reverted and re-landed cleanly. |
| 4 | Containerise the full stack (frontend + APIs + pipelines) with a single docker-compose entry point and harden the runtime (no CDN deps, robust Supabase ingest) | ⬜ Done ✅ Partial ⬜ Not Started | Root `docker-compose.yml` orchestrates frontend / Flask pipeline API / preprocessor / root-cause job / classification service; React/ReactDOM/Babel/Firebase vendored locally; Supabase ingest batched + paginated. Remaining: `backend/Dockerfile.api` still runs the old Flask CMD and there's no compose service for the new `backend/app` FastAPI platform — and the `:8000` port collision is documented but not resolved. |
| 5 | Write the project-level documentation: a real top-level README (service map, ports, branch model, quick-start), a pipeline runbook, and an honest known-issues / cleanup list | ✅ Done ⬜ Partial ⬜ Not Started | `README.md` (229 lines), `docs/unified-pipeline-runbook.md` (589 lines), `docs/pipeline-analysis.md`, production-delivery workstream plan; §7 Known issues lists the `:8000` overlap, the stale Dockerfile CMD, the ingest batching, and the Firebase-JSON history scrub + key rotation. |

**If something didn't get done — what happened?**  
Goal 4 is partial: the stack runs under compose and the runtime hardening (no CDN, batched ingest) is done, but the new `backend/app` FastAPI platform still doesn't have its own compose service and shares port `:8000` with the classification service — only one can bind it. That's an architecture decision (which service moves ports) I didn't want to make unilaterally, so it's written up in the README's known-issues as the next task rather than rushed.

**Was my Sunday plan realistic?**  
- [ ] Yes — I estimated well
- [ ] Too ambitious — I set too many goals
- [ ] Too easy — I finished early and could have done more
- [x] Mixed — some goals were right, others were off

### Week Summary

**Hours I put in this week (approx.)**: 14 hours

**My biggest strength this week**: Integration under chaos — taking twenty people's parallel work on shared branches and turning it into one runnable monorepo with a release snapshot, without losing anyone's work and while keeping `dev` demoable (revert-to-green, then re-land small).

**The skill I most need to level up**: CI/CD and release engineering — I did the branch model, the merges, the containerisation and the docs by hand; the next level is making the safety automatic: branch protection + required review on `dev`, a CI smoke check that the dashboard renders after a merge, a secret scanner that bounces the Firebase JSON at commit time, and a real deploy pipeline instead of "docker compose up on someone's laptop".

**If I had to give myself a grade this week (A-F)**: A-  
**Why?**: 4 of 5 goals fully done and the partial (Goal 4) is partial because of an architecture decision I deliberately deferred to the team rather than because I ran out of time. Marking down half a grade for not getting branch protection / CI in place — most of this week's hardest problems (blank-app merge, repeated frontend conflicts, the leaked secret) were exactly the things automation would have caught.

**What I want to focus on next week** (this feeds into Sunday's plan):  
Resolve the `:8000` collision (move one service, add a compose entry for `backend/app`) and fix `backend/Dockerfile.api` to run the FastAPI platform. Run the `git filter-repo` scrub of the `frontend` branch's history + rotate the Firebase admin key (with the team's sign-off). Enable branch protection + required review on `dev` and add a minimal CI: lint + tests + a "does the dashboard render" smoke check + a secret scanner. Stand up an actual deploy target so there's a single canonical running instance instead of per-laptop compose.

---
