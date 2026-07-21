# -*- coding: utf-8 -*-
"""Điện Máy Xuân Son — website bán đồ điện máy (điều hòa, máy giặt,
bình nóng lạnh, tủ lạnh). Đặt hàng qua hotline / để lại số điện thoại,
không tích hợp thanh toán online.

Chạy:  python app.py   rồi mở http://127.0.0.1:5130
"""
from __future__ import annotations

import os
import sys
import uuid
from urllib.parse import quote as urlquote

from flask import (
    Flask, Response, abort, flash, g, redirect, render_template, request,
    session, url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

import db

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads", "products")
BRAND_UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads", "brands")
try:
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    os.makedirs(BRAND_UPLOAD_DIR, exist_ok=True)
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


def save_upload(file_storage):
    if not file_storage or not file_storage.filename:
        return None
    if not allowed_file(file_storage.filename):
        return None
    ext = file_storage.filename.rsplit(".", 1)[1].lower()
    fname = f"{uuid.uuid4().hex}.{ext}"
    try:
        file_storage.save(os.path.join(UPLOAD_DIR, fname))
    except OSError:
        flash("Bản online không lưu được ảnh upload (chỉ đọc) — sửa ảnh ở máy chủ chính rồi đẩy lại lên GitHub.", "error")
        return None
    return f"uploads/products/{fname}"


def save_brand_logo(file_storage):
    if not file_storage or not file_storage.filename:
        return None
    if not allowed_file(file_storage.filename):
        return None
    ext = file_storage.filename.rsplit(".", 1)[1].lower()
    fname = f"{uuid.uuid4().hex}.{ext}"
    try:
        file_storage.save(os.path.join(BRAND_UPLOAD_DIR, fname))
    except OSError:
        flash("Bản online không lưu được ảnh upload (chỉ đọc) — sửa ảnh ở máy chủ chính rồi đẩy lại lên GitHub.", "error")
        return None
    return f"uploads/brands/{fname}"


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
    featured, _ = db.list_products(featured=True, per_page=8)
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
    fridge_slug = db.slugify("Tủ lạnh")
    tivi_slug = db.slugify("Tivi")
    washer_products, _ = db.list_products(category_slug=washer_slug, per_page=4)
    heater_products, _ = db.list_products(category_slug=heater_slug, per_page=4)

    ac_all_slugs = [db.slugify(n) for n in AC_CATEGORY_NAMES]
    brand_groups = [
        ("Thương hiệu điều hòa", db.list_brands_for_categories(ac_all_slugs), ac_slug),
        ("Thương hiệu tủ lạnh", db.list_brands_for_category(fridge_slug), fridge_slug),
        ("Thương hiệu máy giặt", db.list_brands_for_category(washer_slug), washer_slug),
        ("Thương hiệu bình nóng lạnh", db.list_brands_for_category(heater_slug), heater_slug),
        ("Thương hiệu tivi", db.list_brands_for_category(tivi_slug), tivi_slug),
    ]
    brand_groups = [g for g in brand_groups if g[1]]

    return render_template(
        "home.html", featured=featured, latest=latest, brands=brands,
        brand_groups=brand_groups,
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
    return render_template("article_detail.html", article=article, others=others)


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
    if not name or not phone:
        flash("Vui lòng nhập đầy đủ họ tên và số điện thoại.", "error")
    else:
        db.create_lead(name, phone, product_id, note)
        flash("Cảm ơn bạn! Xuân Son sẽ gọi lại trong ít phút để tư vấn.", "success")
    back = request.form.get("back") or url_for("home")
    return redirect(back)


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
    return render_template("admin/dashboard.html", counts=db.counts())


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
        }
        db.create_article(data)
        flash("Đã đăng bài viết.", "success")
        return redirect(url_for("admin_articles"))
    return render_template("admin/article_form.html", article=None)


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
        }
        if image:
            data["image"] = image
        db.update_article(article_id, data)
        flash("Đã cập nhật bài viết.", "success")
        return redirect(url_for("admin_articles"))
    return render_template("admin/article_form.html", article=article)


@app.route("/admin/tin-tuc/<int:article_id>/xoa", methods=["POST"])
@login_required
def admin_article_delete(article_id):
    db.delete_article(article_id)
    flash("Đã xoá bài viết.", "success")
    return redirect(url_for("admin_articles"))


@app.route("/admin/cai-dat", methods=["GET", "POST"])
@login_required
def admin_settings():
    s = db.load_settings()
    if request.method == "POST":
        s["company_name"] = request.form.get("company_name", s["company_name"]).strip()
        s["hotline"] = request.form.get("hotline", s["hotline"]).strip()
        s["address"] = request.form.get("address", s["address"]).strip()
        s["tagline"] = request.form.get("tagline", s["tagline"]).strip()
        s["facebook"] = request.form.get("facebook", "").strip()
        s["youtube"] = request.form.get("youtube", "").strip()
        s["zalo"] = request.form.get("zalo", "").strip()
        s["email"] = request.form.get("email", "").strip()
        new_password = request.form.get("new_password", "").strip()
        if new_password:
            s["admin_password_hash"] = generate_password_hash(new_password)
        db.save_settings(s)
        flash("Đã lưu cài đặt.", "success")
        return redirect(url_for("admin_settings"))
    return render_template("admin/settings.html", s=s)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5130, debug=False, threaded=True)
