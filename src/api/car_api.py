import time
import re
import sys

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

sys.stdout.reconfigure(encoding="utf-8")

def clean_text(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def get_text(el):
    return clean_text(el.get_text(" ", strip=True)) if el else ""


def crawl_mioto_cars(url, limit=30, max_scroll=20):
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1920,1080")

    driver = webdriver.Chrome(options=options)

    try:
        print("Đang mở trang Mioto...")
        driver.get(url.strip())

        wait = WebDriverWait(driver, 20)

        # Đợi danh sách xe xuất hiện
        wait.until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, 'a.item-car, a[href^="/car/"]')
            )
        )

        print("Đang cuộn để load thêm xe...")

        last_count = 0
        same_count_round = 0

        for _ in range(max_scroll):
            car_count = len(driver.find_elements(By.CSS_SELECTOR, 'a.item-car, a[href^="/car/"]'))

            print(f"Hiện có {car_count} xe")

            if car_count >= limit:
                break

            # Cuộn body
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

            # Một số layout Mioto có container scroll riêng
            driver.execute_script("""
                const el = document.querySelector('.scroll-fix');
                if (el) {
                    el.scrollTop = el.scrollHeight;
                }
            """)

            time.sleep(4)

            new_count = len(driver.find_elements(By.CSS_SELECTOR, 'a.item-car, a[href^="/car/"]'))

            if new_count == last_count:
                same_count_round += 1
            else:
                same_count_round = 0

            last_count = new_count

            # Nếu cuộn vài lần mà không có xe mới thì dừng
            if same_count_round >= 3:
                break

        soup = BeautifulSoup(driver.page_source, "html.parser")

    finally:
        driver.quit()

    car_elements = soup.select('a.item-car, a[href^="/car/"]')

    cars_data = []
    seen_links = set()

    for car in car_elements:
        if len(cars_data) >= limit:
            break

        # Strip all whitespace from href to avoid embedded newlines in malformed HTML
        href = re.sub(r"\s+", "", car.get("href", ""))
        if href.startswith("http"):
            full_link = href
        elif href.startswith("/"):
            full_link = "https://www.mioto.vn" + href
        else:
            full_link = ""

        # Normalize link for deduplication (ignore query params and fragments)
        dedup_key = full_link.split("?")[0].split("#")[0]
        if dedup_key in seen_links:
            continue

        seen_links.add(dedup_key)

        # Tên xe
        name = get_text(car.select_one(".desc-name"))

        # Skip elements without a car name — these are nested sub-links, not car cards
        if not name:
            continue

        # Tags: Miễn thế chấp, giao xe tận nơi...
        tags = []
        for tag in car.select(".desc-tag *"):
            txt = get_text(tag)
            if txt and txt not in tags:
                tags.append(txt)

        # Features: số tự động, 5 chỗ, xăng...
        feature_elements = car.select(".desc-features__item")
        features = [get_text(x) for x in feature_elements if get_text(x)]

        transmission = features[0] if len(features) > 0 else ""
        seats = features[1] if len(features) > 1 else ""
        fuel = features[2] if len(features) > 2 else ""

        # Địa chỉ
        address = (
            get_text(car.select_one(".desc-address-price .address p"))
            or get_text(car.select_one(".address p"))
            or get_text(car.select_one(".address"))
        )

        # # Giá
        price_block = (
            car.select_one(".desc-info-price .wrap-price .price")
            or car.select_one(".wrap-price .price")
            or car.select_one(".price")
        )

        price_special = ""
        price_origin = ""

        if price_block:
            # Tìm thẻ chứa giá
            origin_el = price_block.select_one(".price-origin")
            special_el = price_block.select_one(".price-special")
            
            # Lấy text
            txt_origin = get_text(origin_el)
            txt_special = get_text(special_el)
            
            if txt_origin and txt_special:
                # Nếu có cả 2 -> Xe đang giảm giá
                price_origin = txt_origin
                price_special = txt_special
            elif txt_special:
                # Nếu chỉ có special -> Xe KHÔNG giảm giá, giá special chính là giá gốc
                price_origin = txt_special
                price_special = "Không có"
            elif txt_origin:
                # Trường hợp dự phòng nếu chỉ có origin
                price_origin = txt_origin
                price_special = "Không có"
        
        # Rating và số chuyến
        info_spans = car.select(".desc-info-price span.info")
        info_values = [get_text(x) for x in info_spans if get_text(x)]

        rating = info_values[0] if len(info_values) > 0 else ""
        trips = info_values[1] if len(info_values) > 1 else ""

        # Ảnh xe nếu cần
        img = car.select_one(".img-car img, img")
        image_url = ""
        if img:
            image_url = (
                img.get("src")
                or img.get("data-src")
                or img.get("data-original")
                or ""
            )

        cars_data.append({
            "Tên xe": name,
            "Giá sau giảm": price_special,
            "Giá gốc": price_origin,
            "Hộp số": transmission,
            "Số chỗ": seats,
            "Nhiên liệu": fuel,
            "Địa chỉ": address,
            "Rating": rating,
            "Số chuyến": trips,
            "Tags": ", ".join(tags),
            "Ảnh": image_url,
            "Link": full_link,
        })

    return cars_data

