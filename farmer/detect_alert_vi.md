# Farmer — Cảnh Báo Rủi Ro Phát Hiện

> Các rủi ro detection còn tồn tại sau khi đã hardening. Tham khảo khi vận hành trên các trang có anti-bot.

---

## Mức độ nguy hiểm

| Mức | Mô tả |
|-----|-------|
| `[!!!]` **NGHIÊM TRỌNG** | Gần như chắc chắn bị phát hiện bởi anti-bot hàng đầu (DataDome, hCaptcha, Cloudflare) |
| `[!]` **TRUNG BÌNH** | Có thể bị phát hiện bởi fingerprinting nâng cao hoặc phân tích timing |
| `[~]` **THẤP** | Rủi ro nhỏ, chỉ bị phát hiện bởi hệ thống rất tinh vi |

---

## 1. `[!!!]` evaluate_safe — Thực thi JS trong Isolated World

**File:** `page/page.py`

`Page.createIsolatedWorld` + `Runtime.evaluate` tạo execution context mới mà trang có thể phát hiện được.

**Các vector phát hiện:**
- Trang có thể đếm số execution context qua `performance.measureUserAgentSpecificMemory()`
- FingerprintJS / CreepJS giám sát việc tạo execution context bất thường
- `Runtime.evaluate` gây micro-latency đo được bằng `performance.now()` trong script của trang

**Khuyến nghị:**
- CHỈ dùng khi không còn cách thay thế qua DOM/CDP
- TUYỆT ĐỐI KHÔNG dùng trên trang có hCaptcha, DataDome, Cloudflare Turnstile, hoặc reCAPTCHA Enterprise
- Ưu tiên truy vấn DOM (`querySelector`, `getBoxModel`) thay vì chạy JavaScript

---

## 2. `[!]` Emulation Overrides — Không nhất quán fingerprint

**File:** `page/page.py`

Các lệnh CDP emulation có thể tạo sự không nhất quán mà script fingerprinting phát hiện được.

**Các vector phát hiện:**
- `Emulation.setUserAgentOverride` có thể không đồng bộ với `navigator.userAgent` đọc từ JavaScript
- `Emulation.setDeviceMetricsOverride` tạo mâu thuẫn giữa `window.innerWidth` và metrics thực tế
- `Emulation.setTimezoneOverride` có thể xung đột với vị trí địa lý dựa trên IP (múi giờ ≠ quốc gia IP)
- `Emulation.setLocaleOverride` có thể xung đột với header `Accept-Language`

**Khuyến nghị:**
- KHÔNG override trừ khi thực sự cần thiết — để Chrome tự dùng giá trị gốc
- Nếu override UA, phải đồng bộ cả `navigator.platform` và `navigator.appVersion`
- Đảm bảo timezone + locale + IP proxy nhất quán về mặt địa lý
- Dùng GPM profile vì GPM xử lý override ở tầng trình duyệt

---

## 3. `[!]` DOM.enable — Latency trên main thread

**File:** `page/page.py`

Khi domain DOM đang active, mỗi truy vấn DOM (`querySelector`, `getBoxModel`, `getOuterHTML`) tạo micro-latency trên main thread của Chrome.

**Các vector phát hiện:**
- JavaScript trên trang chạy trên cùng main thread có thể đo chênh lệch timing qua `performance.now()` hoặc khoảng cách `requestAnimationFrame`
- Burst truy vấn DOM liên tục tạo hiện tượng jank quan sát được

**Khuyến nghị:**
- Gọi `page.dom_disable()` sau mỗi block thao tác DOM
- DOM tự động bật lại khi có truy vấn tiếp theo — không cần bật lại thủ công
- Tránh vòng lặp truy vấn DOM quá nhanh (polling hiện tại dùng khoảng cách ngẫu nhiên 200-500ms — an toàn)

---

## 4. `[~]` Page.enable — Overhead sự kiện

**File:** `page/page.py`

`Page.enable` khiến Chrome gửi các sự kiện lifecycle qua WebSocket, tạo overhead nhỏ.

