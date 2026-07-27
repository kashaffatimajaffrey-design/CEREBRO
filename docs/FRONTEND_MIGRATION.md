# Frontend: exactly what to delete and what to rewire

Line numbers refer to the current `C:\cerebro_repo (apollo int)` tree. Work
top-to-bottom; the deletions are independent of each other.

---

## A. Delete outright

### 1. `components/Team.tsx` — delete the file

Remove the import in `App.tsx`, the `View.TEAM` enum member in `types.ts`, and
the nav entry in `Sidebar.tsx`.

Two reasons, and the second matters more than the first:

- Registration numbers (`Reg: 84381`, `Reg: 84010`) and formal "Research Lead"
  titles read as a course submission.
- It hardcodes two personal Gmail addresses into the shipped JavaScript bundle.
  That is a PII leak in a security product, which is the worst possible place
  for one.

If you want attribution, put it in `README.md` or a `CONTRIBUTORS` file — server
side, not in the client bundle.

### 2. `services/authService.ts` — delete the file

Dead code: imported at `Auth.tsx:3`, never called. It stores passwords in
plaintext in `localStorage` and compares them with `u.password === password`.
It is one line away from being live, and if anyone ever wires it up by accident
you have a credential breach. Delete the file and the import.

### 3. `CyberMonitor.tsx:7-40` — `generateMockLogs()`

```js
logs[3].packetSize = 15000;
logs[3].flags = 'SYN_FLOOD';   // the answer, written into the input
logs[7].sourceIP = '192.168.1.99';
```

Delete the function and the `useEffect` that calls it. Replace with a fetch from
`GET /v1/flows/recent`. Also change the panel label — it currently says
"Live Network Traffic" over generated data, with `Simulating Interface: eth0`
in the corner.

### 4. `DashboardHome.tsx:25` — the `threatData` array

Seven hardcoded days feeding two charts, one of them titled
`[ THREAT ANALYTICS REAL-TIME OVERVIEW ]`. Delete the constant and both chart
bindings; rewire per section B.

### 5. `DashboardHome.tsx:158-160` — the padded baselines

```js
const totalScansValue   = (1284 + realScansCount).toLocaleString();
const fakeNewsValue     = (142 + realFakeNewsCount).toLocaleString();
const cyberThreatsValue = (89 + realCyberCount).toLocaleString();
```

A brand-new user sees "Total Scans: 1,284". Delete the constants. Also delete
line 204's `change={...(realScansCount / 1284)...}` — it computes a percentage
against a made-up denominator, so it isn't a change rate at all.

Show real zeros. An empty dashboard with an honest empty state is more credible
than a full one that's lying, and it's a better demo moment: "this populates as
detections come in" is a sentence you can say confidently.

### 6. `DashboardHome.tsx:226` — `title="System Health" value="98%"`

A string. Either wire it to `GET /ready` (which returns real capability status)
or remove the card.

### 7. `Auth.tsx:335-392` — `triggerDecryptionSim()`

A 70 ms `setInterval` printing `'🔑 INITIATING QUANTUM SECURE SHAKE...'` and
`'💻 ATTEMPTING BIOMETRIC SIGNATURE DECRYPTION...'`. There is no biometrics and
no decryption.

Worse than cosmetic: `handleSubmit` runs the animation first and only calls
`login()` inside a `setTimeout(..., 1200)` after the bar reaches 100%. Users
watch ~5 seconds of "ACCESS CONFIRMED" *before* credentials are checked, then
get an error. Delete the sim; call `login()` immediately and show a normal
spinner.

### 8. `NewsScanner.tsx` — the `loadingLogs` array

Six fake steps at 900 ms including `'Injecting NLP lexical model tokens...'`,
with a progress bar computed as `(loadingStep + 1) / loadingLogs.length` — step
count, not progress. The code comments it as
`// Futuristic loading step log simulation`.

Replace with real pipeline stages streamed from the backend over WebSocket:
`extracting claims → embedding → retrieving evidence → scoring stance → done`.
Those stages actually exist now, so the log becomes true rather than decorative.

### 9. Small cosmetic lies

