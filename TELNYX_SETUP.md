# TELNYX SETUP — 15 minutes, then flip one config line

The Telnyx engine is **already built into cell_coach2** (added 2026-07-29). Twilio
stays the active engine until you flip the switch. Nothing to install.

## Step 1 — Telnyx Mission Control (portal.telnyx.com)

1. **Sign up + fund** the account (outbound calls need a balance; ~$10 is plenty to start).
2. **API Key** → *Account → Keys & Credentials → Create API Key (V2)*. Copy it.
3. **Credential SIP Connection** → *SIP Connections → Add → type "Credentials"*.
   Name it `cellcoach`. Copy the **connection ID** (starts with a long number).
4. **Outbound Voice Profile** → *Outbound Voice Profiles → Add*. Defaults are fine.
   Then open your credential connection → **Outbound** section → assign this profile.
5. **TeXML Application** → *Programmable Voice → TeXML → Create App*.
   - **Voice URL:** `https://atrophy-strict-heroics.ngrok-free.dev/api/telnyx_voice`
   - Method: **POST**
   - Under Outbound: assign your **Outbound Voice Profile**.
   - Associate your **credential connection** with this app.
6. **Buy numbers** → *Numbers → Search & Buy*. Local US numbers purchase instantly
   (no manual review like Twilio). At checkout assign each to the **TeXML app**.
   Buy as many as you want in the rotation pool.

## Step 2 — cell_coach2 config

Edit `C:\Users\Admin\data_center\data\cc_config.json`:

```json
"telephony_provider": "telnyx",
"telnyx_api_key": "KEY...your v2 key...",
"telnyx_credential_id": "1234567890123456789",
"telnyx_phone_number": "+1...one of your new numbers (fallback caller ID)"
```

## Step 3 — DID rotation pool

Add the new Telnyx numbers to `did_pool` in `data/command_center.db` (same table
Twilio uses — the pool doesn't care who the carrier is). Rotation, `dials_today`
counting, and the test-mode dial guard work identically through Telnyx.

⚠️ Caller-ID rule: Telnyx will only send caller IDs that live on **your Telnyx
account**. Your old Twilio numbers won't work as Telnyx caller IDs unless ported.

## Step 4 — test

Reload `http://127.0.0.1:5099/` — the hint under START CALL should say **"over
Telnyx"**. Test-call **7036460021** (guard still armed). Verify: ring, connect,
dual transcription, hangup → wrap-up freeze, dispo → autodial countdown.

## Flip back anytime

`"telephony_provider": "twilio"` → reload. Twilio code path is fully intact.
If `telephony_provider` is `telnyx` but Telnyx keys are missing/bad and Twilio
is configured, the app **falls back to Twilio automatically** so dialing never dies.

---

### How it works (what was built)

- **`/api/telnyx_token`** — mints a short-lived JWT from your API key + credential
  ID (cached ~55 min server-side). The browser SDK logs in with it; no secrets
  reach the page.
- **`/api/telnyx_voice`** — TeXML webhook. TeXML is TwiML-compatible, so the
  **same dial guard + DID rotation + caller-ID injection** code serves both
  engines. Verified: guard blocks non-allowlisted numbers with an audible
  message; allowlisted calls get `<Dial callerId="...pool DID...">`.
- **Client**: `startTelnyxCall()` mirrors the Twilio path — token → connect →
  dial → ringing/connected/hangup events feed the exact same state machine
  (wrap-up freeze, dispo hotkeys, autodial cadence). Mute/hangup are
  provider-aware. The prospect's remote audio feeds the **same** AssemblyAI
  dual-STT + recording pipeline — the AI coach is unaffected.
