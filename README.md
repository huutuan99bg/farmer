# 🌾 Farmer

**Stealth browser automation via raw CDP — human-like interaction with zero `Runtime.enable`.**

Farmer is a Python library that controls Chrome through the Chrome DevTools Protocol (CDP) at the lowest level possible, designed to be undetectable by anti-bot systems. Unlike Playwright or Puppeteer, Farmer never enables `Runtime.enable` — the #1 fingerprinting signal that anti-bot systems look for.

---

## ✨ Features

| Layer | Description |
|-------|-------------|
| **Page** | Mechanical CDP bridge — navigation, DOM queries, screenshots, cookies, emulation |
| **Human** | Behavioral simulation — Bézier mouse curves, Gaussian typing, typo simulation, position memory |
| **ImageSearch** | OpenCV template matching — find/click elements behind shadow DOM or cross-origin iframes |
| **Browser** | Tab/target management — multi-page orchestration with minimal CDP footprint |

### Stealth by Design

- 🔒 **No `Runtime.enable`** — zero background heartbeat from Runtime domain
- 🔒 **Lazy DOM** — `DOM.enable` / `DOM.disable` on demand, never persistent
- 🔒 **`isTrusted: true`** — all mouse/keyboard events dispatched via `Input.*` (trusted by browser)
- 🔒 **Isolated worlds** — JS evaluation via `Page.createIsolatedWorld` (not `Runtime.evaluate`)
- 🔒 **Random world names** — UUID-based context names to prevent fingerprinting

---

## 📦 Installation

```bash
pip install git+https://github.com/huutuan99bg/farmer.git
```

### Requirements

- Python ≥ 3.10
- Chrome/Chromium with `--remote-debugging-port` enabled
- `websockets`, `opencv-python`, `numpy` (auto-installed)

---

## 🚀 Quick Start

### Async (recommended)

```python
import asyncio
from farmer import Farmer

async def main():
    async with await Farmer.connect("http://127.0.0.1:9222") as f:
        await f.goto("https://example.com")
        await f.click("#submit")
        await f.fill("#email", "user@example.com")
        await f.human.idle(2.0)  # random mouse wandering

asyncio.run(main())
```

### Sync

```python
from farmer import FarmerSync

with FarmerSync.connect("http://127.0.0.1:9222") as f:
    f.goto("https://example.com")
    f.click("#submit")
    f.fill("#email", "user@example.com")
```

### Launch Chrome Automatically

```python
async with await Farmer.launch(
    headless=False,
    viewport=(1920, 1080),
    proxy="http://user:pass@proxy:8080",
) as f:
    await f.goto("https://example.com")
```

---

## 🏗️ Architecture

```
farmer/
├── __init__.py          # Public API: Farmer, FarmerSync
├── farmer.py            # Async entry point — combines all layers
├── farmer_sync.py       # Sync wrapper (background event loop)
├── element.py           # Lazy Element with auto-resolve
├── image_search.py      # OpenCV template matching
├── core/
│   ├── connection.py    # WebSocket CDP transport + reconnection
│   └── logger.py        # Structured session logging
├── browser/
│   ├── browser.py       # Tab/target management
│   ├── connector.py     # CDP HTTP → WebSocket resolver
│   └── launcher.py      # Chrome process launcher
├── page/
│   ├── page.py          # Mechanical CDP layer (navigation, DOM, etc.)
│   ├── mouse_raw.py     # Raw Input.dispatchMouseEvent
│   └── keyboard_raw.py  # Raw Input.dispatchKeyEvent
├── human/
│   ├── human.py         # Human-like interaction (extends Page)
│   ├── curves.py        # Bézier path generation
│   └── timing.py        # Gaussian timing distributions
└── utils/
    └── key_map.py       # Key name → CDP key definition mapping
```

### Layer Hierarchy

```
Farmer (entry point)
 ├── Browser  → tab management, target discovery
 ├── Page     → mechanical CDP (navigation, DOM, screenshots)
 ├── Human    → behavioral simulation (extends Page)
 └── ImageSearch → OpenCV-based visual element detection
```

---

## 📖 API Overview

