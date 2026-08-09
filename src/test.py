import asyncio
import re
import sys
from urllib.parse import urljoin, urlencode, urlparse, parse_qs

from playwright.async_api import async_playwright

# Windows console thường lỗi khi print tiếng Việt
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _abs(href: str | None) -> str | None:
    if not href:
        return None
    return urljoin("https://www.booking.com", href)


def _href_has_hotel_id(href: str, hotel_id: str | int) -> bool:
    hid = str(hotel_id)
    if hid in href:
        return True
    qs = parse_qs(urlparse(href).query)
    for key in ("dest_id", "hotel_id", "highlighted_hotels"):
        if hid in (qs.get(key) or []):
            return True
    return False


async def _dismiss_cookies(page) -> None:
    for selector in (
        "#onetrust-accept-btn-handler",
        "button:has-text('Accept all')",
        "button:has-text('Accept')",
        "button:has-text('Chấp nhận')",
    ):
        btn = page.locator(selector)
        try:
            if await btn.count() > 0:
                await btn.first.click(timeout=2000)
                return
        except Exception:
            continue


async def get_booking_url(
    hotel_id: str | int,
    checkin: str,
    checkout: str,
    adults: int = 2,
    hotel_name: str | None = None,
) -> str | None:
    """
    Mở searchresults Booking, lấy href card khớp hotel_id (ưu tiên)
    hoặc khớp tên khách sạn.
    """
    params = {
        "ss": hotel_name or str(hotel_id),
        "dest_id": str(hotel_id),
        "dest_type": "hotel",
        "checkin": checkin,
        "checkout": checkout,
        "group_adults": adults,
        "group_children": 0,
        "no_rooms": 1,
        "req_adults": adults,
        "req_children": 0,
        "selected_currency": "VND",
    }
    search_url = "https://www.booking.com/searchresults.vi.html?" + urlencode(params)
    print("search_url:", search_url)

    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(headless=True, channel="chrome")
        except Exception:
            browser = await p.chromium.launch(headless=True)

        context = await browser.new_context(
            locale="vi-VN",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        try:
            await page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
            await _dismiss_cookies(page)

            # Đôi khi Booking redirect thẳng vào trang KS
            await page.wait_for_timeout(3000)
            current = page.url
            print("page.url:", current)
            if re.search(r"/hotel/[a-z]{2}/[^/?#]+\.html", current):
                return current

            try:
                await page.wait_for_selector(
                    'a[data-testid="title-link"]',
                    timeout=25000,
                )
            except Exception:
                print("Không thấy title-link. title=", await page.title())
                return None

            links = page.locator('a[data-testid="title-link"]')
            n = await links.count()
            print(f"title-link count = {n}")

            name_match = None
            for i in range(n):
                a = links.nth(i)
                title = (await a.inner_text()).strip()
                href = _abs(await a.get_attribute("href"))
                if not href:
                    continue

                print(f"  [{i}] {title}")
                print(f"      {href[:160]}...")

                if _href_has_hotel_id(href, hotel_id):
                    return href

                if (
                    hotel_name
                    and hotel_name.lower() in title.lower()
                    and name_match is None
                ):
                    name_match = href

            return name_match
        finally:
            await browser.close()


async def main():
    url = await get_booking_url(
        hotel_id=4295623,
        hotel_name="Solare De Monte Hotel & Spa",
        checkin="2026-09-20",
        checkout="2026-09-25",
        adults=4,
    )
    print("RESULT:", url)


if __name__ == "__main__":
    asyncio.run(main())
