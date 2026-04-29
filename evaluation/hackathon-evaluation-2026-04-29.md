# Hackathon Evaluation Notes

## Day 1

### Karam
**Gaps:** the UI seems confusing — too much data with no information, many signs and words and characters that aren't high-level English or language.

**Strengths:** a lot of data, amazing YOLO output, super smart looking.

**Recommendation:** make the UI allow users to digest information better and more easily so they can know truly how helpful your product is.

---

### Ahmad Hanayneh
**Gaps:** the UI seems too complicated — too much data with no information, many signs and words and characters that aren't high-level English or language.

**Strengths:** amazing detection models and prediction, such as the person walking with cars.

**Recommendation:** make the UI allow users to digest information better and more easily so they can know truly how helpful your product is.

---

### Shahed
**Gaps:** not much data to back up her awesome idea.

**Strengths:** really nice interface and idea concept with the *what-if* simulation.

**Recommendation:** get more data to back up her work and solidify it.

---

### Khalid
**Gaps:** not that information- or knowledge-filled; he had an issue with the Docker container and the ports aren't aligned.

**Strengths:** amazing simulator — honestly covers everything to see hypothetically what would happen if certain changes happen.

**Recommendation:** find the best solution for the Docker port issue.

---

### Ali
**Gaps:** says he's like everyone else with some additional things, so I assume he has similar issues as above. He has a lot of human-in-the-loop, which isn't practical.

**Strengths:** he has advisors per lane (which is nice and customizable), incident categories (which is nice), and a snapshot analysis that makes it more detailed (which is nice).

**Recommendation:** cut the human-in-the-loop touchpoints down to exceptions only — keep the lane-level advisors and incident categories as configuration, but let the system act autonomously by default. Practicality is the gap; the structural pieces are already good.

---

### Issa
**Gaps:** doesn't have the core functionality like prediction for 15 / 30 / 60 mins or anything else, since the project is so one-objective-oriented. His cost assumptions are not based on facts but on bias. His system seems not flexible (but I'm not sure about that).

**Strengths:** straight-to-the-point admin interface with a clear goal. He has data from research papers (Webster) to understand the behind-the-scenes aspect. He has his service costs known — every request is $1.50. Nice visualizations.

**Recommendation:** add the missing prediction layer (15 / 30 / 60 min horizons) — without it the project is one-dimensional. Replace the assumed/biased cost numbers with measured benchmarks ($1.5/request needs evidence), and pressure-test flexibility by running a second use case beyond the current single objective.

---

### Yaman
**Gaps:** his YOLO videos don't seem that accurate. He is innovative but doesn't apply very well practically — which I can understand.

**Strengths:** his dashboard is very nice and seems very clear with the information side. His idea is very nice and he's very innovative. He's very aware of what his models can and can't do.

**Recommendation:** lock in detection accuracy first — retrain/fine-tune YOLO on this intersection's footage before layering more innovation on top. The dashboard and self-awareness are strong; the bottleneck is the model. Then pair it with one concrete real-world deployment to prove it lands practically.

---

### Mahdi
**Gaps:** a lot of backend but not enough frontend — whatever is in the back needs to be reflected frontend-wise. Very nice approaches but not much implementation or output. He lacks the research backing needed to aid the recommendation aspect, and lacks visualizations.

**Strengths:** feeds the video into an LLM and has it analyze it, creating instances of cars and their description, etc., and the state of their traffic light, to generate real data based on the videos.

**Recommendation:** invest in frontend and visualizations so what the LLM is generating actually surfaces to stakeholders — backend output that no one can see is wasted. Back the LLM-driven recommendations with research citations or benchmarks so the suggestions are defensible, not just plausible.

---

### Mahmoud
**Gaps:** not the best detection of cars.

**Strengths:** proper SUMO simulation, best frontend so far, best implementation so far with the zoning of the videos in/out and stuff.

**Recommendation:** improve car detection accuracy — that's the only weak link. The frontend, SUMO integration, and zoning are already best-in-class. A better model (or fine-tuning on this footage) lifts everything else from "best demo" to production-ready.

---

### Ahmad Qalawah
**Gaps:** his SUMO visualization didn't make sense or add anything.