def crawl_car_details(url, headless=False):
    options = webdriver.ChromeOptions()

    if headless:
        options.add_argument("--headless=new")

    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1920,1080")

    driver = webdriver.Chrome(options=options)
    detail = []
    try:
        print("Đang mở trang chi tiết Mioto...")
        driver.get(url.strip())

        wait = WebDriverWait(driver, 25)

        # Đợi phần detail-car load
        wait.until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "div.detail-car, div.info-car-basic")
            )
        )

        time.sleep(10)

        # Cuộn xuống để Mioto lazy-load hết nội dung
        for _ in range(8):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1)

        # Cuộn về đầu
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(10)

        soup = BeautifulSoup(driver.page_source, "html.parser")

    finally:
        driver.quit()


    # ======================
    # 1. Thông tin cơ bản
    # ======================

    basic_block = soup.select_one(".info-car-basic")

    name = get_text(
        soup.select_one(".info-car-basic .group-name h3")
        or soup.select_one(".group-name h3")
        or soup.select_one("h3")
        or soup.select_one("h1")
    )

    total_infos = []
    if basic_block:
        total_infos = [
            get_text(x)
            for x in basic_block.select(".group-total span.info")
            if get_text(x)
        ]

    trips = total_infos[0] if len(total_infos) >= 1 else ""
    address = total_infos[1] if len(total_infos) >= 2 else ""

    tags = []
    if basic_block:
        for tag in basic_block.select(".group-tag .tag-item"):
            txt = get_text(tag)
            if txt and txt not in tags:
                tags.append(txt)

    # detail["Tên xe"] = name
    # detail["Số chuyến"] = trips
    # detail["Địa chỉ"] = address
    # detail["Tags"] = tags

    # ======================
    # 2. Ảnh xe
    # ======================

    images = []

    for img in soup.select(".cover-car img, .detail-car img, img"):
        src = (
            img.get("src")
            or img.get("data-src")
            or img.get("data-original")
            or ""
        )

        if not src:
            continue

        if src.startswith("//"):
            src = "https:" + src
        elif src.startswith("/"):
            src = "https://www.mioto.vn" + src

        if src.startswith("http") and src not in images:
            images.append(src)

    # detail["Ảnh"] = images

    # ======================
    # 3. Giá thuê / box thuê xe
    # ======================

    rent_box = soup.select_one(".sidebar-detail .rent-box") or soup.select_one("#cardetail")

    price_text = ""

    if rent_box:
        price_text = (
            get_text(rent_box.select_one(".price-special"))
            or get_text(rent_box.select_one(".price"))
            or get_text(rent_box.select_one(".wrap-price"))
        )

    # detail["Giá thuê"] = price_text

    # ======================
    # 4. Phụ phí có thể phát sinh
    # ======================

    surcharges = []

    surcharge_block = soup.select_one(".sidebar-detail .surcharge .surcharge-container")

    if surcharge_block:
        surcharges = []
        for item in surcharge_block.select(".surcharge-item"):
            content_items = item.select(".content .content-item")
            title = get_text(content_items[0].select_one(".title"))
            cost = get_text(content_items[0].select_one(".cost.text-primary"))
            content = get_text(content_items[1])
            surcharges.append({
                "Tên phụ phí": title,
                "Chi phí": cost,
                "Nội dung": content,
            })

    # detail["Phụ phí"] = surcharges

    # ======================
    # 5. Đặc điểm xe
    # ======================

    features = {}

    for item in soup.select(".outstanding-features .outstanding-features__item"):
        key = get_text(item.select_one(".title .sub"))
        value = get_text(item.select_one(".title .main"))

        if key:
            features[key] = value

    # detail["Đặc điểm"] = features

    # ======================
    # 6. Mô tả
    # ======================

    description = ""

    for section in soup.select(".info-car-desc"):
        heading = get_text(section.select_one("h6"))

        if "Mô tả" in heading:
            description = (
                get_text(section.select_one("pre"))
                or get_text(section)
            )
            break

    # detail["Mô tả"] = description

    # ======================
    # 7. Giấy tờ thuê xe
    # ======================

    papers = []
    note = ""

    papers_block = soup.select_one("#papers")

    if papers_block:
        note = get_text(papers_block.select_one(".required-papers__item .font-12"))

        for item in papers_block.select(".required-papers__item"):
            type_name = get_text(item.select_one(".type-name"))
            item_text = get_text(item)

            if type_name:
                papers.append(type_name)
            elif item_text and item_text not in papers:
                papers.append(item_text)

        # detail["Ghi chú giấy tờ"] = note

    # detail["Giấy tờ thuê xe"] = papers

    # ======================
    # 8. Tài sản thế chấp
    # ======================

    mortgage = ""

    for section in soup.select(".info-car-desc"):
        heading = get_text(section.select_one("h6"))

        if "Tài sản thế chấp" in heading:
            mortgage = (
                get_text(section.select_one(".required-papers"))
                or get_text(section.select_one("p"))
                or get_text(section)
            )
            break

    # detail["Tài sản thế chấp"] = mortgage

    # ======================
    # 9. Điều khoản
    # ======================

    terms = ""

    for section in soup.select(".info-car-desc"):
        heading = get_text(section.select_one("h6"))

        if "Điều khoản" in heading:
            terms = (
                get_text(section.select_one("pre"))
                or get_text(section)
            )
            break

    # detail["Điều khoản"] = terms

    # detail["Link"] = url

    detail = {
        "Tên xe": name,
        "Số chuyến": trips,
        "Địa chỉ": address,
        "Tags": tags,
        "Ảnh": images,
        "Giá thuê": price_text,
        "Phụ phí": surcharges,
        "Đặc điểm": features,
        "Mô tả": description,
        "Giấy tờ thuê xe": papers,
        "Ghi chú giấy tờ": note,
        "Tài sản thế chấp": mortgage,
        "Điều khoản": terms,
        "Link": url,
    }

    return detail