| Location | Issue |
|---|---|
| `StatCard.tsx` | `SYS_N{Math.floor(Math.random()*900+100)}_SEC` — random ID re-rolled every render |
| `StatCard.tsx` | static `[ SECURE_LINK ]` badge meaning nothing |
| `DashboardHome.tsx` | `SHA256: {item.id.slice(0,10)}` — not a hash, it's the document ID |
| `Auth.tsx` | left "[SEC_ANALYSIS_STREAM]" panel — static JSX styled as a live feed (`IP 192.168.0.1 blocked - SYN Flood`) |
| `GmailScanner.tsx:521` | `"None detected. Header alignment aligns with safe origin."` — printed when no headers were ever examined |
| `GmailScanner.tsx` | Client-ID input box; `clientId` state is never sent anywhere. Its default is the AI Studio *app* ID, not an OAuth client ID |

---

## B. Rewire — what each element binds to instead

| UI element | Was | Becomes |
|---|---|---|
| Threat analytics area chart | `threatData` constant | `GET /v1/metrics/threat-volume?window=7d` → `threat_volume_hourly` continuous aggregate |
| Detection efficiency bars | same constant | `GET /v1/metrics/detection-rates` |
| **New: forecast band** | — | `GET /v1/forecast/email.phishing` → TFT p10/p50/p90, drawn as a shaded band past "now" |
| Total Scans / Fake News / Cyber Threats | padded constants | `GET /v1/metrics/summary` — real counts, zero when zero |
| System Health | `"98%"` | `GET /ready` capability flags |
| Network log table | `generateMockLogs()` | `GET /v1/flows/recent` (Zeek/Suricata ingest) |
| Cyber analysis button | Gemini on fake logs | `POST /v1/analyze/flows` → IsolationForest + autoencoder ensemble |
| **New: anomaly attribution** | — | per-flow `attribution[]` — feature, z-score, direction |
| **New: incident grouping** | — | DBSCAN clusters; render N alerts as one incident card |
| News verdict | Gemini `credibilityScore` | `POST /v1/analyze/text` → RoBERTa + retrieval |
| News "sources" | model-invented strings | `evidence[]` — real URLs, publisher, stance, rerank score |
| Email scan | snippet → Gemini | `POST /v1/analyze/email` with `format=raw` → ~35 real features |
| **New: SPF/DKIM/DMARC row** | — | actual header values, with alignment flag |
| Live updates | none (polling) | WebSocket `/v1/stream` on Postgres `LISTEN/NOTIFY` |

---

## C. Two live bugs to fix while you're in there

**1. `GmailScanner.tsx:185` — advisory mails the phisher**

```js
setWarningRecipient(email.from);   // the suspicious sender
```

The "Dispatch Cyber Advisory Reply" flow pre-fills the recipient with the
sender under investigation, then sends them the full forensic report — risk
score, indicators, reasoning. That tells an attacker exactly which of their
techniques you detected. Default to the analyst or a SOC distribution list.

**2. `GmailScanner.tsx:66` — token in localStorage**

```js
localStorage.setItem('cerebro_gmail_token', accessToken);
```

An OAuth token carrying `gmail.readonly` **and** `gmail.send`, in a store any
XSS on the origin can read, with no expiry check. Move it server-side (the
`oauth_credentials` table in the v2 schema, encrypted at rest, keyed by session).

While there: drop `gmail.metadata` (redundant with `readonly`) and drop
`gmail.send` unless sending is a hard requirement. Requesting the ability to
send mail as the user, for a tool that reads mail, is a blast radius you don't
need — and it's the scope most likely to fail Google's verification review.

---

## D. Keep

Genuinely good, don't touch:

- The dark tactical visual language, glassmorphism, scanlines, motion work
- `utils/audio.ts` — a hand-written Web Audio synthesizer is real engineering.
  One fix: it calls `new AudioContext()` per invocation and never `close()`s;
  Chrome caps ~6, so audio dies after heavy hovering. Create one context lazily
  and reuse it.
- The Gmail OAuth flow structure (once tokens move server-side)
- jsPDF export — fix two bugs: `pageWidth * 1.3` computes a *y* coordinate from
  page **width**, and there's no `addPage()` so long reports run off page 1
- `firestore.rules` — keep as the reference when writing the Postgres RLS
  policies. It's the best-written file in v1.

---

## E. Branding

The Omnitrix dial (Ben 10) and the name CEREBRO (X-Men) are the loudest
remaining "student project" signal after the Team page. The dark SOC aesthetic
around them is genuinely professional — the franchise references are what
undercut it.

Cheapest credibility win available: keep every pixel of the visual design, drop
the cartoon references, retire the `'omnitrix'` sound case and the "Omnitrix
Core Dial" label (keep the widget, call it a theme selector). Renaming is
optional and entirely your call — but if you keep CEREBRO, give it a backronym
in the README so it reads as an acronym rather than a comic reference.