### Farmer

| Method | Description |
|--------|-------------|
| `Farmer.connect(url)` | Connect to existing Chrome |
| `Farmer.launch(...)` | Launch new Chrome instance |
| `f.goto(url)` | Navigate to URL |
| `f.click(target)` | Human-like click |
| `f.fill(target, text)` | Human-like fill (click → clear → type) |
| `f.type(text)` | Human-like typing with typos/bursts |
| `f.screenshot()` | Capture PNG screenshot |

### Human Layer

```python
# Bézier mouse movement
await f.human.move(x, y, jitter=1.5)
await f.human.move_to_element("#btn")

# Click variants
await f.human.click("#btn")
await f.human.click("#btn", hold=500)       # press-and-hold (ms)
await f.human.double_click("#btn")
await f.human.right_click("#btn")

# Drag
await f.human.drag("#src", "#dst")

# Typing
await f.human.type("Hello", wpm=200, typo_rate=0.02)
await f.human.fill("#input", "text", clear_first=True)

# Keyboard
await f.human.press("Enter")
await f.human.hotkey("Control", "a")

# Scroll
await f.human.scroll(delta_y=300)
await f.human.scroll_to_bottom(speed="normal")

# Behavior
await f.human.idle(2.0)              # random mouse wandering
await f.human.reading_pause(500)     # pause proportional to text

# Auto-wait locators
el = await f.human.locator("button.submit", timeout=10)
sel, el = await f.human.locator_any(["#success", "#error"], timeout=15)
```

### Page Layer (Mechanical)

```python
# Navigation
await f.page.goto("https://example.com", wait_until="load")
await f.page.reload()
await f.page.go_back()

# DOM
el = await f.page.query_selector("h1")
els = await f.page.query_selector_all("li")
text = await f.page.inner_text("h1")
html = await f.page.content()
attr = await f.page.get_attribute("#el", "href")

# Wait
await f.page.wait_for_selector(".loaded", timeout=10)
await f.page.wait_for_navigation(timeout=30)

# Screenshots
png_bytes = await f.page.screenshot(full_page=True)

# JavaScript (⚠️ detection risk — use sparingly)
result = await f.page.evaluate_safe("document.title")

# Emulation
await f.page.set_viewport_size(1920, 1080)
await f.page.set_user_agent("Mozilla/5.0 ...")
await f.page.set_geolocation(10.762622, 106.660172)
await f.page.set_timezone("Asia/Ho_Chi_Minh")
```

### ImageSearch (OpenCV)

```python
# Find template in screenshot
rect = await f.images.find("btn_submit.png", threshold=0.85)

# Find and click
await f.images.click("captcha_icon.png", timeout=10)

# Find any of multiple templates
tmpl, rect = await f.images.find_any(["ok.png", "error.png"])

# Fill via image match
await f.images.fill("input_email.png", "user@test.com")
```

### Element

```python
el = await f.page.query_selector("#myel")

# Properties
await el.inner_text()
await el.inner_html()
await el.get_attribute("href")
await el.bounding_box()
await el.is_visible()

# Actions (raw CDP — not human-like)
await el.click()
await el.type("text")
await el.screenshot()
await el.scroll_into_view_if_needed()
```

---

## ⚠️ Detection Risks

Farmer is designed to minimize detection, but CDP automation has inherent limitations:

| Risk | Level | Description |
|------|-------|-------------|
| `evaluate_safe` | 🔴 HIGH | `createIsolatedWorld` can be detected by sites hooking the API |
| CDP WebSocket | 🟡 MEDIUM | WebSocket connection to `127.0.0.1` can be port-scanned |
| `Network.enable` | 🟡 MEDIUM | Temporarily enabled during `wait_network_idle` |
| `--remote-debugging-port` | 🟡 MEDIUM | Chrome flag visible in `chrome://version` |

See [detect_alert.md](farmer/detect_alert.md) for full analysis.

---

## 🧪 Testing

```bash
# Start Chrome with debugging
chrome --remote-debugging-port=9222

# Run tests
python tests/test_basic.py
```

---

## 📄 License

[MIT](LICENSE)
