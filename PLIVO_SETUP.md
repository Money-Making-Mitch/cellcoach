# PLIVO SETUP — third engine, same 15-minute shape

Plivo is **built into cell_coach2** (added 2026-07-29) alongside Twilio and Telnyx.
Twilio stays active until you flip `telephony_provider`. Three engines, one switch:

```json
"telephony_provider": "twilio" | "telnyx" | "plivo"
```

## Step 1 — Plivo Console (console.plivo.com)

1. **Sign up + fund** the account.
2. **Auth ID + Auth Token** — on the console dashboard home (top-left account panel).
3. **Endpoint** → *Voice → Endpoints → Add New Endpoint*.
   - Username `cellcoach`, a strong password, alias `Cell Coach`.
   - Attach it to the Application you create next (or come back and attach).
4. **Application** → *Voice → Applications → Add Application*.
   - **Answer URL:** `https://atrophy-strict-heroics.ngrok-free.dev/api/plivo_voice`
   - Answer method: **POST**
   - Hangup URL: same base + `/api/plivo_voice` (not critical, we drive state client-side).
5. **Link** the Endpoint to the Application.
6. **Buy numbers** → *Phone Numbers → Buy Numbers*. Assign each to the Application.

## Step 2 — cell_coach2 config

Edit `C:\Users\Admin\data_center\data\cc_config.json`:

```json
"telephony_provider": "plivo",
"plivo_auth_id": "MA...",
"plivo_auth_token": "...",
"plivo_phone_number": "+1...fallback caller ID"
```

You do NOT need to put the endpoint username/password in our config — the browser
logs in with a short-lived JWT that the server mints from your Auth ID/Token
(`POST /v1/Account/{auth_id}/JWT/Token/`, cached ~55 min). Secrets stay server-side.

## Step 3 — DID pool

Add the Plivo numbers to `did_pool` in `data/command_center.db`. Rotation,
`dials_today`, and the test-mode dial guard work identically. Caller IDs must be
Plivo-owned numbers (same rule as every carrier).

## Step 4 — test

Reload `http://127.0.0.1:5099/` — the START hint should say **"over Plivo"**.
Test-call **7036460021** (guard still armed). Verify ring → connect → dual
transcription → hangup → wrap-up freeze → dispo → autodial countdown.

## Notes

- Plivo XML is TwiML-shaped with one verb rename: our dial-guard messages use
  `<Speak>` (not `<Say>`) — handled automatically per-provider, verified live.
- The SDK plays remote audio through its own internal `<audio>` element; we
  capture that stream into the **same** AssemblyAI dual-STT + recording pipeline,
  so the AI coach works unchanged.
- If `telephony_provider` is `plivo` but keys are missing and Twilio is
  configured, the app **falls back to Twilio automatically**.
