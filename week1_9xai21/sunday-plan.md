# 🗓️ Weekly Plan — 9XAI Fellowship

> ⏱️ **Estimated time to complete: 5 minutes**  
> Fill this out every **Sunday** before the week starts. It sets your targets for Tuesday and Thursday check-ins.

---

## 📋 The Basics

**Your Name**: 9xai21
**Week Starting**: 2026-04-26 (Week 1)

---

## 🎯 What I Plan to Deliver This Week

> Be specific and realistic. These are the things you'll check yourself against on Thursday.  
> ❌ Bad: "Work on the project"  
> ✅ Good: "Finish the login API endpoint with JWT + write the RBAC middleware"

### My Deliverables for This Week (list 3-5 specific outcomes)

| # | What I Will Deliver | Priority | Confidence I'll Finish It |
|---|---|:---:|:---:|
| 1 | Write the LLM advisor design spec under `docs/superpowers/specs/` (architecture, API contract, opt-in gating, safety constraints) and lock it before any code lands | 🔴 Must | ✅ High ⬜ Medium ⬜ Low |
| 2 | Build all six advisor backend modules (`client`, `conversations`, `runner`, `safety`, `system_prompt`, `tools`) gated behind `ANTHROPIC_API_KEY`, merged with full test suite covering isolation, persistence, safety, status, tools, and signal-sim/video anchor | 🔴 Must | ⬜ High ✅ Medium ⬜ Low |
| 3 | Deliver the frontend: `AdvisorDrawer` component + chat session hook wired into Live, Forecast, and Signal pages; drawer only renders when env var is set | 🟡 Should | ⬜ High ✅ Medium ⬜ Low |
| 4 | Refactor the message bus to a pluggable factory pattern with asyncio, Kafka, and RabbitMQ adapters so Phase-3 events are backend-agnostic | 🟢 Nice to have | ⬜ High ⬜ Medium ✅ Low |
| 5 | Finalize Phase-2 hackathon delivery polish — clean demo flow, no regressions, full stack runs without `ANTHROPIC_API_KEY` set | 🟢 Nice to have | ✅ High ⬜ Medium ⬜ Low |

> **🔴 Must** = The team depends on this  
> **🟡 Should** = Important but won't block anyone  
> **🟢 Nice to have** = I'll do this if I have time

---

## 🧩 What I Need to Succeed

**Is there anything I need from someone else to hit my goals?**  
- [ ] No — I have everything I need
- [x] Yes → What? Anthropic API key with sufficient rate-limit headroom for integration tests and demo runs  From whom? Team lead / fellowship organizer

**Any known risks that could slow me down?**  
Anthropic API rate limits hitting during demo or test runs; the opt-in gate must be airtight so the default no-key path never regresses.

---

## 🔗 Carry-Over from Last Week

**Did I have anything unfinished from last Thursday?**  
- [x] No — everything was wrapped up
- [ ] Yes → What's carrying over? _______________

---

## 💬 One Sentence

**In one sentence, what does success look like for me by Thursday?**  
The opt-in LLM advisor is merged, fully tested, and visible in the SPA when `ANTHROPIC_API_KEY` is set — and the entire stack demos cleanly without it.

---

> 📌 **Keep this handy!** Your Tuesday and Thursday check-ins will refer back to these goals.