**Strengths:** he can customize the zones that he wants, which is very nice and flexible.

**Recommendation:** rework the SUMO visualization so it tells a clear story — before/after comparison, throughput delta, queue length over time. Flexible zone selection + a meaningful simulation view together would make the tool genuinely useful; right now the simulation isn't earning its screen space.

---

### Abdallah
**Gaps:** not the best frontend, and not many noticeable or known features except the *wow* one.

**Strengths:** very sci-fi frontend. The *wow* feature was a very nice idea that would aid the ministry and helps automate and make the process post-accident more efficient and effective. Has a nice prediction aspect.

**Recommendation:** lead with the wow / post-accident automation feature — that's the differentiator the ministry would actually buy. Build the supporting features around it. Tighten the frontend so the sci-fi aesthetic supports the core flow rather than competing with it.

---

## Day 2

### Salsabel
**Gaps:** used the wrong visualization types in some cases — like a line graph for something that should be tabular, or cards where numbers have to be clearly shown.

**Strengths:** she has the efficiency and effectivity of traffic-light visualization to evaluate the performance of that light. Nice visualizations and nice features.

**Recommendation:** do a chart-type audit — single KPIs → cards, comparisons → tables, time series → lines. The analytics underneath are sound; the presentation just needs to match the data shape. Once that's right, the traffic-light efficiency view becomes the standout feature.

---

### Nizar
**Gaps:** confusing visualizations; confusing frontend that looks too close to backend.

**Strengths:** he has a decision-support feature, a nice generator, and his ID tracking is actually functional. He used an intensity-zone YOLO detection, which seems very smart and solves the car-ID-tracking issue.

**Recommendation:** separate the frontend visual language from the backend/dev-tools aesthetic — make it look like an end-user product, not a debugger. The intensity-zone detection, decision support, and ID tracking are technically strong; what's missing is the polish layer that makes it legible to non-engineers.

---

### Hamza
**Gaps:** maybe his method isn't the best for the actual intersection.

**Strengths:** he has a C++ YOLO approach which (according to him) was faster and lighter on the device — which is amazing. His detection method and framework seem more stable. Good execution. Amazing to see how flow affects other streets. He stabilized his video and it made a positive difference in the outcome — so amazing approach.

**Recommendation:** validate the C++ approach against the actual intersection geometry — run a side-by-side with a baseline method on this specific footage. Engineering quality is high; the missing piece is the use-case fit proof. If it holds up, the speed/stability advantage becomes a defensible moat.

---

### Ez
**Gaps:** not the best frontend; the visualizations don't clearly present data; didn't mention where he got his data from. How does he know or reflect all that — is it all simulation based on the single video the guys gave us, a dataset, an assumption, etc.?

**Strengths:** he has a *stalled* and *over-flooded* feature. He has a *view what changed and how decisions affected things* view, which is nice — like an archive.

**Recommendation:** clearly label the data source (real footage vs. synthetic vs. assumed) so the audience can trust the output — right now the provenance is unclear and that undercuts the rest. Tighten the visualizations to make the stalled / over-flood detection the headline feature; the archive is good supporting context but shouldn't lead.

---

### Eman
**Gaps:** not the best features or data in comparison to the others — nothing unique.

**Strengths:** very nice frontend; she hit all the goals and objectives, all working.

**Recommendation:** pick one differentiator no one else has and go deep on it. Execution and polish are already strong, so what's missing is a memorable angle — without that, "everything works" gets lost in a room of similar projects.

---

### Qutaiba
**Gaps:** very bland frontend; way too overfilled with data. YOLO26 has automatic segmentation but maybe his way is better. His model detects parked cars (which is an issue). His detection confidence rates aren't the best — 0.32 for a traffic light isn't the best.

**Strengths:** he has live streaming in the structure. He has YOLO as an optional turn on/off (so which live), a chatbot, and a segmentation type of clustering for videos (YOLO).

**Recommendation:** fix detection confidence first — retrain or use YOLO26's native segmentation, and filter parked cars as a separate class so they don't pollute the active-traffic count. 0.32 confidence on a traffic light isn't shippable. Then redesign the frontend around the live streaming + chatbot as the differentiators instead of dumping all data on one screen.
