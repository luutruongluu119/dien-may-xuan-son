# -*- coding: utf-8 -*-
"""Điện Máy Xuân Son — website bán đồ điện máy (điều hòa, máy giặt,
bình nóng lạnh, tủ lạnh). Đặt hàng qua hotline / để lại số điện thoại,
không tích hợp thanh toán online.

Chạy:  python app.py   rồi mở http://127.0.0.1:5130
"""
from __future__ import annotations

import base64
import os
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timedelta
from urllib.parse import quote as urlquote

from flask import (
    Flask, Response, abort, flash, g, jsonify, redirect, render_template,
    request, session, url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

import ai
import db
import fb_capi

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads", "products")
BRAND_UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads", "brands")
ARTICLE_UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads", "articles")
try:
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    os.makedirs(BRAND_UPLOAD_DIR, exist_ok=True)
    os.makedirs(ARTICLE_UPLOAD_DIR, exist_ok=True)
except OSError:
    pass  # read-only filesystem (Vercel) — dirs are already bundled with existing uploads
ALLOWED_EXT = {"jpg", "jpeg", "png", "webp", "gif", "svg"}
PER_PAGE = 12
AC_TREO_TUONG_BRANDS = ["Panasonic", "Daikin", "LG", "Casper", "Funiki", "Nagakawa"]
AC_CATEGORY_NAMES = ["Điều hòa treo tường", "Điều hòa âm trần", "Điều hòa nối ống gió", "Điều hòa tủ đứng"]

INSTALL_PRICING = [
    ("Công lắp đặt tiêu chuẩn — máy 1 chiều ≤ 18.000 BTU", "300.000đ"),
    ("Công lắp đặt tiêu chuẩn — máy 1 chiều > 18.000 BTU hoặc 2 chiều", "400.000đ - 500.000đ"),
    ("Dây đồng bổ sung (ống 6/10), mỗi mét vượt tiêu chuẩn", "150.000đ/m"),
    ("Dây đồng bổ sung (ống 6/12 — máy công suất lớn), mỗi mét", "220.000đ/m"),
    ("Khoan tường bê tông / mái tôn", "100.000đ - 150.000đ/lỗ"),
    ("Giá treo dàn nóng tiêu chuẩn", "Miễn phí"),
    ("Giá treo dàn nóng trên cao / vị trí khó thi công", "200.000đ - 500.000đ"),
    ("Bảo dưỡng vệ sinh máy định kỳ", "150.000đ - 250.000đ/lần"),
]

POLICIES = {
    "thanh-toan": {
        "title": "Hình thức thanh toán",
        "body": [
            "Thanh toán tiền mặt khi nhận hàng (COD) áp dụng cho khu vực nội thành Hà Nội.",
            "Chuyển khoản trước qua tài khoản ngân hàng của Điện Máy Xuân Son đối với đơn hàng"
            " ở xa hoặc giá trị lớn, có xác nhận qua điện thoại trước khi giao.",
            "Có thể thanh toán một phần khi đặt cọc giữ hàng, phần còn lại thanh toán khi giao"
            " lắp đặt xong và khách hàng kiểm tra sản phẩm.",
        ],
    },
    "van-chuyen": {
        "title": "Chính sách vận chuyển",
        "body": [
            "Giao hàng miễn phí trong nội thành Hà Nội với đơn từ 3 triệu đồng trở lên.",
            "Thời gian giao hàng thông thường từ 1-3 ngày sau khi xác nhận đơn hàng, khu vực xa"
            " trung tâm có thể lâu hơn tuỳ lịch trình vận chuyển.",
            "Đội ngũ kỹ thuật hỗ trợ lắp đặt tận nơi đối với điều hòa, bình nóng lạnh; có báo giá"
            " công lắp đặt/vật tư phát sinh (nếu có) trước khi thi công.",
        ],
    },
    "bao-hanh": {
        "title": "Bảo hành & đổi trả",
        "body": [
            "Sản phẩm được bảo hành chính hãng theo đúng thời hạn ghi trên phiếu bảo hành/tem"
            " nhà sản xuất, thường từ 12-24 tháng tuỳ loại sản phẩm.",
            "Đổi mới trong 7 ngày đầu nếu sản phẩm lỗi do nhà sản xuất, còn nguyên tem/phụ kiện,"
            " chưa qua sử dụng lắp đặt làm thay đổi hiện trạng máy.",
            "Hỗ trợ tiếp nhận bảo hành, sửa chữa tại nhà đối với các sản phẩm cồng kềnh như điều"
            " hòa, tủ lạnh, máy giặt.",
        ],
    },
    "bao-mat": {
        "title": "Chính sách bảo mật thông tin",
        "body": [
            "Thông tin khách hàng (họ tên, số điện thoại, địa chỉ) chỉ được sử dụng để liên hệ tư"
            " vấn, xác nhận và giao nhận đơn hàng.",
            "Điện Máy Xuân Son cam kết không chia sẻ, bán thông tin khách hàng cho bên thứ ba vì"
            " mục đích thương mại.",
            "Khách hàng có quyền yêu cầu chỉnh sửa hoặc xoá thông tin cá nhân đã cung cấp bằng"
            " cách liên hệ trực tiếp qua hotline.",
        ],
    },
    "dai-ly": {
        "title": "Chính sách ưu đãi đại lý",
        "body": [
            "Áp dụng chiết khấu theo số lượng cho đại lý, cửa hàng, đơn vị thi công lắp đặt mua"
            " hàng thường xuyên.",
            "Hỗ trợ giá sỉ, ưu tiên đơn hàng và tư vấn kỹ thuật riêng cho đối tác đại lý.",
            "Liên hệ hotline để được tư vấn chính sách chiết khấu chi tiết theo từng nhóm sản"
            " phẩm và sản lượng dự kiến.",
        ],
    },
}

AI_CONTENT_TYPES = {
    "so_sanh": "So sánh sản phẩm — so sánh trực tiếp các sản phẩm được cung cấp, chỉ rõ sản"
               " phẩm nào hợp với nhu cầu/ngân sách nào.",
    "huong_dan": "Hướng dẫn chọn mua — hướng dẫn khách chọn sản phẩm phù hợp trong danh mục,"
                 " có nhắc tới các sản phẩm cụ thể được cung cấp làm ví dụ minh hoạ.",
    "faq": "Hỏi đáp — trả lời các câu hỏi khách hay thắc mắc khi mua nhóm sản phẩm này, có"
           " nhắc tới sản phẩm cụ thể khi phù hợp.",
}

AI_SYSTEM_TMPL = """Bạn là biên tập viên nội dung SEO tiếng Việt cho "{company}", cửa hàng điện máy tại {address}. Giọng văn thân thiện, đáng tin cậy, không thổi phồng, tuyệt đối không bịa đặt chứng nhận/giải thưởng/lời chứng thực khách hàng không có thật.

Nhiệm vụ: viết 1 bài blog SEO dạng "{content_label}" nhắm tới từ khóa mục tiêu, dựa trên dữ liệu sản phẩm THẬT được cung cấp bên dưới (tên, giá, thông số) — không tự bịa thêm sản phẩm, thông số hay mức giá khác với dữ liệu đã cho.

CHỈ trả về JSON thuần (không bọc ```json, không giải thích gì thêm ngoài JSON), đúng cấu trúc:
{{
  "meta_title": "tối đa 60 ký tự, chứa từ khóa mục tiêu",
  "meta_description": "tối đa 160 ký tự, hấp dẫn, chứa từ khóa mục tiêu",
  "title": "tiêu đề bài viết (thẻ H1)",
  "excerpt": "1-2 câu mô tả ngắn, hiển thị ở danh sách bài viết",
  "content": "nội dung bài viết — xem quy tắc định dạng bắt buộc bên dưới"
}}

Quy tắc định dạng BẮT BUỘC cho "content" (hệ thống hiển thị parse theo từng dòng, không hỗ trợ markdown):
- Mỗi dòng là MỘT khối nội dung hoàn chỉnh: hoặc là tiêu đề phụ (bắt đầu bằng "## "), hoặc là MỘT đoạn văn trọn vẹn.
- TUYỆT ĐỐI không xuống dòng ở giữa một đoạn văn — cả đoạn phải nằm trên đúng 1 dòng duy nhất (có thể dài).
- Bài nên có 3-4 tiêu đề phụ ("## ...") xen giữa các đoạn văn, tổng cộng khoảng 500-800 chữ.
- Khi nhắc tới sản phẩm cụ thể, dùng đúng tên sản phẩm đã được cung cấp."""


def build_ai_user_message(keyword: str, category_name: str, products, notes: str) -> str:
    lines = [f"Từ khóa mục tiêu: {keyword}"]
    if category_name:
        lines.append(f"Danh mục: {category_name}")
    if notes:
        lines.append(f"Ghi chú thêm từ chủ shop: {notes}")
    if products:
        lines.append("Sản phẩm thật để nhắc tới trong bài (không bịa thêm sản phẩm khác):")
        for p in products:
            price = format_price(p["sale_price"] or p["price"])
            specs = spec_map(p["specs"])
            specs_line = "; ".join(f"{k}: {v}" for k, v in list(specs.items())[:6])
            brand = p["brand_name"] or "đang cập nhật"
            lines.append(f"- {p['name']} (thương hiệu {brand}, giá {price}): {specs_line}")
    else:
        lines.append("Không có sản phẩm cụ thể nào được chọn — viết nội dung tổng quan về danh mục.")
    return "\n".join(lines)


CHAT_SYSTEM_TMPL = """Bạn là trợ lý tư vấn bán hàng của "{company}", cửa hàng điện máy tại {address}, hotline {hotline}. Xưng "shop" hoặc "{company}", gọi khách là "anh/chị". Giọng văn thân thiện, ngắn gọn, tự nhiên như nhân viên tư vấn thật đang nhắn tin — không rao giảng, không liệt kê dài dòng.

QUY TẮC BẮT BUỘC:
- CHỈ tư vấn dựa trên sản phẩm THẬT trong danh sách "SẢN PHẨM LIÊN QUAN" bên dưới (đúng tên, giá, thông số, link). TUYỆT ĐỐI không bịa thêm sản phẩm, giá hay thông số nào khác.
- Nếu danh sách rỗng hoặc không có sản phẩm phù hợp với câu hỏi, thành thật nói shop chưa có thông tin chính xác và mời khách gọi hotline {hotline} — KHÔNG đoán hay bịa sản phẩm.
- Khi nhắc một sản phẩm cụ thể, luôn kèm giá đã có sẵn trong dữ liệu.
- Trả lời ngắn gọn (khoảng 2-4 câu mỗi lượt). Nếu khách có vẻ muốn mua/đặt hàng, chủ động hỏi xin số điện thoại để shop gọi lại tư vấn kỹ hơn và báo giá lắp đặt.
- Nếu khách hỏi ngoài chủ đề mua sắm/sản phẩm điện máy, trả lời ngắn gọn rồi nhẹ nhàng lái về việc tư vấn sản phẩm.

DANH MỤC ĐANG BÁN: {categories}

SẢN PHẨM LIÊN QUAN TỚI CÂU HỎI GẦN NHẤT CỦA KHÁCH (dữ liệu thật, đang bán):
{products_block}"""


def build_chat_system(settings: dict, categories, products) -> str:
    cat_names = ", ".join(c["name"] for c in categories)
    if products:
        lines = []
        for p in products:
            price = format_price(p["sale_price"] or p["price"])
            brand = p["brand_name"] or "đang cập nhật"
            url = url_for("product_page", slug=p["slug"], _external=False)
            lines.append(f"- {p['name']} (hãng {brand}, danh mục {p['category_name']}, giá {price}): "
                         f"{p['short_desc'] or ''} — link: {url}")
        products_block = "\n".join(lines)
    else:
        products_block = "(không có sản phẩm nào khớp câu hỏi gần nhất — nói thật với khách, đừng bịa)"
    return CHAT_SYSTEM_TMPL.format(
        company=settings["company_name"], address=settings["address"],
        hotline=settings["hotline"], categories=cat_names, products_block=products_block,
    )


def generate_article_draft(settings: dict, content_type: str, keyword: str,
                            category_name: str, products, notes: str) -> dict:
    """Gọi Claude sinh 1 bài nháp. Dùng chung cho route thủ công và job chạy theo lịch.
    Có thể raise ai.AIError — caller tự quyết định xử lý (báo lỗi cho người dùng hoặc
    đánh dấu hàng đợi bị lỗi)."""
    if content_type not in AI_CONTENT_TYPES:
        content_type = "huong_dan"
    system = AI_SYSTEM_TMPL.format(
        company=settings["company_name"], address=settings["address"],
        content_label=AI_CONTENT_TYPES[content_type],
    )
    user_msg = build_ai_user_message(keyword, category_name, products, notes)
    raw = ai.generate_text(settings, system, user_msg)
    draft = ai.extract_json(raw)
    draft["keyword"] = keyword
    draft["related_product_ids"] = ",".join(str(p["id"]) for p in products)
    return draft


app = Flask(__name__, static_folder="static", static_url_path="/static")
try:
    app.json.ensure_ascii = False
except AttributeError:
    app.config["JSON_AS_ASCII"] = False
app.secret_key = "dienmay-xuanson-" + uuid.uuid5(uuid.NAMESPACE_DNS, "xuanson.local").hex

db.init_db()
AC_CATEGORY_SLUGS = {db.slugify(n) for n in AC_CATEGORY_NAMES}


# --------------------------------------------------------------- tiện ích

def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


def optimize_to_webp(path: str) -> str:
    """Convert a just-saved JPG/PNG upload to WebP in place for faster page loads.
    Returns the (possibly new) file path; falls back to the original on any error."""
    root, ext = os.path.splitext(path)
    if ext.lower() not in (".jpg", ".jpeg", ".png"):
        return path
    try:
        from PIL import Image
        im = Image.open(path)
        webp_path = root + ".webp"
        if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
            im.convert("RGBA").save(webp_path, "WEBP", quality=85, method=6)
        else:
            im.convert("RGB").save(webp_path, "WEBP", quality=82, method=6)
        os.remove(path)
        return webp_path
    except Exception:
        return path


def save_upload(file_storage):
    if not file_storage or not file_storage.filename:
        return None
    if not allowed_file(file_storage.filename):
        return None
    ext = file_storage.filename.rsplit(".", 1)[1].lower()
    fname = f"{uuid.uuid4().hex}.{ext}"
    dest = os.path.join(UPLOAD_DIR, fname)
    try:
        file_storage.save(dest)
    except OSError:
        flash("Bản online không lưu được ảnh upload (chỉ đọc) — sửa ảnh ở máy chủ chính rồi đẩy lại lên GitHub.", "error")
        return None
    dest = optimize_to_webp(dest)
    return f"uploads/products/{os.path.basename(dest)}"


def save_brand_logo(file_storage):
    if not file_storage or not file_storage.filename:
        return None
    if not allowed_file(file_storage.filename):
        return None
    ext = file_storage.filename.rsplit(".", 1)[1].lower()
    fname = f"{uuid.uuid4().hex}.{ext}"
    dest = os.path.join(BRAND_UPLOAD_DIR, fname)
    try:
        file_storage.save(dest)
    except OSError:
        flash("Bản online không lưu được ảnh upload (chỉ đọc) — sửa ảnh ở máy chủ chính rồi đẩy lại lên GitHub.", "error")
        return None
    dest = optimize_to_webp(dest)
    return f"uploads/brands/{os.path.basename(dest)}"


def save_generated_image_bytes(mime: str, b64data: str) -> str:
    ext = {"image/png": "png", "image/jpeg": "jpg", "image/jpg": "jpg", "image/webp": "webp"}.get(mime, "png")
    fname = f"{uuid.uuid4().hex}.{ext}"
    dest = os.path.join(ARTICLE_UPLOAD_DIR, fname)
    try:
        with open(dest, "wb") as f:
            f.write(base64.b64decode(b64data))
    except OSError:
        return ""
    dest = optimize_to_webp(dest)
    return f"uploads/articles/{os.path.basename(dest)}"


def build_article_image_prompt(title: str, category_name: str) -> str:
    return (
        f'Vẽ 1 ảnh bìa minh hoạ cho bài blog điện máy tiếng Việt, chủ đề: "{title}"'
        f" (danh mục: {category_name or 'đồ điện gia dụng'}). "
        "Phong cách: ảnh chụp thực tế, sáng, gọn gàng, bối cảnh nhà ở Việt Nam hiện đại — "
        "ví dụ phòng khách/phòng bếp có sản phẩm điện máy đang sử dụng. "
        "TUYỆT ĐỐI không vẽ logo, nhãn hiệu hay chữ trên ảnh — đây là ảnh minh hoạ bối cảnh "
        "sử dụng, không phải ảnh chụp đúng sản phẩm thật của cửa hàng."
    )


def run_scheduled_generation():
    """Job chạy nền theo lịch: lấy 1 chủ đề chờ xử lý trong hàng đợi, viết nháp + tạo ảnh
    minh hoạ, lưu thành bài viết chưa đăng (published=0) để chủ shop duyệt sau."""
    settings = db.load_settings()
    if not settings.get("schedule_enabled"):
        return
    per_week = int(settings.get("schedule_per_week") or 2)
    since = (datetime.utcnow() - timedelta(days=7)).isoformat()
    if db.queue_generated_count_since(since) >= per_week:
        return
    item = db.next_pending_queue_item()
    if not item:
        return

    product_ids = [int(i) for i in (item["product_ids"] or "").split(",") if i.strip().isdigit()]
    products = db.get_products_by_ids(product_ids)
    category_name = ""
    if item["category_id"]:
        cat = next((c for c in db.list_categories() if c["id"] == item["category_id"]), None)
        category_name = cat["name"] if cat else ""

    try:
        draft = generate_article_draft(
            settings, item["content_type"], item["keyword"], category_name, products,
            item["notes"] or "",
        )
    except ai.AIError as e:
        db.update_queue_item(item["id"], {"status": "loi", "error": str(e)})
        return

    image_path = ""
    if (settings.get("gemini_key") or "").strip():
        try:
            prompt = build_article_image_prompt(draft.get("title") or item["keyword"], category_name)
            img = ai.generate_image(settings, prompt)
            image_path = save_generated_image_bytes(img["mime"], img["data"])
        except ai.AIError:
            pass  # không có ảnh vẫn đăng nháp được, không chặn cả bài viết

    article_id = db.create_article({
        "title": draft.get("title") or item["keyword"],
        "image": image_path,
        "excerpt": draft.get("excerpt", ""),
        "content": draft.get("content", ""),
        "category": category_name or "Kiến thức tiêu dùng",
        "published": 0,
        "meta_title": draft.get("meta_title", ""),
        "meta_description": draft.get("meta_description", ""),
        "keyword": draft.get("keyword", item["keyword"]),
        "related_product_ids": draft.get("related_product_ids", ""),
    })
    db.update_queue_item(item["id"], {"status": "da_tao", "article_id": article_id})


# --------------------------------------------------- đăng bài nhanh (1 nút)

PUBLISH_JOBS: dict[str, dict] = {}
PUBLISH_JOBS_LOCK = threading.Lock()


def _set_publish_job(job_id: str, **kw) -> None:
    with PUBLISH_JOBS_LOCK:
        PUBLISH_JOBS[job_id].update(kw)


def _new_publish_job() -> str:
    job_id = uuid.uuid4().hex[:10]
    with PUBLISH_JOBS_LOCK:
        PUBLISH_JOBS[job_id] = {"status": "running", "stage": "Chuẩn bị…",
                                "error": None, "result": None}
    return job_id


def do_publish_now(job_id: str, content_type: str, keyword: str, category_name: str,
                   notes: str, product_ids: list[int]) -> None:
    """Viết bài bằng AI (ưu tiên Gemini, xem ai.generate_text) + tạo ảnh minh
    hoạ + đăng NGAY (published=1), rồi tự commit + push GitHub + deploy
    Vercel để bài lên thật trên site ngay lập tức. Chỉ chạy được ở máy local
    (cần git + vercel CLI) — bản chạy trên Vercel có filesystem chỉ đọc nên
    không thể tự commit/deploy chính nó."""
    if os.environ.get("VERCEL"):
        _set_publish_job(job_id, status="error",
                         error="Chức năng này chỉ chạy được ở máy local (cần git/vercel CLI).")
        return
    try:
        settings = db.load_settings()
        products = db.get_products_by_ids(product_ids[:4])

        _set_publish_job(job_id, stage="AI đang viết bài…")
        draft = generate_article_draft(settings, content_type, keyword, category_name, products, notes)

        _set_publish_job(job_id, stage="Đang tạo ảnh minh hoạ…")
        image_path = ""
        if (settings.get("gemini_key") or "").strip():
            try:
                prompt = build_article_image_prompt(draft.get("title") or keyword, category_name)
                img = ai.generate_image(settings, prompt)
                image_path = save_generated_image_bytes(img["mime"], img["data"])
            except ai.AIError:
                pass  # không có ảnh vẫn đăng được, không chặn cả bài viết

        _set_publish_job(job_id, stage="Đang lưu bài viết…")
        article_id = db.create_article({
            "title": draft.get("title") or keyword,
            "image": image_path,
            "excerpt": draft.get("excerpt", ""),
            "content": draft.get("content", ""),
            "category": category_name or "Kiến thức tiêu dùng",
            "published": 1,
            "meta_title": draft.get("meta_title", ""),
            "meta_description": draft.get("meta_description", ""),
            "keyword": draft.get("keyword", keyword),
            "related_product_ids": draft.get("related_product_ids", ""),
        })
        article = db.get_article(article_id)

        _set_publish_job(job_id, stage="Đang đưa bài lên site thật (git + Vercel)…")
        git_files = ["data/shop.db"]
        if image_path:
            git_files.append("static/" + image_path)
        try:
            add = subprocess.run(["git", "add"] + git_files, cwd=BASE_DIR,
                                 capture_output=True, text=True, encoding="utf-8", errors="replace")
            if add.returncode != 0:
                raise RuntimeError("git add lỗi: " + (add.stderr or add.stdout)[-500:])
            commit = subprocess.run(
                ["git", "commit", "-m", f"Tự động đăng bài: {article['title']}"],
                cwd=BASE_DIR, capture_output=True, text=True, encoding="utf-8", errors="replace")
            if commit.returncode != 0 and "nothing to commit" not in (commit.stdout + commit.stderr):
                raise RuntimeError("git commit lỗi: " + (commit.stderr or commit.stdout)[-500:])
            push = subprocess.run(["git", "push"], cwd=BASE_DIR, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace")
            if push.returncode != 0:
                raise RuntimeError("git push lỗi: " + push.stderr[-500:])
            deploy = subprocess.run("npx vercel --prod --yes", cwd=BASE_DIR, shell=True,
                                    capture_output=True, text=True, timeout=240,
                                    encoding="utf-8", errors="replace")
            if deploy.returncode != 0:
                raise RuntimeError("vercel deploy lỗi: " + deploy.stderr[-500:])
        except Exception as exc:  # noqa: BLE001 — bài đã lưu local, chỉ bước đẩy lên site lỗi
            _set_publish_job(
                job_id, status="done", stage="Đã lưu bài, nhưng CHƯA đẩy lên site thật được",
                result={"article_id": article_id, "slug": article["slug"],
                        "title": article["title"], "deployed": False,
                        "deploy_error": str(exc)[:500]})
            return

        _set_publish_job(
            job_id, status="done", stage="Hoàn tất — đã lên site thật",
            result={"article_id": article_id, "slug": article["slug"],
                    "title": article["title"], "deployed": True})
    except ai.AIError as exc:
        _set_publish_job(job_id, status="error", error=str(exc))
    except Exception as exc:  # noqa: BLE001 — surfaced to the UI
        _set_publish_job(job_id, status="error", error=str(exc))


def parse_specs(text: str):
    specs = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            specs.append({"k": k.strip(), "v": v.strip()})
        else:
            specs.append({"k": line, "v": ""})
    return specs


def specs_to_text(specs) -> str:
    return "\n".join(f"{s['k']}: {s['v']}" if s.get("v") else s["k"] for s in specs)


def format_price(value) -> str:
    if value is None:
        return ""
    return f"{int(value):,}".replace(",", ".") + " đ"


def parse_article(text):
    blocks = []
    for line in (text or "").split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("## "):
            blocks.append(("h3", line[3:].strip()))
        else:
            blocks.append(("p", line))
    return blocks


def spec_map(specs_json):
    import json
    return {s["k"]: s["v"] for s in json.loads(specs_json or "[]")}


app.jinja_env.filters["price"] = format_price
app.jinja_env.filters["specs"] = lambda s: __import__("json").loads(s or "[]")
app.jinja_env.filters["urlencode"] = urlquote
app.jinja_env.filters["article"] = parse_article


@app.before_request
def load_common():
    g.settings = db.load_settings()
    g.nav_categories = db.list_categories()


@app.context_processor
def inject_globals():
    return {"settings": g.settings, "nav_categories": g.nav_categories}


def login_required(view):
    from functools import wraps

    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin_login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


# ------------------------------------------------------------- trang public

@app.route("/")
def home():
    featured, _ = db.list_products(featured=True, per_page=12)
    latest, _ = db.list_products(sort="new", per_page=8)
    articles = db.list_articles(limit=5)
    brands = db.list_brands()
    brand_by_name = {b["name"]: b for b in brands}

    ac_slug = db.slugify("Điều hòa treo tường")
    ac_blocks = []
    for name in AC_TREO_TUONG_BRANDS:
        b = brand_by_name.get(name)
        if not b:
            continue
        products, _ = db.list_products(category_slug=ac_slug, brand_id=b["id"], per_page=4)
        if products:
            ac_blocks.append({"brand": b, "products": products})

    washer_slug = db.slugify("Máy giặt")
    heater_slug = db.slugify("Bình nóng lạnh")
    washer_products, _ = db.list_products(category_slug=washer_slug, per_page=4)
    heater_products, _ = db.list_products(category_slug=heater_slug, per_page=4)
    deal_products, _ = db.list_products(on_sale=True, sort="discount", per_page=4)

    return render_template(
        "home.html", featured=featured, latest=latest, brands=brands,
        deal_products=deal_products,
        articles=articles, ac_blocks=ac_blocks, ac_category_slug=ac_slug,
        washer_products=washer_products, washer_slug=washer_slug,
        heater_products=heater_products, heater_slug=heater_slug,
    )


@app.route("/danh-muc/<slug>")
def category_page(slug):
    cat = db.get_category_by_slug(slug)
    if not cat:
        abort(404)
    page = max(1, request.args.get("page", 1, type=int))
    brand_id = request.args.get("brand", type=int)
    sort = request.args.get("sort", "new")
    loai = request.args.get("loai")
    duoi = request.args.get("duoi", type=int)
    xuat_xu = request.args.get("xuat_xu")
    noibat = request.args.get("noibat", type=int)
    products, total = db.list_products(
        category_slug=slug, brand_id=brand_id, sort=sort, page=page, per_page=PER_PAGE,
        loai=loai, duoi=duoi, xuat_xu=xuat_xu, featured=bool(noibat) if noibat else None,
    )
    pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    extra_args = {}
    if loai:
        extra_args["loai"] = loai
    if duoi:
        extra_args["duoi"] = duoi
    if xuat_xu:
        extra_args["xuat_xu"] = xuat_xu
    if noibat:
        extra_args["noibat"] = noibat
    filter_label = None
    if loai:
        filter_label = loai.capitalize()
    elif duoi:
        filter_label = f"Dưới {format_price(duoi)}"
    elif xuat_xu:
        filter_label = f"Xuất xứ {xuat_xu}"
    elif noibat:
        filter_label = "Sản phẩm bán chạy"
    return render_template(
        "category.html", category=cat, products=products,
        brands=db.list_brands_for_category(slug),
        total=total, page=page, pages=pages, brand_id=brand_id, sort=sort,
        extra_args=extra_args, filter_label=filter_label,
    )


@app.route("/san-pham/<slug>")
def product_page(slug):
    product = db.get_product_by_slug(slug)
    if not product:
        abort(404)
    related = db.related_products(product["category_slug"], product["id"])

    internal_links = []
    specs = spec_map(product["specs"])
    if product["brand_id"] and product["brand_name"]:
        base = f"{product['category_name']} {product['brand_name']}"
        cat_slug, brand_id = product["category_slug"], product["brand_id"]
        loai_text = specs.get("Loại", "")
        if "2 chiều" in loai_text:
            internal_links.append((f"{base} 2 Chiều", url_for("category_page", slug=cat_slug, brand=brand_id, loai="2 chiều")))
        elif "1 chiều" in loai_text:
            internal_links.append((f"{base} 1 Chiều", url_for("category_page", slug=cat_slug, brand=brand_id, loai="1 chiều")))
        internal_links.append((f"{base} Sản phẩm bán chạy", url_for("category_page", slug=cat_slug, brand=brand_id, noibat=1)))
        price_val = product["sale_price"] or product["price"]
        for muc in (5000000, 10000000, 20000000):
            if price_val < muc:
                internal_links.append((f"{base} Dưới {muc // 1000000} Triệu", url_for("category_page", slug=cat_slug, brand=brand_id, duoi=muc)))
                break
        internal_links.append((f"{base} Sản phẩm mới", url_for("category_page", slug=cat_slug, brand=brand_id, sort="new")))
        xuat_xu = specs.get("Xuất xứ", "")
        if xuat_xu:
            first_origin = xuat_xu.split("/")[0].strip()
            internal_links.append((f"{base} {first_origin}", url_for("category_page", slug=cat_slug, brand=brand_id, xuat_xu=first_origin)))

    install_pricing = INSTALL_PRICING if product["category_slug"] in AC_CATEGORY_SLUGS else None

    return render_template(
        "product.html", product=product, related=related,
        internal_links=internal_links, install_pricing=install_pricing,
    )


@app.route("/tim-kiem")
def search_page():
    q = request.args.get("q", "").strip()
    page = max(1, request.args.get("page", 1, type=int))
    products, total = db.list_products(q=q, page=page, per_page=PER_PAGE) if q else ([], 0)
    pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    return render_template(
        "category.html", category=None, products=products,
        brands=db.list_brands_for_search(q) if q else [],
        total=total, page=page, pages=pages, brand_id=None, sort="new",
        search_q=q,
    )


@app.route("/gioi-thieu")
def about_page():
    return render_template("contact.html")


@app.route("/tin-tuc")
def article_list_page():
    return render_template("article_list.html", articles=db.list_articles())


@app.route("/tin-tuc/<slug>")
def article_detail_page(slug):
    article = db.get_article_by_slug(slug)
    if not article or not article["published"]:
        abort(404)
    others = [a for a in db.list_articles(limit=5) if a["id"] != article["id"]][:4]
    related_ids = [int(i) for i in (article["related_product_ids"] or "").split(",") if i.strip().isdigit()]
    related_products = db.get_products_by_ids(related_ids)
    return render_template(
        "article_detail.html", article=article, others=others, related_products=related_products,
    )


@app.route("/chinh-sach/<slug>")
def policy_page(slug):
    policy = POLICIES.get(slug)
    if not policy:
        abort(404)
    return render_template("policy.html", policy=policy)


@app.route("/robots.txt")
def robots():
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /admin/",
        f"Sitemap: {url_for('sitemap', _external=True)}",
    ]
    return Response("\n".join(lines), mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap():
    urls = [url_for("home", _external=True), url_for("about_page", _external=True),
            url_for("article_list_page", _external=True)]
    for c in db.list_categories():
        urls.append(url_for("category_page", slug=c["slug"], _external=True))
    products, _ = db.list_products(per_page=1000)
    for p in products:
        urls.append(url_for("product_page", slug=p["slug"], _external=True))
    for a in db.list_articles():
        urls.append(url_for("article_detail_page", slug=a["slug"], _external=True))
    xml = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    xml += [f"<url><loc>{u}</loc></url>" for u in urls]
    xml.append("</urlset>")
    return Response("\n".join(xml), mimetype="application/xml")


@app.route("/dat-hang", methods=["POST"])
def submit_lead():
    name = request.form.get("name", "").strip()
    phone = request.form.get("phone", "").strip()
    product_id = request.form.get("product_id", type=int)
    note = request.form.get("note", "").strip()
    variant = request.form.get("variant", "order")
    is_htmx = request.headers.get("HX-Request") == "true"

    if not name or not phone:
        if is_htmx:
            return render_template(
                "_lead_form_fields.html", lead_variant=variant, lead_name=name,
                lead_phone=phone, lead_note=note, lead_product_id=product_id,
                lead_back=request.form.get("back"),
                lead_error="Vui lòng nhập đầy đủ họ tên và số điện thoại.",
            )
        flash("Vui lòng nhập đầy đủ họ tên và số điện thoại.", "error")
        return redirect(request.form.get("back") or url_for("home"))

    db.create_lead(name, phone, product_id, note)
    settings = db.load_settings()
    if settings.get("fb_pixel_id") and settings.get("fb_capi_token"):
        fb_capi.send_lead_event(
            settings["fb_pixel_id"], settings["fb_capi_token"],
            phone=phone, name=name, event_source_url=request.url,
            client_ip=request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip(),
            user_agent=request.headers.get("User-Agent", ""),
            fbp=request.cookies.get("_fbp", ""), fbc=request.cookies.get("_fbc", ""))
    if is_htmx:
        return render_template("_lead_success.html", lead_variant=variant, lead_phone=phone)
    flash("Cảm ơn bạn! Xuân Son sẽ gọi lại trong ít phút để tư vấn.", "success")
    return redirect(request.form.get("back") or url_for("home"))


@app.route("/api/chat", methods=["POST"])
def api_chat():
    payload = request.get_json(silent=True) or {}
    history = payload.get("history") or []
    if not isinstance(history, list) or not history:
        return {"error": "Thiếu nội dung tin nhắn."}, 400
    last_user = ""
    for m in reversed(history):
        if isinstance(m, dict) and m.get("role") == "user":
            last_user = (m.get("content") or "").strip()
            break
    if not last_user:
        return {"error": "Thiếu nội dung tin nhắn."}, 400

    settings = db.load_settings()
    if not (settings.get("claude_key") or settings.get("gemini_key") or "").strip():
        return {"error": "Chat AI chưa được bật — chủ shop cần dán Gemini hoặc Claude API key trong Cài đặt."}, 400

    messages = [
        {"role": m["role"], "content": m["content"]}
        for m in history
        if isinstance(m, dict) and m.get("role") in ("user", "assistant") and m.get("content")
    ][-16:]
    products = db.search_products_for_chat(last_user, limit=6)
    system = build_chat_system(settings, g.nav_categories, products)
    try:
        reply = ai.chat_reply(settings, system, messages, max_tokens=1024)
    except ai.AIError as e:
        print(f"[api_chat] AIError: {e}", file=sys.stderr)
        return {"error": f"Xin lỗi, trợ lý AI đang gặp sự cố kỹ thuật. Anh/chị vui lòng gọi hotline {settings['hotline']} để được tư vấn ngay ạ."}, 400
    return {"reply": reply}


# -------------------------------------------------------------------- admin

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        s = db.load_settings()
        if username == s["admin_username"] and check_password_hash(
            s["admin_password_hash"], password
        ):
            session["admin"] = True
            return redirect(request.args.get("next") or url_for("admin_dashboard"))
        flash("Sai tên đăng nhập hoặc mật khẩu.", "error")
    return render_template("admin/login.html")


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("admin_login"))


@app.route("/admin")
@login_required
def admin_dashboard():
    return render_template(
        "admin/dashboard.html", counts=db.counts(), pending_articles=db.list_pending_articles(),
    )


@app.route("/admin/san-pham")
@login_required
def admin_products():
    return render_template("admin/products.html", products=db.list_all_products_admin())


@app.route("/admin/san-pham/moi", methods=["GET", "POST"])
@login_required
def admin_product_new():
    if request.method == "POST":
        image = save_upload(request.files.get("image")) or ""
        data = {
            "name": request.form["name"].strip(),
            "category_id": int(request.form["category_id"]),
            "brand_id": request.form.get("brand_id", type=int) or None,
            "price": int(request.form.get("price") or 0),
            "sale_price": request.form.get("sale_price", type=int) or None,
            "image": image,
            "short_desc": request.form.get("short_desc", "").strip(),
            "description": request.form.get("description", "").strip(),
            "specs": parse_specs(request.form.get("specs_text", "")),
            "warranty_months": request.form.get("warranty_months", type=int) or 12,
            "in_stock": 1 if request.form.get("in_stock") else 0,
            "is_featured": 1 if request.form.get("is_featured") else 0,
        }
        db.create_product(data)
        flash("Đã thêm sản phẩm.", "success")
        return redirect(url_for("admin_products"))
    return render_template(
        "admin/product_form.html", product=None,
        categories=db.list_categories(), brands=db.list_brands(),
    )


@app.route("/admin/san-pham/<int:product_id>/sua", methods=["GET", "POST"])
@login_required
def admin_product_edit(product_id):
    product = db.get_product(product_id)
    if not product:
        abort(404)
    if request.method == "POST":
        image = save_upload(request.files.get("image"))
        data = {
            "name": request.form["name"].strip(),
            "category_id": int(request.form["category_id"]),
            "brand_id": request.form.get("brand_id", type=int) or None,
            "price": int(request.form.get("price") or 0),
            "sale_price": request.form.get("sale_price", type=int) or None,
            "short_desc": request.form.get("short_desc", "").strip(),
            "description": request.form.get("description", "").strip(),
            "specs": parse_specs(request.form.get("specs_text", "")),
            "warranty_months": request.form.get("warranty_months", type=int) or 12,
            "in_stock": 1 if request.form.get("in_stock") else 0,
            "is_featured": 1 if request.form.get("is_featured") else 0,
        }
        if image:
            data["image"] = image
        db.update_product(product_id, data)
        flash("Đã cập nhật sản phẩm.", "success")
        return redirect(url_for("admin_products"))
    return render_template(
        "admin/product_form.html", product=product,
        categories=db.list_categories(), brands=db.list_brands(),
        specs_text=specs_to_text(__import__("json").loads(product["specs"] or "[]")),
    )


@app.route("/admin/san-pham/<int:product_id>/xoa", methods=["POST"])
@login_required
def admin_product_delete(product_id):
    db.delete_product(product_id)
    flash("Đã xoá sản phẩm.", "success")
    return redirect(url_for("admin_products"))


@app.route("/admin/san-pham/gia-hang-loat", methods=["GET", "POST"])
@login_required
def admin_bulk_price():
    if request.method == "POST":
        category_id = request.form.get("category_id", type=int) or None
        brand_id = request.form.get("brand_id", type=int) or None
        try:
            delta = int(request.form.get("delta", "0").strip().replace(".", "").replace(" ", ""))
        except ValueError:
            delta = 0
        if not delta:
            flash("Vui lòng nhập số tiền thay đổi khác 0 (vd 50000 hoặc -20000).", "error")
        else:
            count = db.bulk_adjust_price(category_id, brand_id, delta)
            flash(f"Đã cập nhật giá cho {count} sản phẩm.", "success")
        return redirect(url_for("admin_bulk_price"))
    return render_template(
        "admin/bulk_price.html", categories=db.list_categories(), brands=db.list_brands(),
    )


@app.route("/admin/api/gia-hang-loat/xem-truoc")
@login_required
def admin_api_bulk_price_preview():
    category_id = request.args.get("category_id", type=int) or None
    brand_id = request.args.get("brand_id", type=int) or None
    count = db.count_products_for_filter(category_id, brand_id)
    return {"count": count}


@app.route("/admin/danh-muc", methods=["GET", "POST"])
@login_required
def admin_categories():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        icon = request.form.get("icon", "").strip()
        if name:
            db.create_category(name, icon)
            flash("Đã thêm danh mục.", "success")
        return redirect(url_for("admin_categories"))
    return render_template("admin/categories.html", categories=db.list_categories())


@app.route("/admin/danh-muc/<int:cat_id>/xoa", methods=["POST"])
@login_required
def admin_category_delete(cat_id):
    db.delete_category(cat_id)
    flash("Đã xoá danh mục.", "success")
    return redirect(url_for("admin_categories"))


@app.route("/admin/thuong-hieu", methods=["GET", "POST"])
@login_required
def admin_brands():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        logo = save_brand_logo(request.files.get("logo")) or ""
        if name:
            db.create_brand(name, logo)
            flash("Đã thêm thương hiệu.", "success")
        return redirect(url_for("admin_brands"))
    return render_template("admin/brands.html", brands=db.list_brands())


@app.route("/admin/thuong-hieu/<int:brand_id>/sua", methods=["POST"])
@login_required
def admin_brand_edit(brand_id):
    brand = db.get_brand(brand_id)
    if not brand:
        abort(404)
    name = request.form.get("name", "").strip() or brand["name"]
    logo = save_brand_logo(request.files.get("logo"))
    db.update_brand(brand_id, name, logo if logo else brand["logo"])
    flash("Đã cập nhật thương hiệu.", "success")
    return redirect(url_for("admin_brands"))


@app.route("/admin/thuong-hieu/<int:brand_id>/xoa", methods=["POST"])
@login_required
def admin_brand_delete(brand_id):
    db.delete_brand(brand_id)
    flash("Đã xoá thương hiệu.", "success")
    return redirect(url_for("admin_brands"))


@app.route("/admin/lien-he")
@login_required
def admin_leads():
    return render_template("admin/leads.html", leads=db.list_leads())


@app.route("/admin/lien-he/<int:lead_id>/trang-thai", methods=["POST"])
@login_required
def admin_lead_status(lead_id):
    db.update_lead_status(lead_id, request.form.get("status", "moi"))
    return redirect(url_for("admin_leads"))


@app.route("/admin/tin-tuc")
@login_required
def admin_articles():
    return render_template("admin/articles.html", articles=db.list_articles_admin())


def _article_form_context():
    products = db.list_all_products_admin()
    return {
        "categories": db.list_categories(),
        "products_for_ai": [
            {"id": p["id"], "name": p["name"], "category": p["category_name"]}
            for p in products
        ],
        "content_types": AI_CONTENT_TYPES,
    }


@app.route("/admin/tin-tuc/moi", methods=["GET", "POST"])
@login_required
def admin_article_new():
    if request.method == "POST":
        image = save_upload(request.files.get("image")) or ""
        data = {
            "title": request.form["title"].strip(),
            "image": image,
            "excerpt": request.form.get("excerpt", "").strip(),
            "content": request.form.get("content", "").strip(),
            "category": request.form.get("category", "Kiến thức tiêu dùng").strip(),
            "published": 1 if request.form.get("published") else 0,
            "meta_title": request.form.get("meta_title", "").strip(),
            "meta_description": request.form.get("meta_description", "").strip(),
            "keyword": request.form.get("keyword", "").strip(),
            "related_product_ids": request.form.get("related_product_ids", "").strip(),
        }
        db.create_article(data)
        if os.environ.get("VERCEL"):
            flash("Lưu ý: bản online không lưu bài viết vĩnh viễn (mất khi server khởi động lại) — nên tạo/duyệt bài ở máy local rồi deploy lại.", "error")
        flash("Đã đăng bài viết.", "success")
        return redirect(url_for("admin_articles"))
    return render_template("admin/article_form.html", article=None, **_article_form_context())


@app.route("/admin/tin-tuc/<int:article_id>/sua", methods=["GET", "POST"])
@login_required
def admin_article_edit(article_id):
    article = db.get_article(article_id)
    if not article:
        abort(404)
    if request.method == "POST":
        image = save_upload(request.files.get("image"))
        data = {
            "title": request.form["title"].strip(),
            "excerpt": request.form.get("excerpt", "").strip(),
            "content": request.form.get("content", "").strip(),
            "category": request.form.get("category", "Kiến thức tiêu dùng").strip(),
            "published": 1 if request.form.get("published") else 0,
            "meta_title": request.form.get("meta_title", "").strip(),
            "meta_description": request.form.get("meta_description", "").strip(),
            "keyword": request.form.get("keyword", "").strip(),
            "related_product_ids": request.form.get("related_product_ids", "").strip(),
        }
        if image:
            data["image"] = image
        db.update_article(article_id, data)
        if os.environ.get("VERCEL"):
            flash("Lưu ý: bản online không lưu bài viết vĩnh viễn (mất khi server khởi động lại) — nên tạo/duyệt bài ở máy local rồi deploy lại.", "error")
        flash("Đã cập nhật bài viết.", "success")
        return redirect(url_for("admin_articles"))
    return render_template("admin/article_form.html", article=article, **_article_form_context())


@app.route("/admin/api/generate-article", methods=["POST"])
@login_required
def admin_api_generate_article():
    payload = request.get_json(silent=True) or {}
    content_type = payload.get("content_type") or "huong_dan"
    keyword = (payload.get("keyword") or "").strip()
    if not keyword:
        return {"error": "Vui lòng nhập từ khóa mục tiêu trước khi tạo nháp."}, 400
    category_name = (payload.get("category_name") or "").strip()
    notes = (payload.get("notes") or "").strip()
    try:
        product_ids = [int(i) for i in (payload.get("product_ids") or [])][:4]
    except (TypeError, ValueError):
        product_ids = []

    products = db.get_products_by_ids(product_ids)
    settings = db.load_settings()
    try:
        draft = generate_article_draft(settings, content_type, keyword, category_name, products, notes)
    except ai.AIError as e:
        return {"error": str(e)}, 400
    return draft


@app.route("/admin/tin-tuc/dang-nhanh")
@login_required
def admin_publish_now_page():
    return render_template("admin/publish_now.html", **_article_form_context())


@app.route("/admin/api/dang-nhanh", methods=["POST"])
@login_required
def admin_api_publish_now():
    if os.environ.get("VERCEL"):
        return {"error": "Chức năng này chỉ chạy được ở máy local (cần git/vercel CLI)."}, 400
    payload = request.get_json(silent=True) or {}
    content_type = payload.get("content_type") or "huong_dan"
    keyword = (payload.get("keyword") or "").strip()
    if not keyword:
        return {"error": "Vui lòng nhập chủ đề trước khi đăng."}, 400
    category_name = (payload.get("category_name") or "").strip()
    notes = (payload.get("notes") or "").strip()
    try:
        product_ids = [int(i) for i in (payload.get("product_ids") or [])][:4]
    except (TypeError, ValueError):
        product_ids = []

    job_id = _new_publish_job()
    threading.Thread(target=do_publish_now,
                     args=(job_id, content_type, keyword, category_name, notes, product_ids),
                     daemon=True).start()
    return {"job_id": job_id}


@app.route("/admin/api/dang-nhanh/<job_id>")
@login_required
def admin_api_publish_now_status(job_id):
    with PUBLISH_JOBS_LOCK:
        job = PUBLISH_JOBS.get(job_id)
    if not job:
        abort(404)
    return jsonify(job)


@app.route("/admin/tin-tuc/<int:article_id>/xoa", methods=["POST"])
@login_required
def admin_article_delete(article_id):
    db.delete_article(article_id)
    flash("Đã xoá bài viết.", "success")
    return redirect(url_for("admin_articles"))


@app.route("/admin/tin-tuc/<int:article_id>/duyet", methods=["POST"])
@login_required
def admin_article_approve(article_id):
    article = db.get_article(article_id)
    if not article:
        abort(404)
    db.update_article(article_id, {
        "title": article["title"], "excerpt": article["excerpt"], "content": article["content"],
        "category": article["category"], "published": 1,
        "meta_title": article["meta_title"], "meta_description": article["meta_description"],
        "keyword": article["keyword"], "related_product_ids": article["related_product_ids"],
    })
    flash("Đã duyệt & đăng bài viết.", "success")
    return redirect(request.referrer or url_for("admin_articles"))


@app.route("/admin/hang-doi")
@login_required
def admin_queue():
    return render_template(
        "admin/queue.html", queue=db.list_queue(),
        categories=db.list_categories(), content_types=AI_CONTENT_TYPES,
        products_for_ai=[
            {"id": p["id"], "name": p["name"], "category": p["category_name"]}
            for p in db.list_all_products_admin()
        ],
    )


@app.route("/admin/hang-doi/de-xuat", methods=["POST"])
@login_required
def admin_queue_seed():
    added = db.seed_queue_from_categories()
    if added:
        flash(f"Đã đề xuất thêm {added} chủ đề mới — nhớ xem lại từ khóa trước khi để hệ thống viết bài.", "success")
    else:
        flash("Không có danh mục nào cần đề xuất thêm (mỗi danh mục đã có ít nhất 1 chủ đề trong hàng đợi).", "success")
    return redirect(url_for("admin_queue"))


@app.route("/admin/hang-doi/moi", methods=["POST"])
@login_required
def admin_queue_new():
    keyword = request.form.get("keyword", "").strip()
    if not keyword:
        flash("Vui lòng nhập từ khóa cho chủ đề.", "error")
        return redirect(url_for("admin_queue"))
    db.create_queue_item({
        "category_id": request.form.get("category_id", type=int) or None,
        "product_ids": request.form.get("product_ids", "").strip(),
        "keyword": keyword,
        "content_type": request.form.get("content_type", "huong_dan"),
        "notes": request.form.get("notes", "").strip(),
    })
    flash("Đã thêm chủ đề vào hàng đợi.", "success")
    return redirect(url_for("admin_queue"))


@app.route("/admin/hang-doi/<int:queue_id>/xoa", methods=["POST"])
@login_required
def admin_queue_delete(queue_id):
    db.delete_queue_item(queue_id)
    flash("Đã xoá chủ đề khỏi hàng đợi.", "success")
    return redirect(url_for("admin_queue"))


@app.route("/admin/cai-dat", methods=["GET", "POST"])
@login_required
def admin_settings():
    s = db.load_settings_raw()
    env_gemini = bool(os.environ.get("GEMINI_API_KEY"))
    env_claude = bool(os.environ.get("CLAUDE_API_KEY"))
    env_capi = bool(os.environ.get("FB_CAPI_TOKEN"))
    if request.method == "POST":
        s["company_name"] = request.form.get("company_name", s["company_name"]).strip()
        s["hotline"] = request.form.get("hotline", s["hotline"]).strip()
        s["address"] = request.form.get("address", s["address"]).strip()
        s["tagline"] = request.form.get("tagline", s["tagline"]).strip()
        s["facebook"] = request.form.get("facebook", "").strip()
        s["youtube"] = request.form.get("youtube", "").strip()
        s["zalo"] = request.form.get("zalo", "").strip()
        s["email"] = request.form.get("email", "").strip()
        s["fb_page_id"] = request.form.get("fb_page_id", "").strip()
        if "pixel_config_submitted" in request.form:
            s["fb_pixel_id"] = request.form.get("fb_pixel_id", "").strip()
            s["fb_capi_token"] = request.form.get("fb_capi_token", s.get("fb_capi_token", "")).strip()
        s["claude_key"] = request.form.get("claude_key", s.get("claude_key", "")).strip()
        s["claude_model"] = request.form.get("claude_model", s.get("claude_model", "")).strip() or ai.DEFAULT_CLAUDE_MODEL
        s["gemini_key"] = request.form.get("gemini_key", s.get("gemini_key", "")).strip()
        s["schedule_per_week"] = request.form.get("schedule_per_week", type=int) or s.get("schedule_per_week", 2)
        if "ai_config_submitted" in request.form:
            s["schedule_enabled"] = bool(request.form.get("schedule_enabled"))
        new_password = request.form.get("new_password", "").strip()
        if new_password:
            s["admin_password_hash"] = generate_password_hash(new_password)
        db.save_settings(s)
        flash("Đã lưu cài đặt.", "success")
        return redirect(url_for("admin_settings"))
    return render_template("admin/settings.html", s=s, env_gemini=env_gemini, env_claude=env_claude, env_capi=env_capi)


# Lịch tự động chỉ chạy khi đây là 1 tiến trình sống lâu dài (VPS, không phải Vercel
# serverless) — trên serverless mỗi request có thể là 1 cold start riêng nên không có
# chỗ để giữ 1 tiến trình nền chạy liên tục.
if not os.environ.get("VERCEL"):
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        _scheduler = BackgroundScheduler(timezone="Asia/Ho_Chi_Minh")
        _scheduler.add_job(run_scheduled_generation, "cron", hour=8, minute=0, id="seo_auto_generate")
        _scheduler.start()
    except ImportError:
        pass  # chưa cài APScheduler (pip install APScheduler) — lịch tự động chưa hoạt động


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5130, debug=False, threaded=True)
