# Cell Coach — Enterprise Production-Readiness Audit
**Date:** 2026-07-17 · **Audited:** cellcoach.py (~2,025 lines), cellcoach_ui.html (~2,660 lines), cc_config.json handling, DB schema, live behavior from prior sessions
**Verdict up front:** Cell Coach today is a strong single-operator internal tool. Selling it to an enterprise requires work in six areas — two of which (compliance and the script's factual claims) are dealbreakers no buyer's legal team will waive. Everything below is grounded in the actual code, not guesses.

---

## A. COMPLIANCE & LEGAL — dealbreakers first

### A1. Script makes untrue factual claims ⛔ HIGHEST PRIORITY
The persona's exemplar intros include "I checked with the inspector this morning" and "I spoke with the city inspector this morning and he flagged it." Unless the rep actually did, this is a false statement of fact used to induce a sale — deceptive trade practice territory (FTC Act §5, state UDAP statutes). The "Risk and Compliance Bureau" name plus inspector-conversation claims will read to any enterprise counsel as government impersonation adjacent, even with the "never imply being the city" rule in the persona.
**Fix:** rewrite exemplars to claims that are always true: "I was reviewing the city's public code enforcement records and your property came up." Same pattern-interrupt power, zero legal exposure. This must be done before ANY external sale — an enterprise buying a coach that teaches deception inherits the liability and they know it.

### A2. Call recording consent — not handled at all
`startRecorder()` records every call locally. No consent capture, no two-party-consent state detection, no recording disclosure prompt for the rep. Texas is one-party consent so the current user is likely fine — but an enterprise with reps calling CA, FL, IL, PA, WA (all two-party) is exposed on every call.
**Fix:** per-lead state lookup from area code/zip → consent mode flag → either auto-disable recording, prompt rep to disclose, or record-with-disclosure workflows. Log the consent decision per call in the `calls` table.

### A3. TCPA / DNC — nothing exists
Lead queues dial straight from imported CSVs and scraped DBs. No DNC scrub (federal or state), no calling-hours windows (8am–9pm local at prospect), no call-frequency caps, no consent provenance on leads.
**Fix:** DNC scrub integration on import (litigator scrub + federal DNC), timezone-aware calling window enforcement in the queue UI, per-lead call attempt caps, and a `consent_source` column on imported_leads.

### A4. PII lifecycle — no retention, deletion, or export
Transcripts, recordings, phone numbers, addresses, and AI-generated "prospect_intel" (financial urgency, decision-making, stated numbers) all live unencrypted in SQLite + .webm files forever. No delete endpoint, no retention policy, no data-subject export. CCPA/CPRA and similar state laws apply the moment an enterprise customer processes California residents.
**Fix:** retention config (auto-purge recordings after N days), a delete-by-phone endpoint that cascades calls/recordings/scores, and export-by-phone for DSRs. Encrypt recordings at rest.

### A5. AI-on-calls disclosure
Several states are moving on AI-call disclosure. Cell Coach's rep is human (lower risk), but the AI training mode generates synthetic voices and the coach shapes what's said. Low urgency, but an enterprise will ask — have a written answer.

---

## B. SECURITY — blocking for any multi-user deployment

### B1. Zero authentication
Every endpoint is open: `/api/history` (all PII), `/recordings/*` (call audio), `/api/personas` POST (overwrite the coach's brain), `/api/import_delete`. Bound to 127.0.0.1 which saves it today — but that binding is the *only* control.
**Fix (near-term):** session token generated at boot, required header on all /api routes, printed to console/injected into served HTML. **Fix (enterprise):** real user auth + SSO (SAML/OIDC) — see §E.

### B2. CSRF / DNS-rebinding on localhost
No Origin/Host header validation. Any webpage the user visits can fire POSTs at `127.0.0.1:5099` — overwrite personas, delete imports, trigger paid GPT calls. Reads are protected by browser CORS, writes are not.
**Fix:** validate `Host` is `127.0.0.1:5099` and `Origin` (when present) matches, reject otherwise. ~10 lines.

### B3. Secrets in plaintext JSON
All keys (OpenAI, AssemblyAI, Twilio secret, ElevenLabs) in `cc_config.json`, world-readable. Acceptable single-machine; unacceptable enterprise.
**Fix (enterprise):** server-side key vault, keys never on rep machines — implies the SaaS re-architecture in §E.

### B4. Unauthenticated recordings with guessable filenames
`/recordings/YYYYMMDD_HHMMSS_phone.webm` — path traversal is blocked (basename + extension check, good) but any local process can enumerate timestamps and download call audio.

### B5. Lead-source SQL from config
`where`/`order` clauses from cc_sources.json are interpolated raw into SQL. The file is local-trusted so risk is low today, but in a hosted product this is injection-by-config. Parameterize or whitelist.

### B6. No TLS
Fine on loopback; mandatory the moment anything is hosted.

---

## C. COACHING QUALITY — the product itself

### C1. No state carry-over between turns (already identified this session)
`ep_analyze` gets transcript + latest line only. Prior `checklist`, `staircase_step`, `prospect_intel` are discarded — GPT re-derives everything per turn, so steps can jump backward, the four qualification pillars aren't tracked, and there's no accumulated fail/pass judgment.
**Fix:** frontend echoes last analysis state back; backend injects "CURRENT CALL STATE" block. Small change, big win. **Planned.**

### C2. No exemplar library (the staircase-sections plan)
Coaching quality rests on abstract rules; every drift bug so far (intro+agenda merge, wrong crisis tone) came from that. **Fix:** per-step, per-sub-step exemplar sets extracted from the G.U.T.S. demo transcripts, injected only for the active step. **Planned — combined with C1 it's one build.**

### C3. No qualification-fail → disengage logic
G.U.T.S. says 75% of prospects don't qualify and firing them is a win. The coach has no mechanism to conclude "this prospect fails, wrap up politely" — it will coach forever. **Fix:** add `qualification_verdict: pass | fail | undetermined` + a disqualification say_next path once state tracking (C1) exists.

### C4. No eval harness
Every persona/prompt edit ships blind. There's a training mode but no automated regression: no fixed set of transcript snapshots with expected coach behavior, no scoring of coach outputs against G.U.T.S. rules. An enterprise will ask "how do you know an update didn't make the coach worse?"
**Fix:** eval suite — ~30 frozen transcript states with expected step/objection/behavior assertions, run on every prompt change. This is also what makes the exemplar library safe to iterate.

### C5. Latency
Full GPT-4o call per turn with up to 4,000 chars of transcript, 250ms debounce, no streaming. Real-world guidance lands ~2–4s after the prospect stops talking — usable but behind the market. **Fix options:** stream the response and render say_next as it arrives; or split into fast model for step-tracking + 4o for say_next. Measure first.

### C6. Scoring pipeline has no failure visibility
`_score_session` runs in a fire-and-forget daemon thread (`time.sleep(4)` coordination — fragile). If it dies, the session is silently never scored. `scored` flag exists but nothing retries. **Fix:** persistent job flag + retry on next boot; surface scoring failures in the UI.

---

## D. RELIABILITY & OPERATIONS

- **D1. No retries anywhere.** `_http` is single-shot, 30s timeout. One transient OpenAI 429/500 = a dead coaching turn (UI shows error, but no auto-retry with backoff). Add 2-retry exponential backoff for idempotent calls.
- **D2. No WebSocket reconnect.** If an AssemblyAI socket drops mid-call, transcription for that channel silently ends (`onerror` → pill only). Add auto-reconnect with fresh token + resume.
- **D3. AAI token expiry**: tokens minted with 600s expiry; calls longer than the token's validity depend on AAI not re-validating — untested edge. Verify or refresh proactively.
- **D4. No logging.** `log_message` is suppressed and there's no application log at all — no error log, no request log, no way to debug a customer issue after the fact. Add rotating file log (stdlib `logging`) for errors + API failures + scoring runs.
- **D5. No usage/cost metering.** GPT-4o per turn, 4o-mini per training message, ElevenLabs per minute — nothing counts tokens or dollars. Enterprise needs per-seat cost visibility; you need it now for margin math. Log tokens per call into a `usage` table.
- **D6. SQLite ops**: WAL enabled (good), but no backup story, no migration system beyond try/except ALTERs. Fine local; hosted needs Postgres + migrations.
- **D7. Process supervision**: manual `python cellcoach.py`, dies with the console. Needs a service wrapper (NSSM/Task Scheduler) at minimum.
- **D8. Phone Link capture** (rebuilt this session to Stereo Mix): needs a live-call verification pass; the audio path depends on a Windows setting the app can detect but not set.

---

## E. MULTI-TENANCY & PRODUCT PACKAGING — the biggest lift

The architecture is one rep, one machine, one profile:

- **E1.** `rep_profile` is a single-row table — literally one user per install.
- **E2.** No accounts, roles, or teams. Enterprise minimum: rep / manager / admin roles.
- **E3.** No manager surface at all — no team dashboard, no call review queue, no coaching-trend reporting across reps, no leaderboards. *This is what the enterprise buyer actually pays for* — the rep UI is for reps, but managers sign the check.
- **E4.** Desktop-python distribution: keys on every machine, updates by file copy, no version control of what's deployed. Enterprise expects hosted SaaS (or at minimum a centrally-managed server) with per-seat licensing.
- **E5.** No SSO, no audit log of who accessed which call/recording (SOC 2 blocker).
- **E6.** No billing/metering/licensing enforcement.
- **E7.** Personas/exemplars are per-install JSON — enterprise wants org-level script management with versioning and rollout control.

**Honest framing:** E is a re-architecture (FastAPI/Postgres backend, hosted, browser client unchanged in spirit), not a patch. Everything in A–D is worth doing regardless because it hardens the tool you use daily; E is only worth starting once there's a real buyer conversation.

---

## F. PRIORITIZED PLAN

**Phase 0 — legal hygiene (do before selling to anyone, ~1 session)**
1. Rewrite all "inspector this morning" claims to always-true public-records language (personas + exemplars). [A1]
2. Recording consent: state detection by area code, per-call consent flag, config toggle to disable recording. [A2]
3. Calling-hours enforcement in queue (prospect-local 8am–9pm). [A3 partial]

**Phase 1 — coach quality (the product core, ~2 sessions)**
4. State carry-over: echo checklist/step/intel back into each analyze call. [C1]
5. G.U.T.S. exemplar library from demo transcripts, per-step injection. [C2]
6. Qualification verdict + disengage coaching. [C3]
7. Eval harness: ~30 frozen states + assertions, run per prompt change. [C4]

**Phase 2 — hardening (~1-2 sessions)**
8. Boot-time session token + Host/Origin validation. [B1, B2]
9. Retry/backoff on GPT + AAI calls; WS auto-reconnect. [D1, D2]
10. File logging + usage/cost metering table. [D4, D5]
11. Scoring-job retry on boot; failure surfacing. [C6]
12. Retention + delete-by-phone + export-by-phone endpoints. [A4]

**Phase 3 — enterprise re-architecture (only with a buyer in hand)**
13. Hosted backend (accounts, teams, roles, SSO, Postgres, TLS, key vault). [E1-E5, B3, B6]
14. Manager dashboard: team scores, call review, trends. [E3]
15. DNC scrub integration + consent provenance. [A3 full]
16. Licensing/metering/billing. [E6]
17. SOC 2 groundwork: audit logging, access controls, encryption at rest. [E5]

---

## Gaps in this audit (disclosed)
- Twilio TwiML webhook security (signature validation) not deep-audited — if the TwiML URL is public-internet reachable it needs `X-Twilio-Signature` checks.
- ElevenLabs signed-URL flow not verified for key leakage to the client (the code path builds a signed URL server-side, which looks right, but I did not trace the full response payload).
- D3 (AAI token expiry on long calls) is untested, not confirmed broken.
- No load testing done — single-user concurrency assumptions unverified beyond ThreadingHTTPServer defaults.