# def main():
#     url = "https://www.mioto.vn/car/mitsubishi-xpander-2023/KGASGK"

#     detail = crawl_car_details(url, headless=False)

#     print("\n===== CHI TIẾT XE =====")
#     print(f"Tên xe: {detail.get('Tên xe')}")
#     print(f"Số chuyến: {detail.get('Số chuyến')}")
#     print(f"Địa chỉ: {detail.get('Địa chỉ')}")
#     print(f"Giá thuê: {detail.get('Giá thuê')}")
#     print(f"Tags: {', '.join(detail.get('Tags', []))}")

#     print("\nĐặc điểm:")
#     for key, value in detail.get("Đặc điểm", {}).items():
#         print(f"- {key}: {value}")

#     print("\nPhụ phí:")
#     for fee in detail.get("Phụ phí", []):
#         print(f"- {fee.get('Tên phụ phí')}: {fee.get('Chi phí')}")
#         print(f"  {fee.get('Nội dung')}")

#     print("\nMô tả:")
#     print(detail.get("Mô tả"))

#     print("\nGiấy tờ thuê xe:")
#     for item in detail.get("Giấy tờ thuê xe", []):
#         print(f"- {item}")

#     print("\nTài sản thế chấp:")
#     print(detail.get("Tài sản thế chấp"))

#     print("\nĐiều khoản:")
#     print(detail.get("Điều khoản"))

#     print("\nẢnh:")
#     for img in detail.get("Ảnh", [])[:5]:
#         print(img)

#     print("\nLink:")
#     print(detail.get("Link"))


# if __name__ == "__main__":
#     main()