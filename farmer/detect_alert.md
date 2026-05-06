# Farmer — Detection Risk Alert

> Remaining detection risks after hardening. Use this as a reference when operating on anti-bot protected sites.

---

## Severity Levels

| Level | Description |
|-------|-------------|
| `[!!!]` **CRITICAL** | Almost certainly detected by top-tier anti-bot (DataDome, hCaptcha, Cloudflare) |
| `[!]` **MEDIUM** | Detectable by advanced fingerprinting or timing analysis |
| `[~]` **LOW** | Minor risk, only detectable by very sophisticated systems |

---

## 1. `[!!!]` evaluate_safe — Isolated World JS Execution

**File:** `page/page.py`

`Page.createIsolatedWorld` + `Runtime.evaluate` creates a new execution context that the page can detect.

**Detection vectors:**
- Sites can count execution contexts via `performance.measureUserAgentSpecificMemory()`
- FingerprintJS / CreepJS monitor for unexpected execution context creation
- `Runtime.evaluate` introduces micro-latency measurable by `performance.now()` in page scripts

**Recommendation:**
- Use ONLY when no DOM/CDP alternative exists
- NEVER use on pages with hCaptcha, DataDome, Cloudflare Turnstile, or reCAPTCHA Enterprise
- Prefer DOM queries (`querySelector`, `getBoxModel`) over JS evaluation whenever possible

---

## 2. `[!]` Emulation Overrides — Fingerprint Inconsistency

**File:** `page/page.py`

CDP emulation commands can create mismatches detectable by fingerprinting scripts.

**Detection vectors:**
- `Emulation.setUserAgentOverride` may not sync with `navigator.userAgent` read from JS
- `Emulation.setDeviceMetricsOverride` creates inconsistency between `window.innerWidth` and actual rendering metrics
- `Emulation.setTimezoneOverride` can conflict with IP-based geolocation (timezone ≠ IP country)
- `Emulation.setLocaleOverride` can conflict with `Accept-Language` header

**Recommendation:**
- Do NOT override unless absolutely necessary — let Chrome use its native values
- If overriding UA, also synchronize `navigator.platform` and `navigator.appVersion`
- Ensure timezone + locale + proxy IP are geographically consistent
- Use GPM profiles which handle these overrides at the browser level

---

## 3. `[!]` DOM.enable — Main Thread Latency

**File:** `page/page.py`

When DOM domain is active, every DOM query (`querySelector`, `getBoxModel`, `getOuterHTML`) creates micro-latency on Chrome's main thread.

**Detection vectors:**
- Page JavaScript running on the same main thread can measure timing deltas via `performance.now()` or `requestAnimationFrame` intervals
- Rapid DOM query bursts create observable jank

**Recommendation:**
- Call `page.dom_disable()` after completing each batch of DOM operations
- DOM re-enables automatically on next query — no need to manually re-enable
- Avoid tight DOM query loops (current polling uses random 200-500ms intervals — safe)

---

## 4. `[~]` Page.enable — Event Overhead

**File:** `page/page.py`

`Page.enable` causes Chrome to send page lifecycle events over WebSocket, creating minor overhead.

**Recommendation:**
- Accept — required for navigation tracking and dialog handling
- Low risk since virtually all automation frameworks enable this domain

---

## 5. `[~]` Chrome Launch Flags — Behavioral Side-Effects

**File:** `browser/launcher.py`

Some flags have detectable side-effects:
- `--disable-background-timer-throttling`: `setTimeout` runs accurately even in background tabs (real users get throttled)
- `--disable-hang-monitor`: Different behavior when page hangs

**Recommendation:**
- Keep tabs active/visible during automation
- When using GPM profiles, these flags are managed by GPM — Farmer launcher flags are irrelevant

---

## 6. `[~]` Element.scrollIntoViewIfNeeded — Instant Scroll (Page Layer)

**File:** `element.py`

`DOM.scrollIntoViewIfNeeded` scrolls instantly without animation. The Human layer uses wheel-based scroll instead, but the Page layer still has this method available.

**Recommendation:**
- Always use Human layer for stealth operations
- If using Page layer directly, be aware scroll events lack `wheel` event precursors

---

## 7. `[~]` Input.insertText — No Key Events

**File:** `page/keyboard_raw.py`

`Input.insertText` inserts text without generating `keydown`/`keyup` events. Sites listening for individual key events will not receive them.

**Recommendation:**
- Only used in Page layer (non-stealth) and `ImageSearch.fill(simulate=False)`
- Always use `human.type()` or `images.fill(simulate=True)` for stealth

---

## 8. `[~]` Screenshot Polling — CPU Pattern

**File:** `image_search.py`

ImageSearch polls screenshots every ~400ms (randomized 280-600ms). Each `Page.captureScreenshot` briefly freezes rendering.

**Recommendation:**
- Avoid running ImageSearch during heavy page rendering
- Increase `interval` if stealth is prioritized over speed

---

## 9. `[~]` WebSocket /json Endpoint — Inherent CDP Exposure

**File:** `core/connection.py`

The `/json` debug endpoint exposes all targets and WebSocket URLs. Any script on the page could potentially fetch `http://127.0.0.1:{port}/json` to detect CDP.

**Recommendation:**
- Cannot be fixed — inherent to CDP architecture
- Use random debug ports (GPM does this automatically)
- Never use well-known port 9222
- Most browsers block localhost cross-origin requests via CORS

---

## Summary

| # | Risk | Severity | Can Fix? |
|---|------|----------|----------|
| 1 | evaluate_safe (isolated world) | `[!!!]` | No — inherent CDP |
| 2 | Emulation override mismatch | `[!]` | Partial — developer discipline |
| 3 | DOM.enable main-thread latency | `[!]` | Partial — call `dom_disable()` |
| 4 | Page.enable overhead | `[~]` | No — required |
| 5 | Chrome launch flags | `[~]` | No — use GPM instead |
| 6 | Instant scrollIntoView (Page layer) | `[~]` | No — use Human layer |
| 7 | insertText no key events | `[~]` | No — use Human layer |
| 8 | Screenshot CPU pattern | `[~]` | Partial — increase interval |
| 9 | /json endpoint exposure | `[~]` | No — inherent CDP |

**Overall:** 1 CRITICAL (unavoidable), 2 MEDIUM (mitigatable), 6 LOW (acceptable).
Always use the Human layer for stealth-critical operations.