**Khuyến nghị:**
- Chấp nhận — cần thiết cho theo dõi điều hướng và xử lý dialog
- Rủi ro thấp vì hầu hết framework automation đều bật domain này

---

## 5. `[~]` Chrome Launch Flags — Tác dụng phụ hành vi

**File:** `browser/launcher.py`

Một số flag có tác dụng phụ phát hiện được:
- `--disable-background-timer-throttling`: `setTimeout` chạy chính xác ngay cả khi tab ở background (người thật bị throttle)
- `--disable-hang-monitor`: Hành vi khác khi trang bị treo

**Khuyến nghị:**
- Giữ tab active/visible trong quá trình automation
- Khi dùng GPM profile, các flag do GPM quản lý — flag của Farmer launcher không liên quan

---

## 6. `[~]` Element.scrollIntoViewIfNeeded — Cuộn tức thì (Page layer)

**File:** `element.py`

`DOM.scrollIntoViewIfNeeded` cuộn ngay lập tức không có animation. Tầng Human dùng scroll bằng wheel thay thế, nhưng tầng Page vẫn có method này.

**Khuyến nghị:**
- Luôn dùng Human layer cho các thao tác cần stealth
- Nếu dùng Page layer trực tiếp, lưu ý sự kiện scroll thiếu `wheel` event trước đó

---

## 7. `[~]` Input.insertText — Không có sự kiện phím

**File:** `page/keyboard_raw.py`

`Input.insertText` chèn text mà không tạo sự kiện `keydown`/`keyup`. Các trang lắng nghe sự kiện phím riêng lẻ sẽ không nhận được.

**Khuyến nghị:**
- Chỉ dùng ở Page layer (không stealth) và `ImageSearch.fill(simulate=False)`
- Luôn dùng `human.type()` hoặc `images.fill(simulate=True)` khi cần stealth

---

## 8. `[~]` Screenshot Polling — Pattern CPU

**File:** `image_search.py`

ImageSearch poll screenshot mỗi ~400ms (ngẫu nhiên 280-600ms). Mỗi lần `Page.captureScreenshot` tạm dừng rendering trong thời gian ngắn.

**Khuyến nghị:**
- Tránh chạy ImageSearch trong lúc trang đang render nội dung nặng
- Tăng `interval` nếu ưu tiên stealth hơn tốc độ

---

## 9. `[~]` WebSocket /json Endpoint — Lộ thông tin CDP

**File:** `core/connection.py`

Endpoint `/json` của debug port lộ tất cả target và WebSocket URL. Bất kỳ script nào trên trang đều có thể fetch `http://127.0.0.1:{port}/json` để phát hiện CDP.

**Khuyến nghị:**
- Không thể fix — là kiến trúc cốt lõi của CDP
- Dùng port debug ngẫu nhiên (GPM tự động làm điều này)
- Không bao giờ dùng port phổ biến 9222
- Hầu hết trình duyệt chặn request cross-origin tới localhost qua CORS

---

## Tổng hợp

| # | Rủi ro | Mức | Có thể fix? |
|---|--------|-----|-------------|
| 1 | evaluate_safe (isolated world) | `[!!!]` | Không — bản chất CDP |
| 2 | Emulation override không nhất quán | `[!]` | Một phần — kỷ luật dev |
| 3 | DOM.enable latency main thread | `[!]` | Một phần — gọi `dom_disable()` |
| 4 | Page.enable overhead | `[~]` | Không — bắt buộc |
| 5 | Chrome launch flags | `[~]` | Không — dùng GPM thay thế |
| 6 | scrollIntoView tức thì (Page layer) | `[~]` | Không — dùng Human layer |
| 7 | insertText không có key events | `[~]` | Không — dùng Human layer |
| 8 | Screenshot CPU pattern | `[~]` | Một phần — tăng interval |
| 9 | /json endpoint lộ thông tin | `[~]` | Không — bản chất CDP |

**Tổng thể:** 1 NGHIÊM TRỌNG (không tránh được), 2 TRUNG BÌNH (giảm thiểu được), 6 THẤP (chấp nhận).
Luôn sử dụng Human layer cho các thao tác yêu cầu stealth.
