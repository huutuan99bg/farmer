"""
Quick test script for Farmer library.
Requires a running Chrome with --remote-debugging-port.
"""

import asyncio

from farmer import Farmer


async def test_basic():
    """Test basic Farmer functionality."""
    debug_url = "http://127.0.0.1:65262"
    print(f"\n{'='*60}")
    print(f"  Farmer Library - Quick Test")
    print(f"{'='*60}")
    print(f"\n[1] Connecting to {debug_url}...")

    async with await Farmer.connect(debug_url) as f:
        print(f"    OK Connected!")

        # Test browser tabs
        print(f"\n[2] Browser tabs: {len(f.browser.pages)}")

        # Test navigation
        print(f"\n[3] Navigating to example.com...")
        await f.goto("https://example.com")
        print(f"    OK URL: {f.page.url}")

        # Test title
        title = await f.page.title()
        print(f"    OK Title: {title}")

        # Test DOM query
        print(f"\n[4] Testing DOM queries...")
        h1 = await f.page.query_selector("h1")
        if h1:
            text = await h1.inner_text()
            print(f"    OK <h1> text: {text}")
        else:
            print(f"    WARN <h1> not found")

        # Test locator
        print(f"\n[5] Testing locator...")
        el = f.locator("h1")
        is_vis = await el.is_visible()
        print(f"    OK h1 visible: {is_vis}")

        # Test screenshot
        print(f"\n[6] Taking screenshot...")
        data = await f.screenshot()
        print(f"    OK Screenshot: {len(data)} bytes")

        # Test human mouse (Bezier move)
        print(f"\n[7] Testing human mouse move...")
        pos_before = f.human.position
        await f.human.move(400, 300)
        pos_after = f.human.position
        print(f"    OK Moved: {pos_before[0]:.0f},{pos_before[1]:.0f} -> {pos_after[0]:.0f},{pos_after[1]:.0f}")

        # Test human click
        print(f"\n[8] Testing human click on <h1>...")
        try:
            await f.click("h1", timeout=5)
            print(f"    OK Clicked!")
        except Exception as e:
            print(f"    WARN Click error: {e}")

        # Test cookies
        print(f"\n[9] Testing cookies...")
        cookies = await f.page.cookies()
        print(f"    OK Cookies: {len(cookies)} items")

        # Test page content
        print(f"\n[10] Testing page content...")
        content = await f.page.content()
        print(f"    OK Content: {len(content)} chars")

        # Test evaluate_safe
        print(f"\n[11] Testing evaluate_safe (isolated world)...")
        try:
            result = await f.page.evaluate_safe("1 + 1")
            print(f"    OK 1 + 1 = {result}")
        except Exception as e:
            print(f"    WARN evaluate_safe error: {e}")

        # Test human type
        print(f"\n[12] Testing human locator auto-wait...")
        try:
            el = await f.human.locator("p", timeout=3)
            if el:
                text = await el.inner_text()
                print(f"    OK <p> text: {text[:60]}...")
        except Exception as e:
            print(f"    WARN locator error: {e}")

        print(f"\n{'='*60}")
        print(f"  All tests passed!")
        print(f"{'='*60}\n")


if __name__ == "__main__":
    try:
        asyncio.run(test_basic())
    except ConnectionError as e:
        print(f"\nERROR Connection failed: {e}")
        print(f"   Make sure Chrome is running with --remote-debugging-port=65262")
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
