# 🗓️ Weekly Plan — 9XAI Fellowship

> ⏱️ **Estimated time to complete: 5 minutes**  
> Fill this out every **Sunday** before the week starts. It sets your targets for Tuesday and Thursday check-ins.

---

## 📋 The Basics

**Your Name**: 9xai21  
**Week Starting**: 2026-05-03 (Week 2)  

---

## 🎯 What I Plan to Deliver This Week

> Be specific and realistic. These are the things you'll check yourself against on Thursday.  
> ❌ Bad: "Work on the project"  
> ✅ Good: "Finish the login API endpoint with JWT + write the RBAC middleware"

### My Deliverables for This Week (list 3-5 specific outcomes)

| # | What I Will Deliver | Priority | Confidence I'll Finish It |
|---|---|:---:|:---:|
| 1 | Build the Taregak app: integrate weather/crowd/time-of-day data sources, run an LLM-based scoring pipeline, and surface a ranked "best time to go out" recommendation in the UI | 🔴 Must | ✅ High ⬜ Medium ⬜ Low |
| 2 | Improve lane detection to dynamically adapt to lane width and curvature changes in real-time, benchmarked against at least two road scenarios | 🔴 Must | ⬜ High ✅ Medium ⬜ Low |
| 3 | Evaluate and compare at least two alternative car-detection models (e.g. YOLOv8 vs. RT-DETR), document accuracy/latency tradeoffs, and integrate the best-performing one | 🟡 Should | ⬜ High ✅ Medium ⬜ Low |
| 4 | Harden the Taregak app to production level: add error handling, loading states, and an LLM prompt layer that explains the recommended time window to the user | 🟢 Nice to have | ⬜ High ✅ Medium ⬜ Low |
| 5 | Refactor and document last week's detection codebase — clean up model configs, add inline comments, and push a reproducible notebook | 🟢 Nice to have | ✅ High ⬜ Medium ⬜ Low |

> **🔴 Must** = The team depends on this  
> **🟡 Should** = Important but won't block anyone  
> **🟢 Nice to have** = I'll do this if I have time

---

## 🧩 What I Need to Succeed

**Is there anything I need from someone else to hit my goals?**  
- [ ] No — I have everything I need
- [x] Yes → What? Access to reliable real-time data APIs (traffic, weather, venue crowd levels) and GPU compute for model benchmarking  From whom? Fellowship mentors / infrastructure team

**Any known risks that could slow me down?**  
Finding high-quality, free real-time data sources for the Taregak recommendation engine may take longer than expected; model benchmarking is compute-intensive and could hit resource limits.

---

## 🔗 Carry-Over from Last Week

**Did I have anything unfinished from last Thursday?**  
- [ ] No — everything was wrapped up
- [x] Yes → What's carrying over? Car detection model improvements and lane detection stability work started last week but need refinement and proper evaluation.

---

## 💬 One Sentence

**In one sentence, what does success look like for me by Thursday?**  
The Taregak app produces a working LLM-powered "best time to go out" recommendation, and the vehicle/lane detection pipeline shows measurable accuracy improvements backed by a model comparison report.

---

> 📌 **Keep this handy!** Your Tuesday and Thursday check-ins will refer back to these goals.
