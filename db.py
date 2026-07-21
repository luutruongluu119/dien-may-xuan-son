# -*- coding: utf-8 -*-
"""Lớp dữ liệu SQLite cho Điện Máy Xuân Son — không dùng ORM, chỉ sqlite3
chuẩn thư viện để khỏi thêm dependency ngoài, giống tinh thần các app khác
trong "AGEN MỚI" (tự chứa, không cần pip install thêm)."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
_BUNDLED_DB_PATH = os.path.join(DATA_DIR, "shop.db")

if os.environ.get("VERCEL"):
    # Vercel's serverless filesystem is read-only except /tmp. Copy the
    # bundled (pre-seeded) database into /tmp so writes don't crash — they
    # just won't persist across cold starts/deploys, which is expected here.
    import shutil
    DB_PATH = "/tmp/shop.db"
    if not os.path.exists(DB_PATH):
        shutil.copy(_BUNDLED_DB_PATH, DB_PATH)
else:
    os.makedirs(DATA_DIR, exist_ok=True)
    DB_PATH = _BUNDLED_DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    icon TEXT DEFAULT '',
    sort_order INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS brands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    logo TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    category_id INTEGER NOT NULL REFERENCES categories(id),
    brand_id INTEGER REFERENCES brands(id),
    price INTEGER NOT NULL DEFAULT 0,
    sale_price INTEGER,
    image TEXT DEFAULT '',
    short_desc TEXT DEFAULT '',
    description TEXT DEFAULT '',
    specs TEXT DEFAULT '[]',
    warranty_months INTEGER DEFAULT 12,
    in_stock INTEGER DEFAULT 1,
    is_featured INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    product_id INTEGER REFERENCES products(id),
    note TEXT DEFAULT '',
    status TEXT DEFAULT 'moi',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    image TEXT DEFAULT '',
    excerpt TEXT DEFAULT '',
    content TEXT DEFAULT '',
    category TEXT DEFAULT 'Kiến thức tiêu dùng',
    published INTEGER DEFAULT 1,
    meta_title TEXT DEFAULT '',
    meta_description TEXT DEFAULT '',
    keyword TEXT DEFAULT '',
    related_product_ids TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS content_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER REFERENCES categories(id),
    product_ids TEXT DEFAULT '',
    keyword TEXT NOT NULL,
    content_type TEXT DEFAULT 'huong_dan',
    notes TEXT DEFAULT '',
    status TEXT DEFAULT 'cho_xu_ly',
    article_id INTEGER REFERENCES articles(id),
    error TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
"""

DEFAULT_SETTINGS = {
    "company_name": "Điện Máy Xuân Son",
    "hotline": "0966.09.22.61",
    "address": "Ngách 1A/1 Phú Kiều, Kiều Mai, Bắc Từ Liêm, Hà Nội",
    "tagline": "Điện máy chính hãng — giá kho, giao lắp tận nơi",
    "facebook": "",
    "youtube": "",
    "zalo": "",
    "email": "",
    "admin_username": "admin",
    # mật khẩu mặc định: xuanson2026 — đổi ngay trong Cài đặt sau khi đăng nhập
    "admin_password_hash": "scrypt:32768:8:1$xxxxxxxx_placeholder",
    "claude_key": "",
    "claude_model": "claude-sonnet-5",
    "gemini_key": "",
    "schedule_enabled": False,
    "schedule_per_week": 2,
    "fb_page_id": "",
}

SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _migrate(conn):
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(brands)")}
    if "logo" not in cols:
        conn.execute("ALTER TABLE brands ADD COLUMN logo TEXT DEFAULT ''")

    cols = {row["name"] for row in conn.execute("PRAGMA table_info(articles)")}
    for col in ("meta_title", "meta_description", "keyword", "related_product_ids"):
        if col not in cols:
            conn.execute(f"ALTER TABLE articles ADD COLUMN {col} TEXT DEFAULT ''")


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)
    if not os.path.exists(SETTINGS_PATH):
        from werkzeug.security import generate_password_hash

        settings = dict(DEFAULT_SETTINGS)
        settings["admin_password_hash"] = generate_password_hash("xuanson2026")
        save_settings(settings)
    seed_if_empty()


SEED_CATEGORIES = [
    ("Điều hòa treo tường", "img/cat-icons/dieu-hoa-treo-tuong.jpg"),
    ("Điều hòa âm trần", "img/cat-icons/dieu-hoa-am-tran.jpg"),
    ("Điều hòa nối ống gió", "💨"),
    ("Điều hòa tủ đứng", "img/cat-icons/dieu-hoa-tu-dung.jpg"),
    ("Máy giặt", "img/cat-icons/may-giat.jpg"),
    ("Bình nóng lạnh", "img/cat-icons/binh-nong-lanh.jpg"),
    ("Tủ lạnh", "img/cat-icons/tu-lanh.jpg"),
    ("Gia dụng", "img/cat-icons/gia-dung.jpg"),
    ("Tivi", "img/cat-icons/tivi.jpg"),
]

SEED_BRANDS = [
    "Panasonic", "Daikin", "LG", "Casper", "Funiki", "Midea", "Nagakawa",
    "Mitsubishi Heavy", "Mitsubishi Electric", "Sumikura", "Gree", "Samsung",
    "Sharp", "Toshiba", "Comfee", "Electrolux", "Ariston", "Ferroli", "Sony",
    "AQUA", "Rossi", "Kangaroo", "Atlantic", "Sơn Hà", "Hòa Phát",
]

# One representative product photo per (category, brand) pair — every product of
# that brand within that category shares this image instead of a per-SKU photo.
CATEGORY_BRAND_IMAGES = {
    ("Tivi", "Casper"): "uploads/products/tivi-casper.jpg",
    ("Tivi", "Sony"): "uploads/products/tivi-sony.jpg",
    ("Điều hòa treo tường", "Casper"): "uploads/products/treotuong-casper.jpg",
    ("Điều hòa treo tường", "Comfee"): "uploads/products/treotuong-comfee.jpg",
    ("Điều hòa treo tường", "Daikin"): "uploads/products/treotuong-daikin.jpg",
    ("Điều hòa treo tường", "Funiki"): "uploads/products/treotuong-funiki.jpg",
    ("Điều hòa treo tường", "Gree"): "uploads/products/treotuong-gree.jpg",
    ("Điều hòa treo tường", "LG"): "uploads/products/treotuong-lg.jpg",
    ("Điều hòa treo tường", "Midea"): "uploads/products/treotuong-midea.jpg",
    ("Điều hòa treo tường", "Mitsubishi Electric"): "uploads/products/treotuong-mitsubishi-electric.jpg",
    ("Điều hòa treo tường", "Mitsubishi Heavy"): "uploads/products/treotuong-mitsubishi-heavy.png",
    ("Điều hòa treo tường", "Nagakawa"): "uploads/products/treotuong-nagakawa.jpg",
    ("Điều hòa treo tường", "Panasonic"): "uploads/products/treotuong-panasonic.jpg",
    ("Điều hòa treo tường", "Samsung"): "uploads/products/treotuong-samsung.png",
    ("Điều hòa treo tường", "Sharp"): "uploads/products/treotuong-sharp.jpg",
    ("Điều hòa treo tường", "Sumikura"): "uploads/products/treotuong-sumikura.jpg",
    ("Điều hòa treo tường", "Toshiba"): "uploads/products/treotuong-toshiba.jpg",
}

SEED_PRODUCTS = [
    # (category, brand, name, price, sale_price, short_desc, specs, warranty)
    # -- Điều hòa treo tường --
    ("Điều hòa treo tường", "Panasonic", "Điều hòa Panasonic N9AKH-8 9000BTU", 9040000, 7550000,
     "Dòng phổ thông giá tốt, làm lạnh nhanh, phù hợp phòng ngủ nhỏ.",
     [("Mã sản phẩm", "N9AKH-8"), ("Công suất", "9.000 BTU (2.65kW)"),
      ("Loại", "1 chiều, không Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "760W"), ("Dòng điện", "3.6A"),
      ("Kích thước dàn lạnh", "779×290×209mm"), ("Kích thước dàn nóng", "650×511×230mm"),
      ("Khối lượng dàn lạnh", "8kg"), ("Khối lượng dàn nóng", "22kg"),
      ("Bảo hành", "1 năm máy / 12 năm máy nén"), ("Xuất xứ", "Indonesia")], 12),
    ("Điều hòa treo tường", "Panasonic", "Điều hòa Panasonic N12AKH-8 12000BTU", 11070000, 9300000,
     "Công suất lớn hơn cho phòng vừa, giá tốt trong phân khúc máy thường.",
     [("Mã sản phẩm", "N12AKH-8"), ("Công suất", "12.000 BTU (3.52kW)"),
      ("Loại", "1 chiều, không Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "1.000W"), ("Dòng điện", "4.8A"),
      ("Kích thước dàn lạnh", "779×290×209mm"), ("Kích thước dàn nóng", "780×542×289mm"),
      ("Khối lượng dàn lạnh", "8kg"), ("Khối lượng dàn nóng", "27kg"),
      ("Bảo hành", "1 năm máy / 12 năm máy nén"), ("Xuất xứ", "Indonesia")], 12),
    ("Điều hòa treo tường", "Panasonic", "Điều hòa Panasonic N18AKH-8 18000BTU", 14400000, None,
     "Công suất lớn cho phòng khách rộng, làm lạnh nhanh trong phân khúc máy thường.",
     [("Mã sản phẩm", "N18AKH-8"), ("Công suất", "18.000 BTU (5.28kW)"),
      ("Loại", "1 chiều, không Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "1.600W"), ("Dòng điện", "7.4A"),
      ("Kích thước dàn lạnh", "1040×295×244mm"), ("Kích thước dàn nóng", "824×619×299mm"),
      ("Khối lượng dàn lạnh", "12kg"), ("Khối lượng dàn nóng", "36kg"),
      ("Bảo hành", "1 năm máy / 12 năm máy nén"), ("Xuất xứ", "Indonesia")], 12),
    ("Điều hòa treo tường", "Panasonic", "Điều hòa Panasonic N24AKH-8 24000BTU", 23800000, 20000000,
     "Model công suất lớn nhất dòng thường, phù hợp phòng rất rộng hoặc không gian mở.",
     [("Mã sản phẩm", "N24AKH-8"), ("Công suất", "24.000 BTU (6.6kW)"),
      ("Loại", "1 chiều, không Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "2.080W"), ("Dòng điện", "9.6A"),
      ("Kích thước dàn lạnh", "1040×295×244mm"), ("Kích thước dàn nóng", "824×619×299mm"),
      ("Bảo hành", "1 năm máy / 12 năm máy nén"), ("Xuất xứ", "Indonesia / Malaysia")], 12),
    ("Điều hòa treo tường", "Panasonic", "Điều hòa Panasonic RU9CKH-8D Inverter 9000BTU", 10830000, 9150000,
     "Inverter tiêu chuẩn, lọc khuẩn nanoe, tiết kiệm điện, bảo hành máy nén dài hạn.",
     [("Mã sản phẩm", "RU9CKH-8D"), ("Công suất", "9.000 BTU (2.65kW)"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "800W"), ("Dòng điện", "3.9A"),
      ("Kích thước dàn lạnh", "779×290×209mm"), ("Kích thước dàn nóng", "650×511×230mm"),
      ("Khối lượng dàn lạnh", "8kg"), ("Khối lượng dàn nóng", "18kg"),
      ("Bảo hành", "1 năm máy / 12 năm máy nén"), ("Xuất xứ", "Malaysia")], 12),
    ("Điều hòa treo tường", "Panasonic", "Điều hòa Panasonic RU12CKH-8D Inverter 12000BTU", 13150000, 11050000,
     "Inverter công suất vừa, tiết kiệm điện, phù hợp phòng khách nhỏ đến vừa.",
     [("Mã sản phẩm", "RU12CKH-8D"), ("Công suất", "12.000 BTU (3.50kW)"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "1.070W"), ("Dòng điện", "5.0A"),
      ("Kích thước dàn lạnh", "779×290×209mm"), ("Kích thước dàn nóng", "780×542×289mm"),
      ("Bảo hành", "1 năm máy / 12 năm máy nén"), ("Xuất xứ", "Malaysia")], 12),
    ("Điều hòa treo tường", "Panasonic", "Điều hòa Panasonic RU18CKH-8BD Inverter 18000BTU", 20710000, 17550000,
     "Inverter công suất lớn cho phòng khách rộng, làm lạnh nhanh, tiết kiệm điện.",
     [("Mã sản phẩm", "RU18CKH-8BD"), ("Công suất", "18.000 BTU (5.15kW)"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "1.550W"), ("Dòng điện", "7.1A"),
      ("Kích thước dàn lạnh", "1040×295×244mm"), ("Khối lượng dàn lạnh", "12kg"),
      ("Bảo hành", "1 năm máy / 12 năm máy nén"), ("Xuất xứ", "Malaysia")], 12),
    ("Điều hòa treo tường", "Panasonic", "Điều hòa Panasonic RU24CKH-8D Inverter 24000BTU", 28020000, 23700000,
     "Inverter công suất mạnh nhất dòng tiêu chuẩn, phù hợp không gian rộng.",
     [("Mã sản phẩm", "RU24CKH-8D"), ("Công suất", "24.000 BTU (6.10kW)"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "1.650W"), ("Dòng điện", "7.7A"),
      ("Kích thước dàn lạnh", "1040×295×244mm"), ("Kích thước dàn nóng", "824×619×299mm"),
      ("Khối lượng dàn lạnh", "12kg"), ("Khối lượng dàn nóng", "32kg"),
      ("Bảo hành", "1 năm máy / 12 năm máy nén"), ("Xuất xứ", "Malaysia")], 12),
    ("Điều hòa treo tường", "Panasonic", "Điều hòa Panasonic U9BKH-8 Inverter cao cấp 9000BTU", 12710000, 10550000,
     "Inverter cao cấp, công nghệ Nanoe-X ức chế vi khuẩn virus, vận hành êm ái.",
     [("Mã sản phẩm", "U9BKH-8"), ("Công suất", "9.000 BTU (2.55kW)"),
      ("Loại", "1 chiều, Inverter cao cấp"), ("Gas lạnh", "R32"),
      ("Công suất điện", "680W"), ("Dòng điện", "3.2A"),
      ("Kích thước dàn lạnh", "870×295×229mm"), ("Kích thước dàn nóng", "650×511×230mm"),
      ("Khối lượng dàn lạnh", "10kg"), ("Khối lượng dàn nóng", "18kg"),
      ("Bảo hành", "1 năm máy / 12 năm máy nén"), ("Xuất xứ", "Malaysia")], 12),
    ("Điều hòa treo tường", "Panasonic", "Điều hòa Panasonic U12BKH-8 Inverter cao cấp 12000BTU", 12800000, None,
     "Inverter cao cấp công suất vừa, tiết kiệm điện vượt trội, vận hành êm.",
     [("Mã sản phẩm", "U12BKH-8"), ("Công suất", "12.000 BTU (3.50kW)"),
      ("Loại", "1 chiều, Inverter cao cấp"), ("Gas lạnh", "R32"),
      ("Công suất điện", "950W"), ("Dòng điện", "4.4A"),
      ("Kích thước dàn lạnh", "870×295×229mm"), ("Kích thước dàn nóng", "780×542×289mm"),
      ("Khối lượng dàn lạnh", "10kg"), ("Khối lượng dàn nóng", "23kg"),
      ("Bảo hành", "1 năm máy / 12 năm máy nén"), ("Xuất xứ", "Malaysia")], 12),
    ("Điều hòa treo tường", "Panasonic", "Điều hòa Panasonic YZ9AKH-8 2 chiều 9000BTU", 12500000, None,
     "Sưởi ấm mùa đông, làm mát mùa hè, lọc khuẩn nanoe.",
     [("Mã sản phẩm", "YZ9AKH-8"), ("Công suất", "9.000 BTU lạnh / 10.700 BTU sưởi"),
      ("Loại", "2 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "730W"), ("Dòng điện", "3.5-3.7A"),
      ("Kích thước dàn lạnh", "870×290×214mm"), ("Khối lượng dàn lạnh", "9kg"),
      ("Bảo hành", "1 năm máy / 12 năm máy nén"), ("Xuất xứ", "Malaysia")], 12),
    ("Điều hòa treo tường", "Panasonic", "Điều hòa Panasonic YZ12AKH-8 2 chiều Inverter 12000BTU", 15710000, 13200000,
     "2 chiều Inverter công suất vừa, tích hợp WiFi điều khiển qua app Comfort Cloud.",
     [("Mã sản phẩm", "YZ12AKH-8"), ("Công suất", "12.000 BTU lạnh / 13.100 BTU sưởi"),
      ("Loại", "2 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "1.080W"), ("Dòng điện", "5.0A"),
      ("Kích thước dàn lạnh", "870×290×214mm"), ("Kích thước dàn nóng", "780×542×289mm"),
      ("Bảo hành", "1 năm máy / 12 năm máy nén"), ("Xuất xứ", "Malaysia")], 12),
    ("Điều hòa treo tường", "Panasonic", "Điều hòa Panasonic YZ18AKH-8 2 chiều Inverter 18000BTU", 24100000, 20250000,
     "2 chiều Inverter công suất lớn cho phòng khách rộng, kèm chức năng hút ẩm.",
     [("Mã sản phẩm", "YZ18AKH-8"), ("Công suất", "18.000 BTU lạnh / 18.400 BTU sưởi"),
      ("Loại", "2 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Bảo hành", "1 năm máy / 12 năm máy nén"), ("Xuất xứ", "Malaysia")], 12),
    ("Điều hòa treo tường", "Daikin", "Điều hòa Daikin FTF25XAV1V 9000BTU", 8450000, 7200000,
     "Dòng phổ thông sản xuất tại Việt Nam, làm lạnh nhanh, giá hợp lý.",
     [("Mã sản phẩm", "FTF25XAV1V"), ("Công suất", "9.000 BTU (2.72kW)"),
      ("Loại", "1 chiều, không Inverter"), ("Gas lạnh", "R32, 0.65kg"),
      ("Công suất điện", "798W"), ("Dòng điện", "3.8A"),
      ("Kích thước dàn lạnh", "283×770×242mm"), ("Kích thước dàn nóng", "418×695×244mm"),
      ("Khối lượng dàn lạnh", "9kg"), ("Khối lượng dàn nóng", "26kg"),
      ("Bảo hành", "2 năm máy / 5 năm máy nén"), ("Xuất xứ", "Việt Nam")], 24),
    ("Điều hòa treo tường", "Daikin", "Điều hòa Daikin FTF35XAV1V 12000BTU", 10650000, 8950000,
     "Công suất lớn hơn cho phòng vừa, sản xuất tại Việt Nam, giá hợp lý.",
     [("Mã sản phẩm", "FTF35XAV1V"), ("Công suất", "12.000 BTU (3.26kW)"),
      ("Loại", "1 chiều, không Inverter"), ("Gas lạnh", "R32, 0.71kg"),
      ("Công suất điện", "933W"),
      ("Kích thước dàn lạnh", "283×770×242mm"), ("Kích thước dàn nóng", "550×658×275mm"),
      ("Khối lượng dàn lạnh", "9kg"), ("Khối lượng dàn nóng", "30kg"),
      ("Bảo hành", "2 năm máy / 5 năm máy nén"), ("Xuất xứ", "Việt Nam")], 24),
    ("Điều hòa treo tường", "Daikin", "Điều hòa Daikin FTF50XV1V 18000BTU", 16600000, 13950000,
     "Công suất lớn cho phòng khách rộng, làm lạnh nhanh trong phân khúc máy thường.",
     [("Mã sản phẩm", "FTF50XV1V"), ("Công suất", "18.000 BTU (5.02kW)"),
      ("Loại", "1 chiều, không Inverter"), ("Gas lạnh", "R32, 0.73kg"),
      ("Công suất điện", "1.630W"), ("Dòng điện", "7.9A"),
      ("Kích thước dàn lạnh", "295×990×263mm"), ("Kích thước dàn nóng", "595×845×300mm"),
      ("Khối lượng dàn lạnh", "13kg"), ("Khối lượng dàn nóng", "37kg"),
      ("Bảo hành", "1 năm máy / 5 năm máy nén"), ("Xuất xứ", "Việt Nam")], 12),
    ("Điều hòa treo tường", "Daikin", "Điều hòa Daikin FTKB25ZVMV Inverter 9000BTU", 9820000, 8250000,
     "Tiết kiệm điện, làm lạnh nhanh cho phòng 15-20m², sản xuất tại Việt Nam.",
     [("Mã sản phẩm", "FTKB25ZVMV"), ("Công suất", "9.000 BTU (2.7kW)"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32, 0.41kg"),
      ("Công suất điện", "930W"), ("Dòng điện", "4.4A"),
      ("Kích thước dàn lạnh", "291×775×242mm"), ("Kích thước dàn nóng", "418×695×244mm"),
      ("Khối lượng dàn lạnh", "9kg"), ("Khối lượng dàn nóng", "19kg"),
      ("Bảo hành", "2 năm máy / 5 năm máy nén"), ("Xuất xứ", "Việt Nam (Daikin Hưng Yên)")], 24),
    ("Điều hòa treo tường", "Daikin", "Điều hòa Daikin FTKB35ZVMV Inverter 12000BTU", 12500000, 10500000,
     "Inverter công suất vừa, tiết kiệm điện, phù hợp phòng khách nhỏ đến vừa.",
     [("Mã sản phẩm", "FTKB35ZVMV"), ("Công suất", "12.000 BTU (1.5HP)"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32, 0.49kg"),
      ("Công suất điện", "1.240W"), ("Dòng điện", "5.8A"),
      ("Kích thước dàn lạnh", "291×775×242mm"), ("Kích thước dàn nóng", "550×675×284mm"),
      ("Khối lượng dàn lạnh", "9kg"), ("Khối lượng dàn nóng", "24kg"),
      ("Bảo hành", "2 năm máy / 5 năm máy nén"), ("Xuất xứ", "Việt Nam")], 24),
    ("Điều hòa treo tường", "Daikin", "Điều hòa Daikin FTKB50ZVMV Inverter 18000BTU", 19400000, 16300000,
     "Dàn lạnh mỏng, vận hành siêu êm, công suất lớn cho phòng khách rộng.",
     [("Mã sản phẩm", "FTKB50ZVMV"), ("Công suất", "18.000 BTU (5.3kW)"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32, 0.78kg"),
      ("Công suất điện", "1.850W"),
      ("Kích thước dàn lạnh", "775×291×242mm"), ("Kích thước dàn nóng", "550×675×284mm"),
      ("Khối lượng dàn lạnh", "9kg"), ("Khối lượng dàn nóng", "27kg"),
      ("Bảo hành", "2 năm máy / 5 năm máy nén"), ("Xuất xứ", "Việt Nam")], 24),
    ("Điều hòa treo tường", "Daikin", "Điều hòa Daikin FTKM25AVMV Inverter 9000BTU", 13390000, 11250000,
     "Model mới nhập khẩu Thái Lan nguyên chiếc, vận hành siêu êm chỉ 19dB.",
     [("Mã sản phẩm", "FTKM25AVMV"), ("Công suất", "9.000 BTU"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Bảo hành", "1 năm máy / 5 năm máy nén"), ("Xuất xứ", "Thái Lan")], 12),
    ("Điều hòa treo tường", "Daikin", "Điều hòa Daikin FTHF25XVMV 2 chiều Inverter 9000BTU", 12320000, 10350000,
     "2 chiều Inverter sản xuất tại Việt Nam, sưởi ấm mùa đông làm mát mùa hè.",
     [("Mã sản phẩm", "FTHF25XVMV"), ("Công suất", "9.000 BTU lạnh (2.7kW) / 9.400 BTU sưởi (2.75kW)"),
      ("Loại", "2 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "630W lạnh / 670W sưởi"), ("Dòng điện", "3.2A / 3.3A"),
      ("Kích thước dàn lạnh", "286×770×244mm"), ("Kích thước dàn nóng", "550×675×284mm"),
      ("Khối lượng dàn lạnh", "9kg"), ("Khối lượng dàn nóng", "26kg"),
      ("Bảo hành", "2 năm máy / 5 năm máy nén"), ("Xuất xứ", "Việt Nam (Daikin Hưng Yên)")], 24),
    ("Điều hòa treo tường", "Daikin", "Điều hòa Daikin FTHF35XVMV 2 chiều Inverter 12000BTU", 15350000, 12900000,
     "2 chiều Inverter công suất vừa, sưởi ấm mùa đông làm mát mùa hè hiệu quả.",
     [("Mã sản phẩm", "FTHF35XVMV"), ("Công suất", "12.000 BTU lạnh / sưởi (3.6kW)"),
      ("Loại", "2 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "1.075W"), ("Dòng điện", "5.1A"),
      ("Kích thước dàn lạnh", "286×770×244mm"), ("Kích thước dàn nóng", "550×675×284mm"),
      ("Khối lượng dàn lạnh", "9kg"), ("Khối lượng dàn nóng", "26kg"),
      ("Bảo hành", "2 năm máy / 5 năm máy nén"), ("Xuất xứ", "Việt Nam")], 24),
    ("Điều hòa treo tường", "Daikin", "Điều hòa Daikin FTHF50VAVMV 2 chiều Inverter 18000BTU", 23260000, 19550000,
     "2 chiều Inverter công suất lớn, công nghệ COANDA làm lạnh không thổi trực diện.",
     [("Mã sản phẩm", "FTHF50VAVMV"), ("Công suất", "18.000 BTU"),
      ("Loại", "2 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Bảo hành", "2 năm máy / 5 năm máy nén"), ("Xuất xứ", "Việt Nam (Daikin Hưng Yên)")], 24),
    ("Điều hòa treo tường", "LG", "Điều hòa LG IFC09M1 9000BTU", 6490000, 5500000,
     "Model bán chạy nhất của LG, giá tốt, làm lạnh nhanh cho phòng nhỏ.",
     [("Mã sản phẩm", "IFC09M1"), ("Công suất", "9.000 BTU (2.54kW)"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "1.015W"), ("Dòng điện", "4.6A"),
      ("Kích thước dàn lạnh", "698×255×190mm"), ("Kích thước dàn nóng", "722×275×459mm"),
      ("Bảo hành", "2 năm máy / 5 năm máy nén"), ("Xuất xứ", "Indonesia")], 24),
    ("Điều hòa treo tường", "LG", "Điều hòa LG IFC12M1 12000BTU", 7560000, 6400000,
     "Công suất lớn hơn cho phòng vừa, giá tốt trong dòng phổ thông.",
     [("Mã sản phẩm", "IFC12M1"), ("Công suất", "12.000 BTU (3.51kW)"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "1.303W"), ("Dòng điện", "6.3A"),
      ("Kích thước dàn lạnh", "777×250×201mm"), ("Kích thước dàn nóng", "722×276×459mm"),
      ("Khối lượng dàn lạnh", "7.5kg"), ("Khối lượng dàn nóng", "18.5kg"),
      ("Bảo hành", "2 năm máy / 5 năm máy nén"), ("Xuất xứ", "Indonesia")], 24),
    ("Điều hòa treo tường", "LG", "Điều hòa LG IFC18M1 18000BTU", 12320000, 10350000,
     "Công suất lớn cho phòng khách rộng, làm lạnh nhanh.",
     [("Mã sản phẩm", "IFC18M1"), ("Công suất", "18.000 BTU (5.42kW)"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "1.972W"), ("Dòng điện", "7.7A"),
      ("Kích thước dàn lạnh", "910×294×206mm"), ("Kích thước dàn nóng", "810×305×549mm"),
      ("Khối lượng dàn lạnh", "9kg"), ("Khối lượng dàn nóng", "23kg"),
      ("Bảo hành", "2 năm máy / 5 năm máy nén"), ("Xuất xứ", "Indonesia")], 24),
    ("Điều hòa treo tường", "LG", "Điều hòa LG IFC24M1 24000BTU", 16360000, 13750000,
     "Công suất lớn nhất dòng phổ thông, phù hợp không gian rất rộng.",
     [("Mã sản phẩm", "IFC24M1"), ("Công suất", "24.000 BTU (7.03kW)"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "2.400W"), ("Dòng điện", "10.5A"),
      ("Kích thước dàn lạnh", "1010×315×220mm"), ("Kích thước dàn nóng", "853×349×602mm"),
      ("Khối lượng dàn lạnh", "13kg"), ("Khối lượng dàn nóng", "30kg"),
      ("Bảo hành", "2 năm máy / 5 năm máy nén"), ("Xuất xứ", "Indonesia")], 24),
    ("Điều hòa treo tường", "LG", "Điều hòa LG IEC09G2 9000BTU", 7680000, 6600000,
     "Nhập khẩu Thái Lan, bảo hành máy nén dài hạn, dàn lạnh kháng khuẩn Plasma.",
     [("Mã sản phẩm", "IEC09G2"), ("Công suất", "9.000 BTU (2.70kW)"),
      ("Loại", "1 chiều, không Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "920W"), ("Dòng điện", "5.2A"),
      ("Kích thước dàn lạnh", "756×265×184mm"), ("Kích thước dàn nóng", "720×500×230mm"),
      ("Khối lượng dàn lạnh", "7.7kg"), ("Khối lượng dàn nóng", "21.7kg"),
      ("Bảo hành", "2 năm máy / 10 năm máy nén"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa treo tường", "LG", "Điều hòa LG IDH09M1 2 chiều 9000BTU", 10770000, 9050000,
     "2 chiều sưởi ấm mùa đông làm mát mùa hè, dàn lạnh kháng khuẩn Plasma.",
     [("Mã sản phẩm", "IDH09M1"), ("Công suất", "9.000 BTU lạnh (2.73kW) / 10.000 BTU sưởi (2.93kW)"),
      ("Loại", "2 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "730W lạnh / 745W sưởi"), ("Dòng điện", "4.2A"),
      ("Kích thước dàn lạnh", "799×307×235mm"), ("Kích thước dàn nóng", "717×495×230mm"),
      ("Khối lượng dàn lạnh", "10.2kg"), ("Khối lượng dàn nóng", "24.7kg"),
      ("Bảo hành", "2 năm máy / 10 năm máy nén"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa treo tường", "LG", "Điều hòa LG IDH12M1 2 chiều 12000BTU", 13100000, 11000000,
     "2 chiều công suất vừa, sưởi ấm mùa đông làm mát mùa hè hiệu quả.",
     [("Mã sản phẩm", "IDH12M1"), ("Công suất", "12.000 BTU lạnh / sưởi (3.6-3.75kW)"),
      ("Loại", "2 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "1.085W lạnh / 1.030W sưởi"), ("Dòng điện", "6.0A / 5.7A"),
      ("Kích thước dàn lạnh", "799×307×235mm"), ("Kích thước dàn nóng", "717×495×230mm"),
      ("Khối lượng dàn lạnh", "10.2kg"), ("Khối lượng dàn nóng", "24.7kg"),
      ("Bảo hành", "2 năm máy / 10 năm máy nén"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa treo tường", "LG", "Điều hòa LG IDH18M1 2 chiều 18000BTU", 20530000, 17250000,
     "2 chiều công suất lớn cho phòng khách rộng, sưởi/làm lạnh nhanh.",
     [("Mã sản phẩm", "IDH18M1"), ("Công suất", "18.000 BTU lạnh (5.30kW) / 19.000 BTU sưởi (5.57kW)"),
      ("Loại", "2 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "1.490W lạnh / 1.550W sưởi"),
      ("Kích thước dàn lạnh", "895×307×235mm"), ("Kích thước dàn nóng", "870×650×330mm"),
      ("Khối lượng dàn lạnh", "11kg"), ("Khối lượng dàn nóng", "27.5kg"),
      ("Bảo hành", "2 năm máy / 10 năm máy nén"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa treo tường", "LG", "Điều hòa LG IDC09M1 ion 9000BTU", 10650000, 8950000,
     "Dual Inverter tích hợp ionizer lọc không khí, WiFi điều khiển qua điện thoại.",
     [("Mã sản phẩm", "IDC09M1"), ("Công suất", "9.000 BTU"),
      ("Loại", "1 chiều, Dual Inverter, WiFi"), ("Gas lạnh", "R32"),
      ("Công suất điện", "810W"),
      ("Kích thước dàn lạnh", "799×307×235mm"), ("Kích thước dàn nóng", "717×495×230mm"),
      ("Bảo hành", "2 năm máy / 10 năm máy nén"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa treo tường", "LG", "Điều hòa LG IDC12M1 ion 12000BTU", 10450000, None,
     "Dual Inverter công suất lớn hơn, tích hợp ionizer, tiết kiệm điện tới 70%.",
     [("Mã sản phẩm", "IDC12M1"), ("Công suất", "12.000 BTU (3.60kW)"),
      ("Loại", "1 chiều, Dual Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "1.150W"), ("Dòng điện", "5.5A"),
      ("Kích thước dàn lạnh", "799×307×235mm"), ("Kích thước dàn nóng", "717×495×230mm"),
      ("Bảo hành", "2 năm máy / 10 năm máy nén"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa treo tường", "Casper", "Điều hòa Casper SC-09FB36M 9000BTU", 5000000, 4200000,
     "Giá tốt, phù hợp phòng ngủ nhỏ, dễ lắp đặt bảo trì.",
     [("Mã sản phẩm", "SC-09FB36M"), ("Công suất", "9.200 BTU"),
      ("Loại", "1 chiều, không Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "850W"),
      ("Kích thước dàn lạnh", "761×200×295mm"), ("Kích thước dàn nóng", "665×273×503mm"),
      ("Khối lượng dàn lạnh", "8.5kg"), ("Khối lượng dàn nóng", "23kg"),
      ("Bảo hành", "3 năm máy / 5 năm máy nén"), ("Xuất xứ", "Thái Lan")], 36),
    ("Điều hòa treo tường", "Casper", "Điều hòa Casper SC-12FB36A 12000BTU", 6070000, 5100000,
     "Công suất lớn hơn cho phòng vừa, giá tốt trong phân khúc máy thường.",
     [("Mã sản phẩm", "SC-12FB36A"), ("Công suất", "11.700 BTU"),
      ("Loại", "1 chiều, không Inverter"), ("Gas lạnh", "R32, 560g"),
      ("Công suất điện", "1.105W"), ("Dòng điện", "5.02A"),
      ("Kích thước dàn lạnh", "815×190×290mm"), ("Kích thước dàn nóng", "718×300×540mm"),
      ("Khối lượng dàn lạnh", "8kg"), ("Khối lượng dàn nóng", "27kg"),
      ("Bảo hành", "3 năm máy / 5 năm máy nén"), ("Xuất xứ", "Thái Lan")], 36),
    ("Điều hòa treo tường", "Casper", "Điều hòa Casper SC-18FB36M 18000BTU", 8750000, None,
     "Công suất lớn cho phòng khách rộng, giá tốt trong phân khúc máy thường.",
     [("Mã sản phẩm", "SC-18FB36M"), ("Công suất", "18.400 BTU"),
      ("Loại", "1 chiều, không Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "1.650W"),
      ("Kích thước dàn lạnh", "960×222×310mm"), ("Kích thước dàn nóng", "798×317×545mm"),
      ("Khối lượng dàn lạnh", "10.5kg"), ("Khối lượng dàn nóng", "35kg"),
      ("Bảo hành", "3 năm máy / 5 năm máy nén"), ("Xuất xứ", "Thái Lan")], 36),
    ("Điều hòa treo tường", "Casper", "Điều hòa Casper SC-24FB36M 24000BTU", 13920000, 11700000,
     "Công suất lớn nhất dòng thường, phù hợp không gian rất rộng.",
     [("Mã sản phẩm", "SC-24FB36M"), ("Công suất", "23.900 BTU"),
      ("Loại", "1 chiều, không Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "2.100W"),
      ("Kích thước dàn lạnh", "1089×227×328mm"), ("Kích thước dàn nóng", "824×320×655mm"),
      ("Khối lượng dàn lạnh", "12kg"), ("Khối lượng dàn nóng", "42kg"),
      ("Bảo hành", "3 năm máy / 5 năm máy nén"), ("Xuất xứ", "Thái Lan")], 36),
    ("Điều hòa treo tường", "Casper", "Điều hòa Casper JC-09IU36 Inverter 9000BTU", 5650000, 4750000,
     "Tiết kiệm điện, remote cảm ứng hiện đại, giá cạnh tranh trong phân khúc Inverter.",
     [("Mã sản phẩm", "JC-09IU36"), ("Công suất", "9.250 BTU"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32, 360g"),
      ("Công suất điện", "1.040W"), ("Dòng điện", "4.9A"),
      ("Kích thước dàn lạnh", "708×193×282mm"), ("Kích thước dàn nóng", "650×233×455mm"),
      ("Khối lượng dàn lạnh", "6.5kg"), ("Khối lượng dàn nóng", "16kg"),
      ("Bảo hành", "3 năm máy / 12 năm máy nén"), ("Xuất xứ", "Thái Lan")], 36),
    ("Điều hòa treo tường", "Casper", "Điều hòa Casper JC-12IU36 Inverter 12000BTU", 5650000, None,
     "Inverter công suất lớn hơn, phù hợp phòng 15-20m².",
     [("Mã sản phẩm", "JC-12IU36"), ("Công suất", "12.000 BTU"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32, 360g"),
      ("Công suất điện", "1.500W"), ("Dòng điện", "7A"),
      ("Kích thước dàn lạnh", "761×200×295mm"), ("Kích thước dàn nóng", "703×233×455mm"),
      ("Khối lượng dàn lạnh", "8kg"), ("Khối lượng dàn nóng", "16kg"),
      ("Bảo hành", "3 năm máy / 12 năm máy nén"), ("Xuất xứ", "Thái Lan")], 36),
    ("Điều hòa treo tường", "Casper", "Điều hòa Casper QH-09IU36A 2 chiều Inverter 9000BTU", 6250000, None,
     "2 chiều Inverter, sưởi ấm mùa đông làm mát mùa hè, phù hợp phòng nhỏ.",
     [("Mã sản phẩm", "QH-09IU36A"), ("Công suất", "10.000 BTU lạnh / 8.530 BTU sưởi"),
      ("Loại", "2 chiều, Inverter"), ("Gas lạnh", "R32, 420g"),
      ("Công suất điện", "1.100W lạnh / 800W sưởi"), ("Dòng điện", "5.2A / 3.8A"),
      ("Kích thước dàn lạnh", "768×201×299mm"), ("Kích thước dàn nóng", "650×233×455mm"),
      ("Khối lượng dàn lạnh", "7.5kg"), ("Khối lượng dàn nóng", "18kg"),
      ("Bảo hành", "3 năm máy / 12 năm máy nén"), ("Xuất xứ", "Thái Lan")], 36),
    ("Điều hòa treo tường", "Casper", "Điều hòa Casper QH-12IU36A 2 chiều Inverter 12000BTU", 8630000, 7250000,
     "2 chiều Inverter công suất vừa, sưởi ấm mùa đông làm mát mùa hè.",
     [("Mã sản phẩm", "QH-12IU36A"), ("Công suất", "12.000 BTU"),
      ("Loại", "2 chiều, Inverter"), ("Gas lạnh", "R32, 550g"),
      ("Công suất điện", "1.500W lạnh / 1.000W sưởi"), ("Dòng điện", "7A / 4.7A"),
      ("Kích thước dàn lạnh", "768×201×299mm"), ("Kích thước dàn nóng", "650×233×455mm"),
      ("Khối lượng dàn lạnh", "8kg"), ("Khối lượng dàn nóng", "18kg"),
      ("Bảo hành", "3 năm máy / 12 năm máy nén"), ("Xuất xứ", "Thái Lan")], 36),
    ("Điều hòa treo tường", "Casper", "Điều hòa Casper QH-18IU36A 2 chiều Inverter 18000BTU", 12350000, None,
     "2 chiều Inverter công suất lớn, công nghệ i-Saving tiết kiệm điện 30%.",
     [("Mã sản phẩm", "QH-18IU36A"), ("Công suất", "18.000 BTU"),
      ("Loại", "2 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Bảo hành", "3 năm máy / 12 năm máy nén"), ("Xuất xứ", "Thái Lan")], 36),
    ("Điều hòa treo tường", "Casper", "Điều hòa Casper QC-09IU36A Inverter 9000BTU", 5830000, 4900000,
     "Inverter phổ thông, giá cạnh tranh, phù hợp phòng ngủ nhỏ.",
     [("Mã sản phẩm", "QC-09IU36A"), ("Công suất", "9.500 BTU"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32, 360g"),
      ("Công suất điện", "1.030W"),
      ("Kích thước dàn lạnh", "768×200×299mm"), ("Kích thước dàn nóng", "703×233×455mm"),
      ("Khối lượng dàn lạnh", "7.5kg"), ("Khối lượng dàn nóng", "16kg"),
      ("Bảo hành", "3 năm máy / 12 năm máy nén"), ("Xuất xứ", "Thái Lan")], 36),
    # -- Điều hòa Funiki (đầy đủ dải sản phẩm 1 chiều/2 chiều, thường/Inverter) --
    ("Điều hòa treo tường", "Funiki", "Điều hòa Funiki HSC09TMU 9000BTU", 4200000, None,
     "Model phổ thông bán chạy nhất, làm lạnh nhanh cho phòng ngủ nhỏ, dễ bảo trì, phụ tùng phổ biến.",
     [("Mã sản phẩm", "HSC09TMU"), ("Công suất", "9.000 BTU (1.0HP)"),
      ("Loại", "1 chiều, không Inverter"), ("Gas lạnh", "R32, 420g"),
      ("Công suất điện", "775W"), ("Dòng điện", "3.6A"),
      ("Kích thước dàn lạnh", "715×194×285mm"), ("Kích thước dàn nóng", "720×270×495mm"),
      ("Khối lượng dàn lạnh", "7.6kg / 9.8kg"), ("Khối lượng dàn nóng", "23.7kg / 25.5kg"),
      ("Lưu lượng gió", "496/380/334 m³/h"), ("Xuất xứ", "Thái Lan / Malaysia")], 24),
    ("Điều hòa treo tường", "Funiki", "Điều hòa Funiki HSC12TMU 12000BTU", 5350000, None,
     "Công suất lớn hơn, phù hợp phòng khách vừa, vận hành ổn định.",
     [("Mã sản phẩm", "HSC12TMU"), ("Công suất", "12.000 BTU"),
      ("Loại", "1 chiều, không Inverter"), ("Gas lạnh", "R32, 430g"),
      ("Công suất điện", "1.035W"), ("Dòng điện", "4.5A"),
      ("Kích thước dàn lạnh", "805×194×285mm"), ("Kích thước dàn nóng", "765×303×555mm"),
      ("Khối lượng dàn lạnh", "8.2kg / 10.5kg"), ("Khối lượng dàn nóng", "27.3kg / 29.7kg"),
      ("Lưu lượng gió", "639/462/391 m³/h"), ("Xuất xứ", "Thái Lan / Malaysia")], 24),
    ("Điều hòa treo tường", "Funiki", "Điều hòa Funiki HSC18TMU 18000BTU", 9940000, 8350000,
     "Model công suất lớn cho phòng rộng, dàn lạnh gọn, làm mát nhanh.",
     [("Mã sản phẩm", "HSC18TMU"), ("Công suất", "18.000 BTU"),
      ("Loại", "1 chiều, không Inverter"), ("Gas lạnh", "R32, 750g"),
      ("Công suất điện", "1.640W"), ("Dòng điện", "7.6A"),
      ("Kích thước dàn lạnh", "957×213×302mm"), ("Kích thước dàn nóng", "765×303×555mm"),
      ("Khối lượng dàn lạnh", "11.0kg / 14.0kg"), ("Khối lượng dàn nóng", "33.6kg / 36kg"),
      ("Lưu lượng gió", "790/640/520 m³/h"), ("Xuất xứ", "Thái Lan / Malaysia")], 24),
    ("Điều hòa treo tường", "Funiki", "Điều hòa Funiki HSC24TMU 24000BTU", 11600000, None,
     "Công suất mạnh nhất dòng thường, phù hợp phòng lớn hoặc không gian mở.",
     [("Mã sản phẩm", "HSC24TMU"), ("Công suất", "24.000 BTU (2.5HP)"),
      ("Loại", "1 chiều, không Inverter"), ("Gas lạnh", "R32, 1.300g"),
      ("Công suất điện", "2.312W"), ("Dòng điện", "10.56A"),
      ("Kích thước dàn lạnh", "1040×220×327mm"), ("Kích thước dàn nóng", "890×342×673mm"),
      ("Khối lượng dàn lạnh", "13.6kg / 17.4kg"), ("Khối lượng dàn nóng", "51.8kg / 55kg"),
      ("Lưu lượng gió", "995/895/740 m³/h"), ("Xuất xứ", "Thái Lan / Malaysia")], 24),
    ("Điều hòa treo tường", "Funiki", "Điều hòa Funiki HIC09TMU Inverter 9000BTU", 5950000, 5000000,
     "Công nghệ Inverter tiết kiệm điện, vận hành êm, khởi động mượt.",
     [("Mã sản phẩm", "HIC09TMU"), ("Công suất", "9.000 BTU"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32, 360g"),
      ("Công suất điện", "790W"), ("Dòng điện", "3.9A"),
      ("Kích thước dàn lạnh", "715×194×285mm"), ("Kích thước dàn nóng", "668×252×469mm"),
      ("Khối lượng dàn lạnh", "7.4kg / 9.5kg"), ("Khối lượng dàn nóng", "17kg / 18.6kg"),
      ("Lưu lượng gió", "508/406/330 m³/h"), ("Xuất xứ", "Thái Lan / Malaysia")], 24),
    ("Điều hòa treo tường", "Funiki", "Điều hòa Funiki HIC12TMU Inverter 12000BTU", 7100000, 5970000,
     "Inverter tiết kiệm điện cho phòng vừa, làm lạnh ổn định quanh năm.",
     [("Mã sản phẩm", "HIC12TMU"), ("Công suất", "12.000 BTU"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32, 440g"),
      ("Công suất điện", "1.120W"), ("Dòng điện", "5.13A"),
      ("Kích thước dàn lạnh", "805×194×285mm"), ("Kích thước dàn nóng", "720×270×495mm"),
      ("Khối lượng dàn lạnh", "8.2kg / 10.4kg"), ("Khối lượng dàn nóng", "21.7kg / 23.7kg"),
      ("Lưu lượng gió", "599/442/350 m³/h"), ("Xuất xứ", "Thái Lan / Malaysia")], 24),
    ("Điều hòa treo tường", "Funiki", "Điều hòa Funiki HIC18TMU Inverter 18000BTU", 11720000, 9850000,
     "Inverter công suất lớn, tiết kiệm điện tới 30% so với máy thường.",
     [("Mã sản phẩm", "HIC18TMU"), ("Công suất", "18.000 BTU"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32, 650g"),
      ("Công suất điện", "1.687W"), ("Dòng điện", "7.37A"),
      ("Kích thước dàn lạnh", "957×213×302mm"), ("Kích thước dàn nóng", "765×303×555mm"),
      ("Khối lượng dàn lạnh", "10.85kg"), ("Khối lượng dàn nóng", "27.2kg"),
      ("Lưu lượng gió", "737/625/501 m³/h"), ("Xuất xứ", "Thái Lan / Malaysia")], 24),
    ("Điều hòa treo tường", "Funiki", "Điều hòa Funiki HIC24TMU Inverter 24000BTU", 15590000, 13100000,
     "Inverter công suất mạnh, tiết kiệm điện đáng kể cho phòng rộng.",
     [("Mã sản phẩm", "HIC24TMU"), ("Công suất", "24.000 BTU"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32, 830g"),
      ("Công suất điện", "2.101W"), ("Dòng điện", "9.2A"),
      ("Kích thước dàn lạnh", "1040×220×327mm"), ("Kích thước dàn nóng", "805×330×554mm"),
      ("Khối lượng dàn lạnh", "13.6kg"), ("Khối lượng dàn nóng", "29.6kg"),
      ("Xuất xứ", "Thái Lan / Malaysia")], 24),
    ("Điều hòa treo tường", "Funiki", "Điều hòa Funiki HSH10TMU 2 chiều 9000BTU", 5830000, 4900000,
     "2 chiều nóng lạnh, dùng được cả mùa đông lẫn mùa hè, phù hợp phòng nhỏ.",
     [("Mã sản phẩm", "HSH10TMU"), ("Công suất", "9.000 BTU"),
      ("Loại", "2 chiều, không Inverter"), ("Gas lạnh", "R32, 560g"),
      ("Công suất điện", "821W làm lạnh / 730W sưởi"), ("Dòng điện", "3.6A / 3.2A"),
      ("Kích thước dàn lạnh", "715×194×285mm"), ("Kích thước dàn nóng", "720×270×495mm"),
      ("Khối lượng dàn lạnh", "7.4kg / 10kg"), ("Khối lượng dàn nóng", "24.7kg / 26.6kg"),
      ("Xuất xứ", "Thái Lan / Malaysia")], 24),
    ("Điều hòa treo tường", "Funiki", "Điều hòa Funiki HSH12TMU 2 chiều 12000BTU", 7140000, 6000000,
     "2 chiều công suất vừa, sưởi ấm mùa đông và làm mát mùa hè hiệu quả.",
     [("Mã sản phẩm", "HSH12TMU"), ("Công suất", "12.000 BTU"),
      ("Loại", "2 chiều, không Inverter"), ("Gas lạnh", "R32, 530g"),
      ("Công suất điện", "1.096W làm lạnh / 1.104W sưởi"), ("Dòng điện", "4.9A / 5.12A"),
      ("Kích thước dàn lạnh", "805×194×285mm"), ("Kích thước dàn nóng", "720×270×495mm"),
      ("Khối lượng dàn lạnh", "8.1kg / 10.6kg"), ("Khối lượng dàn nóng", "25.6kg / 27.4kg"),
      ("Lưu lượng gió", "540/420/340 m³/h"), ("Xuất xứ", "Thái Lan / Malaysia")], 24),
    ("Điều hòa treo tường", "Funiki", "Điều hòa Funiki HSH18TMU 2 chiều 18000BTU", 10960000, 9210000,
     "2 chiều công suất lớn cho phòng rộng, sưởi/làm lạnh nhanh.",
     [("Mã sản phẩm", "HSH18TMU"), ("Công suất", "18.000 BTU"),
      ("Loại", "2 chiều, không Inverter"), ("Gas lạnh", "R32, 1.000g"),
      ("Công suất điện", "1.649W làm lạnh / 1.501W sưởi"), ("Dòng điện", "7.3A / 6.95A"),
      ("Kích thước dàn lạnh", "957×213×302mm"), ("Kích thước dàn nóng", "765×303×555mm"),
      ("Khối lượng dàn lạnh", "10.9kg / 13.8kg"), ("Khối lượng dàn nóng", "34.5kg / 37kg"),
      ("Lưu lượng gió", "772/614/535 m³/h"), ("Xuất xứ", "Thái Lan / Malaysia")], 24),
    ("Điều hòa treo tường", "Funiki", "Điều hòa Funiki HSH24TMU 2 chiều 24000BTU", 12220000, None,
     "2 chiều công suất mạnh nhất, phù hợp không gian lớn cần sưởi ấm/làm mát.",
     [("Mã sản phẩm", "HSH24TMU"), ("Công suất", "24.000 BTU"),
      ("Loại", "2 chiều, không Inverter"), ("Gas lạnh", "R32, 1.300g"),
      ("Công suất điện", "2.044W làm lạnh / 2.060W sưởi"), ("Dòng điện", "8.98A / 9A"),
      ("Kích thước dàn lạnh", "1040×220×327mm"), ("Kích thước dàn nóng", "890×342×673mm"),
      ("Khối lượng dàn lạnh", "13.7kg / 17.5kg"), ("Khối lượng dàn nóng", "47.9kg / 50.9kg"),
      ("Xuất xứ", "Thái Lan / Malaysia")], 24),
    ("Điều hòa treo tường", "Funiki", "Điều hòa Funiki HIH09TMU 2 chiều Inverter 9000BTU", 7910000, 6650000,
     "2 chiều Inverter tiết kiệm điện, làm mát và sưởi ấm êm ái.",
     [("Mã sản phẩm", "HIH09TMU"), ("Công suất", "9.000 BTU"),
      ("Loại", "2 chiều, Inverter"), ("Gas lạnh", "R32, 550g"),
      ("Công suất điện", "707W làm lạnh / 733W sưởi"), ("Dòng điện", "4.64A / 3.18A"),
      ("Kích thước dàn lạnh", "805×194×285mm"), ("Kích thước dàn nóng", "720×270×495mm"),
      ("Khối lượng dàn lạnh", "7.6kg (net)"), ("Khối lượng dàn nóng", "23.2kg (net)"),
      ("Lưu lượng gió", "466/360/325 m³/h"), ("Xuất xứ", "Thái Lan / Malaysia")], 24),
    ("Điều hòa treo tường", "Funiki", "Điều hòa Funiki HIH12TMU 2 chiều Inverter 12000BTU", 9410000, 7910000,
     "2 chiều Inverter công suất vừa, tiết kiệm điện cho cả 2 mùa.",
     [("Mã sản phẩm", "HIH12TMU"), ("Công suất", "12.000 BTU"),
      ("Loại", "2 chiều, Inverter"), ("Gas lạnh", "R32, 550g"),
      ("Công suất điện", "1.213W làm lạnh / 1.088W sưởi"), ("Dòng điện", "5.27A / 4.73A"),
      ("Kích thước dàn lạnh", "805×194×285mm"), ("Kích thước dàn nóng", "720×270×495mm"),
      ("Khối lượng dàn lạnh", "7.6kg / 9.8kg"), ("Khối lượng dàn nóng", "23.2kg / 25kg"),
      ("Lưu lượng gió", "540/430/314 m³/h"), ("Xuất xứ", "Thái Lan / Malaysia")], 24),
    ("Điều hòa treo tường", "Funiki", "Điều hòa Funiki HSIC09TMU Inverter WiFi 9000BTU", 6490000, 5490000,
     "Inverter tích hợp WiFi, điều khiển từ xa qua điện thoại, tiết kiệm điện vượt trội.",
     [("Mã sản phẩm", "HSIC09TMU"), ("Công suất", "9.000 BTU"),
      ("Loại", "1 chiều, Inverter, WiFi"), ("Gas lạnh", "R32"),
      ("Tính năng", "Điều khiển qua app điện thoại, đèn ngủ LED, khử mùi diệt khuẩn"),
      ("Xuất xứ", "Thái Lan / Malaysia")], 24),
    ("Điều hòa treo tường", "Nagakawa", "Điều hòa Nagakawa NS-C09R2T30 9000BTU", 5000000, 4200000,
     "Thương hiệu Việt giá rẻ, phù hợp phòng ngủ nhỏ, phụ tùng dễ tìm.",
     [("Mã sản phẩm", "NS-C09R2T30"), ("Công suất", "9.000 BTU (2.64kW)"),
      ("Loại", "1 chiều, không Inverter"), ("Gas lạnh", "R32, 0.31kg"),
      ("Công suất điện", "790W"), ("Dòng điện", "3.7A"),
      ("Kích thước dàn lạnh", "790×275×192mm"), ("Kích thước dàn nóng", "712×459×276mm"),
      ("Khối lượng dàn lạnh", "8kg"), ("Khối lượng dàn nóng", "21kg"),
      ("Bảo hành", "2 năm"), ("Xuất xứ", "Malaysia")], 24),
    ("Điều hòa treo tường", "Nagakawa", "Điều hòa Nagakawa NS-C12R2T30 12000BTU", 5950000, 5000000,
     "Công suất lớn hơn cho phòng vừa, giá cạnh tranh trong phân khúc máy thường.",
     [("Mã sản phẩm", "NS-C12R2T30"), ("Công suất", "12.000 BTU (3.52kW)"),
      ("Loại", "1 chiều, không Inverter"), ("Gas lạnh", "R32, 0.33kg"),
      ("Công suất điện", "1.030W"), ("Dòng điện", "4.8A"),
      ("Kích thước dàn lạnh", "790×275×192mm"), ("Kích thước dàn nóng", "777×498×290mm"),
      ("Bảo hành", "2 năm máy / 5 năm máy nén"), ("Xuất xứ", "Malaysia")], 24),
    ("Điều hòa treo tường", "Nagakawa", "Điều hòa Nagakawa NS-C18R2T30 18000BTU", 9460000, 7950000,
     "Công suất lớn cho phòng khách rộng, giá cạnh tranh trong phân khúc máy thường.",
     [("Mã sản phẩm", "NS-C18R2T30"), ("Công suất", "18.000 BTU (5.28kW)"),
      ("Loại", "1 chiều, không Inverter"), ("Gas lạnh", "R32, 0.52kg"),
      ("Công suất điện", "1.600W"), ("Dòng điện", "7A"),
      ("Kích thước dàn lạnh", "920×306×195mm"), ("Kích thước dàn nóng", "853×602×349mm"),
      ("Khối lượng dàn lạnh", "10kg"), ("Khối lượng dàn nóng", "29kg"),
      ("Bảo hành", "2 năm máy / 5 năm máy nén"), ("Xuất xứ", "Malaysia")], 24),
    ("Điều hòa treo tường", "Nagakawa", "Điều hòa Nagakawa NS-C24R2U86 24000BTU", 13390000, 11250000,
     "Công suất lớn nhất dòng thường, phù hợp không gian rất rộng.",
     [("Mã sản phẩm", "NS-C24R2U86"), ("Công suất", "24.000 BTU"),
      ("Loại", "1 chiều, không Inverter"), ("Gas lạnh", "R410A"),
      ("Công suất điện", "2.380W"), ("Dòng điện", "11A"),
      ("Kích thước dàn lạnh", "1040×327×220mm"), ("Kích thước dàn nóng", "845×702×363mm"),
      ("Khối lượng dàn lạnh", "13.5kg"), ("Khối lượng dàn nóng", "47.5kg"),
      ("Bảo hành", "2 năm máy / 10 năm máy nén"), ("Xuất xứ", "Malaysia")], 24),
    ("Điều hòa treo tường", "Nagakawa", "Điều hòa Nagakawa NIS-C09R2U51 Inverter 9000BTU", 4850000, None,
     "Tiết kiệm điện, giá cạnh tranh, dàn lạnh phủ Golden Fin chống ăn mòn.",
     [("Mã sản phẩm", "NIS-C09R2U51"), ("Công suất", "9.000 BTU (2.8kW)"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32, 360g"),
      ("Công suất điện", "1.030W"), ("Dòng điện", "4.4A"),
      ("Kích thước dàn lạnh", "768×299×201mm"), ("Kích thước dàn nóng", "650×455×233mm"),
      ("Khối lượng dàn lạnh", "7.5kg"), ("Khối lượng dàn nóng", "16kg"),
      ("Bảo hành", "2 năm máy / 10 năm máy nén"), ("Xuất xứ", "Malaysia")], 24),
    ("Điều hòa treo tường", "Nagakawa", "Điều hòa Nagakawa NIS-C12R2U51 Inverter 12000BTU", 6610000, 5550000,
     "Inverter công suất vừa, tiết kiệm điện, phù hợp phòng 15-20m².",
     [("Mã sản phẩm", "NIS-C12R2U51"), ("Công suất", "12.000 BTU (3.5kW)"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "1.200W"),
      ("Kích thước dàn lạnh", "768×299×201mm"), ("Kích thước dàn nóng", "650×455×233mm"),
      ("Bảo hành", "2 năm máy / 10 năm máy nén"), ("Xuất xứ", "Malaysia")], 24),
    ("Điều hòa treo tường", "Nagakawa", "Điều hòa Nagakawa NIS-C18R2U51 Inverter 18000BTU", 8900000, None,
     "Inverter công suất lớn cho phòng khách rộng, tiết kiệm điện.",
     [("Mã sản phẩm", "NIS-C18R2U51"), ("Công suất", "18.000 BTU (5.3kW)"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32, 580g"),
      ("Công suất điện", "1.700W"), ("Dòng điện", "7.7A"),
      ("Kích thước dàn lạnh", "997×312×222mm"), ("Kích thước dàn nóng", "709×536×280mm"),
      ("Khối lượng dàn lạnh", "11kg"), ("Khối lượng dàn nóng", "21.5kg"),
      ("Bảo hành", "2 năm máy / 10 năm máy nén"), ("Xuất xứ", "Malaysia")], 24),
    ("Điều hòa treo tường", "Nagakawa", "Điều hòa Nagakawa NIS-C24R2U51 Inverter 24000BTU", 14160000, 11900000,
     "Inverter công suất mạnh nhất dòng 1 chiều, phù hợp không gian rất rộng.",
     [("Mã sản phẩm", "NIS-C24R2U51"), ("Công suất", "22.500 BTU (6.6kW)"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "2.300W"), ("Dòng điện", "11A"),
      ("Kích thước dàn lạnh", "1140×334×229mm"), ("Kích thước dàn nóng", "825×655×310mm"),
      ("Khối lượng dàn lạnh", "13kg"), ("Khối lượng dàn nóng", "28.5kg"),
      ("Bảo hành", "2 năm máy / 10 năm máy nén"), ("Xuất xứ", "Malaysia")], 24),
    ("Điều hòa treo tường", "Nagakawa", "Điều hòa Nagakawa NIS-A09R2T29 2 chiều Inverter 9000BTU", 7260000, 6100000,
     "2 chiều Inverter sưởi ấm mùa đông làm mát mùa hè, giá cạnh tranh.",
     [("Mã sản phẩm", "NIS-A09R2T29"), ("Công suất", "9.000 BTU"),
      ("Loại", "2 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Bảo hành", "2 năm máy / 10 năm máy nén"), ("Xuất xứ", "Malaysia")], 24),
    ("Điều hòa treo tường", "Nagakawa", "Điều hòa Nagakawa NIS-A12R2T29 2 chiều Inverter 12000BTU", 8330000, 7000000,
     "2 chiều Inverter công suất vừa, sưởi ấm mùa đông làm mát mùa hè.",
     [("Mã sản phẩm", "NIS-A12R2T29"), ("Công suất", "12.000 BTU"),
      ("Loại", "2 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Bảo hành", "2 năm máy / 10 năm máy nén"), ("Xuất xứ", "Malaysia")], 24),
    # -- Thêm 7 thương hiệu điều hòa (2 model/hãng, đủ dải hãng sản xuất) --
    ("Điều hòa treo tường", "Midea", "Điều hòa Midea MSFQ-09CRN8 9000BTU", 5120000, 4300000,
     "Máy thường giá tốt, phù hợp phòng ngủ nhỏ, bảo hành máy nén dài hạn.",
     [("Mã sản phẩm", "MSFQ-09CRN8"), ("Công suất", "9.000 BTU"),
      ("Loại", "1 chiều, không Inverter"), ("Gas lạnh", "R32, 0.44kg"),
      ("Công suất điện", "820W"),
      ("Kích thước dàn lạnh", "813×201×289mm"), ("Kích thước dàn nóng", "668×252×469mm"),
      ("Khối lượng dàn lạnh", "8.5kg"), ("Khối lượng dàn nóng", "21.5kg"),
      ("Bảo hành", "3 năm máy / 5 năm máy nén"), ("Xuất xứ", "Thái Lan")], 36),
    ("Điều hòa treo tường", "Midea", "Điều hòa Midea MSFQ-12CRN8 12000BTU", 6070000, 5100000,
     "Công suất lớn hơn cho phòng vừa, giá tốt trong phân khúc máy thường.",
     [("Mã sản phẩm", "MSFQ-12CRN8"), ("Công suất", "12.000 BTU"),
      ("Loại", "1 chiều, không Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "1.050W"), ("Dòng điện", "4.92A"),
      ("Kích thước dàn lạnh", "813×201×289mm"), ("Kích thước dàn nóng", "765×303×555mm"),
      ("Bảo hành", "3 năm máy / 5 năm máy nén"), ("Xuất xứ", "Thái Lan")], 36),
    ("Điều hòa treo tường", "Midea", "Điều hòa Midea MSFQ-24CRN8 24000BTU", 10700000, None,
     "Công suất lớn nhất dòng thường, phù hợp không gian rất rộng.",
     [("Mã sản phẩm", "MSFQ-24CRN8"), ("Công suất", "24.000 BTU (2.5HP)"),
      ("Loại", "1 chiều, không Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "2.100W"), ("Dòng điện", "10.0A"),
      ("Kích thước dàn lạnh", "1055×231×330mm"), ("Kích thước dàn nóng", "890×342×673mm"),
      ("Khối lượng dàn nóng", "47kg"),
      ("Bảo hành", "3 năm máy / 5 năm máy nén"), ("Xuất xứ", "Thái Lan")], 36),
    ("Điều hòa treo tường", "Midea", "Điều hòa Midea MSCE-10CRFN8 Inverter 9000BTU", 6070000, 5100000,
     "Inverter tiết kiệm điện, thương hiệu phổ biến dễ tìm phụ tùng.",
     [("Mã sản phẩm", "MSCE-10CRFN8"), ("Công suất", "9.000 BTU"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "750W"), ("Dòng điện", "3.2A"),
      ("Kích thước dàn lạnh", "805×194×285mm"), ("Kích thước dàn nóng", "720×270×495mm"),
      ("Bảo hành", "3 năm máy / 5 năm máy nén"), ("Xuất xứ", "Thái Lan")], 36),
    ("Điều hòa treo tường", "Midea", "Điều hòa Midea MSCE-13CRFN8 Inverter 12000BTU", 6720000, 5650000,
     "Inverter công suất lớn hơn, phù hợp phòng 16-23m².",
     [("Mã sản phẩm", "MSCE-13CRFN8"), ("Công suất", "11.500 BTU"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "1.053W"), ("Dòng điện", "5A"),
      ("Kích thước dàn lạnh", "805×194×285mm"), ("Kích thước dàn nóng", "765×303×555mm"),
      ("Khối lượng dàn lạnh", "8.4kg"), ("Khối lượng dàn nóng", "27.3kg"),
      ("Bảo hành", "3 năm máy / 5 năm máy nén"), ("Xuất xứ", "Thái Lan")], 36),
    ("Điều hòa treo tường", "Midea", "Điều hòa Midea MSCE-19CRFN8 Inverter 18000BTU", 12080000, 10150000,
     "Inverter công suất lớn cho phòng khách rộng, tiết kiệm điện.",
     [("Mã sản phẩm", "MSCE-19CRFN8"), ("Công suất", "18.000 BTU"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32, 0.75kg"),
      ("Công suất điện", "1.660W"), ("Dòng điện", "7.3A"),
      ("Kích thước dàn lạnh", "957×213×302mm"), ("Kích thước dàn nóng", "765×303×555mm"),
      ("Khối lượng dàn lạnh", "11kg"), ("Khối lượng dàn nóng", "33.6kg"),
      ("Bảo hành", "3 năm máy / 5 năm máy nén"), ("Xuất xứ", "Thái Lan")], 36),
    ("Điều hòa treo tường", "Midea", "Điều hòa Midea MSAFBU-10HRDN8 2 chiều 9000BTU", 6900000, None,
     "2 chiều sưởi ấm mùa đông làm mát mùa hè, giá hợp lý.",
     [("Mã sản phẩm", "MSAFBU-10HRDN8"), ("Công suất", "9.000 BTU lạnh / 8.500 BTU sưởi"),
      ("Loại", "2 chiều, không Inverter"), ("Gas lạnh", "R410A, 0.66kg"),
      ("Công suất điện", "821W lạnh / 711W sưởi"), ("Dòng điện", "3.6A / 3.2A"),
      ("Kích thước dàn lạnh", "805×194×285mm"), ("Kích thước dàn nóng", "720×270×365mm"),
      ("Khối lượng dàn lạnh", "8.1kg"), ("Khối lượng dàn nóng", "26.9kg"),
      ("Bảo hành", "3 năm máy / 5 năm máy nén"), ("Xuất xứ", "Việt Nam")], 36),
    ("Điều hòa treo tường", "Midea", "Điều hòa Midea MSAFBU-13HRDN8 2 chiều 12000BTU", 7800000, None,
     "2 chiều công suất vừa, sưởi ấm mùa đông làm mát mùa hè.",
     [("Mã sản phẩm", "MSAFBU-13HRDN8"), ("Công suất", "11.600 BTU lạnh / 11.000 BTU sưởi"),
      ("Loại", "2 chiều, không Inverter"), ("Gas lạnh", "R410A, 1.03kg"),
      ("Công suất điện", "1.005W lạnh / 948W sưởi"),
      ("Kích thước dàn lạnh", "805×194×285mm"), ("Kích thước dàn nóng", "720×270×495mm"),
      ("Khối lượng dàn lạnh", "8.4kg"), ("Khối lượng dàn nóng", "28.8kg"),
      ("Bảo hành", "3 năm máy / 5 năm máy nén"), ("Xuất xứ", "Việt Nam")], 36),
    ("Điều hòa treo tường", "Mitsubishi Heavy", "Điều hòa Mitsubishi Heavy SRK/SRC09CTR-S5 9000BTU", 7560000, 6750000,
     "Thương hiệu Nhật Bản bền bỉ, phù hợp gia đình muốn máy chạy ổn định nhiều năm.",
     [("Mã sản phẩm", "SRK/SRC09CTR-S5"), ("Công suất", "9.000 BTU (2.268kW)"),
      ("Loại", "1 chiều, không Inverter"), ("Gas lạnh", "R410A"),
      ("Công suất điện", "868W"), ("Dòng điện", "4.0A"),
      ("Kích thước dàn lạnh", "262×679×230mm"), ("Kích thước dàn nóng", "435×695×275mm"),
      ("Khối lượng dàn lạnh", "7.5kg"), ("Khối lượng dàn nóng", "24.5kg"),
      ("Bảo hành", "2 năm máy / 5 năm máy nén"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa treo tường", "Mitsubishi Heavy", "Điều hòa Mitsubishi Heavy SRK/SRC12CT-S5 12000BTU", 9910000, 8850000,
     "Công suất lớn hơn, phù hợp phòng khách vừa, thương hiệu Nhật Bản bền bỉ.",
     [("Mã sản phẩm", "SRK/SRC12CT-S5"), ("Công suất", "12.000 BTU (1.5HP)"),
      ("Loại", "1 chiều, không Inverter"), ("Gas lạnh", "R410a"),
      ("Bảo hành", "2 năm máy / 5 năm máy nén"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa treo tường", "Mitsubishi Heavy", "Điều hòa Mitsubishi Heavy SRK/SRC18CS-S5 18000BTU", 15580000, 13910000,
     "Công suất lớn cho phòng khách rộng, thương hiệu Nhật Bản bền bỉ.",
     [("Mã sản phẩm", "SRK/SRC18CS-S5"), ("Công suất", "17.401 BTU (5.10kW)"),
      ("Loại", "1 chiều, không Inverter"), ("Gas lạnh", "R410A"),
      ("Công suất điện", "1.6kW"), ("Dòng điện", "7.4A"),
      ("Kích thước dàn lạnh", "309×890×251mm"), ("Kích thước dàn nóng", "640×850×290mm"),
      ("Khối lượng dàn lạnh", "12kg"), ("Khối lượng dàn nóng", "39kg"),
      ("Bảo hành", "2 năm máy / 5 năm máy nén"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa treo tường", "Mitsubishi Heavy", "Điều hòa Mitsubishi Heavy SRK/SRC24CS-S5 24000BTU", 20590000, 18380000,
     "Công suất lớn nhất dòng thường, phù hợp không gian rất rộng.",
     [("Mã sản phẩm", "SRK/SRC24CS-S5"), ("Công suất", "24.566 BTU (7.20kW)"),
      ("Loại", "1 chiều, không Inverter"), ("Gas lạnh", "R410A"),
      ("Công suất điện", "2.2kW"), ("Dòng điện", "10.6A"),
      ("Kích thước dàn lạnh", "339×1197×262mm"), ("Kích thước dàn nóng", "640×850×290mm"),
      ("Khối lượng dàn lạnh", "16kg"), ("Khối lượng dàn nóng", "46kg"),
      ("Bảo hành", "2 năm máy / 5 năm máy nén"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa treo tường", "Mitsubishi Heavy", "Điều hòa Mitsubishi Heavy SRK10YZP-W5 Inverter 9000BTU", 9410000, 8400000,
     "Inverter Nhật Bản tiết kiệm điện, làm lạnh nhanh, vận hành êm ái.",
     [("Mã sản phẩm", "SRK10YZP-W5"), ("Công suất", "9.000 BTU"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Bảo hành", "2 năm máy / 5 năm máy nén"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa treo tường", "Mitsubishi Heavy", "Điều hòa Mitsubishi Heavy SRK13YZP-W5 Inverter 12000BTU", 11200000, None,
     "Inverter công suất lớn hơn, phù hợp phòng khách vừa, thương hiệu Nhật Bản bền bỉ.",
     [("Mã sản phẩm", "SRK13YZP-W5"), ("Công suất", "12.000 BTU"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Bảo hành", "2 năm máy / 5 năm máy nén"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa treo tường", "Mitsubishi Heavy", "Điều hòa Mitsubishi Heavy SRK18YZP-W5 Inverter 18000BTU", 18760000, 16750000,
     "Inverter công suất lớn cho phòng khách rộng, công nghệ DC PAM Inverter tiết kiệm điện.",
     [("Mã sản phẩm", "SRK18YZP-W5"), ("Công suất", "18.000 BTU"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Bảo hành", "2 năm máy / 5 năm máy nén"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa treo tường", "Mitsubishi Heavy", "Điều hòa Mitsubishi Heavy SRK/SRC25ZSPS-W5 2 chiều Inverter 9000BTU", 11350000, 10130000,
     "2 chiều Inverter Nhật Bản, sưởi ấm mùa đông làm mát mùa hè, công nghệ Jet Flow.",
     [("Mã sản phẩm", "SRK/SRC25ZSPS-W5"), ("Công suất", "8.530 BTU lạnh (2.5kW) / 9.554 BTU sưởi (2.8kW)"),
      ("Loại", "2 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "780W lạnh / 755W sưởi"),
      ("Kích thước dàn lạnh", "267×783×210mm"), ("Kích thước dàn nóng", "540×645×275mm"),
      ("Khối lượng dàn lạnh", "7kg"), ("Khối lượng dàn nóng", "25kg"),
      ("Bảo hành", "2 năm máy / 5 năm máy nén"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa treo tường", "Mitsubishi Electric", "Điều hòa Mitsubishi Electric MS-JS25VF 9000BTU", 8270000, 6950000,
     "Dòng phổ thông của Mitsubishi Electric, làm lạnh nhanh cho phòng nhỏ.",
     [("Mã sản phẩm", "MS-JS25VF"), ("Công suất", "9.212 BTU (2.7kW)"),
      ("Loại", "1 chiều, không Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "770W"), ("Dòng điện", "3.5A"),
      ("Kích thước dàn lạnh", "799×290×232mm"), ("Kích thước dàn nóng", "718×525×255mm"),
      ("Khối lượng dàn lạnh", "9kg"), ("Khối lượng dàn nóng", "24.5kg"),
      ("Bảo hành", "2 năm máy / 5 năm máy nén"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa treo tường", "Mitsubishi Electric", "Điều hòa Mitsubishi Electric MS-JS35VF 12000BTU", 10770000, 9050000,
     "Công suất lớn hơn dòng phổ thông, phù hợp phòng khách vừa.",
     [("Mã sản phẩm", "MS-JS35VF"), ("Công suất", "12.283 BTU (3.6kW)"),
      ("Loại", "1 chiều, không Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "1.03kW"), ("Dòng điện", "4.8A"),
      ("Kích thước dàn lạnh", "799×290×232mm"), ("Kích thước dàn nóng", "718×525×255mm"),
      ("Khối lượng dàn lạnh", "9.5kg"), ("Khối lượng dàn nóng", "31.5kg"),
      ("Bảo hành", "2 năm máy / 5 năm máy nén"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa treo tường", "Mitsubishi Electric", "Điều hòa Mitsubishi Electric MS-JS50VF 18000BTU", 17200000, 14450000,
     "Công suất lớn cho phòng khách rộng, làm lạnh nhanh, luồng gió thổi xa.",
     [("Mã sản phẩm", "MS-JS50VF"), ("Công suất", "17.742 BTU (5.2kW)"),
      ("Loại", "1 chiều, không Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "1.60kW"), ("Dòng điện", "7.5A"),
      ("Kích thước dàn lạnh", "923×305×250mm"), ("Kích thước dàn nóng", "800×550×285mm"),
      ("Khối lượng dàn lạnh", "13kg"), ("Khối lượng dàn nóng", "34kg"),
      ("Bảo hành", "2 năm máy / 5 năm máy nén"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa treo tường", "Mitsubishi Electric", "Điều hòa Mitsubishi Electric MSY/MUY-JA25VF Inverter 9000BTU", 10350000, 8700000,
     "Inverter cao cấp, tiết kiệm điện vượt trội, độ bền cao theo tiêu chuẩn Nhật Bản.",
     [("Mã sản phẩm", "MSY/MUY-JA25VF"), ("Công suất", "8.871 BTU (2.6kW)"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "990W"), ("Dòng điện", "5A"),
      ("Kích thước dàn lạnh", "838×280×228mm"), ("Kích thước dàn nóng", "660×454×235mm"),
      ("Khối lượng dàn lạnh", "8kg"), ("Khối lượng dàn nóng", "18kg"),
      ("Bảo hành", "2 năm máy / 5 năm máy nén"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa treo tường", "Mitsubishi Electric", "Điều hòa Mitsubishi Electric MSY/MUY-JA35VF Inverter 12000BTU", 12850000, 10700000,
     "Inverter công suất lớn hơn, phù hợp phòng khách vừa, tiết kiệm điện vượt trội.",
     [("Mã sản phẩm", "MSY/MUY-JA35VF"), ("Công suất", "12.000 BTU (3.6kW)"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "1.33kW"), ("Dòng điện", "6.4A"),
      ("Kích thước dàn lạnh", "838×280×228mm"), ("Kích thước dàn nóng", "699×538×249mm"),
      ("Khối lượng dàn lạnh", "8.5kg"), ("Khối lượng dàn nóng", "21kg"),
      ("Bảo hành", "2 năm máy / 5 năm máy nén"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa treo tường", "Mitsubishi Electric", "Điều hòa Mitsubishi Electric MSY/MUY-JA50VF Inverter 18000BTU", 21060000, 17700000,
     "Inverter công suất lớn cho phòng khách rộng, tiết kiệm điện vượt trội.",
     [("Mã sản phẩm", "MSY/MUY-JA50VF"), ("Công suất", "18.000 BTU (5.2kW)"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "1.94kW"), ("Dòng điện", "8.9A"),
      ("Kích thước dàn lạnh", "838×280×228mm"), ("Kích thước dàn nóng", "800×550×285mm"),
      ("Khối lượng dàn lạnh", "9kg"), ("Khối lượng dàn nóng", "31.5kg"),
      ("Bảo hành", "2 năm máy / 5 năm máy nén"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa treo tường", "Mitsubishi Electric", "Điều hòa Mitsubishi Electric MSZ/MUZ-HT25VF 2 chiều Inverter 9000BTU", 12260000, 10300000,
     "2 chiều Inverter cao cấp, sưởi ấm mùa đông làm mát mùa hè, độ bền cao.",
     [("Mã sản phẩm", "MSZ/MUZ-HT25VF"), ("Công suất", "8.530 BTU lạnh (2.5kW) / 10.745 BTU sưởi (3.15kW)"),
      ("Loại", "2 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "800W lạnh / 870W sưởi"),
      ("Kích thước dàn lạnh", "799×290×232mm"), ("Kích thước dàn nóng", "699×538×249mm"),
      ("Khối lượng dàn lạnh", "9kg"), ("Khối lượng dàn nóng", "23kg"),
      ("Bảo hành", "2 năm máy / 5 năm máy nén"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa treo tường", "Mitsubishi Electric", "Điều hòa Mitsubishi Electric MSZ/MUZ-HT35VF 2 chiều Inverter 12000BTU", 12900000, None,
     "2 chiều Inverter công suất vừa, sưởi ấm mùa đông làm mát mùa hè.",
     [("Mã sản phẩm", "MSZ/MUZ-HT35VF"), ("Công suất", "11.260 BTU lạnh (3.3kW) / 12.283 BTU sưởi (3.6kW)"),
      ("Loại", "2 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "1.17kW lạnh / 995W sưởi"),
      ("Kích thước dàn lạnh", "799×290×232mm"), ("Kích thước dàn nóng", "699×538×249mm"),
      ("Khối lượng dàn lạnh", "9kg"), ("Khối lượng dàn nóng", "24kg"),
      ("Bảo hành", "2 năm máy / 5 năm máy nén"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa treo tường", "Sumikura", "Điều hòa Sumikura APS/APO-092 9000BTU", 4790000, 4130000,
     "Giá rẻ, phù hợp phòng nhỏ, linh kiện nhập khẩu Malaysia.",
     [("Mã sản phẩm", "APS/APO-092"), ("Công suất", "9.000 BTU (2.64kW)"),
      ("Loại", "1 chiều, không Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "765W"), ("Dòng điện", "3.8A"),
      ("Kích thước dàn lạnh", "805×270×197mm"), ("Kích thước dàn nóng", "660×538×250mm"),
      ("Khối lượng dàn lạnh", "8kg"), ("Khối lượng dàn nóng", "23kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Malaysia")], 24),
    ("Điều hòa treo tường", "Sumikura", "Điều hòa Sumikura APS/APO-120 12000BTU", 5970000, 5130000,
     "Công suất lớn hơn cho phòng vừa, vẫn giữ mức giá cạnh tranh.",
     [("Mã sản phẩm", "APS/APO-120"), ("Công suất", "12.000 BTU (3.52kW)"),
      ("Loại", "1 chiều, không Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "1.020W"), ("Dòng điện", "5.1A"),
      ("Kích thước dàn lạnh", "805×270×197mm"), ("Kích thước dàn nóng", "730×530×250mm"),
      ("Khối lượng dàn lạnh", "8kg"), ("Khối lượng dàn nóng", "25kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Malaysia")], 24),
    ("Điều hòa treo tường", "Sumikura", "Điều hòa Sumikura APS/APO-180 18000BTU", 8400000, None,
     "Công suất lớn cho phòng khách rộng, giá cạnh tranh trong phân khúc máy thường.",
     [("Mã sản phẩm", "APS/APO-180"), ("Công suất", "18.000 BTU"),
      ("Loại", "1 chiều, không Inverter"), ("Gas lạnh", "R32"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Malaysia")], 24),
    ("Điều hòa treo tường", "Sumikura", "Điều hòa Sumikura APS/APO-240 24000BTU", 13200000, 11100000,
     "Công suất lớn nhất dòng thường, phù hợp không gian rất rộng.",
     [("Mã sản phẩm", "APS/APO-240"), ("Công suất", "24.000 BTU (7.03kW)"),
      ("Loại", "1 chiều, không Inverter"), ("Gas lạnh", "R32, 1.1kg"),
      ("Công suất điện", "2.010W"), ("Dòng điện", "9.4A"),
      ("Kích thước dàn lạnh", "1030×319×223mm"), ("Kích thước dàn nóng", "820×635×310mm"),
      ("Khối lượng dàn lạnh", "13kg"), ("Khối lượng dàn nóng", "42kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Malaysia")], 24),
    ("Điều hòa treo tường", "Sumikura", "Điều hòa Sumikura APS/APO-092 OSAKA Inverter 9000BTU", 5580000, 4800000,
     "Inverter tiết kiệm điện, giá cạnh tranh, linh kiện nhập khẩu Malaysia.",
     [("Mã sản phẩm", "APS/APO-092 OSAKA"), ("Công suất", "9.000 BTU (2.6kW)"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32, 370g"),
      ("Công suất điện", "1.022W"), ("Dòng điện", "4.5A"),
      ("Kích thước dàn lạnh", "700×270×200mm"), ("Kích thước dàn nóng", "660×421×250mm"),
      ("Khối lượng dàn lạnh", "7kg"), ("Khối lượng dàn nóng", "18kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Malaysia")], 24),
    ("Điều hòa treo tường", "Sumikura", "Điều hòa Sumikura APS/APO-120 OSAKA Inverter 12000BTU", 6570000, 5650000,
     "Inverter công suất lớn hơn, phù hợp phòng 15-20m².",
     [("Mã sản phẩm", "APS/APO-120 OSAKA"), ("Công suất", "12.000 BTU (3.5kW)"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32, 440g"),
      ("Công suất điện", "1.558W"), ("Dòng điện", "6.8A"),
      ("Kích thước dàn lạnh", "805×270×200mm"), ("Kích thước dàn nóng", "660×530×250mm"),
      ("Khối lượng dàn lạnh", "8kg"), ("Khối lượng dàn nóng", "20kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Malaysia")], 24),
    ("Điều hòa treo tường", "Sumikura", "Điều hòa Sumikura APS/APO-H092 2 chiều 9000BTU", 4800000, None,
     "2 chiều sưởi ấm mùa đông làm mát mùa hè, phù hợp phòng nhỏ.",
     [("Mã sản phẩm", "APS/APO-H092"), ("Công suất", "9.000 BTU lạnh / 9.200 BTU sưởi"),
      ("Loại", "2 chiều, không Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "765W lạnh / 800W sưởi"),
      ("Kích thước dàn lạnh", "805×270×197mm"), ("Kích thước dàn nóng", "660×538×250mm"),
      ("Khối lượng dàn lạnh", "8kg"), ("Khối lượng dàn nóng", "24kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Malaysia")], 24),
    ("Điều hòa treo tường", "Sumikura", "Điều hòa Sumikura APS/APO-H120 2 chiều 12000BTU", 6730000, 5800000,
     "2 chiều công suất vừa, sưởi ấm mùa đông làm mát mùa hè.",
     [("Mã sản phẩm", "APS/APO-H120"), ("Công suất", "12.000 BTU lạnh (3.52kW) / 12.300 BTU sưởi (3.60kW)"),
      ("Loại", "2 chiều, không Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "1.020W lạnh / 1.050W sưởi"),
      ("Kích thước dàn lạnh", "805×270×197mm"), ("Kích thước dàn nóng", "730×530×250mm"),
      ("Khối lượng dàn lạnh", "8kg"), ("Khối lượng dàn nóng", "26kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Malaysia")], 24),
    ("Điều hòa treo tường", "Gree", "Điều hòa Gree BD9CN 9000BTU", 7620000, 6400000,
     "Làm lạnh nhanh, giá hợp lý, phù hợp phòng ngủ nhỏ.",
     [("Mã sản phẩm", "BD9CN"), ("Công suất", "9.000 BTU (2.638kW)"),
      ("Loại", "1 chiều, không Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "819W"), ("Dòng điện", "3.8A"),
      ("Kích thước dàn lạnh", "810×190×260mm"), ("Kích thước dàn nóng", "732×330×555mm"),
      ("Khối lượng dàn lạnh", "8kg"), ("Khối lượng dàn nóng", "24kg"),
      ("Bảo hành", "3 năm máy / 5 năm máy nén"), ("Xuất xứ", "Trung Quốc")], 36),
    ("Điều hòa treo tường", "Gree", "Điều hòa Gree BD12CN 12000BTU", 10000000, 8400000,
     "Công suất lớn hơn cho phòng vừa, giá tốt trong phân khúc máy thường.",
     [("Mã sản phẩm", "BD12CN"), ("Công suất", "12.000 BTU (3.517kW)"),
      ("Loại", "1 chiều, không Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "1.040W"),
      ("Kích thước dàn lạnh", "867×206×276mm"), ("Kích thước dàn nóng", "732×330×555mm"),
      ("Khối lượng dàn lạnh", "9.5kg"), ("Khối lượng dàn nóng", "28kg"),
      ("Bảo hành", "3 năm máy / 5 năm máy nén"), ("Xuất xứ", "Trung Quốc")], 36),
    ("Điều hòa treo tường", "Gree", "Điều hòa Gree BD18CN 18000BTU", 12550000, None,
     "Công suất lớn cho phòng khách rộng, đèn LED hiển thị nhiệt độ.",
     [("Mã sản phẩm", "BD18CN"), ("Công suất", "18.000 BTU"),
      ("Loại", "1 chiều, không Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "1.566W"),
      ("Kích thước dàn lạnh", "978×248×333mm"), ("Kích thước dàn nóng", "802×350×555mm"),
      ("Khối lượng dàn lạnh", "14kg"), ("Khối lượng dàn nóng", "35.5kg"),
      ("Bảo hành", "3 năm máy / 5 năm máy nén"), ("Xuất xứ", "Trung Quốc")], 36),
    ("Điều hòa treo tường", "Gree", "Điều hòa Gree BD9CI Inverter 9000BTU", 7300000, None,
     "Inverter tiết kiệm điện, bảo hành máy nén dài hạn.",
     [("Mã sản phẩm", "BD9CI"), ("Công suất", "9.000 BTU (2650W)"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "795W"), ("Dòng điện", "3.9A"),
      ("Kích thước dàn lạnh", "810×190×260mm"), ("Kích thước dàn nóng", "710×293×450mm"),
      ("Khối lượng dàn lạnh", "7.5kg"), ("Khối lượng dàn nóng", "19.5kg"),
      ("Bảo hành", "5 năm máy / 10 năm máy nén"), ("Xuất xứ", "Trung Quốc")], 60),
    ("Điều hòa treo tường", "Gree", "Điều hòa Gree BD12CI Inverter 12000BTU", 10470000, 8800000,
     "Inverter công suất lớn hơn, làm lạnh nhanh gấp 3 lần, phù hợp phòng vừa.",
     [("Mã sản phẩm", "BD12CI"), ("Công suất", "12.000 BTU (3550W)"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "1.170W"),
      ("Kích thước dàn lạnh", "810×190×260mm"), ("Kích thước dàn nóng", "732×330×555mm"),
      ("Khối lượng dàn lạnh", "8kg"), ("Khối lượng dàn nóng", "23kg"),
      ("Bảo hành", "5 năm máy / 10 năm máy nén"), ("Xuất xứ", "Trung Quốc")], 60),
    ("Điều hòa treo tường", "Gree", "Điều hòa Gree BD9HI 2 chiều Inverter 9000BTU", 10950000, 9200000,
     "2 chiều Inverter sưởi ấm mùa đông làm mát mùa hè, bảo hành máy nén dài hạn.",
     [("Mã sản phẩm", "BD9HI"), ("Công suất", "2.500W lạnh / 2.800W sưởi"),
      ("Loại", "2 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "680W lạnh / 730W sưởi"), ("Dòng điện", "3.1A / 3.2A"),
      ("Kích thước dàn lạnh", "735×190×260mm"), ("Kích thước dàn nóng", "732×330×555mm"),
      ("Khối lượng dàn lạnh", "7.5kg"), ("Khối lượng dàn nóng", "24.5kg"),
      ("Bảo hành", "5 năm máy / 10 năm máy nén"), ("Xuất xứ", "Trung Quốc")], 60),
    ("Điều hòa treo tường", "Gree", "Điều hòa Gree BD12HI 2 chiều Inverter 12000BTU", 12050000, None,
     "2 chiều Inverter công suất vừa, sưởi ấm mùa đông làm mát mùa hè.",
     [("Mã sản phẩm", "BD12HI"), ("Công suất", "3.200W lạnh / 3.400W sưởi"),
      ("Loại", "2 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "991W lạnh / 916W sưởi"),
      ("Kích thước dàn lạnh", "810×190×260mm"), ("Kích thước dàn nóng", "732×330×555mm"),
      ("Khối lượng dàn lạnh", "8.5kg"), ("Khối lượng dàn nóng", "25kg"),
      ("Bảo hành", "5 năm máy / 10 năm máy nén"), ("Xuất xứ", "Trung Quốc")], 60),
    ("Điều hòa treo tường", "Gree", "Điều hòa Gree COSMO12CI Inverter thiết kế cao cấp 12000BTU", 11500000, 9800000,
     "Thiết kế sang trọng đường cong mềm mại, Inverter tiết kiệm điện tới 60%.",
     [("Mã sản phẩm", "COSMO12CI"), ("Công suất", "12.000 BTU"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Bảo hành", "5 năm máy / 10 năm máy nén"), ("Xuất xứ", "Trung Quốc")], 60),
    ("Điều hòa treo tường", "Sharp", "Điều hòa Sharp AH-X10CEW J-tech Inverter 9000BTU", 7320000, 6150000,
     "Công nghệ J-tech Inverter tiết kiệm điện tới 60%, thương hiệu Nhật Bản quen thuộc.",
     [("Mã sản phẩm", "AH-X10CEW"), ("Công suất", "9.000 BTU"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Thái Lan / Indonesia")], 12),
    ("Điều hòa treo tường", "Sharp", "Điều hòa Sharp AH-X13CEW Inverter 12000BTU", 8510000, 7150000,
     "Inverter công suất lớn hơn, làm lạnh nhanh, tiết kiệm điện cho phòng vừa.",
     [("Mã sản phẩm", "AH-X13CEW"), ("Công suất", "12.000 BTU"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Thái Lan / Indonesia")], 12),
    ("Điều hòa treo tường", "Sharp", "Điều hòa Sharp AH-X18CEW Inverter 18000BTU", 13330000, 11200000,
     "Inverter công suất lớn cho phòng khách rộng, làm lạnh nhanh.",
     [("Mã sản phẩm", "AH-X18CEW"), ("Công suất", "18.000 BTU"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Thái Lan / Indonesia")], 12),
    ("Điều hòa treo tường", "Sharp", "Điều hòa Sharp AH-X10DEW Inverter 9000BTU", 8260000, 6550000,
     "J-tech Inverter, Plasmacluster khử khuẩn, tiết kiệm điện tới 65%.",
     [("Mã sản phẩm", "AH-X10DEW"), ("Công suất", "9.000 BTU"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Indonesia")], 12),
    ("Điều hòa treo tường", "Sharp", "Điều hòa Sharp AH-X13DEW Inverter 12000BTU", 9500000, 7550000,
     "J-tech Inverter công suất lớn hơn, Plasmacluster khử khuẩn, làm lạnh nhanh hơn 28%.",
     [("Mã sản phẩm", "AH-X13DEW"), ("Công suất", "12.000 BTU"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Indonesia")], 12),
    ("Điều hòa treo tường", "Sharp", "Điều hòa Sharp AH-XP10DSW Inverter Plasmacluster 9000BTU", 8400000, 7050000,
     "Plasmacluster Ion khử khuẩn 3 bước, J-tech Inverter tiết kiệm điện.",
     [("Mã sản phẩm", "AH-XP10DSW"), ("Công suất", "9.000 BTU"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Thái Lan")], 12),
    ("Điều hòa treo tường", "Sharp", "Điều hòa Sharp AH-XP13DSW Inverter Plasmacluster 12000BTU", 9600000, 8050000,
     "Plasmacluster Ion công suất lớn hơn, khử khuẩn diệt mùi hiệu quả.",
     [("Mã sản phẩm", "AH-XP13DSW"), ("Công suất", "12.000 BTU"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Thái Lan")], 12),
    ("Điều hòa treo tường", "Sharp", "Điều hòa Sharp AH-XP10WHW Inverter WiFi 9000BTU", 8900000, 7490000,
     "Tích hợp AIoT điều khiển từ xa qua điện thoại, J-tech Inverter tiết kiệm điện.",
     [("Mã sản phẩm", "AH-XP10WHW"), ("Công suất", "9.000 BTU"),
      ("Loại", "1 chiều, Inverter, WiFi"), ("Gas lạnh", "R32"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Thái Lan")], 12),
    ("Điều hòa treo tường", "Comfee", "Điều hòa Comfee CFS-09FGY 9000BTU", 5180000, 4300000,
     "Giá rẻ, phù hợp phòng nhỏ, thương hiệu thuộc tập đoàn Midea.",
     [("Mã sản phẩm", "CFS-09FGY"), ("Công suất", "9.000 BTU (2.64kW)"),
      ("Loại", "1 chiều, không Inverter"), ("Gas lạnh", "R32, 0.42kg"),
      ("Công suất điện", "820W"),
      ("Kích thước dàn lạnh", "813×201×289mm"), ("Kích thước dàn nóng", "668×252×469mm"),
      ("Khối lượng dàn lạnh", "8.5kg"), ("Khối lượng dàn nóng", "21.5kg"),
      ("Bảo hành", "3 năm máy / 5 năm máy nén"), ("Xuất xứ", "Thái Lan")], 36),
    ("Điều hòa treo tường", "Comfee", "Điều hòa Comfee CFS-12FGY 12000BTU", 5250000, None,
     "Công suất lớn hơn cho phòng vừa, giá rẻ, bảo hành máy nén dài hạn.",
     [("Mã sản phẩm", "CFS-12FGY"), ("Công suất", "12.000 BTU (3.52kW)"),
      ("Loại", "1 chiều, không Inverter"), ("Gas lạnh", "R32, 0.43kg"),
      ("Công suất điện", "1.050W"), ("Dòng điện", "4.9A"),
      ("Kích thước dàn lạnh", "813×201×289mm"), ("Kích thước dàn nóng", "765×303×555mm"),
      ("Khối lượng dàn lạnh", "8.5kg"), ("Khối lượng dàn nóng", "25.9kg"),
      ("Bảo hành", "3 năm máy / 5 năm máy nén"), ("Xuất xứ", "Thái Lan")], 36),
    ("Điều hòa treo tường", "Comfee", "Điều hòa Comfee CFS-10VGX Inverter 9000BTU", 5950000, 5000000,
     "Inverter đời mới, tiết kiệm điện, thiết kế hiện đại.",
     [("Mã sản phẩm", "CFS-10VGX"), ("Công suất", "9.350 BTU (2.74kW)"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32, 0.36kg"),
      ("Công suất điện", "830W"),
      ("Kích thước dàn lạnh", "723×199×286mm"), ("Kích thước dàn nóng", "668×252×469mm"),
      ("Khối lượng dàn lạnh", "7.1kg"), ("Khối lượng dàn nóng", "16.7kg"),
      ("Bảo hành", "3 năm máy / 5 năm máy nén"), ("Xuất xứ", "Thái Lan")], 36),
    ("Điều hòa treo tường", "Comfee", "Điều hòa Comfee CFS-13VGX Inverter 12000BTU", 7140000, 6000000,
     "Inverter công suất lớn hơn, tiết kiệm điện, thiết kế hiện đại.",
     [("Mã sản phẩm", "CFS-13VGX"), ("Công suất", "12.000 BTU (3.52kW)"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32, 0.42kg"),
      ("Công suất điện", "1.250W"), ("Dòng điện", "5.09A"),
      ("Kích thước dàn lạnh", "813×201×289mm"), ("Kích thước dàn nóng", "668×252×469mm"),
      ("Khối lượng dàn lạnh", "7.8kg"), ("Khối lượng dàn nóng", "17kg"),
      ("Bảo hành", "3 năm máy / 5 năm máy nén"), ("Xuất xứ", "Thái Lan")], 36),
    ("Điều hòa treo tường", "Comfee", "Điều hòa Comfee CFS-18VGX Inverter 18000BTU", 10710000, 9000000,
     "Inverter công suất lớn cho phòng khách rộng, tiết kiệm điện.",
     [("Mã sản phẩm", "CFS-18VGX"), ("Công suất", "18.000 BTU (5.28kW)"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32, 0.65kg"),
      ("Công suất điện", "1.758W"),
      ("Kích thước dàn lạnh", "975×218×308mm"), ("Kích thước dàn nóng", "765×303×555mm"),
      ("Khối lượng dàn lạnh", "10.1kg"), ("Khối lượng dàn nóng", "24.2kg"),
      ("Bảo hành", "3 năm máy / 5 năm máy nén"), ("Xuất xứ", "Thái Lan")], 36),
    ("Điều hòa treo tường", "Comfee", "Điều hòa Comfee CFS-25VGX Inverter 24000BTU", 14160000, 11900000,
     "Inverter công suất lớn nhất, phù hợp không gian rất rộng.",
     [("Mã sản phẩm", "CFS-25VGX"), ("Công suất", "24.000 BTU (7.03kW)"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32, 0.83kg"),
      ("Công suất điện", "2.512W"), ("Dòng điện", "10.92A"),
      ("Kích thước dàn lạnh", "1055×231×330mm"), ("Kích thước dàn nóng", "805×330×554mm"),
      ("Khối lượng dàn lạnh", "12.1kg"), ("Khối lượng dàn nóng", "29.9kg"),
      ("Bảo hành", "3 năm máy / 5 năm máy nén"), ("Xuất xứ", "Thái Lan")], 36),
    ("Điều hòa treo tường", "Comfee", "Điều hòa Comfee CFS-10VGP Inverter WiFi 9000BTU", 5950000, 5000000,
     "Inverter tích hợp WiFi điều khiển qua điện thoại, tiết kiệm điện.",
     [("Mã sản phẩm", "CFS-10VGP"), ("Công suất", "9.350 BTU"),
      ("Loại", "1 chiều, Inverter, WiFi"), ("Gas lạnh", "R32, 0.36kg"),
      ("Công suất điện", "830W"),
      ("Kích thước dàn lạnh", "723×199×286mm"), ("Kích thước dàn nóng", "668×252×469mm"),
      ("Khối lượng dàn lạnh", "7.2kg"), ("Khối lượng dàn nóng", "16.9kg"),
      ("Bảo hành", "3 năm máy / 5 năm máy nén"), ("Xuất xứ", "Thái Lan")], 36),
    # -- Samsung --
    ("Điều hòa treo tường", "Samsung", "Điều hòa Samsung AR40H09D0BTNSV Inverter 9000BTU", 7140000, 6000000,
     "Digital Inverter tiết kiệm điện tới 68%, làm lạnh nhanh, vận hành êm.",
     [("Mã sản phẩm", "AR40H09D0BTNSV"), ("Công suất", "9.000 BTU (1HP)"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Bảo hành", "24 tháng máy / 10 năm máy nén"), ("Xuất xứ", "Trung Quốc")], 24),
    ("Điều hòa treo tường", "Samsung", "Điều hòa Samsung AR40H12D0BTNSV Inverter 12000BTU", 8450000, 7100000,
     "Công suất lớn hơn, Digital Inverter tiết kiệm điện, phù hợp phòng vừa.",
     [("Mã sản phẩm", "AR40H12D0BTNSV"), ("Công suất", "12.000 BTU (1.5HP)"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Bảo hành", "24 tháng máy / 10 năm máy nén"), ("Xuất xứ", "Trung Quốc")], 24),
    ("Điều hòa treo tường", "Samsung", "Điều hòa Samsung AR70H18D1BWNSV Inverter 18000BTU", 14760000, 12400000,
     "Công suất lớn cho phòng khách rộng, lọc không khí 3-Care Filter.",
     [("Mã sản phẩm", "AR70H18D1BWNSV"), ("Công suất", "18.000 BTU (2HP)"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Bảo hành", "24 tháng máy / 10 năm máy nén"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa treo tường", "Samsung", "Điều hòa Samsung AR60H24D1MWNSV Inverter 24000BTU", 17970000, 15100000,
     "Công suất lớn nhất dòng 1 chiều, làm lạnh nhanh cho không gian rộng.",
     [("Mã sản phẩm", "AR60H24D1MWNSV"), ("Công suất", "24.000 BTU (2.5HP)"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Bảo hành", "24 tháng máy / 10 năm máy nén"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa treo tường", "Samsung", "Điều hòa Samsung AR40H09C1AMNSV 2 chiều Inverter 9000BTU", 8570000, 7200000,
     "2 chiều Digital Inverter, sưởi ấm mùa đông làm mát mùa hè.",
     [("Mã sản phẩm", "AR40H09C1AMNSV"), ("Công suất", "9.000 BTU (1HP)"),
      ("Loại", "2 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Bảo hành", "24 tháng máy / 10 năm máy nén"), ("Xuất xứ", "Trung Quốc")], 24),
    ("Điều hòa treo tường", "Samsung", "Điều hòa Samsung AR40H12C1AMNSV 2 chiều Inverter 12000BTU", 10770000, 9050000,
     "2 chiều công suất vừa, tiết kiệm điện, phù hợp phòng 15-20m².",
     [("Mã sản phẩm", "AR40H12C1AMNSV"), ("Công suất", "12.000 BTU (1.5HP)"),
      ("Loại", "2 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Bảo hành", "24 tháng máy / 10 năm máy nén"), ("Xuất xứ", "Trung Quốc")], 24),
    ("Điều hòa treo tường", "Samsung", "Điều hòa Samsung AR40H18C1AMNSV 2 chiều Inverter 18000BTU", 16900000, 14200000,
     "2 chiều công suất lớn, làm lạnh/sưởi nhanh, vận hành êm.",
     [("Mã sản phẩm", "AR40H18C1AMNSV"), ("Công suất", "18.000 BTU (2HP)"),
      ("Loại", "2 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Bảo hành", "24 tháng máy / 10 năm máy nén"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa treo tường", "Samsung", "Điều hòa Samsung AR24ASHZAWKNSV 2 chiều Inverter 24000BTU", 20230000, 17000000,
     "2 chiều công suất mạnh nhất, phù hợp không gian rất rộng.",
     [("Mã sản phẩm", "AR24ASHZAWKNSV"), ("Công suất", "24.000 BTU (2.5HP)"),
      ("Loại", "2 chiều, Inverter"), ("Gas lạnh", "R410a"),
      ("Bảo hành", "24 tháng máy / 10 năm máy nén"), ("Xuất xứ", "Thái Lan")], 24),
    # -- Toshiba --
    ("Điều hòa treo tường", "Toshiba", "Điều hòa Toshiba RAS-H10S5KCV2G-V Inverter 9000BTU", 9150000, 7690000,
     "Hybrid Inverter tiết kiệm điện 35%, công nghệ Plasma Ion khử khuẩn.",
     [("Mã sản phẩm", "RAS-H10S5KCV2G-V"), ("Công suất", "9.000 BTU (2.640W)"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "800W"),
      ("Kích thước dàn lạnh", "288×770×225mm"), ("Kích thước dàn nóng", "530×598×200mm"),
      ("Khối lượng dàn lạnh", "9kg"), ("Khối lượng dàn nóng", "16kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa treo tường", "Toshiba", "Điều hòa Toshiba RAS-H13S5KCV2G-V Inverter 12000BTU", 11650000, 9790000,
     "Công suất lớn hơn, Hybrid Inverter tiết kiệm điện, phù hợp phòng vừa.",
     [("Mã sản phẩm", "RAS-H13S5KCV2G-V"), ("Công suất", "12.000 BTU (3.520W)"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "1.150W"),
      ("Kích thước dàn lạnh", "288×770×225mm"), ("Kích thước dàn nóng", "530×660×240mm"),
      ("Khối lượng dàn lạnh", "9kg"), ("Khối lượng dàn nóng", "21kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa treo tường", "Toshiba", "Điều hòa Toshiba RAS-H18S5KCV2G-V Inverter 18000BTU", 18670000, 15690000,
     "Công suất lớn cho phòng khách rộng, công nghệ IAQ lọc không khí.",
     [("Mã sản phẩm", "RAS-H18S5KCV2G-V"), ("Công suất", "17.000 BTU (5.000W)"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "1.660W"),
      ("Kích thước dàn lạnh", "293×798×230mm"), ("Kích thước dàn nóng", "550×780×290mm"),
      ("Khối lượng dàn lạnh", "9kg"), ("Khối lượng dàn nóng", "32kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa treo tường", "Toshiba", "Điều hòa Toshiba RAS-H24S5KCV2G-V Inverter 24000BTU", 22000000, 18490000,
     "Công suất lớn nhất dòng 1 chiều, chế độ Power Cooling làm lạnh cực nhanh.",
     [("Mã sản phẩm", "RAS-H24S5KCV2G-V"), ("Công suất", "20.400 BTU (6.000W)"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "2.000W"),
      ("Kích thước dàn lạnh", "320×1050×250mm"), ("Kích thước dàn nóng", "550×780×290mm"),
      ("Khối lượng dàn lạnh", "13kg"), ("Khối lượng dàn nóng", "32kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa treo tường", "Toshiba", "Điều hòa Toshiba RAS-H10P2KCVG-V Hi Power Inverter 9000BTU", 7200000, 6250000,
     "Chế độ Hi Power làm lạnh cực nhanh, công nghệ Magic Coil chống bám bụi.",
     [("Mã sản phẩm", "RAS-H10P2KCVG-V"), ("Công suất", "9.000 BTU (1HP)"),
      ("Loại", "1 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa treo tường", "Toshiba", "Điều hòa Toshiba RAS-H10S3KV 2 chiều Inverter 9000BTU", 9980000, 8900000,
     "2 chiều Hybrid Inverter, sưởi ấm mùa đông làm mát mùa hè, tiết kiệm điện tới 50%.",
     [("Mã sản phẩm", "RAS-H10S3KV"), ("Công suất", "9.000 BTU (1HP)"),
      ("Loại", "2 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa treo tường", "Toshiba", "Điều hòa Toshiba RAS-H13S3KV 2 chiều Inverter 12000BTU", 12450000, 11100000,
     "2 chiều công suất vừa, công nghệ kháng khuẩn khử mùi.",
     [("Mã sản phẩm", "RAS-H13S3KV"), ("Công suất", "12.000 BTU (1.5HP)"),
      ("Loại", "2 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa treo tường", "Toshiba", "Điều hòa Toshiba RAS-H18S3KV 2 chiều Inverter 18000BTU", 19900000, 17800000,
     "2 chiều công suất lớn, tự làm sạch bộ lọc.",
     [("Mã sản phẩm", "RAS-H18S3KV"), ("Công suất", "18.000 BTU (2HP)"),
      ("Loại", "2 chiều, Inverter"), ("Gas lạnh", "R32"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Thái Lan")], 24),
    # -- Điều hòa âm trần --
    ("Điều hòa âm trần", "Daikin", "Điều hòa âm trần Daikin FCNQ18MV1 18000BTU", 24200000, None,
     "Âm trần 4 hướng thổi, làm lạnh đều khắp phòng, phù hợp văn phòng vừa.",
     [("Mã sản phẩm", "FCNQ18MV1/RNQ18MV19"), ("Công suất", "18.000 BTU (5.3kW)"),
      ("Loại", "Âm trần cassette, 4 hướng thổi"), ("Gas lạnh", "R410A"),
      ("Công suất điện", "1.89kW"),
      ("Kích thước dàn lạnh", "256×840×840mm"), ("Kích thước dàn nóng", "595×845×300mm"),
      ("Khối lượng dàn lạnh", "19.5kg"), ("Khối lượng dàn nóng", "40kg"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Thái Lan")], 12),
    ("Điều hòa âm trần", "Daikin", "Điều hòa âm trần Daikin FCNQ26MV1 24000BTU", 38210000, 31820000,
     "Công suất lớn hơn, phù hợp phòng họp, showroom diện tích lớn.",
     [("Mã sản phẩm", "FCNQ26MV1/RNQ26MV19"), ("Công suất", "26.000 BTU (7.6kW)"),
      ("Loại", "Âm trần cassette, 4 hướng thổi"), ("Gas lạnh", "R410A, 2.0kg"),
      ("Công suất điện", "2.53kW"),
      ("Kích thước dàn lạnh", "256×840×840mm"), ("Kích thước dàn nóng", "735×825×300mm"),
      ("Khối lượng dàn lạnh", "21kg"), ("Khối lượng dàn nóng", "56kg"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Thái Lan")], 12),
    ("Điều hòa âm trần", "Daikin", "Điều hòa âm trần Daikin FCNQ36MV1 36000BTU", 45400000, 37660000,
     "Công suất mạnh, bảo hành máy nén 4 năm, phù hợp không gian thương mại rộng.",
     [("Mã sản phẩm", "FCNQ36MV1/RNQ36MV1"), ("Công suất", "36.000 BTU (10.6kW)"),
      ("Loại", "Âm trần cassette, 4 hướng thổi"), ("Gas lạnh", "R410A, 3.2kg"),
      ("Công suất điện", "3.31kW"),
      ("Kích thước dàn lạnh", "298×840×840mm"), ("Kích thước dàn nóng", "1345×900×320mm"),
      ("Khối lượng dàn lạnh", "24kg"), ("Khối lượng dàn nóng", "103kg"),
      ("Bảo hành", "12 tháng máy / 4 năm máy nén"), ("Xuất xứ", "Thái Lan")], 12),
    ("Điều hòa âm trần", "Panasonic", "Điều hòa âm trần Panasonic S-19PU1H5B 18500BTU", 21110000, 18200000,
     "Nhập khẩu Malaysia, làm lạnh đều 4 hướng cho văn phòng vừa.",
     [("Mã sản phẩm", "S-19PU1H5B/U-19PN1H5"), ("Công suất", "18.500 BTU (5.42kW)"),
      ("Loại", "Âm trần cassette, 4 hướng thổi"), ("Gas lạnh", "R32"),
      ("Công suất điện", "1.52kW"),
      ("Kích thước dàn lạnh", "256×840×840mm"), ("Kích thước dàn nóng", "619×824×299mm"),
      ("Khối lượng dàn lạnh", "21kg"), ("Khối lượng dàn nóng", "36kg"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Malaysia")], 12),
    ("Điều hòa âm trần", "Panasonic", "Điều hòa âm trần Panasonic S-25PU1H5B 25000BTU", 24700000, None,
     "Công suất lớn hơn, phù hợp phòng họp, showroom cỡ vừa.",
     [("Mã sản phẩm", "S-25PU1H5B/U-25PN1H5"), ("Công suất", "25.000 BTU (7.33kW)"),
      ("Loại", "Âm trần cassette, 4 hướng thổi"), ("Gas lạnh", "R32"),
      ("Công suất điện", "2.07kW"), ("Dòng điện", "9.6A"),
      ("Kích thước dàn lạnh", "256×840×840mm"), ("Kích thước dàn nóng", "619×824×299mm"),
      ("Khối lượng dàn lạnh", "21kg"), ("Khối lượng dàn nóng", "42kg"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Malaysia")], 12),
    ("Điều hòa âm trần", "Panasonic", "Điều hòa âm trần Panasonic S-36PU1H5B 36000BTU", 31600000, None,
     "Công suất lớn, công nghệ nanoeX lọc không khí, điện 3 pha.",
     [("Mã sản phẩm", "S-36PU1H5B/U-36PN1H8"), ("Công suất", "36.000 BTU (10.55kW)"),
      ("Loại", "Âm trần cassette, 4 hướng thổi, 3 pha"), ("Gas lạnh", "R32"),
      ("Công suất điện", "2.83kW"), ("Dòng điện", "4.9A"),
      ("Kích thước dàn lạnh", "319×840×840mm"), ("Kích thước dàn nóng", "695×875×320mm"),
      ("Khối lượng dàn lạnh", "24kg"), ("Khối lượng dàn nóng", "56kg"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Malaysia")], 12),
    ("Điều hòa âm trần", "LG", "Điều hòa âm trần LG ZTNQ18GPLA1 18000BTU", 25930000, 22300000,
     "Inverter tiết kiệm điện, 4 hướng thổi đều, vận hành êm.",
     [("Mã sản phẩm", "ZTNQ18GPLA1/ZUUQ18GE1"), ("Công suất", "18.000 BTU (5.27kW)"),
      ("Loại", "Âm trần cassette, Inverter"), ("Gas lạnh", "R410A"),
      ("Công suất điện", "1.53kW"), ("Dòng điện", "6.70A"),
      ("Kích thước dàn lạnh", "840×204×840mm"), ("Kích thước dàn nóng", "770×530×459mm"),
      ("Khối lượng dàn lạnh", "19.6kg"), ("Khối lượng dàn nóng", "33kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa âm trần", "LG", "Điều hòa âm trần LG ZTNQ24GNLA1 24000BTU", 28980000, 25100000,
     "Công suất lớn hơn, Inverter tiết kiệm điện, phù hợp phòng họp.",
     [("Mã sản phẩm", "ZTNQ24GNLA1/ZUUQ24GE1"), ("Công suất", "24.000 BTU (7.03kW)"),
      ("Loại", "Âm trần cassette, Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "2.17kW"),
      ("Kích thước dàn lạnh", "840×204×840mm"), ("Kích thước dàn nóng", "870×650×330mm"),
      ("Khối lượng dàn lạnh", "19.7kg"), ("Khối lượng dàn nóng", "41.5kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa âm trần", "LG", "Điều hòa âm trần LG ZTNQ36GNLA1 36000BTU", 39910000, 34700000,
     "Công suất lớn, quạt Turbo Fan động cơ BLDC tiết kiệm điện.",
     [("Mã sản phẩm", "ZTNQ36GNLA1/ZUUQ36GE1"), ("Công suất", "36.000 BTU (10.5kW)"),
      ("Loại", "Âm trần cassette, Inverter"), ("Gas lạnh", "R410A"),
      ("Công suất điện", "3.5kW"),
      ("Kích thước dàn lạnh", "840×246×840mm"), ("Kích thước dàn nóng", "950×834×330mm"),
      ("Khối lượng dàn lạnh", "23.3kg"), ("Khối lượng dàn nóng", "56kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa âm trần", "Funiki", "Điều hòa âm trần Funiki CC18MMC1 18000BTU", 18120000, 15230000,
     "Giá tốt trong phân khúc âm trần, 4 hướng thổi, phù hợp văn phòng nhỏ.",
     [("Mã sản phẩm", "CC18MMC1"), ("Công suất", "18.000 BTU (5.275kW)"),
      ("Loại", "Âm trần cassette, 4 hướng thổi"), ("Gas lạnh", "R32, 720g"),
      ("Công suất điện", "1.600W"), ("Dòng điện", "7A"),
      ("Kích thước dàn lạnh", "830×830×205mm"), ("Kích thước dàn nóng", "805×330×554mm"),
      ("Khối lượng dàn lạnh", "22.2kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Malaysia")], 24),
    ("Điều hòa âm trần", "Funiki", "Điều hòa âm trần Funiki CC24MMC1 24000BTU", 22500000, 18900000,
     "Công suất lớn hơn, phù hợp không gian dưới 40m².",
     [("Mã sản phẩm", "CC24MMC1"), ("Công suất", "24.000 BTU (7.034kW)"),
      ("Loại", "Âm trần cassette, 4 hướng thổi"), ("Gas lạnh", "R32, 1.300g"),
      ("Công suất điện", "2.400W"), ("Dòng điện", "10.5A"),
      ("Kích thước dàn lạnh", "830×830×205mm"), ("Kích thước dàn nóng", "890×342×673mm"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Malaysia")], 24),
    ("Điều hòa âm trần", "Funiki", "Điều hòa âm trần Funiki CIC36MMC Inverter 36000BTU", 34590000, 29070000,
     "Inverter tiết kiệm điện, cảm biến Follow Me tự động điều chỉnh.",
     [("Mã sản phẩm", "CIC36MMC"), ("Công suất", "36.000 BTU (4HP)"),
      ("Loại", "Âm trần cassette, Inverter, 3 pha"), ("Gas lạnh", "R32, 1.550g"),
      ("Công suất điện", "3.800W"), ("Dòng điện", "5.6A"),
      ("Kích thước dàn lạnh", "830×830×245mm"), ("Khối lượng dàn lạnh", "26kg"),
      ("Khối lượng dàn nóng", "58kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Malaysia")], 24),
    ("Điều hòa âm trần", "Mitsubishi Heavy", "Điều hòa âm trần Mitsubishi Heavy FDT50CNZ-W5 18000BTU", 24300000, 21640000,
     "Thương hiệu Nhật Bản bền bỉ, bơm nước ngưng tích hợp, cảm biến hồng ngoại.",
     [("Mã sản phẩm", "FDT50CNZ-W5/FDC50CNZ-W5"), ("Công suất", "18.000 BTU (5kW)"),
      ("Loại", "Âm trần cassette, 4 hướng thổi"), ("Gas lạnh", "R410A"),
      ("Công suất điện", "1.55kW"), ("Dòng điện", "8.2A"),
      ("Kích thước dàn lạnh", "236×840×840mm"), ("Kích thước dàn nóng", "640×800×290mm"),
      ("Khối lượng dàn lạnh", "25kg"), ("Khối lượng dàn nóng", "42kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa âm trần", "Mitsubishi Heavy", "Điều hòa âm trần Mitsubishi Heavy FDT70CNZ-W5 24000BTU", 27970000, 24970000,
     "Công suất lớn hơn, phù hợp phòng họp, showroom vừa.",
     [("Mã sản phẩm", "FDT70CNZ-W5/FDC70CNZ-W5"), ("Công suất", "24.255 BTU (7.1kW)"),
      ("Loại", "Âm trần cassette, 4 hướng thổi"), ("Gas lạnh", "R410A"),
      ("Công suất điện", "2.29kW"), ("Dòng điện", "10.7A"),
      ("Kích thước dàn lạnh", "236×840×840mm"), ("Kích thước dàn nóng", "640×850×290mm"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa âm trần", "Mitsubishi Heavy", "Điều hòa âm trần Mitsubishi Heavy FDT100CNZ-W5 34000BTU", 39770000, 35510000,
     "Công suất lớn, phù hợp không gian thương mại rộng.",
     [("Mã sản phẩm", "FDT100CNZ-W5/FDC100CNZ-W5"), ("Công suất", "34.000 BTU (10.5kW)"),
      ("Loại", "Âm trần cassette, 4 hướng thổi"), ("Gas lạnh", "R32"),
      ("Công suất điện", "2.91kW"), ("Dòng điện", "17.3A"),
      ("Kích thước dàn lạnh", "298×840×840mm"), ("Kích thước dàn nóng", "845×970×370mm"),
      ("Khối lượng dàn lạnh", "30kg"), ("Khối lượng dàn nóng", "77.5kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa âm trần", "Midea", "Điều hòa âm trần Midea MCD1-18CRN8 18000BTU", 17490000, 14750000,
     "Giá cạnh tranh trong phân khúc âm trần, phù hợp văn phòng vừa.",
     [("Mã sản phẩm", "MCD1-18CRN8"), ("Công suất", "18.000 BTU"),
      ("Loại", "Âm trần cassette, 4 hướng thổi"), ("Gas lạnh", "R32, 0.72kg"),
      ("Công suất điện", "1.600W"), ("Dòng điện", "7A"),
      ("Kích thước dàn lạnh", "830×830×205mm"), ("Kích thước dàn nóng", "805×330×554mm"),
      ("Khối lượng dàn lạnh", "22.2kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Trung Quốc")], 24),
    ("Điều hòa âm trần", "Midea", "Điều hòa âm trần Midea MCFO-25CRN8 24000BTU", 17950000, None,
     "Công suất lớn hơn, phù hợp phòng họp, showroom cỡ vừa.",
     [("Mã sản phẩm", "MCFO-25CRN8"), ("Công suất", "24.000 BTU"),
      ("Loại", "Âm trần cassette, 4 hướng thổi"), ("Gas lạnh", "R32"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Trung Quốc")], 24),
    ("Điều hòa âm trần", "Midea", "Điều hòa âm trần Midea MCFO-36CRN8 36000BTU", 24000000, None,
     "Công suất lớn, phù hợp không gian thương mại rộng.",
     [("Mã sản phẩm", "MCFO-36CRN8"), ("Công suất", "36.000 BTU"),
      ("Loại", "Âm trần cassette, 4 hướng thổi"), ("Gas lạnh", "R32"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Trung Quốc")], 24),
    ("Điều hòa âm trần", "Casper", "Điều hòa âm trần Casper CC-18FS35 18000BTU", 18850000, 16450000,
     "Nhập khẩu Thái Lan, phù hợp văn phòng, phòng họp vừa.",
     [("Mã sản phẩm", "CC-18FS35"), ("Công suất", "18.000 BTU (5.28kW)"),
      ("Loại", "Âm trần cassette, 4 hướng thổi"), ("Gas lạnh", "R32, 0.8kg"),
      ("Công suất điện", "1.76kW"), ("Dòng điện", "14A"),
      ("Kích thước dàn lạnh", "840×840×246mm"), ("Kích thước dàn nóng", "800×315×545mm"),
      ("Khối lượng dàn lạnh", "22kg"), ("Khối lượng dàn nóng", "36kg"),
      ("Bảo hành", "2 năm máy / 3 năm máy nén"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa âm trần", "Casper", "Điều hòa âm trần Casper CC-24FS35 24000BTU", 23800000, 19990000,
     "Công suất lớn hơn, luồng gió mạnh, phù hợp không gian rộng hơn.",
     [("Mã sản phẩm", "CC-24FS35"), ("Công suất", "24.000 BTU (7.03kW)"),
      ("Loại", "Âm trần cassette, 4 hướng thổi"), ("Gas lạnh", "R32, 1.05kg"),
      ("Công suất điện", "2.34kW"), ("Dòng điện", "16A"),
      ("Kích thước dàn nóng", "825×310×655mm"), ("Khối lượng dàn nóng", "44kg"),
      ("Bảo hành", "2 năm máy / 3 năm máy nén"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa âm trần", "Casper", "Điều hòa âm trần Casper CC-36FS35 36000BTU", 31710000, 26650000,
     "Công suất lớn, máy nén đôi, phù hợp không gian dưới 60m².",
     [("Mã sản phẩm", "CC-36FS35"), ("Công suất", "36.000 BTU (10.55kW)"),
      ("Loại", "Âm trần cassette, 4 hướng thổi"), ("Gas lạnh", "R32"),
      ("Công suất điện", "3.6kW"),
      ("Kích thước dàn nóng", "970×395×805mm"), ("Khối lượng dàn nóng", "62kg"),
      ("Bảo hành", "2 năm máy / 3 năm máy nén"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa âm trần", "Nagakawa", "Điều hòa âm trần Nagakawa NT-C18R1T20 18000BTU", 17740000, 14900000,
     "Giá tốt, 4 hướng thổi làm lạnh nhanh, phù hợp văn phòng vừa.",
     [("Mã sản phẩm", "NT-C18R1T20"), ("Công suất", "18.000 BTU (5.3kW)"),
      ("Loại", "Âm trần cassette, 4 hướng thổi"), ("Gas lạnh", "R410A, 1.1kg"),
      ("Công suất điện", "1.600W"), ("Dòng điện", "7.2A"),
      ("Kích thước dàn lạnh", "840×840×245mm"), ("Kích thước dàn nóng", "760×260×540mm"),
      ("Khối lượng dàn lạnh", "22kg"), ("Khối lượng dàn nóng", "32kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Malaysia")], 24),
    ("Điều hòa âm trần", "Nagakawa", "Điều hòa âm trần Nagakawa NT-C24R1T20 24000BTU", 21000000, 17650000,
     "Công suất lớn hơn, phù hợp không gian dưới 50m².",
     [("Mã sản phẩm", "NT-C24R1T20"), ("Công suất", "24.000 BTU (8.2kW)"),
      ("Loại", "Âm trần cassette, 4 hướng thổi"), ("Gas lạnh", "R410A, 1.23kg"),
      ("Công suất điện", "2.392W"), ("Dòng điện", "10.4A"),
      ("Kích thước dàn lạnh", "840×840×245mm"), ("Kích thước dàn nóng", "845×330×700mm"),
      ("Khối lượng dàn lạnh", "25kg"), ("Khối lượng dàn nóng", "43kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Malaysia")], 24),
    ("Điều hòa âm trần", "Nagakawa", "Điều hòa âm trần Nagakawa NT-C36R1T20 36000BTU", 30950000, 26000000,
     "Công suất lớn, điện 3 pha, phù hợp không gian thương mại rộng.",
     [("Mã sản phẩm", "NT-C36R1T20"), ("Công suất", "36.000 BTU (10.6kW)"),
      ("Loại", "Âm trần cassette, 3 pha"), ("Gas lạnh", "R410A, 1.6kg"),
      ("Công suất điện", "3.600W"), ("Dòng điện", "7A"),
      ("Kích thước dàn lạnh", "840×840×245mm"), ("Kích thước dàn nóng", "910×360×805mm"),
      ("Khối lượng dàn lạnh", "26kg"), ("Khối lượng dàn nóng", "57kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Malaysia")], 24),
    ("Điều hòa âm trần", "Sumikura", "Điều hòa âm trần Sumikura APC/APO-180 18000BTU", 17520000, 15100000,
     "Giá tốt, nhập khẩu Malaysia, phù hợp văn phòng vừa.",
     [("Mã sản phẩm", "APC/APO-180"), ("Công suất", "18.000 BTU (2HP)"),
      ("Loại", "Âm trần cassette, 4 hướng thổi"), ("Gas lạnh", "R410"),
      ("Công suất điện", "1.860W"),
      ("Kích thước dàn lạnh", "840×240×840mm"), ("Kích thước dàn nóng", "775×590×270mm"),
      ("Khối lượng dàn lạnh", "34kg"), ("Khối lượng dàn nóng", "37kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Malaysia")], 24),
    ("Điều hòa âm trần", "Sumikura", "Điều hòa âm trần Sumikura APC/APO-240 24000BTU", 21900000, 19550000,
     "Công suất lớn hơn, 4 hướng thổi, phù hợp phòng họp.",
     [("Mã sản phẩm", "APC/APO-240"), ("Công suất", "24.000 BTU (2.5HP)"),
      ("Loại", "Âm trần cassette, 4 hướng thổi"), ("Gas lạnh", "R32"),
      ("Công suất điện", "2.600W"),
      ("Kích thước dàn lạnh", "840×240×840mm"), ("Kích thước dàn nóng", "860×700×320mm"),
      ("Khối lượng dàn lạnh", "38kg"), ("Khối lượng dàn nóng", "52kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Malaysia")], 24),
    ("Điều hòa âm trần", "Sumikura", "Điều hòa âm trần Sumikura APC/APO-360 36000BTU", 26050000, None,
     "Công suất lớn, phù hợp không gian thương mại rộng.",
     [("Mã sản phẩm", "APC/APO-360"), ("Công suất", "36.000 BTU (4HP)"),
      ("Loại", "Âm trần cassette"), ("Gas lạnh", "R410"),
      ("Công suất điện", "3.650W"), ("Dòng điện", "18.1A"),
      ("Kích thước dàn lạnh", "840×320×840mm"), ("Kích thước dàn nóng", "860×700×320mm"),
      ("Khối lượng dàn lạnh", "38kg"), ("Khối lượng dàn nóng", "56kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Malaysia")], 24),
    ("Điều hòa âm trần", "Samsung", "Điều hòa âm trần Samsung AC052TN1DKC 18000BTU", 26510000, 23460000,
     "Công nghệ WindFree phân tán khí lạnh nhẹ nhàng qua 10.000 lỗ nhỏ.",
     [("Mã sản phẩm", "AC052TN1DKC/EA"), ("Công suất", "17.100 BTU (5.0kW)"),
      ("Loại", "Âm trần cassette 1 hướng, WindFree"), ("Gas lạnh", "R410A"),
      ("Công suất điện", "1.47kW"), ("Dòng điện", "7.10A"),
      ("Kích thước dàn lạnh", "1200×138×450mm"), ("Kích thước dàn nóng", "880×638×310mm"),
      ("Khối lượng dàn lạnh", "13.4kg"), ("Khối lượng dàn nóng", "40.5kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Hàn Quốc")], 24),
    ("Điều hòa âm trần", "Samsung", "Điều hòa âm trần Samsung AC071TN1DKC 24000BTU", 30750000, 27210000,
     "Công suất lớn hơn, Digital Inverter tiết kiệm điện tới 55%.",
     [("Mã sản phẩm", "AC071TN1DKC/EA"), ("Công suất", "24.000 BTU (2.5HP)"),
      ("Loại", "Âm trần cassette 1 hướng, WindFree"), ("Gas lạnh", "R410A"),
      ("Công suất điện", "1.97kW"),
      ("Kích thước dàn lạnh", "1200×138×450mm"), ("Kích thước dàn nóng", "880×798×310mm"),
      ("Khối lượng dàn lạnh", "13.4kg"), ("Khối lượng dàn nóng", "52.5kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Hàn Quốc")], 24),
    ("Điều hòa âm trần", "Samsung", "Điều hòa âm trần Samsung AC100TN4DKC 36000BTU", 34160000, None,
     "Công suất lớn, tích hợp ion hóa khử khuẩn khử mùi.",
     [("Mã sản phẩm", "AC100TN4DKC/EA"), ("Công suất", "34.100 BTU (10.0kW)"),
      ("Loại", "Âm trần cassette 4 hướng thổi"), ("Gas lạnh", "R410A"),
      ("Công suất điện", "3.13kW"), ("Dòng điện", "14.8A"),
      ("Kích thước dàn lạnh", "840×288×840mm"), ("Kích thước dàn nóng", "940×998×330mm"),
      ("Khối lượng dàn lạnh", "20kg"), ("Khối lượng dàn nóng", "71kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Hàn Quốc")], 24),
    ("Điều hòa âm trần", "Gree", "Điều hòa âm trần Gree GCC18S6IA 18000BTU", 26830000, 22550000,
     "8 hướng thổi với cánh quạt 3D, bảo hành 3 năm.",
     [("Mã sản phẩm", "GCC18S6IA/GMC18S6IA"), ("Công suất", "16.720 BTU (4.900W)"),
      ("Loại", "Âm trần cassette, Inverter"), ("Gas lạnh", "R410a"),
      ("Công suất điện", "1.6kW"), ("Dòng điện", "7.5A"),
      ("Kích thước dàn lạnh", "570×570×265mm"), ("Kích thước dàn nóng", "761×256×548mm"),
      ("Khối lượng dàn lạnh", "17kg"), ("Khối lượng dàn nóng", "37kg"),
      ("Bảo hành", "36 tháng"), ("Xuất xứ", "Trung Quốc")], 36),
    ("Điều hòa âm trần", "Gree", "Điều hòa âm trần Gree GCC24S6IA 24000BTU", 31360000, 26350000,
     "Công suất lớn hơn, 8 hướng thổi đều khắp phòng.",
     [("Mã sản phẩm", "GCC24S6IA/GMC24S6IA"), ("Công suất", "24.225 BTU (7.100W)"),
      ("Loại", "Âm trần cassette, Inverter"), ("Gas lạnh", "R410a"),
      ("Công suất điện", "2.35kW"), ("Dòng điện", "10.7A"),
      ("Kích thước dàn lạnh", "840×840×240mm"), ("Kích thước dàn nóng", "892×340×698mm"),
      ("Khối lượng dàn lạnh", "30kg"), ("Khối lượng dàn nóng", "53kg"),
      ("Bảo hành", "36 tháng"), ("Xuất xứ", "Trung Quốc")], 36),
    ("Điều hòa âm trần", "Gree", "Điều hòa âm trần Gree GCC36S6IA 36000BTU", 36380000, 30570000,
     "Công suất lớn, điện 3 pha, phù hợp không gian thương mại rộng.",
     [("Mã sản phẩm", "GCC36S6IA/GMC36S6IA"), ("Công suất", "35.144 BTU (10.300W)"),
      ("Loại", "Âm trần cassette, Inverter, 3 pha"), ("Gas lạnh", "R410a"),
      ("Công suất điện", "3.5kW"), ("Dòng điện", "7A"),
      ("Kích thước dàn lạnh", "840×840×240mm"), ("Kích thước dàn nóng", "920×370×790mm"),
      ("Khối lượng dàn lạnh", "30kg"), ("Khối lượng dàn nóng", "68kg"),
      ("Bảo hành", "36 tháng"), ("Xuất xứ", "Trung Quốc")], 36),
    # -- Điều hòa nối ống gió --
    ("Điều hòa nối ống gió", "Daikin", "Điều hòa nối ống gió Daikin FBFC50DVM9 18000BTU", 26556000, 22160000,
     "Giấu kín trên trần, phù hợp nhà hàng, spa cỡ vừa.",
     [("Mã sản phẩm", "FBFC50DVM9/RZFC50EVM"), ("Công suất", "17.000 BTU (5.0kW)"),
      ("Loại", "Nối ống gió, Inverter"), ("Gas lạnh", "R32, 0.7kg"),
      ("Công suất điện", "1.56kW"),
      ("Kích thước dàn lạnh", "245×700×800mm"), ("Kích thước dàn nóng", "595×845×300mm"),
      ("Khối lượng dàn lạnh", "26kg"), ("Khối lượng dàn nóng", "34kg"),
      ("Bảo hành", "1 năm máy / 5 năm máy nén"), ("Xuất xứ", "Việt Nam / Thái Lan")], 12),
    ("Điều hòa nối ống gió", "Daikin", "Điều hòa nối ống gió Daikin FDMNQ30MV1 30000BTU", 30420000, None,
     "Công suất lớn, ống dẫn dài tới 50m, phù hợp không gian thương mại.",
     [("Mã sản phẩm", "FDMNQ30MV1/RNQ30MV1"), ("Công suất", "30.000 BTU (8.8kW)"),
      ("Loại", "Nối ống gió"), ("Gas lạnh", "R410a"),
      ("Công suất điện", "3.03kW"),
      ("Kích thước dàn lạnh", "305×1550×680mm"), ("Kích thước dàn nóng", "990×940×320mm"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Thái Lan")], 12),
    ("Điều hòa nối ống gió", "Daikin", "Điều hòa nối ống gió Daikin FBA125BVMA9 42000BTU", 53100000, None,
     "Công suất mạnh, Inverter, phù hợp nhà hàng, showroom rộng dưới 75m².",
     [("Mã sản phẩm", "FBA125BVMA9/RZF125DVM"), ("Công suất", "42.000 BTU (12.5kW)"),
      ("Loại", "Nối ống gió, Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "4.44kW"),
      ("Kích thước dàn lạnh", "245×1400×800mm"), ("Kích thước dàn nóng", "990×940×320mm"),
      ("Khối lượng dàn lạnh", "47kg"), ("Khối lượng dàn nóng", "64kg"),
      ("Bảo hành", "1 năm máy / 5 năm máy nén"), ("Xuất xứ", "Việt Nam / Thái Lan")], 12),
    ("Điều hòa nối ống gió", "Panasonic", "Điều hòa nối ống gió Panasonic S-1821PF3H 18000BTU", 22910000, 19750000,
     "Tích hợp bơm nước ngưng, phù hợp căn hộ, văn phòng nhỏ.",
     [("Mã sản phẩm", "S-1821PF3H/U-18PR1H5"), ("Công suất", "17.100 BTU"),
      ("Loại", "Nối ống gió, Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "1.54kW"),
      ("Kích thước dàn lạnh", "250×800×730mm"), ("Kích thước dàn nóng", "619×824×299mm"),
      ("Khối lượng dàn lạnh", "25kg"), ("Khối lượng dàn nóng", "29kg"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Trung Quốc / Malaysia")], 12),
    ("Điều hòa nối ống gió", "Panasonic", "Điều hòa nối ống gió Panasonic S-2430PF3H 24000BTU", 34360000, 29550000,
     "Công suất lớn hơn, lọc khí nanoeX, phù hợp không gian dưới 40m².",
     [("Mã sản phẩm", "S-2430PF3H/U-24PR1H5"), ("Công suất", "24.200 BTU"),
      ("Loại", "Nối ống gió, Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "2.27kW"),
      ("Kích thước dàn lạnh", "250×1000×730mm"), ("Kích thước dàn nóng", "619×824×299mm"),
      ("Khối lượng dàn lạnh", "30kg"), ("Khối lượng dàn nóng", "33kg"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Trung Quốc / Malaysia")], 12),
    ("Điều hòa nối ống gió", "Panasonic", "Điều hòa nối ống gió Panasonic S-3448PF3H 34000BTU", 34600000, None,
     "Công suất lớn cho không gian thương mại dưới 50m².",
     [("Mã sản phẩm", "S-3448PF3H/U-34PR1H5"), ("Công suất", "34.100 BTU"),
      ("Loại", "Nối ống gió, Inverter"), ("Gas lạnh", "R32"), ("Dòng điện", "13.3-14.5A"),
      ("Kích thước dàn lạnh", "250×1400×730mm"), ("Kích thước dàn nóng", "695×875×320mm"),
      ("Khối lượng dàn lạnh", "39kg"), ("Khối lượng dàn nóng", "48kg"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Trung Quốc / Malaysia")], 12),
    ("Điều hòa nối ống gió", "Mitsubishi Heavy", "Điều hòa nối ống gió Mitsubishi Heavy FDUM50CNZ-W5 18000BTU", 20970000, None,
     "Thương hiệu Nhật Bản bền bỉ, tích hợp bơm nước ngưng.",
     [("Mã sản phẩm", "FDUM50CNZ-W5/FDC50CNZ-W5"), ("Công suất", "18.000 BTU (5.0kW)"),
      ("Loại", "Nối ống gió"), ("Gas lạnh", "R410A"),
      ("Công suất điện", "1.613W"), ("Dòng điện", "7.2A"),
      ("Kích thước dàn lạnh", "280×750×635mm"), ("Kích thước dàn nóng", "640×850×290mm"),
      ("Khối lượng dàn lạnh", "29kg"), ("Khối lượng dàn nóng", "40kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa nối ống gió", "Mitsubishi Heavy", "Điều hòa nối ống gió Mitsubishi Heavy FDUM70CNZ-W5 24000BTU", 23470000, None,
     "Công suất lớn hơn, cửa gió linh hoạt, làm lạnh nhanh.",
     [("Mã sản phẩm", "FDUM70CNZ-W5/FDC70CNZ-W5"), ("Công suất", "24.000 BTU (7.1kW)"),
      ("Loại", "Nối ống gió"), ("Gas lạnh", "R32"), ("Dòng điện", "13A"),
      ("Kích thước dàn lạnh", "280×950×635mm"), ("Kích thước dàn nóng", "640×800×290mm"),
      ("Khối lượng dàn lạnh", "34kg"), ("Khối lượng dàn nóng", "46kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa nối ống gió", "Mitsubishi Heavy", "Điều hòa nối ống gió Mitsubishi Heavy FDUM100CNZ-W5 34000BTU", 40850000, 36360000,
     "Công suất lớn, phù hợp không gian thương mại rộng.",
     [("Mã sản phẩm", "FDUM100CNZ-W5/FDC100CNZ-W5"), ("Công suất", "34.000 BTU (10.5kW)"),
      ("Loại", "Nối ống gió"), ("Gas lạnh", "R32"), ("Dòng điện", "18.3A"),
      ("Kích thước dàn lạnh", "280×1370×740mm"), ("Kích thước dàn nóng", "845×970×370mm"),
      ("Khối lượng dàn lạnh", "53kg"), ("Khối lượng dàn nóng", "77.5kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa nối ống gió", "LG", "Điều hòa nối ống gió LG ZBNQ18GL2D1 18000BTU", 25940000, 22600000,
     "Thẩm mỹ cao, cửa gió bố trí linh hoạt, phù hợp không gian dưới 30m².",
     [("Mã sản phẩm", "ZBNQ18GL2D1"), ("Công suất", "18.000 BTU (2HP)"),
      ("Loại", "Nối ống gió, Inverter"), ("Gas lạnh", "R32"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Thái Lan")], 12),
    ("Điều hòa nối ống gió", "LG", "Điều hòa nối ống gió LG ZBNQ24GL3D1 24000BTU", 27850000, None,
     "Công suất lớn hơn, thiết kế mỏng gọn, phù hợp không gian dưới 40m².",
     [("Mã sản phẩm", "ZBNQ24GL3D1"), ("Công suất", "24.000 BTU (2.5HP)"),
      ("Loại", "Nối ống gió, Inverter"), ("Gas lạnh", "R32"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Thái Lan")], 12),
    ("Điều hòa nối ống gió", "LG", "Điều hòa nối ống gió LG ZBNQ36GM3A0 36000BTU", 47960000, 40300000,
     "Công suất lớn, phù hợp không gian dưới 60m².",
     [("Mã sản phẩm", "ZBNQ36GM3A0"), ("Công suất", "36.000 BTU"),
      ("Loại", "Nối ống gió, Inverter"), ("Gas lạnh", "R410a"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Hàn Quốc")], 12),
    ("Điều hòa nối ống gió", "Samsung", "Điều hòa nối ống gió Samsung AC052TNLDKC 18000BTU", 28000000, 24780000,
     "Thiết kế gọn nhẹ, dễ lắp đặt, Inverter tiết kiệm điện.",
     [("Mã sản phẩm", "AC052TNLDKC/EA"), ("Công suất", "18.000 BTU (2HP)"),
      ("Loại", "Nối ống gió, Inverter"), ("Gas lạnh", "R410a"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Trung Quốc / Hàn Quốc")], 24),
    ("Điều hòa nối ống gió", "Samsung", "Điều hòa nối ống gió Samsung AC071TNMDKC 24000BTU", 37110000, 32660000,
     "Công suất lớn hơn, tính thẩm mỹ cao cho nội thất.",
     [("Mã sản phẩm", "AC071TNMDKC/EA"), ("Công suất", "24.000 BTU (2.5HP)"),
      ("Loại", "Nối ống gió, Inverter"), ("Gas lạnh", "R410a"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Trung Quốc / Hàn Quốc")], 24),
    ("Điều hòa nối ống gió", "Samsung", "Điều hòa nối ống gió Samsung AC100TNMDKC 34000BTU", 44210000, 39120000,
     "Công suất lớn, phù hợp không gian thương mại rộng.",
     [("Mã sản phẩm", "AC100TNMDKC/EA"), ("Công suất", "34.000 BTU (4HP)"),
      ("Loại", "Nối ống gió, Inverter"), ("Gas lạnh", "R410a"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Trung Quốc / Hàn Quốc")], 24),
    ("Điều hòa nối ống gió", "Midea", "Điều hòa nối ống gió Midea MTCE-18CRFN8 18000BTU", 14350000, None,
     "Giá cạnh tranh, phù hợp căn hộ, văn phòng nhỏ.",
     [("Mã sản phẩm", "MTCE-18CRFN8"), ("Công suất", "18.000 BTU"),
      ("Loại", "Nối ống gió, Inverter"), ("Gas lạnh", "R32, 1.15kg"),
      ("Công suất điện", "2.800W"),
      ("Kích thước dàn lạnh", "700×750×245mm"), ("Khối lượng dàn lạnh", "24.4kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Trung Quốc")], 24),
    ("Điều hòa nối ống gió", "Midea", "Điều hòa nối ống gió Midea MTCE-24CRFN8 24000BTU", 20200000, None,
     "Công suất lớn hơn, làm lạnh nhanh, giá hợp lý.",
     [("Mã sản phẩm", "MTCE-24CRFN8"), ("Công suất", "24.000 BTU"),
      ("Loại", "Nối ống gió"), ("Gas lạnh", "R32, 1.5kg"),
      ("Công suất điện", "3.000W"),
      ("Kích thước dàn lạnh", "1000×750×245mm"), ("Khối lượng dàn lạnh", "31.8kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Trung Quốc")], 24),
    ("Điều hòa nối ống gió", "Midea", "Điều hòa nối ống gió Midea MTCE-36CRFN8 36000BTU", 24350000, None,
     "Công suất lớn, vận hành êm, phù hợp không gian thương mại.",
     [("Mã sản phẩm", "MTCE-36CRFN8"), ("Công suất", "36.000 BTU"),
      ("Loại", "Nối ống gió"), ("Gas lạnh", "R32"),
      ("Công suất điện", "4.900W"),
      ("Kích thước dàn lạnh", "1200×750×245mm"), ("Khối lượng dàn lạnh", "40.3kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Trung Quốc")], 24),
    ("Điều hòa nối ống gió", "Casper", "Điều hòa nối ống gió Casper DC-18IS35 18000BTU", 21710000, 18240000,
     "Nhập khẩu Thái Lan, phù hợp không gian dưới 30m².",
     [("Mã sản phẩm", "DC-18IS35"), ("Công suất", "18.000 BTU (5.28kW)"),
      ("Loại", "Nối ống gió, Inverter"), ("Gas lạnh", "R32"),
      ("Kích thước dàn lạnh", "1000×460×200mm"), ("Khối lượng dàn lạnh", "23kg"),
      ("Bảo hành", "2 năm máy / 3 năm máy nén"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa nối ống gió", "Casper", "Điều hòa nối ống gió Casper DC-24IS35 24000BTU", 26290000, 22090000,
     "Công suất lớn hơn, phù hợp không gian rộng hơn.",
     [("Mã sản phẩm", "DC-24IS35"), ("Công suất", "24.000 BTU"),
      ("Loại", "Nối ống gió, Inverter"), ("Gas lạnh", "R32"),
      ("Kích thước dàn lạnh", "1000×700×245mm"), ("Kích thước dàn nóng", "825×310×655mm"),
      ("Khối lượng dàn lạnh", "28kg"), ("Khối lượng dàn nóng", "36kg"),
      ("Bảo hành", "2 năm máy / 3 năm máy nén"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa nối ống gió", "Casper", "Điều hòa nối ống gió Casper DC-36IS35 36000BTU", 38210000, 32110000,
     "Công suất lớn, phù hợp không gian 50-60m².",
     [("Mã sản phẩm", "DC-36IS35"), ("Công suất", "36.000 BTU"),
      ("Loại", "Nối ống gió, Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "3.5kW"),
      ("Kích thước dàn lạnh", "1000×700×245mm"), ("Kích thước dàn nóng", "900×350×700mm"),
      ("Bảo hành", "2 năm máy / 3 năm máy nén"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa nối ống gió", "Gree", "Điều hòa nối ống gió Gree GDC18S6IA 18000BTU", 20600000, None,
     "Inverter tiết kiệm điện, cửa gió hồi linh hoạt.",
     [("Mã sản phẩm", "GDC18S6IA"), ("Công suất", "18.000 BTU"),
      ("Loại", "Nối ống gió, Inverter"), ("Gas lạnh", "R410a"),
      ("Bảo hành", "36 tháng"), ("Xuất xứ", "Trung Quốc")], 36),
    ("Điều hòa nối ống gió", "Gree", "Điều hòa nối ống gió Gree GDC24S6IA 24000BTU", 22800000, None,
     "Công suất lớn hơn, vận hành ổn định.",
     [("Mã sản phẩm", "GDC24S6IA"), ("Công suất", "24.000 BTU"),
      ("Loại", "Nối ống gió, Inverter"), ("Gas lạnh", "R410a"),
      ("Bảo hành", "36 tháng"), ("Xuất xứ", "Trung Quốc")], 36),
    ("Điều hòa nối ống gió", "Gree", "Điều hòa nối ống gió Gree GDC36S6IA 36000BTU", 25700000, None,
     "Công suất lớn, phù hợp không gian thương mại.",
     [("Mã sản phẩm", "GDC36S6IA"), ("Công suất", "36.000 BTU"),
      ("Loại", "Nối ống gió, Inverter"), ("Gas lạnh", "R410a"),
      ("Bảo hành", "36 tháng"), ("Xuất xứ", "Trung Quốc")], 36),
    ("Điều hòa nối ống gió", "Sumikura", "Điều hòa nối ống gió Sumikura ACS/APO-180 18000BTU", 17900000, 15400000,
     "Giá tốt, nhập khẩu Malaysia, phù hợp văn phòng vừa.",
     [("Mã sản phẩm", "ACS/APO-180"), ("Công suất", "18.000 BTU (2HP)"),
      ("Loại", "Nối ống gió"), ("Gas lạnh", "R22"), ("Dòng điện", "8.4A"),
      ("Kích thước dàn lạnh", "1204×181×510mm"), ("Kích thước dàn nóng", "880×540×305mm"),
      ("Khối lượng dàn lạnh", "21kg"), ("Khối lượng dàn nóng", "49kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Malaysia")], 24),
    ("Điều hòa nối ống gió", "Sumikura", "Điều hòa nối ống gió Sumikura ACS/APO-280 28000BTU", 24500000, 21200000,
     "Công suất lớn hơn, phù hợp không gian thương mại vừa.",
     [("Mã sản phẩm", "ACS/APO-280"), ("Công suất", "28.000 BTU (3HP)"),
      ("Loại", "Nối ống gió"), ("Gas lạnh", "R22"), ("Dòng điện", "13.7A"),
      ("Kích thước dàn lạnh", "1190×260×643mm"), ("Kích thước dàn nóng", "925×700×366mm"),
      ("Khối lượng dàn lạnh", "36kg"), ("Khối lượng dàn nóng", "60kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Malaysia")], 24),
    ("Điều hòa nối ống gió", "Sumikura", "Điều hòa nối ống gió Sumikura ACS/APO-360 36000BTU", 29800000, 25900000,
     "Công suất lớn, phù hợp không gian thương mại rộng.",
     [("Mã sản phẩm", "ACS/APO-360"), ("Công suất", "36.000 BTU (4HP)"),
      ("Loại", "Nối ống gió"), ("Gas lạnh", "R22"), ("Dòng điện", "7.4A"),
      ("Kích thước dàn nóng", "1050×995×400mm"),
      ("Khối lượng dàn lạnh", "44kg"), ("Khối lượng dàn nóng", "92kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Malaysia")], 24),
    ("Điều hòa nối ống gió", "Nagakawa", "Điều hòa nối ống gió Nagakawa NB-C18R1A18 18000BTU", 16900000, 14500000,
     "Cửa gió linh hoạt, thẩm mỹ cao, phù hợp căn hộ cao cấp.",
     [("Mã sản phẩm", "NB-C18R1A18"), ("Công suất", "18.000 BTU (2HP)"),
      ("Loại", "Nối ống gió"), ("Gas lạnh", "R32"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Malaysia")], 24),
    ("Điều hòa nối ống gió", "Nagakawa", "Điều hòa nối ống gió Nagakawa NB-C24R1A18 24000BTU", 20500000, 17700000,
     "Công suất lớn hơn, phù hợp không gian rộng hơn.",
     [("Mã sản phẩm", "NB-C24R1A18"), ("Công suất", "24.000 BTU (2.5HP)"),
      ("Loại", "Nối ống gió"), ("Gas lạnh", "R32"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Malaysia")], 24),
    ("Điều hòa nối ống gió", "Nagakawa", "Điều hòa nối ống gió Nagakawa NB-C36R1A18 36000BTU", 26500000, 22900000,
     "Công suất lớn, phù hợp căn hộ cao cấp, không gian thương mại.",
     [("Mã sản phẩm", "NB-C36R1A18"), ("Công suất", "36.000 BTU (4HP)"),
      ("Loại", "Nối ống gió"), ("Gas lạnh", "R32"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Malaysia")], 24),
    # -- Điều hòa tủ đứng --
    ("Điều hòa tủ đứng", "Daikin", "Điều hòa tủ đứng Daikin FVA71AMVM 24000BTU", 44770000, None,
     "Inverter tiết kiệm điện, phù hợp phòng khách, showroom vừa.",
     [("Mã sản phẩm", "FVA71AMVM/RZF71DVM"), ("Công suất", "24.200 BTU (7.1kW)"),
      ("Loại", "Tủ đứng, Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "2.51kW"),
      ("Kích thước dàn lạnh", "1850×600×270mm"), ("Kích thước dàn nóng", "595×845×300mm"),
      ("Khối lượng dàn lạnh", "42kg"), ("Khối lượng dàn nóng", "41kg"),
      ("Bảo hành", "1 năm máy / 5 năm máy nén"), ("Xuất xứ", "Trung Quốc / Thái Lan")], 12),
    ("Điều hòa tủ đứng", "Daikin", "Điều hòa tủ đứng Daikin FVC85AV1V 30000BTU", 35208000, 29570000,
     "Công suất lớn hơn, cảm biến nhiệt độ kép, phù hợp không gian rộng hơn.",
     [("Mã sản phẩm", "FVC85AV1V/RC85AGV1V"), ("Công suất", "30.000 BTU (3HP)"),
      ("Loại", "Tủ đứng"), ("Gas lạnh", "R32"),
      ("Công suất điện", "2.74kW"),
      ("Kích thước dàn lạnh", "1850×600×270mm"), ("Kích thước dàn nóng", "695×930×350mm"),
      ("Khối lượng dàn lạnh", "42kg"), ("Khối lượng dàn nóng", "56kg"),
      ("Bảo hành", "1 năm máy / 5 năm máy nén"), ("Xuất xứ", "Malaysia")], 12),
    ("Điều hòa tủ đứng", "Daikin", "Điều hòa tủ đứng Daikin FVC100AV1V 36000BTU", 43408000, 36140000,
     "Công suất lớn, điện 3 pha, phù hợp không gian thương mại rộng.",
     [("Mã sản phẩm", "FVC100AV1V/RC100AGY1V"), ("Công suất", "36.000 BTU (4HP)"),
      ("Loại", "Tủ đứng, điện 3 pha"), ("Gas lạnh", "R32, 1.45kg"),
      ("Công suất điện", "3.4kW"),
      ("Kích thước dàn lạnh", "1850×600×350mm"), ("Kích thước dàn nóng", "852×1030×400mm"),
      ("Khối lượng dàn lạnh", "45kg"), ("Khối lượng dàn nóng", "64kg"),
      ("Bảo hành", "1 năm máy / 5 năm máy nén"), ("Xuất xứ", "Malaysia")], 12),
    ("Điều hòa tủ đứng", "LG", "Điều hòa tủ đứng LG ZPNQ24GS1A0 24000BTU", 28820000, 25650000,
     "Dual Inverter tiết kiệm điện tới 60%, thổi gió xa 20m.",
     [("Mã sản phẩm", "ZPNQ24GS1A0/V24PACU"), ("Công suất", "24.000 BTU (2.5HP)"),
      ("Loại", "Tủ đứng, Dual Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "2.22kW"),
      ("Kích thước dàn lạnh", "530×1800×295mm"), ("Khối lượng dàn lạnh", "25.3kg"),
      ("Khối lượng dàn nóng", "41.5kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Thái Lan / Hàn Quốc")], 24),
    ("Điều hòa tủ đứng", "LG", "Điều hòa tủ đứng LG ZPNQ30GT3A1 30000BTU", 32800000, None,
     "Công suất lớn hơn, thổi gió 4 hướng, tầm xa 20m.",
     [("Mã sản phẩm", "ZPNQ30GT3A1/ZUUQ30GV1"), ("Công suất", "30.000 BTU"),
      ("Loại", "Tủ đứng"), ("Gas lạnh", "R32"),
      ("Công suất điện", "2.73kW"),
      ("Kích thước dàn lạnh", "590×1840×300mm"), ("Kích thước dàn nóng", "870×650×330mm"),
      ("Khối lượng dàn lạnh", "36kg"), ("Khối lượng dàn nóng", "41.5kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Thái Lan / Hàn Quốc")], 24),
    ("Điều hòa tủ đứng", "LG", "Điều hòa tủ đứng LG ZPNQ36GR5A0 36000BTU", 44910000, 40100000,
     "Công suất lớn, chế độ Power Cooling làm lạnh nhanh.",
     [("Mã sản phẩm", "ZPNQ36GR5A0/ZUAD1"), ("Công suất", "36.000 BTU (4HP)"),
      ("Loại", "Tủ đứng"), ("Gas lạnh", "R32"),
      ("Công suất điện", "3.51kW"),
      ("Kích thước dàn lạnh", "590×1840×300mm"), ("Kích thước dàn nóng", "950×834×330mm"),
      ("Khối lượng dàn lạnh", "36kg"), ("Khối lượng dàn nóng", "59.5kg"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Thái Lan / Hàn Quốc")], 12),
    ("Điều hòa tủ đứng", "Panasonic", "Điều hòa tủ đứng Panasonic S-21PB3H5 21000BTU", 34010000, 29250000,
     "Inverter tiết kiệm điện, thổi gió 4 hướng xa 7m.",
     [("Mã sản phẩm", "S-21PB3H5/U-21PRB1H5"), ("Công suất", "20.500 BTU"),
      ("Loại", "Tủ đứng, Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "1.80kW"),
      ("Kích thước dàn lạnh", "1680×500×318mm"), ("Kích thước dàn nóng", "626×825×320mm"),
      ("Khối lượng dàn lạnh", "29kg"), ("Khối lượng dàn nóng", "35kg"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Trung Quốc")], 12),
    ("Điều hòa tủ đứng", "Panasonic", "Điều hòa tủ đứng Panasonic S-24PB3H5 24000BTU", 39150000, 33750000,
     "Công suất lớn hơn, công nghệ nanoeX thế hệ 2.",
     [("Mã sản phẩm", "S-24PB3H5"), ("Công suất", "24.600 BTU"),
      ("Loại", "Tủ đứng"), ("Gas lạnh", "R32"),
      ("Công suất điện", "2.55kW"),
      ("Kích thước dàn lạnh", "1680×500×318mm"), ("Kích thước dàn nóng", "626×825×320mm"),
      ("Khối lượng dàn lạnh", "29.5kg"), ("Khối lượng dàn nóng", "36kg"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Trung Quốc")], 12),
    ("Điều hòa tủ đứng", "Panasonic", "Điều hòa tủ đứng Panasonic S-34PB3H5 34000BTU", 39200000, None,
     "Công suất lớn, thổi gió xa 4 hướng, làm lạnh nhanh.",
     [("Mã sản phẩm", "S-34PB3H5"), ("Công suất", "34.100 BTU (10.00kW)"),
      ("Loại", "Tủ đứng"), ("Gas lạnh", "R410a"),
      ("Công suất điện", "3.45kW"),
      ("Kích thước dàn lạnh", "1880×600×357mm"), ("Kích thước dàn nóng", "786×900×320mm"),
      ("Khối lượng dàn lạnh", "45kg"), ("Khối lượng dàn nóng", "45kg"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Trung Quốc")], 12),
    ("Điều hòa tủ đứng", "Mitsubishi Heavy", "Điều hòa tủ đứng Mitsubishi Heavy FDF71CR-S5 24000BTU", 23500000, 20900000,
     "Thương hiệu Nhật Bản bền bỉ, phù hợp phòng khách, showroom vừa.",
     [("Mã sản phẩm", "FDF71CR-S5/FDC71CR-S5"), ("Công suất", "24.255 BTU (7.1kW)"),
      ("Loại", "Tủ đứng"), ("Gas lạnh", "R410a"),
      ("Công suất điện", "2.507kW"), ("Dòng điện", "11.1A"),
      ("Kích thước dàn lạnh", "1850×600×320mm"), ("Kích thước dàn nóng", "640×850×290mm"),
      ("Khối lượng dàn nóng", "40kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa tủ đứng", "Mitsubishi Heavy", "Điều hòa tủ đứng Mitsubishi Heavy FSHY/FCHY-2801 28000BTU", 26800000, 23800000,
     "Sản xuất tại Việt Nam, công suất lớn hơn, giá hợp lý.",
     [("Mã sản phẩm", "FSHY/FCHY-2801"), ("Công suất", "28.000 BTU (3.2HP)"),
      ("Loại", "Tủ đứng"), ("Gas lạnh", "R410a"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Việt Nam")], 24),
    ("Điều hòa tủ đứng", "Mitsubishi Heavy", "Điều hòa tủ đứng Mitsubishi Heavy FDF125CR-S5 45000BTU", 42500000, 37800000,
     "Công suất lớn, thổi gió mạnh, phù hợp không gian tới 70m².",
     [("Mã sản phẩm", "FDF125CR-S5/FDC125CR-S5"), ("Công suất", "45.000 BTU (12.5kW)"),
      ("Loại", "Tủ đứng"), ("Gas lạnh", "R410A"),
      ("Công suất điện", "4.781kW"),
      ("Kích thước dàn lạnh", "280×750×635mm"), ("Kích thước dàn nóng", "640×850×290mm"),
      ("Khối lượng dàn lạnh", "34kg"), ("Khối lượng dàn nóng", "47kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa tủ đứng", "Midea", "Điều hòa tủ đứng Midea MFPA-24CRN1 24000BTU", 20180000, 17150000,
     "Giá cạnh tranh, đèn LED hiển thị, phù hợp phòng khách.",
     [("Mã sản phẩm", "MFPA-24CRN1"), ("Công suất", "26.000 BTU"),
      ("Loại", "Tủ đứng"), ("Gas lạnh", "R410A, 1.2kg"),
      ("Công suất điện", "2540W"), ("Dòng điện", "11.5A"),
      ("Kích thước dàn lạnh", "510×315×1750mm"), ("Kích thước dàn nóng", "890×342×673mm"),
      ("Khối lượng dàn lạnh", "35.5kg"), ("Khối lượng dàn nóng", "49.8kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Trung Quốc")], 24),
    ("Điều hòa tủ đứng", "Midea", "Điều hòa tủ đứng Midea MFPA-28CRN1 28000BTU", 19500000, 16900000,
     "Công suất lớn hơn, lọc khí ion bạc khử mùi.",
     [("Mã sản phẩm", "MFPA-28CRN1"), ("Công suất", "28.000 BTU"),
      ("Loại", "Tủ đứng"), ("Gas lạnh", "R410A, 1.4kg"),
      ("Công suất điện", "2600W"), ("Dòng điện", "12.7A"),
      ("Kích thước dàn lạnh", "510×315×1750mm"), ("Kích thước dàn nóng", "845×363×702mm"),
      ("Khối lượng dàn lạnh", "35.7kg"), ("Khối lượng dàn nóng", "50.8kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Trung Quốc")], 24),
    ("Điều hòa tủ đứng", "Midea", "Điều hòa tủ đứng Midea MFJJ2-50CRN1 48000BTU", 32840000, 27900000,
     "Công suất lớn, điện 3 pha, phù hợp không gian thương mại.",
     [("Mã sản phẩm", "MFJJ2-50CRN1"), ("Công suất", "48.000 BTU (5.5HP)"),
      ("Loại", "Tủ đứng, điện 3 pha"), ("Gas lạnh", "R410A, 3.5kg"),
      ("Công suất điện", "5250W"), ("Dòng điện", "8.8A"),
      ("Kích thước dàn lạnh", "540×410×1825mm"), ("Kích thước dàn nóng", "900×350×1170mm"),
      ("Khối lượng dàn lạnh", "50.7kg"), ("Khối lượng dàn nóng", "91.3kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Trung Quốc")], 24),
    ("Điều hòa tủ đứng", "Samsung", "Điều hòa tủ đứng Samsung AC030BNPDKC 30000BTU", 33810000, 29920000,
     "Inverter tiết kiệm điện, thổi gió xa 20m, 4 hướng.",
     [("Mã sản phẩm", "AC030BNPDKC/TC"), ("Công suất", "30.000 BTU (3HP, 8.2kW)"),
      ("Loại", "Tủ đứng, Inverter"), ("Gas lạnh", "R410a"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Hàn Quốc")], 12),
    ("Điều hòa tủ đứng", "Samsung", "Điều hòa tủ đứng Samsung AC036BNPDKC 36000BTU", 42530000, 37640000,
     "Công suất lớn hơn, phù hợp không gian rộng hơn.",
     [("Mã sản phẩm", "AC036BNPDKC/TC"), ("Công suất", "36.000 BTU (4HP, 11kW)"),
      ("Loại", "Tủ đứng, Inverter"), ("Gas lạnh", "R410a"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Hàn Quốc")], 12),
    ("Điều hòa tủ đứng", "Samsung", "Điều hòa tủ đứng Samsung AC048BNPDKC 48000BTU", 45960000, 40670000,
     "Công suất lớn, bảng điều khiển cảm ứng, tiết kiệm điện 30-50%.",
     [("Mã sản phẩm", "AC048BNPDKC/TC"), ("Công suất", "48.000 BTU (5HP, 16.7kW)"),
      ("Loại", "Tủ đứng, Inverter"), ("Gas lạnh", "R410a"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Hàn Quốc")], 12),
    ("Điều hòa tủ đứng", "Gree", "Điều hòa tủ đứng Gree GVC24AM-K6NNC7B 24000BTU", 26030000, 21870000,
     "Bảo hành máy nén 5 năm, thổi gió nhanh 4 hướng.",
     [("Mã sản phẩm", "GVC24AM-K6NNC7B"), ("Công suất", "24.000 BTU"),
      ("Loại", "Tủ đứng"), ("Gas lạnh", "R410a"),
      ("Công suất điện", "2500W"), ("Dòng điện", "11A"),
      ("Kích thước dàn lạnh", "507×320×1770mm"), ("Kích thước dàn nóng", "963×396×700mm"),
      ("Khối lượng dàn lạnh", "38.5kg"), ("Khối lượng dàn nóng", "60kg"),
      ("Bảo hành", "3 năm máy / 5 năm máy nén"), ("Xuất xứ", "Trung Quốc")], 36),
    ("Điều hòa tủ đứng", "Gree", "Điều hòa tủ đứng Gree GVC30AMXH-K6NNC7B 30000BTU", 35000000, 29410000,
     "Công suất lớn hơn, điều khiển qua WiFi smartphone.",
     [("Mã sản phẩm", "GVC30AMXH-K6NNC7B"), ("Công suất", "30.000 BTU (3HP)"),
      ("Loại", "Tủ đứng, Inverter"), ("Gas lạnh", "R32"),
      ("Công suất điện", "3140W"), ("Dòng điện", "13.93A"),
      ("Kích thước dàn lạnh", "507×320×1770mm"), ("Kích thước dàn nóng", "790×427×1000mm"),
      ("Khối lượng dàn lạnh", "38.5kg"), ("Khối lượng dàn nóng", "60kg"),
      ("Bảo hành", "3 năm máy / 5 năm máy nén"), ("Xuất xứ", "Trung Quốc")], 36),
    ("Điều hòa tủ đứng", "Gree", "Điều hòa tủ đứng Gree GVC42ALXH-M6NNC7B 42000BTU", 45650000, 38360000,
     "Công suất lớn, điện 3 pha, phù hợp không gian thương mại.",
     [("Mã sản phẩm", "GVC42ALXH-M6NNC7B"), ("Công suất", "42.000 BTU (5HP)"),
      ("Loại", "Tủ đứng, Inverter, điện 3 pha"), ("Gas lạnh", "R32"),
      ("Công suất điện", "4390W"),
      ("Kích thước dàn lạnh", "587×394×1882mm"), ("Kích thước dàn nóng", "1250×412×1032.5mm"),
      ("Khối lượng dàn lạnh", "55kg"), ("Khối lượng dàn nóng", "107kg"),
      ("Bảo hành", "3 năm máy / 5 năm máy nén"), ("Xuất xứ", "Trung Quốc")], 36),
    ("Điều hòa tủ đứng", "Sumikura", "Điều hòa tủ đứng Sumikura APF/APO-210/CL-A 21000BTU", 18790000, 16200000,
     "Giá tốt, nhập khẩu Malaysia, chức năng hút ẩm độc lập.",
     [("Mã sản phẩm", "APF/APO-210/CL-A"), ("Công suất", "21.000 BTU (2.2HP)"),
      ("Loại", "Tủ đứng"), ("Gas lạnh", "R22"),
      ("Công suất điện", "2190W"), ("Dòng điện", "9.6A"),
      ("Kích thước dàn lạnh", "500×1803×316mm"), ("Kích thước dàn nóng", "775×590×270mm"),
      ("Khối lượng dàn lạnh", "34kg"), ("Khối lượng dàn nóng", "39kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Malaysia")], 24),
    ("Điều hòa tủ đứng", "Sumikura", "Điều hòa tủ đứng Sumikura APF/APO-280/CL-A 28000BTU", 18650000, None,
     "Công suất lớn hơn, màn hình LCD hiển thị.",
     [("Mã sản phẩm", "APF/APO-280/CL-A"), ("Công suất", "28.000 BTU (3HP)"),
      ("Loại", "Tủ đứng"), ("Gas lạnh", "R22"),
      ("Công suất điện", "2850W"),
      ("Kích thước dàn lạnh", "500×1803×316mm"), ("Kích thước dàn nóng", "860×700×320mm"),
      ("Khối lượng dàn lạnh", "36kg"), ("Khối lượng dàn nóng", "52kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Malaysia")], 24),
    ("Điều hòa tủ đứng", "Sumikura", "Điều hòa tủ đứng Sumikura APF/APO-360/CL-A 36000BTU", 22700000, None,
     "Công suất lớn, thiết kế gọn, vận hành 1 pha dù công suất cao.",
     [("Mã sản phẩm", "APF/APO-360/CL-A"), ("Công suất", "36.000 BTU"),
      ("Loại", "Tủ đứng"), ("Gas lạnh", "R22"),
      ("Công suất điện", "3550W"), ("Dòng điện", "16.1A"),
      ("Kích thước dàn lạnh", "500×1803×316mm"), ("Kích thước dàn nóng", "860×700×320mm"),
      ("Khối lượng dàn lạnh", "36kg"), ("Khối lượng dàn nóng", "59kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Malaysia")], 24),
    ("Điều hòa tủ đứng", "Funiki", "Điều hòa tủ đứng Funiki FC27MMC1 27000BTU", 21650000, 18190000,
     "Giá tốt, chế độ Powerful làm lạnh nhanh, tự khởi động lại sau mất điện.",
     [("Mã sản phẩm", "FC27MMC1"), ("Công suất", "27.000 BTU (7620W)"),
      ("Loại", "Tủ đứng"), ("Gas lạnh", "R410A, 1200g"),
      ("Công suất điện", "2540W"), ("Dòng điện", "11.5A"),
      ("Kích thước dàn lạnh", "510×315×1750mm"), ("Kích thước dàn nóng", "890×342×673mm"),
      ("Khối lượng dàn lạnh", "35.5kg"), ("Khối lượng dàn nóng", "49.8kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Malaysia")], 24),
    ("Điều hòa tủ đứng", "Funiki", "Điều hòa tủ đứng Funiki FC36MMC1 36000BTU", 27750000, 23320000,
     "Công suất lớn hơn, thiết kế gọn gàng.",
     [("Mã sản phẩm", "FC36MMC1"), ("Công suất", "36.000 BTU"),
      ("Loại", "Tủ đứng"), ("Gas lạnh", "R410A, 2750g"),
      ("Công suất điện", "2900W"), ("Dòng điện", "12.9A"),
      ("Kích thước dàn lạnh", "610×390×1925mm"), ("Kích thước dàn nóng", "946×410×810mm"),
      ("Khối lượng dàn lạnh", "55.5kg"), ("Khối lượng dàn nóng", "72.4kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Malaysia")], 24),
    ("Điều hòa tủ đứng", "Funiki", "Điều hòa tủ đứng Funiki FC50MMC1 50000BTU", 33800000, 28400000,
     "Công suất lớn, vận hành 3 pha, hệ thống lọc khí diệt khuẩn.",
     [("Mã sản phẩm", "FC50MMC1"), ("Công suất", "50.000 BTU"),
      ("Loại", "Tủ đứng, điện 3 pha"), ("Gas lạnh", "R410A, 3000g"),
      ("Công suất điện", "5250W"),
      ("Kích thước dàn lạnh", "550×350×1800mm"), ("Kích thước dàn nóng", "900×350×1170mm"),
      ("Khối lượng dàn lạnh", "49kg"), ("Khối lượng dàn nóng", "91.3kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Malaysia")], 24),
    ("Điều hòa tủ đứng", "Casper", "Điều hòa tủ đứng Casper FC-18TL22 17000BTU", 19880000, 16710000,
     "Giá tốt, thổi gió xa 15m, phù hợp phòng khách nhỏ.",
     [("Mã sản phẩm", "FC-18TL22"), ("Công suất", "17.000 BTU"),
      ("Loại", "Tủ đứng"), ("Gas lạnh", "R410A, 0.97kg"),
      ("Công suất điện", "1.64kW"), ("Dòng điện", "7.3A"),
      ("Kích thước dàn lạnh", "506×315×1780mm"), ("Kích thước dàn nóng", "800×315×545mm"),
      ("Khối lượng dàn lạnh", "39kg"), ("Khối lượng dàn nóng", "40kg"),
      ("Bảo hành", "2 năm máy / 3 năm máy nén"), ("Xuất xứ", "Thái Lan")], 24),
    ("Điều hòa tủ đứng", "Casper", "Điều hòa tủ đứng Casper FC-24FS36 24000BTU", 19550000, None,
     "Công suất lớn hơn, thổi gió 4 hướng, phù hợp phòng 22-43m².",
     [("Mã sản phẩm", "FC-24FS36"), ("Công suất", "24.000 BTU (2.5HP)"),
      ("Loại", "Tủ đứng"), ("Gas lạnh", "R410A"),
      ("Công suất điện", "2100W"),
      ("Kích thước dàn lạnh", "1780×500×300mm"), ("Kích thước dàn nóng", "800×690×300mm"),
      ("Khối lượng dàn lạnh", "32kg"), ("Khối lượng dàn nóng", "44kg"),
      ("Bảo hành", "3 năm máy / 5 năm máy nén"), ("Xuất xứ", "Thái Lan")], 36),
    ("Điều hòa tủ đứng", "Casper", "Điều hòa tủ đứng Casper FC-42FS36 42000BTU", 34280000, None,
     "Công suất lớn, điện 3 pha, phù hợp không gian 44-65m².",
     [("Mã sản phẩm", "FC-42FS36"), ("Công suất", "42.000 BTU (5.0HP)"),
      ("Loại", "Tủ đứng, điện 3 pha"), ("Gas lạnh", "R410A"),
      ("Công suất điện", "4650W"),
      ("Kích thước dàn lạnh", "1910×560×360mm"), ("Kích thước dàn nóng", "1255×945×340mm"),
      ("Khối lượng dàn lạnh", "53kg"), ("Khối lượng dàn nóng", "98kg"),
      ("Bảo hành", "3 năm máy / 5 năm máy nén"), ("Xuất xứ", "Thái Lan")], 36),
    ("Điều hòa tủ đứng", "Nagakawa", "Điều hòa tủ đứng Nagakawa NP-C24R1K58 24000BTU", 19210000, 16700000,
     "Giá tốt, chế độ đảo gió tự động, dàn đồng mạ vàng chống ăn mòn.",
     [("Mã sản phẩm", "NP-C24R1K58"), ("Công suất", "24.000 BTU"),
      ("Loại", "Tủ đứng"), ("Gas lạnh", "R410A"),
      ("Công suất điện", "2690W"), ("Dòng điện", "11.2A"),
      ("Kích thước dàn lạnh", "480×1730×300mm"), ("Kích thước dàn nóng", "902×650×307mm"),
      ("Khối lượng dàn lạnh", "52kg"), ("Khối lượng dàn nóng", "62kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Malaysia")], 24),
    ("Điều hòa tủ đứng", "Nagakawa", "Điều hòa tủ đứng Nagakawa NP-C28R1K58 28000BTU", 21180000, 17800000,
     "Công suất lớn hơn, tích hợp ionizer khử khuẩn.",
     [("Mã sản phẩm", "NP-C28R1K58"), ("Công suất", "28.000 BTU"),
      ("Loại", "Tủ đứng"), ("Gas lạnh", "R410A"),
      ("Công suất điện", "2690W"),
      ("Kích thước dàn lạnh", "480×1730×300mm"), ("Kích thước dàn nóng", "902×650×307mm"),
      ("Khối lượng dàn lạnh", "52kg"), ("Khối lượng dàn nóng", "62kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Malaysia")], 24),
    ("Điều hòa tủ đứng", "Nagakawa", "Điều hòa tủ đứng Nagakawa NP-C50R1K58 50000BTU", 33080000, 27800000,
     "Công suất lớn, điện 3 pha, phù hợp không gian 80-90m².",
     [("Mã sản phẩm", "NP-C50R1K58"), ("Công suất", "50.000 BTU"),
      ("Loại", "Tủ đứng, điện 3 pha"), ("Gas lạnh", "R410a"),
      ("Công suất điện", "4900W"),
      ("Kích thước dàn lạnh", "540×1776×415mm"), ("Kích thước dàn nóng", "900×805×360mm"),
      ("Khối lượng dàn lạnh", "65kg"), ("Khối lượng dàn nóng", "85kg"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Malaysia")], 24),
    # -- Máy giặt --
    # -- Electrolux --
    ("Máy giặt", "Electrolux", "Máy giặt Electrolux EWF9023P5WC 9kg cửa ngang", 7450000, None,
     "Công nghệ UltraMix hòa tan bột giặt trước khi giặt, kháng khuẩn hiệu quả.",
     [("Mã sản phẩm", "EWF9023P5WC"), ("Khối lượng giặt", "9 kg"), ("Loại", "Cửa ngang"),
      ("Công nghệ", "UltraMix, kháng khuẩn"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Thái Lan")], 24),
    ("Máy giặt", "Electrolux", "Máy giặt Electrolux EWF1024D3WC 10kg cửa ngang", 7350000, None,
     "Công suất lớn hơn, tiết kiệm nước, phù hợp gia đình đông người.",
     [("Mã sản phẩm", "EWF1024D3WC"), ("Khối lượng giặt", "10 kg"), ("Loại", "Cửa ngang"),
      ("Công nghệ", "UltraMix, tiết kiệm nước"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Thái Lan")], 24),
    ("Máy giặt", "Electrolux", "Máy giặt sấy Electrolux EWW9024P3WC 9kg/6kg", 10500000, None,
     "Giặt sấy 2 trong 1, hơi nước diệt khuẩn, tiện lợi không cần phơi.",
     [("Mã sản phẩm", "EWW9024P3WC"), ("Khối lượng giặt", "9 kg giặt / 6 kg sấy"), ("Loại", "Cửa ngang, giặt sấy"),
      ("Công nghệ", "Hơi nước diệt khuẩn"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Thái Lan")], 24),
    # -- LG --
    ("Máy giặt", "LG", "Máy giặt LG FB1209S5W 9kg cửa ngang", 6600000, None,
     "AI DD Inverter tiết kiệm điện, vận hành êm ái.",
     [("Mã sản phẩm", "FB1209S5W"), ("Khối lượng giặt", "9 kg"), ("Loại", "Cửa ngang, AI DD Inverter"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "ASEAN")], 24),
    ("Máy giặt", "LG", "Máy giặt LG FX1410N5W 10kg cửa ngang", 8400000, None,
     "Công suất lớn hơn, hơi nước diệt khuẩn 99.9%.",
     [("Mã sản phẩm", "FX1410N5W"), ("Khối lượng giặt", "10 kg"), ("Loại", "Cửa ngang, AI DD Inverter"),
      ("Công nghệ", "Hơi nước diệt khuẩn"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "ASEAN")], 24),
    ("Máy giặt", "LG", "Máy giặt LG FX1412N5G 12kg cửa ngang", 10850000, None,
     "Công suất lớn, phù hợp gia đình đông người.",
     [("Mã sản phẩm", "FX1412N5G"), ("Khối lượng giặt", "12 kg"), ("Loại", "Cửa ngang, AI DD Inverter"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "ASEAN")], 24),
    # -- Toshiba --
    ("Máy giặt", "Toshiba", "Máy giặt Toshiba AW-M905BV(MK) 8kg cửa trên", 4350000, None,
     "Công nghệ Fuzzy Logic tự động cân đồ giặt, giá tốt.",
     [("Mã sản phẩm", "AW-M905BV(MK)"), ("Khối lượng giặt", "8 kg"), ("Loại", "Cửa trên"),
      ("Công nghệ", "Fuzzy Logic"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Thái Lan")], 24),
    ("Máy giặt", "Toshiba", "Máy giặt Toshiba TW-T23BU110UWV(MG) 10kg cửa ngang Inverter", 6810000, None,
     "Real Inverter tiết kiệm điện, công nghệ Greatwave.",
     [("Mã sản phẩm", "TW-T23BU110UWV(MG)"), ("Khối lượng giặt", "10 kg"), ("Loại", "Cửa ngang, Real Inverter"),
      ("Công nghệ", "Greatwave"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Thái Lan")], 24),
    ("Máy giặt", "Toshiba", "Máy giặt Toshiba TW-BL115A2V(SS) 10.5kg cửa ngang Inverter", 9500000, 8200000,
     "Siêu bọt khí nano UFB, giặt hơi nước, điều khiển qua WiFi.",
     [("Mã sản phẩm", "TW-BL115A2V(SS)"), ("Khối lượng giặt", "10.5 kg"), ("Loại", "Cửa ngang, Inverter"),
      ("Công nghệ", "Siêu bọt khí nano UFB, giặt hơi nước, WiFi"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Thái Lan")], 24),
    # -- Samsung --
    ("Máy giặt", "Samsung", "Máy giặt Samsung WA12CG5886BVSV 12kg cửa trên", 6930000, None,
     "Công suất lớn 12kg, Digital Inverter bền bỉ.",
     [("Mã sản phẩm", "WA12CG5886BVSV"), ("Khối lượng giặt", "12 kg"), ("Loại", "Cửa trên, Digital Inverter"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Việt Nam")], 24),
    ("Máy giặt", "Samsung", "Máy giặt Samsung WW10DG6U34LESV 10kg cửa ngang", 7560000, None,
     "AI Control tự động tối ưu chu trình giặt theo khối lượng đồ.",
     [("Mã sản phẩm", "WW10DG6U34LESV"), ("Khối lượng giặt", "10 kg"), ("Loại", "Cửa ngang, AI Control"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Việt Nam")], 24),
    ("Máy giặt", "Samsung", "Máy giặt Samsung WW11CGP44DSHSV 11kg cửa ngang", 8420000, None,
     "Công nghệ Ecobubble hòa tan bọt khí giúp giặt sạch nhanh ở nhiệt độ thấp.",
     [("Mã sản phẩm", "WW11CGP44DSHSV"), ("Khối lượng giặt", "11 kg"), ("Loại", "Cửa ngang"),
      ("Công nghệ", "Ecobubble"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Việt Nam")], 24),
    # -- Panasonic --
    ("Máy giặt", "Panasonic", "Máy giặt Panasonic NA-F90A9DRV 9kg cửa ngang", 6400000, None,
     "Công nghệ Active Foam tạo bọt siêu mịn, kháng khuẩn ion bạc.",
     [("Mã sản phẩm", "NA-F90A9DRV"), ("Khối lượng giặt", "9 kg"), ("Loại", "Cửa ngang"),
      ("Công nghệ", "Active Foam, kháng khuẩn ion bạc"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Việt Nam")], 12),
    ("Máy giặt", "Panasonic", "Máy giặt Panasonic NA-FD10VR1BV 10.5kg cửa ngang", 10450000, None,
     "TD Inverter, công nghệ WaterBazooka đánh bay vết bẩn cứng đầu.",
     [("Mã sản phẩm", "NA-FD10VR1BV"), ("Khối lượng giặt", "10.5 kg"), ("Loại", "Cửa ngang, TD Inverter"),
      ("Công nghệ", "WaterBazooka, StainMaster"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Việt Nam")], 12),
    ("Máy giặt", "Panasonic", "Máy giặt Panasonic NA-V90FR1BVT 9kg cửa ngang AI Smart Wash", 11850000, None,
     "AI Smart Wash, diệt khuẩn bằng tia UV và ion bạc Blue Ag+.",
     [("Mã sản phẩm", "NA-V90FR1BVT"), ("Khối lượng giặt", "9 kg"), ("Loại", "Cửa ngang, AI Smart Wash"),
      ("Công nghệ", "Blue Ag+, tia UV diệt khuẩn"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Việt Nam")], 12),
    # -- Casper --
    ("Máy giặt", "Casper", "Máy giặt Casper WT-75NG1 7.5kg cửa trên", 3350000, None,
     "Nhỏ gọn, giá tốt, phù hợp phòng trọ, gia đình ít người.",
     [("Mã sản phẩm", "WT-75NG1"), ("Khối lượng giặt", "7.5 kg"), ("Loại", "Cửa trên"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Trung Quốc")], 24),
    ("Máy giặt", "Casper", "Máy giặt Casper WF-D8VWR1 8kg cửa ngang", 5150000, None,
     "Tiết kiệm điện nước, vận hành êm ái.",
     [("Mã sản phẩm", "WF-D8VWR1"), ("Khối lượng giặt", "8 kg"), ("Loại", "Cửa ngang"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Trung Quốc")], 24),
    ("Máy giặt", "Casper", "Máy giặt Casper WF-95VG5 9.5kg cửa ngang", 5400000, None,
     "Công suất lớn hơn, phù hợp gia đình đông người.",
     [("Mã sản phẩm", "WF-95VG5"), ("Khối lượng giặt", "9.5 kg"), ("Loại", "Cửa ngang"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Trung Quốc")], 24),
    # -- Sharp --
    ("Máy giặt", "Sharp", "Máy giặt Sharp ES-Y75HV-S 7.5kg cửa trên", 3500000, None,
     "Công nghệ Fuzzy Logic, có khóa trẻ em an toàn.",
     [("Mã sản phẩm", "ES-Y75HV-S"), ("Khối lượng giặt", "7.5 kg"), ("Loại", "Cửa trên"),
      ("Công nghệ", "Fuzzy Logic, khóa trẻ em"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Indonesia")], 24),
    ("Máy giặt", "Sharp", "Máy giặt Sharp ES-Y90HV-S 9kg cửa trên J-Tech Inverter", 4500000, None,
     "J-Tech Inverter, lồng giặt kép cánh cá heo giặt sạch nhẹ nhàng.",
     [("Mã sản phẩm", "ES-Y90HV-S"), ("Khối lượng giặt", "9 kg"), ("Loại", "Cửa trên, J-Tech Inverter"),
      ("Công nghệ", "Lồng giặt kép cánh cá heo"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Indonesia")], 24),
    ("Máy giặt", "Sharp", "Máy giặt Sharp ES-FK1054PV-S 10.5kg cửa ngang J-Tech Inverter", 7200000, 6300000,
     "J-Tech Inverter, giặt hơi nước diệt khuẩn.",
     [("Mã sản phẩm", "ES-FK1054PV-S"), ("Khối lượng giặt", "10.5 kg"), ("Loại", "Cửa ngang, J-Tech Inverter"),
      ("Công nghệ", "Giặt hơi nước"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Indonesia")], 24),
    # -- Funiki --
    ("Máy giặt", "Funiki", "Máy giặt Funiki HWM T685ABG 8.5kg cửa trên", 4520000, 3900000,
     "Lồng giặt 6 cánh, chức năng i-Clean tự vệ sinh lồng giặt.",
     [("Mã sản phẩm", "HWM T685ABG"), ("Khối lượng giặt", "8.5 kg"), ("Loại", "Cửa trên"),
      ("Công nghệ", "Lồng giặt 6 cánh, i-Clean"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Thái Lan")], 24),
    ("Máy giặt", "Funiki", "Máy giặt Funiki HWM F895ADG 9.5kg cửa ngang Inverter", 6900000, 5950000,
     "15 chương trình giặt, công nghệ Hygiene Care+ diệt khuẩn.",
     [("Mã sản phẩm", "HWM F895ADG"), ("Khối lượng giặt", "9.5 kg"), ("Loại", "Cửa ngang, Inverter"),
      ("Công nghệ", "Hygiene Care+, 15 chương trình giặt"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Thái Lan")], 24),
    ("Máy giặt", "Funiki", "Máy giặt Funiki HWM F8125ADG 12.5kg cửa ngang Inverter", 9920000, 8550000,
     "Công suất lớn 12.5kg, phù hợp gia đình đông người.",
     [("Mã sản phẩm", "HWM F8125ADG"), ("Khối lượng giặt", "12.5 kg"), ("Loại", "Cửa ngang, Inverter"),
      ("Công nghệ", "Hygiene Care+"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Thái Lan")], 24),
    # -- AQUA --
    ("Máy giặt", "AQUA", "Máy giặt AQUA AQW-S72CT.H2 7.2kg cửa trên", 4190000, 3750000,
     "Lồng inox chống gỉ, khóa trẻ em, giá tốt.",
     [("Mã sản phẩm", "AQW-S72CT.H2"), ("Khối lượng giặt", "7.2 kg"), ("Loại", "Cửa trên"),
      ("Công nghệ", "Lồng inox chống gỉ, khóa trẻ em"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Indonesia")], 24),
    ("Máy giặt", "AQUA", "Máy giặt AQUA AQD-A852J.BK 8.5kg cửa ngang Inverter", 6990000, 5900000,
     "Inverter tiết kiệm điện, giặt hơi nước, phun sương thông minh.",
     [("Mã sản phẩm", "AQD-A852J.BK"), ("Khối lượng giặt", "8.5 kg"), ("Loại", "Cửa ngang, Inverter"),
      ("Công nghệ", "Giặt hơi nước, phun sương thông minh"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Indonesia")], 24),
    ("Máy giặt", "AQUA", "Máy giặt AQUA AQD-A1102J.BK 11kg cửa ngang Inverter BLDC", 9650000, 8400000,
     "Inverter BLDC, 15 chương trình giặt, công nghệ Refresh.",
     [("Mã sản phẩm", "AQD-A1102J.BK"), ("Khối lượng giặt", "11 kg"), ("Loại", "Cửa ngang, Inverter BLDC"),
      ("Công nghệ", "Refresh, 15 chương trình giặt"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Indonesia")], 24),
    # -- Sumikura --
    ("Máy giặt", "Sumikura", "Máy giặt Sumikura SKWFID-78P1 7.8kg cửa ngang DD Inverter", 5200000, 4500000,
     "DD Inverter tiết kiệm điện, vận hành êm ái.",
     [("Mã sản phẩm", "SKWFID-78P1"), ("Khối lượng giặt", "7.8 kg"), ("Loại", "Cửa ngang, DD Inverter"),
      ("Công nghệ", "14 chương trình giặt thông minh"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Malaysia")], 24),
    ("Máy giặt", "Sumikura", "Máy giặt Sumikura SKWFID-95P1 9.5kg cửa ngang DD Inverter", 6100000, 5300000,
     "14 chương trình giặt thông minh, công suất lớn hơn.",
     [("Mã sản phẩm", "SKWFID-95P1"), ("Khối lượng giặt", "9.5 kg"), ("Loại", "Cửa ngang, DD Inverter"),
      ("Công nghệ", "14 chương trình giặt thông minh"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Malaysia")], 24),
    ("Máy giặt", "Sumikura", "Máy giặt Sumikura SKWFID-108P1 10.8kg cửa ngang DD Inverter", 7000000, 6100000,
     "Công suất lớn, phù hợp gia đình đông người.",
     [("Mã sản phẩm", "SKWFID-108P1"), ("Khối lượng giặt", "10.8 kg"), ("Loại", "Cửa ngang, DD Inverter"),
      ("Công nghệ", "14 chương trình giặt thông minh"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Malaysia")], 24),
    # -- Bình nóng lạnh --
    # -- Ariston --
    ("Bình nóng lạnh", "Ariston", "Bình nóng lạnh Ariston Vitaly 15 15L", 1700000, None,
     "Thanh đốt lõi đồng bền bỉ, cách nhiệt mật độ cao, giá tốt.",
     [("Mã sản phẩm", "Vitaly 15"), ("Dung tích", "15 lít"),
      ("Đặc điểm", "Thanh đốt lõi đồng, cách nhiệt mật độ cao, an toàn TSS"),
      ("Bảo hành", "7 năm"), ("Xuất xứ", "Việt Nam")], 84),
    ("Bình nóng lạnh", "Ariston", "Bình nóng lạnh Ariston SL3 20R 20L", 2800000, None,
     "Tráng men Titan chống bám cặn, chống giật ELCB an toàn.",
     [("Mã sản phẩm", "SL3 20R"), ("Dung tích", "20 lít"),
      ("Đặc điểm", "Lõi đồng, tráng men Titan, chống giật ELCB"),
      ("Bảo hành", "7 năm"), ("Xuất xứ", "Việt Nam")], 84),
    ("Bình nóng lạnh", "Ariston", "Bình nóng lạnh Ariston SL3 30 TOP WIFI VN 30L", 4730000, None,
     "Điều khiển từ xa qua WiFi, đạt chuẩn 5 sao tiết kiệm điện.",
     [("Mã sản phẩm", "SL3 30 TOP WIFI VN"), ("Dung tích", "30 lít"),
      ("Đặc điểm", "Điều khiển WiFi, công nghệ ion bạc, màn hình cảm ứng, 5 sao tiết kiệm điện"),
      ("Bảo hành", "10 năm"), ("Xuất xứ", "Việt Nam")], 120),
    # -- Rossi --
    ("Bình nóng lạnh", "Rossi", "Bình nóng lạnh Rossi Bello S+ BLS15SQ 15L", 1290000, None,
     "Tráng men kim cương, chống giật ELCB, giá rẻ.",
     [("Mã sản phẩm", "BLS15SQ"), ("Dung tích", "15 lít"),
      ("Đặc điểm", "Tráng men kim cương, chống giật ELCB"),
      ("Bảo hành", "7 năm"), ("Xuất xứ", "Việt Nam")], 84),
    ("Bình nóng lạnh", "Rossi", "Bình nóng lạnh Rossi Smart RST20SQ 20L", 1470000, None,
     "Dòng Smart, tráng men kim cương, công suất vừa cho gia đình nhỏ.",
     [("Mã sản phẩm", "RST20SQ"), ("Dung tích", "20 lít"),
      ("Đặc điểm", "Dòng Smart, tráng men kim cương"),
      ("Bảo hành", "7 năm"), ("Xuất xứ", "Việt Nam")], 84),
    ("Bình nóng lạnh", "Rossi", "Bình nóng lạnh Rossi RAM30SL 30L bình ngang", 1910000, None,
     "Kiểu bình ngang, tráng men kim cương, phù hợp lắp trên trần thấp.",
     [("Mã sản phẩm", "RAM30SL"), ("Dung tích", "30 lít"),
      ("Đặc điểm", "Kiểu bình ngang, tráng men kim cương"),
      ("Bảo hành", "7 năm"), ("Xuất xứ", "Việt Nam")], 84),
    # -- Ferroli --
    ("Bình nóng lạnh", "Ferroli", "Bình nóng lạnh Ferroli QQ Evo 15 ME 15L", 1920000, None,
     "Tráng men Titan, dây điện ELCB chống giật.",
     [("Mã sản phẩm", "QQ Evo 15 ME"), ("Dung tích", "15 lít"),
      ("Đặc điểm", "Tráng men Titan, dây ELCB chống giật"),
      ("Bảo hành", "8 năm"), ("Xuất xứ", "Việt Nam")], 96),
    ("Bình nóng lạnh", "Ferroli", "Bình nóng lạnh Ferroli QQ Evo 30 AE 30L", 2450000, None,
     "Chống bám cặn, rơ le chống cháy khô bảo vệ thanh đốt.",
     [("Mã sản phẩm", "QQ Evo 30 AE"), ("Dung tích", "30 lít"),
      ("Đặc điểm", "Chống bám cặn, rơ le chống cháy khô"),
      ("Bảo hành", "8 năm"), ("Xuất xứ", "Việt Nam")], 96),
    ("Bình nóng lạnh", "Ferroli", "Bình nóng lạnh Ferroli AQUA 80SEH 80L bình ngang", 4140000, None,
     "Dung tích lớn 80L, kiểu bình ngang, phù hợp gia đình đông người.",
     [("Mã sản phẩm", "AQUA 80SEH"), ("Dung tích", "80 lít"),
      ("Đặc điểm", "Bình ngang, thanh đốt Titan, dung tích lớn"),
      ("Bảo hành", "8 năm"), ("Xuất xứ", "Việt Nam")], 96),
    # -- Panasonic --
    ("Bình nóng lạnh", "Panasonic", "Bình nóng lạnh Panasonic DH-15HBM 15L", 2820000, None,
     "Lõi inox bền bỉ, tiết kiệm điện, hàng nhập khẩu Malaysia.",
     [("Mã sản phẩm", "DH-15HBM"), ("Dung tích", "15 lít"),
      ("Đặc điểm", "Lõi inox, tiết kiệm điện"),
      ("Bảo hành", "12 tháng máy / 7 năm bình"), ("Xuất xứ", "Malaysia")], 12),
    ("Bình nóng lạnh", "Panasonic", "Bình nóng lạnh Panasonic DH-20HBM 20L", 2940000, None,
     "Công suất lớn hơn, lõi inox tiết kiệm điện.",
     [("Mã sản phẩm", "DH-20HBM"), ("Dung tích", "20 lít"),
      ("Đặc điểm", "Lõi inox, tiết kiệm điện"),
      ("Bảo hành", "12 tháng máy / 7 năm bình"), ("Xuất xứ", "Malaysia")], 12),
    ("Bình nóng lạnh", "Panasonic", "Bình nóng lạnh Panasonic DH-30HBM 30L", 3250000, None,
     "Dung tích lớn, lõi inox, phù hợp gia đình đông người.",
     [("Mã sản phẩm", "DH-30HBM"), ("Dung tích", "30 lít"),
      ("Đặc điểm", "Lõi inox, tiết kiệm điện"),
      ("Bảo hành", "12 tháng máy / 7 năm bình"), ("Xuất xứ", "Malaysia")], 12),
    # -- Funiki --
    ("Bình nóng lạnh", "Funiki", "Bình nóng lạnh Funiki ECO 15 15L", 1580000, None,
     "Lõi tráng Titanium, chống giật ELCB, công nghệ Nano bạc kháng khuẩn.",
     [("Mã sản phẩm", "ECO 15"), ("Dung tích", "15 lít"),
      ("Đặc điểm", "Lõi tráng Titanium, chống giật ELCB, Nano bạc kháng khuẩn"),
      ("Bảo hành", "2 năm máy / 7 năm bình"), ("Xuất xứ", "Việt Nam")], 24),
    ("Bình nóng lạnh", "Funiki", "Bình nóng lạnh Funiki ECO 20 20L", 1730000, None,
     "Công suất lớn hơn, lõi tráng Titanium chống ăn mòn.",
     [("Mã sản phẩm", "ECO 20"), ("Dung tích", "20 lít"),
      ("Đặc điểm", "Lõi tráng Titanium, chống giật ELCB"),
      ("Bảo hành", "2 năm máy / 7 năm bình"), ("Xuất xứ", "Việt Nam")], 24),
    ("Bình nóng lạnh", "Funiki", "Bình nóng lạnh Funiki VI50L 50L", 2550000, None,
     "Kiểu bình tròn dung tích lớn 50L, phù hợp gia đình đông người.",
     [("Mã sản phẩm", "VI50L"), ("Dung tích", "50 lít"),
      ("Đặc điểm", "Kiểu bình tròn, dung tích lớn"),
      ("Bảo hành", "2 năm máy / 7 năm bình"), ("Xuất xứ", "Việt Nam")], 24),
    # -- Midea --
    ("Bình nóng lạnh", "Midea", "Bình nóng lạnh Midea D15-25VA 15L", 1650000, None,
     "Thiết kế thanh lịch, công nghệ lọc nước kháng khuẩn.",
     [("Mã sản phẩm", "D15-25VA"), ("Dung tích", "15 lít"),
      ("Đặc điểm", "Thiết kế thanh lịch, nước kháng khuẩn"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Việt Nam")], 24),
    ("Bình nóng lạnh", "Midea", "Bình nóng lạnh Midea D30-25VA1 30L", 1950000, None,
     "Màn hình LED hiển thị nhiệt độ, dung tích lớn hơn.",
     [("Mã sản phẩm", "D30-25VA1"), ("Dung tích", "30 lít"),
      ("Đặc điểm", "Màn hình LED hiển thị nhiệt độ, kháng khuẩn"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Việt Nam")], 24),
    ("Bình nóng lạnh", "Midea", "Bình nóng lạnh Midea D30-25EVA 30L điều khiển từ xa", 2650000, None,
     "Điều khiển từ xa, lõi tráng Titan, hẹn giờ làm nóng.",
     [("Mã sản phẩm", "D30-25EVA"), ("Dung tích", "30 lít"),
      ("Đặc điểm", "Điều khiển từ xa, lõi tráng Titan, hẹn giờ làm nóng"),
      ("Bảo hành", "7 năm"), ("Xuất xứ", "Việt Nam")], 84),
    # -- Casper --
    ("Bình nóng lạnh", "Casper", "Bình nóng lạnh Casper EH-20TH11 20L", 1750000, None,
     "Thanh đốt lõi đồng, chống giật ELCB kép, hàng nhập khẩu Thái Lan.",
     [("Mã sản phẩm", "EH-20TH11"), ("Dung tích", "20 lít"),
      ("Đặc điểm", "Thanh đốt lõi đồng, chống giật ELCB kép"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Thái Lan")], 24),
    ("Bình nóng lạnh", "Casper", "Bình nóng lạnh Casper SH-20TH11 20L", 1950000, None,
     "Tráng men kim cương, cách nhiệt mật độ cao.",
     [("Mã sản phẩm", "SH-20TH11"), ("Dung tích", "20 lít"),
      ("Đặc điểm", "Tráng men kim cương, cách nhiệt mật độ cao"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Thái Lan")], 24),
    ("Bình nóng lạnh", "Casper", "Bình nóng lạnh Casper SH-30TH11 30L", 2250000, None,
     "Dung tích lớn hơn, tráng men kim cương, chống giật ELCB kép.",
     [("Mã sản phẩm", "SH-30TH11"), ("Dung tích", "30 lít"),
      ("Đặc điểm", "Tráng men kim cương, chống giật ELCB kép"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Thái Lan")], 24),
    # -- Kangaroo --
    ("Bình nóng lạnh", "Kangaroo", "Bình nóng lạnh Kangaroo KG68A2 22L", 1850000, None,
     "Kiểu bình chữ nhật, màn hình hiển thị nhiệt độ, hàng Việt Nam.",
     [("Mã sản phẩm", "KG68A2"), ("Dung tích", "22 lít"),
      ("Đặc điểm", "Kiểu bình chữ nhật, màn hình hiển thị nhiệt độ"),
      ("Bảo hành", "24 tháng máy / 10 năm bình"), ("Xuất xứ", "Việt Nam")], 24),
    ("Bình nóng lạnh", "Kangaroo", "Bình nóng lạnh Kangaroo KG69A2 22L", 1900000, None,
     "Cùng dung tích, thiết kế biến thể, màn hình hiển thị nhiệt độ.",
     [("Mã sản phẩm", "KG69A2"), ("Dung tích", "22 lít"),
      ("Đặc điểm", "Kiểu bình chữ nhật, màn hình hiển thị nhiệt độ"),
      ("Bảo hành", "24 tháng máy / 10 năm bình"), ("Xuất xứ", "Việt Nam")], 24),
    ("Bình nóng lạnh", "Kangaroo", "Bình nóng lạnh Kangaroo KG68A3 30L", 2050000, None,
     "Dung tích lớn hơn, phù hợp gia đình đông người.",
     [("Mã sản phẩm", "KG68A3"), ("Dung tích", "30 lít"),
      ("Đặc điểm", "Kiểu bình chữ nhật, màn hình hiển thị nhiệt độ"),
      ("Bảo hành", "24 tháng máy / 10 năm bình"), ("Xuất xứ", "Việt Nam")], 24),
    # -- Atlantic --
    ("Bình nóng lạnh", "Atlantic", "Bình nóng lạnh Atlantic SWH15AM 15L", 2100000, None,
     "Rơ le chống cháy khô điện trở, hàng nhập khẩu Thái Lan, thương hiệu Pháp.",
     [("Mã sản phẩm", "SWH15AM"), ("Dung tích", "15 lít"),
      ("Đặc điểm", "Rơ le chống cháy khô điện trở"),
      ("Bảo hành", "10 năm"), ("Xuất xứ", "Thái Lan")], 120),
    ("Bình nóng lạnh", "Atlantic", "Bình nóng lạnh Atlantic SWH15AM/AC 15L dòng ACCESS", 2400000, None,
     "Dòng ACCESS, lòng bình tráng men kim cương.",
     [("Mã sản phẩm", "SWH15AM/AC"), ("Dung tích", "15 lít"),
      ("Đặc điểm", "Dòng ACCESS, lòng bình tráng men kim cương"),
      ("Bảo hành", "10 năm"), ("Xuất xứ", "Thái Lan")], 120),
    ("Bình nóng lạnh", "Atlantic", "Bình nóng lạnh Atlantic SWH30AM/AC 30L dòng ACCESS", 2900000, None,
     "Dung tích lớn hơn, tráng men kim cương, tiết kiệm điện.",
     [("Mã sản phẩm", "SWH30AM/AC"), ("Dung tích", "30 lít"),
      ("Đặc điểm", "Dòng ACCESS, tráng men kim cương, tiết kiệm điện"),
      ("Bảo hành", "10 năm"), ("Xuất xứ", "Thái Lan")], 120),
    # -- Sơn Hà --
    ("Bình nóng lạnh", "Sơn Hà", "Bình nóng lạnh Sơn Hà SWAT SW15VO 15L", 1370000, None,
     "Thanh đốt gia nhiệt kép, làm nóng nhanh, hàng Việt Nam.",
     [("Mã sản phẩm", "SWAT SW15VO"), ("Dung tích", "15 lít"),
      ("Đặc điểm", "Thanh đốt gia nhiệt kép, làm nóng nhanh"),
      ("Bảo hành", "12 tháng máy / 7 năm bình"), ("Xuất xứ", "Việt Nam")], 12),
    ("Bình nóng lạnh", "Sơn Hà", "Bình nóng lạnh Sơn Hà SWAT SW20VO 20L", 1460000, None,
     "Công suất lớn hơn, thanh đốt gia nhiệt kép bền bỉ.",
     [("Mã sản phẩm", "SWAT SW20VO"), ("Dung tích", "20 lít"),
      ("Đặc điểm", "Thanh đốt gia nhiệt kép, làm nóng nhanh"),
      ("Bảo hành", "12 tháng máy / 7 năm bình"), ("Xuất xứ", "Việt Nam")], 12),
    ("Bình nóng lạnh", "Sơn Hà", "Bình nóng lạnh Sơn Hà SWAT SW30VO 30L", 1580000, None,
     "Dung tích lớn, giữ nhiệt tiết kiệm điện.",
     [("Mã sản phẩm", "SWAT SW30VO"), ("Dung tích", "30 lít"),
      ("Đặc điểm", "Giữ nhiệt tiết kiệm điện"),
      ("Bảo hành", "12 tháng máy / 7 năm bình"), ("Xuất xứ", "Việt Nam")], 12),
    # -- Tủ lạnh --
    # -- Funiki --
    ("Tủ lạnh", "Funiki", "Tủ lạnh Funiki FR-51DSU 50L mini", 2330000, None,
     "Tủ lạnh mini 1 cánh, nhỏ gọn, phù hợp phòng trọ, ký túc xá.",
     [("Mã sản phẩm", "FR-51DSU"), ("Dung tích", "50 lít"), ("Loại", "1 cánh"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Việt Nam")], 12),
    ("Tủ lạnh", "Funiki", "Tủ lạnh Funiki FR-125CI.1 120L 2 cánh", 3500000, None,
     "Dung tích vừa, 2 cánh, phù hợp gia đình nhỏ.",
     [("Mã sản phẩm", "FR-125CI.1"), ("Dung tích", "120 lít"), ("Loại", "2 cánh"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Việt Nam")], 12),
    ("Tủ lạnh", "Funiki", "Tủ lạnh Funiki HR T6209TDG 210L 2 cánh", 4350000, None,
     "Dung tích lớn hơn, 2 cánh, ngăn đông riêng biệt.",
     [("Mã sản phẩm", "HR T6209TDG"), ("Dung tích", "210 lít"), ("Loại", "2 cánh"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Việt Nam")], 12),
    ("Tủ lạnh", "Funiki", "Tủ lạnh Funiki FRI-166ISU 160L 2 cánh Inverter", 5200000, 4500000,
     "Công nghệ Inverter tiết kiệm điện, 2 cánh.",
     [("Mã sản phẩm", "FRI-166ISU"), ("Dung tích", "160 lít"), ("Loại", "2 cánh, Inverter"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Việt Nam")], 12),
    # -- LG --
    ("Tủ lạnh", "LG", "Tủ lạnh LG LOB16BGM 195L 1 cánh", 6950000, None,
     "1 cánh, dung tích 195L, thiết kế sang trọng.",
     [("Mã sản phẩm", "LOB16BGM"), ("Dung tích", "195 lít"), ("Loại", "1 cánh"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Việt Nam")], 24),
    ("Tủ lạnh", "LG", "Tủ lạnh LG LTB26BLM 266L 2 cánh", 5600000, None,
     "2 cánh, dung tích 266L, phù hợp gia đình vừa.",
     [("Mã sản phẩm", "LTB26BLM"), ("Dung tích", "266 lít"), ("Loại", "2 cánh"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Việt Nam")], 24),
    ("Tủ lạnh", "LG", "Tủ lạnh LG LTB33BLG 335L 2 cánh", 8900000, None,
     "Dung tích lớn hơn, 2 cánh, phù hợp gia đình đông người.",
     [("Mã sản phẩm", "LTB33BLG"), ("Dung tích", "335 lít"), ("Loại", "2 cánh"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Việt Nam")], 24),
    ("Tủ lạnh", "LG", "Tủ lạnh LG GR-B256JDS 519L Side by Side", 11100000, None,
     "Side by side 519L, thiết kế 2 cánh mở song song sang trọng.",
     [("Mã sản phẩm", "GR-B256JDS"), ("Dung tích", "519 lít"), ("Loại", "Side by Side"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Việt Nam")], 24),
    # -- Casper --
    ("Tủ lạnh", "Casper", "Tủ lạnh Casper RO-45PB 45L mini", 2450000, None,
     "Tủ lạnh mini 45L, 1 cánh, nhỏ gọn giá rẻ.",
     [("Mã sản phẩm", "RO-45PB"), ("Dung tích", "45 lít"), ("Loại", "1 cánh"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Trung Quốc")], 12),
    ("Tủ lạnh", "Casper", "Tủ lạnh Casper RT-230PB 218L 2 cánh", 4800000, None,
     "2 cánh, dung tích 218L, phù hợp gia đình nhỏ.",
     [("Mã sản phẩm", "RT-230PB"), ("Dung tích", "218 lít"), ("Loại", "2 cánh"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Trung Quốc")], 12),
    ("Tủ lạnh", "Casper", "Tủ lạnh Casper RT-258VG 240L 2 cánh", 5500000, None,
     "Dung tích lớn hơn, 2 cánh, phù hợp gia đình vừa.",
     [("Mã sản phẩm", "RT-258VG"), ("Dung tích", "240 lít"), ("Loại", "2 cánh"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Trung Quốc")], 12),
    ("Tủ lạnh", "Casper", "Tủ lạnh Casper RT-368VG 337L 2 cánh", 9500000, None,
     "Dung tích lớn, 2 cánh, phù hợp gia đình đông người.",
     [("Mã sản phẩm", "RT-368VG"), ("Dung tích", "337 lít"), ("Loại", "2 cánh"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Trung Quốc")], 12),
    # -- Electrolux --
    ("Tủ lạnh", "Electrolux", "Tủ lạnh Electrolux ETB2100MG 210L 2 cánh Inverter", 6500000, None,
     "Công nghệ Inverter NutriFresh, ngăn rau củ MarketFresh.",
     [("Mã sản phẩm", "ETB2100MG"), ("Dung tích", "210 lít"), ("Loại", "2 cánh, Inverter"),
      ("Công nghệ", "NutriFresh Inverter, MarketFresh"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Việt Nam")], 24),
    ("Tủ lạnh", "Electrolux", "Tủ lạnh Electrolux ETB3200PE-RVN 320L 2 cánh", 8500000, None,
     "Dung tích lớn hơn, 2 cánh, phù hợp gia đình vừa.",
     [("Mã sản phẩm", "ETB3200PE-RVN"), ("Dung tích", "320 lít"), ("Loại", "2 cánh"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Việt Nam")], 24),
    ("Tủ lạnh", "Electrolux", "Tủ lạnh Electrolux ETM4407SD-RVN 440L 3 cánh", 13500000, None,
     "3 cánh, dung tích lớn, ngăn đựng đa dạng cho gia đình đông người.",
     [("Mã sản phẩm", "ETM4407SD-RVN"), ("Dung tích", "440 lít"), ("Loại", "3 cánh"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Việt Nam")], 24),
    # -- Panasonic --
    ("Tủ lạnh", "Panasonic", "Tủ lạnh Panasonic NR-BS62GWVN 532L Side by Side", 15500000, None,
     "Side by Side 532L, dung tích lớn, thiết kế sang trọng.",
     [("Mã sản phẩm", "NR-BS62GWVN"), ("Dung tích", "532 lít"), ("Loại", "Side by Side"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Việt Nam")], 12),
    # -- Midea --
    ("Tủ lạnh", "Midea", "Tủ lạnh Midea HS-65SN 58L mini", 2100000, None,
     "Tủ lạnh mini 58L, 1 cánh, dễ dàng điều chỉnh nhiệt độ.",
     [("Mã sản phẩm", "HS-65SN"), ("Dung tích", "58 lít"), ("Loại", "1 cánh"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Việt Nam")], 24),
    ("Tủ lạnh", "Midea", "Tủ lạnh Midea MRD-160FWG 130L 2 cánh", 4200000, None,
     "2 cánh, dung tích 130L, công nghệ không đóng tuyết.",
     [("Mã sản phẩm", "MRD-160FWG"), ("Dung tích", "130 lít"), ("Loại", "2 cánh"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Việt Nam")], 24),
    ("Tủ lạnh", "Midea", "Tủ lạnh Midea MRD-255FWES 207L 2 cánh", 5900000, None,
     "Dung tích lớn hơn, đèn LED, có ngăn rau củ riêng.",
     [("Mã sản phẩm", "MRD-255FWES"), ("Dung tích", "207 lít"), ("Loại", "2 cánh"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Việt Nam")], 24),
    ("Tủ lạnh", "Midea", "Tủ lạnh Midea MRD-333FWES 268L 2 cánh", 6800000, None,
     "Dung tích lớn, điều chỉnh nhiệt độ điện tử, kệ kính cường lực.",
     [("Mã sản phẩm", "MRD-333FWES"), ("Dung tích", "268 lít"), ("Loại", "2 cánh"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Việt Nam")], 24),
    # -- Gia dụng --
    # -- Quạt trần Panasonic --
    ("Gia dụng", "Panasonic", "Quạt trần Panasonic F-60MZ2 3 cánh", 1190000, None,
     "3 cánh, 5 mức tốc độ gió, giá tốt cho phòng khách.",
     [("Mã sản phẩm", "F-60MZ2"), ("Loại", "Quạt trần, 3 cánh"),
      ("Thông số", "Đường kính 150cm, 5 mức tốc độ, 66W"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Việt Nam")], 12),
    ("Gia dụng", "Panasonic", "Quạt trần Panasonic F-56MZG-GO 4 cánh", 2300000, None,
     "4 cánh, thiết kế hiện đại, vận hành êm ái.",
     [("Mã sản phẩm", "F-56MZG-GO"), ("Loại", "Quạt trần, 4 cánh"),
      ("Thông số", "Đường kính 140cm, 3 mức tốc độ, 64W"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Việt Nam")], 12),
    ("Gia dụng", "Panasonic", "Quạt trần Panasonic F-60UFN 5 cánh Motor DC đèn LED", 8320000, None,
     "Motor DC tiết kiệm điện, tích hợp đèn LED chiếu sáng.",
     [("Mã sản phẩm", "F-60UFN"), ("Loại", "Quạt trần, 5 cánh, Motor DC, đèn LED"),
      ("Thông số", "59W (37W motor + 22W đèn LED)"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Việt Nam")], 12),
    # -- Quạt cây Panasonic --
    ("Gia dụng", "Panasonic", "Quạt cây Panasonic F-307KHB 30cm", 1980000, None,
     "Nhỏ gọn, 3 mức tốc độ, giá tốt.",
     [("Mã sản phẩm", "F-307KHB"), ("Loại", "Quạt cây"),
      ("Thông số", "Đường kính 30cm, 3 mức tốc độ, 37W"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Việt Nam")], 12),
    ("Gia dụng", "Panasonic", "Quạt cây Panasonic F-409KB 40cm điều khiển từ xa", 2750000, None,
     "Điều khiển từ xa tiện lợi, sải cánh lớn hơn.",
     [("Mã sản phẩm", "F-409KB"), ("Loại", "Quạt cây, điều khiển từ xa"),
      ("Thông số", "Đường kính 40cm, 3 mức tốc độ, 51W"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Việt Nam")], 12),
    ("Gia dụng", "Panasonic", "Quạt cây Panasonic F-407WGO 40cm đèn ngủ", 2300000, None,
     "Tích hợp đèn ngủ, phù hợp phòng ngủ.",
     [("Mã sản phẩm", "F-407WGO"), ("Loại", "Quạt cây, đèn ngủ tích hợp"),
      ("Thông số", "Đường kính 40cm, 53.5W"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Việt Nam")], 12),
    # -- Nồi cơm điện Midea --
    ("Gia dụng", "Midea", "Nồi cơm điện Midea MR-GM10SA 1L", 275000, None,
     "Dung tích nhỏ, giá rẻ, phù hợp 1-2 người.",
     [("Mã sản phẩm", "MR-GM10SA"), ("Dung tích", "1 lít"),
      ("Đặc điểm", "Lòng nồi hợp kim nhôm"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Trung Quốc")], 12),
    ("Gia dụng", "Midea", "Nồi cơm điện Midea MR-CM18SQ 1.8L", 375000, None,
     "Dung tích 1.8L, lòng nồi phủ chống dính siêu bền.",
     [("Mã sản phẩm", "MR-CM18SQ"), ("Dung tích", "1.8 lít"),
      ("Đặc điểm", "Phủ lớp chống dính siêu bền, tự động ngắt"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Trung Quốc")], 12),
    ("Gia dụng", "Midea", "Nồi cơm điện Midea MB-FC5019 1.8L lòng nồi hoàng kim", 1100000, None,
     "Lòng nồi hoàng kim đáy tổ ong, chống dính dày 2.0mm cao cấp.",
     [("Mã sản phẩm", "MB-FC5019"), ("Dung tích", "1.8 lít"),
      ("Đặc điểm", "Lòng nồi hoàng kim đáy tổ ong, chống dính dày 2.0mm"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Trung Quốc")], 12),
    # -- Bếp Hòa Phát --
    ("Gia dụng", "Hòa Phát", "Bếp hồng ngoại Hòa Phát HPC F11A2", 1090000, None,
     "Bếp hồng ngoại đơn, 5 chế độ nấu thông minh.",
     [("Mã sản phẩm", "HPC F11A2"), ("Loại", "Bếp hồng ngoại đơn"),
      ("Đặc điểm", "5 chế độ nấu thông minh, 8 mức điều chỉnh công suất"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Thái Lan")], 24),
    ("Gia dụng", "Hòa Phát", "Bếp hồng ngoại Hòa Phát HPC F12A2", 1270000, None,
     "Bếp hồng ngoại đơn, 8 mức điều chỉnh công suất.",
     [("Mã sản phẩm", "HPC F12A2"), ("Loại", "Bếp hồng ngoại đơn"),
      ("Đặc điểm", "4 chế độ nấu thông minh, 8 mức điều chỉnh công suất"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Thái Lan")], 24),
    ("Gia dụng", "Hòa Phát", "Bếp từ Hòa Phát HPC D11A2", 1350000, None,
     "Bếp từ đơn, mặt kính cường lực, màn hình LED.",
     [("Mã sản phẩm", "HPC D11A2"), ("Loại", "Bếp từ đơn"),
      ("Đặc điểm", "Mặt kính cường lực, màn hình LED"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Thái Lan")], 24),
    ("Gia dụng", "Hòa Phát", "Bếp từ Hòa Phát HPC D12A2", 1400000, None,
     "Bếp từ đơn, làm nóng nhanh, tiết kiệm điện hơn bếp gas.",
     [("Mã sản phẩm", "HPC D12A2"), ("Loại", "Bếp từ đơn"),
      ("Đặc điểm", "Mặt kính cường lực, màn hình LED"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Thái Lan")], 24),
    ("Gia dụng", "Hòa Phát", "Bếp từ Hòa Phát HPC D13A2", 1300000, None,
     "Bếp từ đơn, 8 chức năng nấu thông minh, giá tốt.",
     [("Mã sản phẩm", "HPC D13A2"), ("Loại", "Bếp từ đơn"),
      ("Đặc điểm", "8 chức năng nấu thông minh"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Thái Lan")], 24),
    # -- Máy lọc không khí --
    ("Gia dụng", "Daikin", "Máy lọc không khí Daikin MC30VVM-A", 3220000, None,
     "Cảm biến PM2.5, lọc 3 lớp, phù hợp không gian nhỏ.",
     [("Mã sản phẩm", "MC30VVM-A"), ("Loại", "Máy lọc không khí"),
      ("Đặc điểm", "Cảm biến PM2.5, lọc 3 lớp"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Thái Lan")], 12),
    ("Gia dụng", "Sharp", "Máy lọc không khí Sharp FP-J30E-A", 2090000, None,
     "Công nghệ ion Plasmacluster, lọc HEPA, chế độ HAZE.",
     [("Mã sản phẩm", "FP-J30E-A/B/P"), ("Loại", "Máy lọc không khí"),
      ("Đặc điểm", "Ion Plasmacluster, lọc HEPA, chế độ HAZE"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Thái Lan")], 12),
    ("Gia dụng", "LG", "Máy lọc không khí LG AP151MBA1 mini", 3550000, None,
     "Thiết kế mini, motor Dual Inverter, cảm biến PM1.0.",
     [("Mã sản phẩm", "AP151MBA1"), ("Loại", "Máy lọc không khí mini"),
      ("Đặc điểm", "Motor Dual Inverter, cảm biến PM1.0"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Hàn Quốc")], 12),
    ("Gia dụng", "Samsung", "Máy lọc không khí Samsung AX40R3020WU 40m²", 4500000, None,
     "Lọc 99.97% bụi mịn cho diện tích 40m², điều khiển qua app.",
     [("Mã sản phẩm", "AX40R3020WU/SV"), ("Loại", "Máy lọc không khí"),
      ("Đặc điểm", "Lọc 99.97% cho 40m², điều khiển qua app SmartThings"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Hàn Quốc")], 12),
    ("Gia dụng", "Casper", "Máy lọc không khí Casper AP-250MAH 30m²", 1500000, None,
     "Lọc HEPA, màn hình LED hiển thị, giá tốt cho phòng 30m².",
     [("Mã sản phẩm", "AP-250MAH"), ("Loại", "Máy lọc không khí"),
      ("Đặc điểm", "Lọc HEPA + lọc thô, màn hình LED, phù hợp 30m²"),
      ("Bảo hành", "12 tháng"), ("Xuất xứ", "Trung Quốc")], 12),
    # -- Tivi --
    # -- Casper --
    ("Tivi", "Casper", "Tivi Casper 32HN5000 32 inch HD", 2590000, None,
     "32 inch, độ phân giải HD, giá tốt cho phòng ngủ.",
     [("Mã sản phẩm", "32HN5000"), ("Kích thước", "32 inch"), ("Độ phân giải", "HD"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Thái Lan")], 24),
    ("Tivi", "Casper", "Tivi Casper 32HG5000 32 inch Android 2K HDR", 3290000, None,
     "32 inch, Android 9.0, 2K HDR, tích hợp Google Assistant.",
     [("Mã sản phẩm", "32HG5000"), ("Kích thước", "32 inch"), ("Độ phân giải", "2K HDR"),
      ("Hệ điều hành", "Android 9.0, Google Assistant"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Thái Lan")], 24),
    ("Tivi", "Casper", "Tivi Casper 43FG5000 43 inch Android 2K HDR", 4490000, None,
     "43 inch, Android 9.0, bộ xử lý hình ảnh 2K HDR.",
     [("Mã sản phẩm", "43FG5000"), ("Kích thước", "43 inch"), ("Độ phân giải", "2K HDR"),
      ("Hệ điều hành", "Android 9.0"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Thái Lan")], 24),
    ("Tivi", "Casper", "Tivi Casper 50UG6000 50 inch Android 4K HDR", 6490000, None,
     "50 inch, Android 9.0, 4K HDR, phù hợp phòng khách rộng.",
     [("Mã sản phẩm", "50UG6000"), ("Kích thước", "50 inch"), ("Độ phân giải", "4K HDR"),
      ("Hệ điều hành", "Android 9.0, Google Assistant"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Thái Lan")], 24),
    ("Tivi", "Casper", "Tivi Casper 55UG6000 55 inch Android 4K HDR", 7490000, None,
     "55 inch, Android 9.0, 4K HDR, tích hợp Google Assistant.",
     [("Mã sản phẩm", "55UG6000"), ("Kích thước", "55 inch"), ("Độ phân giải", "4K HDR"),
      ("Hệ điều hành", "Android 9.0, Google Assistant"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Thái Lan")], 24),
    ("Tivi", "Casper", "Tivi Casper 65UG6000 65 inch Android 4K HDR", 10990000, None,
     "65 inch, Android 9.0, 4K HDR, màn hình lớn cho phòng khách rộng.",
     [("Mã sản phẩm", "65UG6000"), ("Kích thước", "65 inch"), ("Độ phân giải", "4K HDR"),
      ("Hệ điều hành", "Android 9.0, Google Assistant"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Thái Lan")], 24),
    # -- Sony --
    ("Tivi", "Sony", "Tivi Sony KDL-32R300C 32 inch LED HD", 4990000, None,
     "32 inch LED, độ phân giải HD, thương hiệu Nhật Bản.",
     [("Mã sản phẩm", "KDL-32R300C"), ("Kích thước", "32 inch"), ("Loại", "LED"),
      ("Độ phân giải", "HD"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Malaysia")], 24),
    ("Tivi", "Sony", "Tivi Sony KD-55A1 55 inch OLED 4K HDR", 24990000, None,
     "55 inch OLED, 4K HDR, màu đen sâu và độ tương phản vượt trội.",
     [("Mã sản phẩm", "KD-55A1"), ("Kích thước", "55 inch"), ("Loại", "OLED"),
      ("Độ phân giải", "4K HDR"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Malaysia")], 24),
    ("Tivi", "Sony", "Tivi Sony KD-65A1 65 inch OLED 4K HDR", 34990000, None,
     "65 inch OLED, 4K HDR, màn hình lớn cao cấp.",
     [("Mã sản phẩm", "KD-65A1"), ("Kích thước", "65 inch"), ("Loại", "OLED"),
      ("Độ phân giải", "4K HDR"),
      ("Bảo hành", "24 tháng"), ("Xuất xứ", "Malaysia")], 24),
]

SEED_ARTICLES = [
    ("Cách chọn điều hòa phù hợp với diện tích phòng",
     "Chọn sai công suất BTU khiến điều hòa vừa tốn điện vừa làm lạnh không đủ. Xuân Son gợi ý công thức ước lượng nhanh theo diện tích phòng.",
     "Một trong những sai lầm phổ biến nhất khi mua điều hòa là chọn công suất không phù hợp với diện tích phòng. "
     "Phòng dưới 15m² thường hợp với máy 9.000 BTU, phòng 15-20m² nên chọn 12.000 BTU, còn phòng khách rộng trên "
     "25m² cần từ 18.000 BTU trở lên. Ngoài diện tích, hướng nắng, số người thường xuyên có mặt và độ cao trần nhà "
     "cũng ảnh hưởng đến công suất cần thiết. Nếu không chắc chắn, hãy gọi hotline để được tư vấn theo đúng không "
     "gian thực tế của gia đình."),
    ("Máy giặt cửa ngang hay cửa trên: nên chọn loại nào?",
     "Mỗi loại máy giặt có ưu nhược điểm riêng — bài viết giúp bạn chọn đúng loại phù hợp với không gian và thói quen sử dụng.",
     "Máy giặt cửa ngang thường giặt sạch hơn, tiết kiệm nước và điện, nhưng giá cao hơn và thời gian giặt lâu hơn. "
     "Máy giặt cửa trên có giá dễ tiếp cận, thao tác thêm đồ giữa chừng dễ dàng, phù hợp với không gian đặt máy hạn chế "
     "chiều cao. Nếu gia đình giặt đồ thường xuyên và muốn tiết kiệm chi phí điện nước lâu dài, cửa ngang Inverter là "
     "lựa chọn đáng cân nhắc."),
    ("Mẹo tiết kiệm điện khi dùng điều hòa mùa hè",
     "Vài thay đổi nhỏ trong thói quen sử dụng có thể giúp giảm đáng kể hóa đơn tiền điện mùa nắng nóng.",
     "Đặt nhiệt độ ở mức 26-27°C thay vì để quá lạnh, kết hợp quạt trần để không khí lưu thông đều hơn. Vệ sinh lưới "
     "lọc bụi định kỳ 1-2 tháng/lần giúp máy làm lạnh hiệu quả hơn và giảm tiêu thụ điện. Đóng kín cửa phòng, hạn chế "
     "ánh nắng trực tiếp chiếu vào cũng giúp điều hòa đỡ phải hoạt động hết công suất."),
    ("Bảo dưỡng bình nóng lạnh đúng cách để dùng bền lâu",
     "Bình nóng lạnh dùng lâu năm nếu không bảo dưỡng dễ đóng cặn, giảm hiệu suất và tiềm ẩn rủi ro an toàn điện.",
     "Nên súc rửa bình nóng lạnh định kỳ 6-12 tháng/lần để loại bỏ cặn khoáng, đặc biệt ở khu vực nước cứng. Kiểm tra "
     "thanh magie (anode) và thay mới khi bị mòn để chống ăn mòn bình. Luôn kiểm tra thiết bị chống giật (ELCB) hoạt "
     "động tốt trước mỗi mùa sử dụng nhiều để đảm bảo an toàn cho cả gia đình."),
    ("Tủ lạnh Inverter có thực sự tiết kiệm điện hơn?",
     "So sánh nhanh giữa tủ lạnh Inverter và tủ lạnh thường để biết khoản chênh lệch giá có đáng đầu tư hay không.",
     "Máy nén Inverter điều chỉnh tốc độ linh hoạt theo nhu cầu làm lạnh thay vì chỉ bật/tắt như tủ lạnh thường, nhờ đó "
     "tiết kiệm điện hơn 20-40% và vận hành êm hơn. Dù giá mua ban đầu cao hơn, với gia đình dùng tủ lạnh liên tục "
     "nhiều năm thì khoản tiết kiệm điện về lâu dài thường bù lại phần chênh lệch giá."),
]


PRODUCT_ARTICLES = {
    "HSC09TMU":
        "Điều hòa Funiki HSC09TMU 9.000 BTU là lựa chọn quen thuộc cho phòng ngủ, "
        "phòng làm việc nhỏ dưới 15m². Máy dùng gas R32 thân thiện môi trường, dàn "
        "lạnh gọn nhẹ, dễ lắp đặt ở nhiều vị trí tường khác nhau.\n"
        "## Vận hành bền bỉ, dễ bảo trì\n"
        "Với thiết kế đơn giản, ít linh kiện điện tử phức tạp, dòng máy thường "
        "(non-Inverter) của Funiki nổi tiếng bền, chi phí sửa chữa thấp nếu có sự "
        "cố, phù hợp gia đình muốn tiết kiệm chi phí đầu tư ban đầu.",
    "HSC12TMU":
        "Bản 12.000 BTU phù hợp phòng 15-20m², làm lạnh nhanh hơn bản 9.000 BTU mà "
        "mức giá chỉ nhỉnh hơn không đáng kể.\n"
        "## Phù hợp lắp cho phòng cho thuê, nhà trọ\n"
        "Nhờ giá thành hợp lý và độ bền cao, model này được nhiều chủ nhà trọ, căn "
        "hộ cho thuê lựa chọn lắp đặt số lượng lớn.",
    "HSC18TMU":
        "18.000 BTU phù hợp phòng khách 25-30m², quán ăn, văn phòng nhỏ cần làm "
        "lạnh nhanh trong thời gian ngắn.\n"
        "## Dàn nóng chắc chắn, chịu được thời tiết khắc nghiệt\n"
        "Dàn nóng được gia cố phù hợp lắp đặt ngoài trời, chịu nắng mưa tốt trong "
        "điều kiện khí hậu Việt Nam.",
    "HSC24TMU":
        "24.000 BTU là lựa chọn cho không gian rộng trên 30m² như phòng họp, cửa "
        "hàng, nhà xưởng nhỏ.\n"
        "## Tối ưu chi phí đầu tư ban đầu\n"
        "So với các dòng Inverter cùng công suất, bản thường giá thấp hơn đáng kể, "
        "phù hợp nơi sử dụng không liên tục cả ngày.",
    "HIC09TMU":
        "Máy nén Inverter giúp duy trì nhiệt độ ổn định, tránh tình trạng bật tắt "
        "liên tục như máy thường, nhờ đó tiết kiệm điện đáng kể khi dùng lâu dài.\n"
        "## Khởi động êm, ít gây tiếng ồn\n"
        "Công nghệ biến tần giúp máy khởi động nhẹ nhàng hơn, phù hợp phòng ngủ "
        "cần yên tĩnh vào ban đêm.",
    "HIC12TMU":
        "Bản Inverter 12.000 BTU phù hợp phòng vừa, mức tiêu thụ điện thấp hơn rõ "
        "rệt so với máy thường cùng công suất khi sử dụng trên 8 tiếng/ngày.\n"
        "## Phù hợp sử dụng liên tục\n"
        "Với hộ gia đình bật điều hòa cả ngày, khoản chênh lệch giá mua ban đầu sẽ "
        "được bù lại qua hóa đơn tiền điện chỉ sau vài tháng sử dụng.",
    "HIC18TMU":
        "18.000 BTU Inverter phù hợp phòng khách lớn, duy trì nhiệt độ ổn định "
        "suốt nhiều giờ mà không tốn nhiều điện như máy thường.\n"
        "## Tiết kiệm điện tới 30%\n"
        "Theo thông số nhà sản xuất công bố, công nghệ Inverter trên dòng máy này "
        "giúp tiết kiệm điện năng tới khoảng 30% so với máy không Inverter cùng "
        "công suất.",
    "HIC24TMU":
        "24.000 BTU Inverter phù hợp không gian rộng cần làm lạnh liên tục nhiều "
        "giờ mỗi ngày như văn phòng, cửa hàng.\n"
        "## Đầu tư dài hạn, tiết kiệm chi phí vận hành\n"
        "Dù giá mua cao hơn bản thường, chi phí điện hàng tháng thấp hơn đáng kể, "
        "phù hợp nơi sử dụng máy thường xuyên quanh năm.",
    "HSH10TMU":
        "Điểm khác biệt của dòng 2 chiều là có thêm chức năng sưởi ấm mùa đông, "
        "rất phù hợp khu vực miền Bắc có mùa lạnh kéo dài.\n"
        "## Tích hợp lọc khí nano bạc\n"
        "Máy trang bị màng lọc kháng khuẩn giúp không khí trong phòng sạch hơn, "
        "phù hợp gia đình có trẻ nhỏ.",
    "HSH12TMU":
        "Bản 12.000 BTU 2 chiều phù hợp phòng 15-20m², vừa làm mát mùa hè vừa sưởi "
        "ấm mùa đông hiệu quả.\n"
        "## Chế độ tự làm sạch dàn lạnh\n"
        "Tính năng tự vệ sinh giúp hạn chế nấm mốc, mùi hôi tích tụ trong dàn lạnh "
        "sau thời gian dài sử dụng.",
    "HSH18TMU":
        "18.000 BTU 2 chiều phù hợp phòng khách rộng cần chuyển đổi nhanh giữa chế "
        "độ làm lạnh và sưởi ấm theo mùa.\n"
        "## Phù hợp khu vực có mùa đông lạnh sâu\n"
        "Chức năng sưởi giúp gia đình không cần mua thêm thiết bị sưởi riêng vào "
        "mùa đông, tiết kiệm chi phí đầu tư.",
    "HSH24TMU":
        "24.000 BTU 2 chiều phù hợp không gian rất rộng, vừa làm mát mùa hè vừa "
        "sưởi ấm mùa đông cho cả tầng nhà.\n"
        "## Đầu tư một lần, dùng được quanh năm\n"
        "Với công suất lớn và tính năng 2 chiều, model này giúp gia đình dùng "
        "được máy quanh năm thay vì chỉ riêng mùa hè.",
    "HIH09TMU":
        "Vừa tiết kiệm điện nhờ công nghệ Inverter, vừa dùng được cả mùa đông lẫn "
        "mùa hè, phù hợp gia đình muốn tối ưu chi phí điện quanh năm.\n"
        "## Vận hành êm ái, phù hợp phòng ngủ\n"
        "Máy nén biến tần giúp giảm tiếng ồn khi khởi động, không gây giật mình "
        "khi đang ngủ vào ban đêm.",
    "HIH12TMU":
        "Model 12.000 BTU phù hợp phòng vừa, tiết kiệm điện rõ rệt khi dùng cả hai "
        "chế độ sưởi và làm lạnh liên tục.\n"
        "## Lựa chọn tối ưu cho gia đình dùng lâu dài\n"
        "Dù giá cao hơn các dòng thường, khoản tiết kiệm điện qua nhiều mùa sẽ bù "
        "lại chi phí đầu tư ban đầu.",
    "HSIC09TMU":
        "Model tích hợp WiFi cho phép bật/tắt, chỉnh nhiệt độ từ xa qua ứng dụng "
        "trên điện thoại, tiện lợi khi muốn làm mát phòng trước khi về nhà.\n"
        "## Tiết kiệm điện, khử mùi diệt khuẩn\n"
        "Ngoài công nghệ Inverter tiết kiệm điện, máy còn có chức năng khử mùi, "
        "diệt khuẩn giúp không khí trong phòng dễ chịu hơn.",
    # -- Panasonic --
    "N9AKH-8":
        "Model phổ thông của Panasonic, phù hợp gia đình muốn tiết kiệm chi phí "
        "đầu tư ban đầu.\n"
        "## Thương hiệu Nhật Bản quen thuộc\n"
        "Panasonic là cái tên quen thuộc với người tiêu dùng Việt Nam nhiều năm "
        "qua, dễ tìm phụ tùng và thợ sửa chữa khi cần bảo trì.",
    "RU9CKH-8D":
        "Dòng Inverter tiêu chuẩn của Panasonic, cân bằng giữa giá thành và khả "
        "năng tiết kiệm điện.\n"
        "## Công nghệ lọc khí nanoe\n"
        "Màng lọc nanoe giúp khử mùi, ức chế vi khuẩn trong không khí, phù hợp "
        "gia đình có trẻ nhỏ hoặc người lớn tuổi.",
    "N12AKH-8":
        "Công suất lớn hơn cho phòng vừa, giá tốt trong phân khúc máy thường.\n"
        "## Sản xuất tại Indonesia\n"
        "Hàng nhập khẩu nguyên chiếc, chất lượng đồng bộ theo tiêu chuẩn Panasonic "
        "toàn cầu.",
    "N18AKH-8":
        "Công suất lớn cho phòng khách rộng, làm lạnh nhanh trong phân khúc máy "
        "thường.\n"
        "## Phù hợp không gian trên 25m²\n"
        "Công suất 18.000 BTU đủ sức làm lạnh nhanh cho phòng khách, phòng họp "
        "diện tích lớn.",
    "N24AKH-8":
        "Model công suất lớn nhất dòng thường, phù hợp phòng rất rộng hoặc không "
        "gian mở.\n"
        "## Công nghệ Nanoe-G khử khuẩn\n"
        "Công nghệ Nanoe-G giúp ức chế vi khuẩn, nấm mốc trong không khí, mang "
        "lại không gian sống trong lành hơn.",
    "RU18CKH-8BD":
        "Công suất lớn phù hợp phòng khách rộng hoặc không gian mở, làm lạnh đều "
        "khắp phòng.\n"
        "## Bảo hành máy nén dài hạn\n"
        "Máy nén được bảo hành nhiều năm, an tâm sử dụng lâu dài mà không lo chi "
        "phí sửa chữa phát sinh.",
    "RU12CKH-8D":
        "Inverter công suất vừa, tiết kiệm điện, phù hợp phòng khách nhỏ đến vừa.\n"
        "## Công nghệ lọc khí nanoe\n"
        "Màng lọc nanoe giúp khử mùi, ức chế vi khuẩn, phù hợp gia đình có trẻ nhỏ.",
    "RU24CKH-8D":
        "Inverter công suất mạnh nhất dòng tiêu chuẩn, phù hợp không gian rộng.\n"
        "## Làm lạnh nhanh cho không gian lớn\n"
        "Công suất lên đến 24.000 BTU phù hợp phòng họp, cửa hàng, không gian mở "
        "rộng rãi.",
    "U9BKH-8":
        "Inverter cao cấp, công nghệ Nanoe-X ức chế vi khuẩn virus, vận hành êm "
        "ái.\n"
        "## Công nghệ Nanoe-X cao cấp\n"
        "So với Nanoe-G tiêu chuẩn, Nanoe-X có khả năng ức chế vi khuẩn và virus "
        "hiệu quả hơn, phù hợp gia đình chú trọng sức khỏe.",
    "U12BKH-8":
        "Inverter cao cấp công suất vừa, tiết kiệm điện vượt trội, vận hành êm.\n"
        "## Phù hợp phòng ngủ cần yên tĩnh\n"
        "Độ ồn thấp giúp máy hoạt động êm ái, không làm phiền giấc ngủ ban đêm.",
    "YZ9AKH-8":
        "Dòng 2 chiều giúp gia đình dùng được máy quanh năm thay vì chỉ mùa hè.\n"
        "## Phù hợp khu vực có mùa đông lạnh\n"
        "Chức năng sưởi giúp tiết kiệm chi phí mua thêm thiết bị sưởi riêng vào "
        "mùa đông.",
    "YZ12AKH-8":
        "2 chiều Inverter công suất vừa, tích hợp WiFi điều khiển qua app Comfort "
        "Cloud.\n"
        "## Điều khiển từ xa qua điện thoại\n"
        "Ứng dụng Panasonic Comfort Cloud giúp bật máy sưởi/làm lạnh từ xa trước "
        "khi về đến nhà.",
    "YZ18AKH-8":
        "2 chiều Inverter công suất lớn cho phòng khách rộng, kèm chức năng hút "
        "ẩm.\n"
        "## Phù hợp không gian rộng, dùng quanh năm\n"
        "Công suất lớn kết hợp tính năng 2 chiều giúp gia đình dùng một máy cho "
        "cả mùa hè và mùa đông.",
    # -- Daikin --
    "FTF25XAV1V":
        "Model phổ thông sản xuất tại Việt Nam, giá hợp lý, dễ bảo trì.\n"
        "## Thương hiệu Nhật Bản uy tín lâu năm\n"
        "Daikin là một trong những thương hiệu điều hòa được tin dùng nhiều nhất "
        "tại Việt Nam nhờ độ bền và chất lượng ổn định.",
    "FTKB25ZVMV":
        "Inverter tiết kiệm điện, sản xuất tại Việt Nam nên giá thành hợp lý hơn "
        "hàng nhập khẩu.\n"
        "## Bảo hành máy nén 5 năm\n"
        "Chính sách bảo hành dài hạn giúp khách hàng an tâm sử dụng lâu dài.",
    "FTKB50ZVMV":
        "Công suất lớn cho phòng khách rộng, vận hành êm ái, tiết kiệm điện.\n"
        "## Dàn lạnh mỏng, thiết kế hiện đại\n"
        "Thiết kế mỏng nhẹ giúp dàn lạnh hài hòa với nội thất phòng khách hiện đại.",
    "FTXV25QVMV":
        "Nhập khẩu nguyên chiếc từ Thái Lan, 2 chiều sưởi ấm mùa đông làm mát mùa "
        "hè.\n"
        "## Phù hợp gia đình dùng quanh năm\n"
        "Với tính năng 2 chiều, gia đình không cần mua thêm thiết bị sưởi riêng "
        "vào mùa lạnh.",
    # -- LG --
    "IFC09M1":
        "Model bán chạy nhất của LG tại nhiều đại lý, giá tốt, làm lạnh nhanh.\n"
        "## Phù hợp phòng ngủ, phòng làm việc nhỏ\n"
        "Công suất 9.000 BTU vừa đủ cho không gian dưới 15m², tiết kiệm chi phí "
        "đầu tư ban đầu.",
    "IEC12G1":
        "Công suất lớn hơn, nhập khẩu Thái Lan, phù hợp phòng khách vừa.\n"
        "## Dàn lạnh kháng khuẩn Plasma\n"
        "Công nghệ Plasma giúp khử mùi, kháng khuẩn, mang lại không khí trong "
        "lành hơn.",
    "IDC09B2":
        "Công nghệ Dual Inverter tiết kiệm điện tới 70%, tích hợp WiFi điều khiển "
        "từ xa.\n"
        "## Điều khiển qua điện thoại mọi lúc mọi nơi\n"
        "Ứng dụng LG ThinQ cho phép bật máy làm mát trước khi về nhà, rất tiện "
        "lợi cho gia đình bận rộn.",
    "IDH09M1":
        "2 chiều sưởi ấm mùa đông làm mát mùa hè, dùng được quanh năm.\n"
        "## Dàn lạnh kháng khuẩn Plasma\n"
        "Giúp không khí trong phòng luôn sạch, hạn chế nấm mốc vi khuẩn tích tụ.",
    # -- Casper --
    "SC-09FB36M":
        "Điều hòa Casper SC-09FB36M là dòng máy lạnh phổ thông công suất 9.200 BTU, không trang bị công nghệ Inverter, phù hợp cho những gia đình có ngân sách hạn chế nhưng vẫn cần làm mát hiệu quả cho phòng ngủ, phòng làm việc nhỏ. Đây là một trong những model giá tốt nhất trong dải sản phẩm điều hòa treo tường của Casper hiện có tại Điện Máy Xuân Son.\n## Công nghệ máy thường, giá thành hợp lý\nKhông sử dụng biến tần Inverter, SC-09FB36M vận hành theo cơ chế bật tắt máy nén truyền thống. Ưu điểm là chi phí sản xuất thấp hơn, giúp giá bán cạnh tranh hơn đáng kể so với dòng Inverter cùng công suất. Đây là lựa chọn phù hợp với những ai không dùng điều hòa liên tục cả ngày, ví dụ chỉ bật vào buổi tối để ngủ, vì khoản chênh lệch giá mua ban đầu sẽ khó bù lại bằng tiền điện tiết kiệm được nếu dùng ít giờ.\n## Phù hợp phòng ngủ, phòng làm việc nhỏ dưới 15m²\nCông suất 9.200 BTU tương đương khoảng 1HP, đủ sức làm mát nhanh cho không gian dưới 15m². Đây là mức công suất phổ biến nhất cho phòng ngủ cá nhân, phòng làm việc tại nhà hoặc phòng cho người thuê trọ.\n## Dàn đồng nguyên chất, chống ăn mòn\nGiống các dòng Casper khác, SC-09FB36M sử dụng dàn trao đổi nhiệt bằng đồng nguyên chất kết hợp cánh tản nhiệt phủ lớp Gold Fin chống ăn mòn, giúp máy bền hơn trong điều kiện khí hậu nóng ẩm, gần biển hoặc nhiều mưa axit.\n## Xuất xứ Thái Lan, bảo hành chính hãng\nSản phẩm nhập khẩu nguyên chiếc từ Thái Lan. Casper là thương hiệu quen thuộc tại thị trường Việt Nam nhiều năm nay, mạng lưới bảo hành và linh kiện thay thế rộng khắp, giúp việc bảo trì sau này thuận tiện. Đội ngũ kỹ thuật của Điện Máy Xuân Son hỗ trợ lắp đặt và tư vấn sử dụng miễn phí sau khi mua.\n## Nên chọn máy thường hay nâng cấp lên Inverter?\nĐây là câu hỏi nhiều khách hàng đặt ra khi cân nhắc giữa SC-09FB36M và các model Inverter cùng hãng như JC-09IU36. Nguyên tắc chung: nếu gia đình chỉ bật điều hòa vài tiếng mỗi ngày, ví dụ buổi tối để ngủ, chênh lệch tiền điện giữa hai công nghệ không đáng kể so với khoản chênh lệch giá mua ban đầu, nên máy thường sẽ tiết kiệm hơn về tổng chi phí. Ngược lại, nếu dùng liên tục cả ngày như phòng làm việc, kinh doanh, nên cân nhắc đầu tư thêm cho Inverter để tiết kiệm điện lâu dài.\n## Lắp đặt và những lưu ý khi sử dụng\nKhi lắp đặt SC-09FB36M, nên chọn vị trí dàn lạnh cách trần khoảng 15-20cm để đảm bảo lưu thông không khí tốt, tránh đặt đối diện trực tiếp giường ngủ để hạn chế gió lạnh thổi thẳng vào người khi ngủ. Dàn nóng nên lắp ở nơi thoáng khí, có mái che mưa nắng để tăng tuổi thọ.\nNếu bạn đang tìm một chiếc điều hòa treo tường giá tốt cho phòng nhỏ, không có nhu cầu sử dụng liên tục cả ngày, Casper SC-09FB36M là lựa chọn hợp lý để tiết kiệm chi phí đầu tư ban đầu.",
    "JC-09IU36":
        "Điều hòa Casper JC-09IU36 thuộc dòng ProAir thế hệ mới, công suất 9.250 BTU, trang bị công nghệ Inverter giúp tiết kiệm điện đáng kể so với máy thường cùng công suất. Đây là lựa chọn cân bằng giữa giá thành và hiệu quả sử dụng lâu dài cho phòng ngủ, phòng làm việc.\n## Công nghệ Advanced Inverter tiết kiệm điện\nMáy nén biến tần giúp duy trì nhiệt độ phòng ổn định thay vì bật tắt liên tục như máy thường, nhờ đó tiết kiệm điện năng và vận hành êm ái, bền bỉ hơn theo thời gian. Với những gia đình sử dụng điều hòa trên 6-8 tiếng mỗi ngày, khoản tiền điện tiết kiệm được sẽ bù lại phần chênh lệch giá mua so với máy không Inverter chỉ sau khoảng 1-2 năm sử dụng.\n## Chế độ Turbo làm lạnh nhanh trong 30 giây\nJC-09IU36 tích hợp chế độ Turbo hoạt động ở cấp độ thổi gió cao nhất, giúp phòng giảm nhiệt nhanh chóng chỉ trong khoảng 30 giây sau khi bật — rất hữu ích vào những ngày nắng nóng cao điểm khi vừa đi ngoài trời về.\n## Dàn đồng nguyên chất, phủ Gold Fin chống ăn mòn\nMáy sử dụng 100% dàn đồng nguyên chất, cánh tản nhiệt được phủ lớp Gold Fin giúp hạn chế ăn mòn từ mưa, axit, hơi muối — kéo dài tuổi thọ dàn nóng đặt ngoài trời.\n## Phù hợp phòng dưới 15m², vận hành êm ái\nCông suất 9.250 BTU (1HP) phù hợp phòng ngủ, phòng làm việc dưới 15m². Công nghệ Inverter giúp máy vận hành êm hơn so với máy thường, hạn chế tiếng ồn khi ngủ vào ban đêm.\n## Bảo hành 3 năm toàn máy, 12 năm máy nén\nCasper áp dụng chính sách bảo hành dài hạn cho dòng Inverter: toàn máy 3 năm, riêng máy nén lên đến 12 năm tại nhà, giúp khách hàng an tâm hơn khi đầu tư.\n## So sánh với dòng máy thường SC cùng hãng\nSo với model SC-09FB36M không Inverter, JC-09IU36 có giá cao hơn một khoảng nhất định nhưng bù lại tiết kiệm điện đáng kể nếu sử dụng thường xuyên. Với các gia đình bật điều hòa từ 6 tiếng mỗi ngày trở lên, khoản chênh lệch giá mua ban đầu thường được bù lại sau 1-2 năm sử dụng nhờ tiền điện tiết kiệm được, sau đó là lãi ròng về lâu dài.\n## Lắp đặt đúng cách để tối ưu hiệu quả làm lạnh\nĐể máy hoạt động hiệu quả nhất, dàn lạnh nên được lắp ở độ cao khoảng 2-2,2m so với sàn nhà, tránh các vật cản phía trước luồng gió thổi ra. Dàn nóng cần đặt nơi thông thoáng, tránh ánh nắng chiếu trực tiếp cả ngày để máy nén không phải hoạt động quá tải trong điều kiện nhiệt độ môi trường cao.\nVới mức giá vẫn thuộc phân khúc phổ thông nhưng đã có công nghệ Inverter tiết kiệm điện, Casper JC-09IU36 là bước nâng cấp hợp lý cho gia đình muốn giảm hóa đơn tiền điện về lâu dài.",
    "SC-18FB36M":
        "Điều hòa Casper SC-18FB36M là dòng máy thường công suất lớn 18.400 BTU, phù hợp cho phòng khách rộng, cửa hàng nhỏ hoặc văn phòng cần làm lạnh nhanh mà không muốn đầu tư vào công nghệ Inverter đắt hơn.\n## Công suất lớn cho không gian rộng\nVới 18.400 BTU (tương đương 2HP), SC-18FB36M đủ sức làm lạnh nhanh cho các không gian rộng hơn phòng ngủ tiêu chuẩn như phòng khách, phòng họp nhỏ hoặc cửa hàng kinh doanh diện tích vừa.\n## Máy thường, giá tốt cho công suất lớn\nKhông trang bị Inverter giúp SC-18FB36M có mức giá dễ tiếp cận hơn đáng kể so với dòng Inverter cùng công suất, phù hợp với các không gian thương mại chỉ bật điều hòa trong giờ hoạt động chứ không chạy liên tục cả ngày.\n## Chế độ Turbo làm lạnh nhanh\nMáy được trang bị chế độ Turbo giúp đẩy nhanh tốc độ làm lạnh trong những ngày nắng nóng cao điểm, phù hợp với nhu cầu làm mát tức thời khi khách hàng hoặc nhân viên vừa bước vào không gian.\n## Dàn đồng nguyên chất, bền bỉ với thời gian\nDàn trao đổi nhiệt bằng đồng nguyên chất phủ Gold Fin chống ăn mòn giúp máy vận hành ổn định trong thời gian dài, kể cả khi lắp đặt ở khu vực gần biển hoặc thời tiết khắc nghiệt.\n## Bảo hành chính hãng, hỗ trợ lắp đặt chuyên nghiệp\nVới công suất lớn, việc lắp đặt cần đội ngũ kỹ thuật có kinh nghiệm để đảm bảo hiệu quả làm lạnh tối ưu. Điện Máy Xuân Son hỗ trợ khảo sát và lắp đặt tận nơi cho các model công suất lớn như SC-18FB36M.\n## Điện 1 pha, phù hợp lắp đặt phổ thông\nDù công suất lớn, SC-18FB36M vẫn sử dụng điện 1 pha tiêu chuẩn như các model nhỏ hơn, không yêu cầu nâng cấp hệ thống điện 3 pha phức tạp — thuận tiện cho hầu hết các hộ gia đình, cửa hàng nhỏ đã có sẵn hệ thống điện dân dụng thông thường.\n## Nên cân nhắc gì trước khi lắp máy công suất lớn\nVới những không gian có trần cao hoặc nhiều cửa kính hấp thụ nhiệt, nên khảo sát thực tế trước khi chốt công suất, vì đôi khi 18.400 BTU vẫn chưa đủ nếu diện tích thực tế vượt quá 30m² hoặc phòng có nhiều nguồn nhiệt phụ như máy tính, đèn chiếu sáng công suất lớn. Điện Máy Xuân Son luôn tư vấn khảo sát miễn phí trước khi báo giá lắp đặt.\nNếu bạn cần một chiếc điều hòa công suất lớn cho phòng khách hoặc không gian kinh doanh mà không muốn chi thêm cho công nghệ Inverter, Casper SC-18FB36M là lựa chọn tiết kiệm chi phí hợp lý.\n## Đường ống và khoảng cách lắp đặt\nVới công suất lớn, khoảng cách tối đa giữa dàn lạnh và dàn nóng cũng như độ chênh cao cho phép sẽ lớn hơn các model nhỏ, tạo thuận lợi hơn khi cần lắp dàn nóng ở vị trí xa hoặc trên tầng thượng của các công trình nhiều tầng.",
    "QH-12IU36A":
        "Điều hòa Casper QH-12IU36A là phiên bản công suất lớn hơn trong dòng 2 chiều Inverter, đạt 12.000 BTU cho cả hai chế độ làm mát và sưởi ấm, phù hợp phòng ngủ lớn hoặc phòng khách nhỏ cần dùng quanh năm.\n## Lựa chọn kinh tế cho máy 2 chiều công suất lớn\nSo với các thương hiệu cao cấp như Daikin, Mitsubishi, Casper mang đến tính năng 2 chiều sưởi/lạnh với mức giá dễ tiếp cận hơn đáng kể, phù hợp với những gia đình muốn có đầy đủ tính năng mà vẫn tối ưu ngân sách.\n## Sưởi ấm mùa đông, làm mát mùa hè cùng một máy\nVới công suất 12.000 BTU đồng đều cho cả hai chiều, QH-12IU36A phù hợp sử dụng quanh năm mà không cần sắm thêm thiết bị sưởi riêng, tiết kiệm không gian lắp đặt và chi phí đầu tư dài hạn.\n## Phù hợp phòng 15-20m²\nCông suất lớn hơn phiên bản 9.000 BTU cùng dòng, đáp ứng tốt nhu cầu 2 chiều cho phòng ngủ lớn hoặc phòng khách căn hộ chung cư có diện tích 15-20m².\n## Công nghệ Inverter và dàn đồng bền bỉ\nMáy nén Inverter giúp tiết kiệm điện ở cả hai chế độ vận hành, kết hợp dàn đồng nguyên chất phủ Gold Fin chống ăn mòn, tăng tuổi thọ khi máy phải hoạt động liên tục quanh năm thay vì chỉ theo mùa.\n## Bảo hành dài hạn, an tâm sử dụng\nCasper áp dụng bảo hành 3 năm toàn máy, 12 năm máy nén cho dòng Inverter, đảm bảo quyền lợi khách hàng trong suốt thời gian sử dụng dài hạn.\n## Phù hợp cả gia đình lẫn văn phòng nhỏ\nVới công suất 12.000 BTU, QH-12IU36A không chỉ phù hợp phòng ngủ, phòng khách gia đình mà còn thích hợp lắp cho văn phòng nhỏ cần vừa làm mát mùa hè vừa sưởi ấm mùa đông, tránh phải sắm thêm quạt sưởi cồng kềnh trong không gian làm việc.\n## Tiết kiệm điện hơn dòng 2 chiều không Inverter\nSo với các dòng 2 chiều không có công nghệ Inverter, QH-12IU36A tiết kiệm điện đáng kể nhờ máy nén biến tần điều chỉnh công suất linh hoạt theo nhu cầu thực tế, thay vì chạy hết công suất liên tục ở cả hai chế độ nóng và lạnh.\nCasper QH-12IU36A phù hợp với các gia đình ở khu vực có mùa đông lạnh, cần công suất lớn hơn mức phổ thông mà vẫn giữ được mức giá hợp lý so với các thương hiệu cao cấp.\n## Bảo hành và hỗ trợ kỹ thuật\nCũng như các model Inverter khác, QH-12IU36A được bảo hành 3 năm toàn máy, 12 năm máy nén. Điện Máy Xuân Son hỗ trợ kiểm tra, bảo dưỡng định kỳ để đảm bảo cả hai chế độ nóng và lạnh luôn hoạt động ổn định trong suốt vòng đời sử dụng, đồng thời tư vấn thời điểm bảo dưỡng hợp lý trước khi bước vào mùa hè hoặc mùa đông cao điểm.",
    # -- Nagakawa --
    "NS-C09R2T30":
        "Thương hiệu Việt giá rẻ, phù hợp phòng ngủ nhỏ, phụ tùng dễ tìm.\n"
        "## Thương hiệu điều hòa Việt Nam\n"
        "Nagakawa là thương hiệu nội địa được nhiều gia đình lựa chọn nhờ giá "
        "thành cạnh tranh.",
    "NIS-C09R2U51":
        "Tiết kiệm điện, giá cạnh tranh, dàn lạnh phủ Golden Fin chống ăn mòn.\n"
        "## Bảo hành máy nén 10 năm\n"
        "Chính sách bảo hành dài hạn hiếm có ở phân khúc giá rẻ, giúp khách hàng "
        "an tâm hơn khi lựa chọn.",
    "NIS-C18R2U51":
        "Inverter công suất lớn cho phòng khách rộng, tiết kiệm điện.\n"
        "## Phù hợp không gian rộng, giá vẫn cạnh tranh\n"
        "So với các thương hiệu lớn cùng công suất, đây là lựa chọn tiết kiệm chi "
        "phí đáng cân nhắc.",
    "NIS-A09R2T29":
        "2 chiều Inverter sưởi ấm mùa đông làm mát mùa hè, giá cạnh tranh.\n"
        "## Lựa chọn kinh tế cho máy 2 chiều\n"
        "Giúp gia đình có ngân sách vừa phải vẫn sở hữu được máy điều hòa dùng "
        "quanh năm.",
    # -- Daikin (bổ sung) --
    "FTF35XAV1V":
        "Công suất lớn hơn cho phòng vừa, sản xuất tại Việt Nam nên giá thành "
        "hợp lý.\n"
        "## Phù hợp phòng 15-20m²\n"
        "Mức công suất 12.000 BTU đáp ứng tốt nhu cầu làm lạnh cho phòng ngủ lớn "
        "hoặc phòng khách nhỏ.",
    "FTF50XV1V":
        "Công suất lớn cho phòng khách rộng, làm lạnh nhanh trong phân khúc máy "
        "thường.\n"
        "## Phù hợp không gian trên 25m²\n"
        "Công suất 18.000 BTU đủ sức làm lạnh nhanh cho phòng khách, phòng họp "
        "diện tích lớn.",
    "FTKB35ZVMV":
        "Inverter công suất vừa, tiết kiệm điện, phù hợp phòng khách nhỏ đến "
        "vừa.\n"
        "## Sản xuất tại Việt Nam\n"
        "Hàng nội địa hóa giúp giá thành hợp lý hơn so với các dòng nhập khẩu "
        "nguyên chiếc.",
    "FTKM25AVMV":
        "Model mới nhập khẩu Thái Lan nguyên chiếc, vận hành siêu êm chỉ 19dB.\n"
        "## Độ ồn cực thấp\n"
        "Phù hợp phòng ngủ cần yên tĩnh tuyệt đối, gần như không nghe thấy tiếng "
        "máy hoạt động.",
    "FTHF25XVMV":
        "2 chiều Inverter sản xuất tại Việt Nam, sưởi ấm mùa đông làm mát mùa "
        "hè.\n"
        "## Dùng được quanh năm\n"
        "Chức năng sưởi giúp gia đình không cần mua thêm thiết bị sưởi riêng vào "
        "mùa lạnh.",
    "FTHF35XVMV":
        "2 chiều Inverter công suất vừa, sưởi ấm mùa đông làm mát mùa hè hiệu "
        "quả.\n"
        "## Phù hợp phòng 15-20m²\n"
        "Công suất 12.000 BTU đáp ứng tốt nhu cầu 2 chiều cho phòng ngủ hoặc "
        "phòng khách nhỏ.",
    "FTHF50VAVMV":
        "2 chiều Inverter công suất lớn, công nghệ COANDA làm lạnh không thổi "
        "trực diện.\n"
        "## Cảm biến thông minh nhận diện chuyển động\n"
        "Giúp máy tự động điều chỉnh luồng gió, tránh thổi trực tiếp vào người, "
        "tăng cảm giác thoải mái.",
    # -- LG (bổ sung) --
    "IFC12M1":
        "Công suất lớn hơn cho phòng vừa, giá tốt trong dòng phổ thông.\n"
        "## Phù hợp phòng 15-20m²\n"
        "Công suất 12.000 BTU đáp ứng tốt nhu cầu làm lạnh cho phòng ngủ lớn "
        "hoặc phòng khách nhỏ.",
    "IFC18M1":
        "Công suất lớn cho phòng khách rộng, làm lạnh nhanh.\n"
        "## Phù hợp không gian trên 25m²\n"
        "Công suất 18.000 BTU đủ sức làm lạnh nhanh cho phòng khách, cửa hàng "
        "nhỏ.",
    "IFC24M1":
        "Công suất lớn nhất dòng phổ thông, phù hợp không gian rất rộng.\n"
        "## Giải pháp cho không gian mở\n"
        "Phù hợp phòng họp, cửa hàng, nhà xưởng nhỏ cần làm lạnh nhanh diện tích "
        "lớn.",
    "IEC09G2":
        "Nhập khẩu Thái Lan, bảo hành máy nén dài hạn, dàn lạnh kháng khuẩn "
        "Plasma.\n"
        "## Bảo hành máy nén 10 năm\n"
        "Chính sách bảo hành dài hạn giúp khách hàng an tâm sử dụng lâu dài.",
    "IDH12M1":
        "2 chiều công suất vừa, sưởi ấm mùa đông làm mát mùa hè hiệu quả.\n"
        "## Phù hợp phòng 15-20m²\n"
        "Công suất 12.000 BTU đáp ứng tốt nhu cầu 2 chiều cho phòng ngủ hoặc "
        "phòng khách nhỏ.",
    "IDH18M1":
        "2 chiều công suất lớn cho phòng khách rộng, sưởi/làm lạnh nhanh.\n"
        "## Phù hợp không gian rộng, dùng quanh năm\n"
        "Công suất lớn kết hợp tính năng 2 chiều giúp gia đình dùng một máy cho "
        "cả mùa hè và mùa đông.",
    "IDC09M1":
        "Dual Inverter tích hợp ionizer lọc không khí, WiFi điều khiển qua điện "
        "thoại.\n"
        "## Công nghệ ionizer lọc không khí\n"
        "Giúp khử mùi, loại bỏ bụi mịn, mang lại không khí trong lành hơn cho "
        "căn phòng.",
    "IDC12M1":
        "Dual Inverter công suất lớn hơn, tích hợp ionizer, tiết kiệm điện tới "
        "70%.\n"
        "## Tiết kiệm điện vượt trội\n"
        "Công nghệ Dual Inverter giúp giảm đáng kể hóa đơn tiền điện so với máy "
        "Inverter thông thường.",
    # -- Casper (bổ sung) --
    "SC-12FB36A":
        "Điều hòa Casper SC-12FB36A là dòng máy thường (không Inverter) công suất 11.700 BTU, phù hợp cho phòng ngủ lớn, phòng khách nhỏ hoặc các mô hình cho thuê cần lắp đặt số lượng lớn với chi phí tối ưu.\n## Máy thường công suất lớn, giá thành cạnh tranh\nSo với dòng Inverter cùng công suất, SC-12FB36A có mức giá dễ tiếp cận hơn nhờ không trang bị công nghệ biến tần. Đây là lựa chọn hợp lý cho các không gian không sử dụng điều hòa liên tục, hoặc các chủ nhà trọ, phòng cho thuê cần tối ưu chi phí đầu tư ban đầu cho nhiều phòng cùng lúc.\n## Phù hợp phòng cho thuê, nhà trọ\nMức giá phải chăng cùng công suất 11.700 BTU khiến model này được nhiều chủ nhà trọ, chung cư mini lựa chọn lắp đặt số lượng lớn — vừa đủ mát cho phòng khách thuê tiêu chuẩn mà không phải chi phí quá cao cho từng phòng.\n## Phù hợp phòng 15-20m²\nCông suất lớn hơn mức phổ thông 9.000 BTU, đáp ứng tốt nhu cầu làm lạnh cho phòng ngủ lớn hoặc phòng khách nhỏ có diện tích khoảng 15-20m².\n## Dàn đồng chống ăn mòn, độ bền cao\nVẫn giữ chất lượng dàn đồng nguyên chất phủ Gold Fin như các dòng Casper khác, giúp máy bền bỉ dù không có công nghệ Inverter, phù hợp sử dụng trong thời gian dài mà ít gặp sự cố rò rỉ gas do ăn mòn dàn.\n## Bảo hành chính hãng, dễ bảo trì\nLà thương hiệu phổ biến tại Việt Nam, Casper có mạng lưới bảo hành và linh kiện thay thế rộng khắp, thuận tiện cho việc bảo trì định kỳ nhất là với các mô hình lắp đặt số lượng lớn.\n## Lắp đặt số lượng lớn cho mô hình cho thuê\nVới các chủ đầu tư nhà trọ, chung cư mini cần lắp đặt hàng chục máy cùng lúc, SC-12FB36A là lựa chọn tối ưu chi phí ban đầu. Điện Máy Xuân Son hỗ trợ báo giá theo số lượng lớn kèm chính sách lắp đặt trọn gói, giúp tiết kiệm thời gian và chi phí nhân công so với đặt lắp lẻ từng phòng.\n## Lưu ý về điện năng tiêu thụ\nDo không có Inverter, SC-12FB36A tiêu thụ điện ổn định theo công suất định mức khi máy nén hoạt động, không tự động giảm công suất khi phòng đã đạt nhiệt độ cài đặt như dòng Inverter. Với mô hình cho thuê, chủ nhà nên cân nhắc thu thêm phụ phí điện nước hợp lý nếu khách thuê sử dụng điều hòa thường xuyên.\nCasper SC-12FB36A là lựa chọn tối ưu chi phí cho những ai cần công suất lớn hơn mức phổ thông mà không muốn chi thêm cho công nghệ Inverter.\n## Thời gian lắp đặt nhanh chóng\nVới thiết kế đơn giản, quy trình lắp đặt SC-12FB36A thường chỉ mất khoảng 2-3 giờ cho một bộ hoàn chỉnh, phù hợp cho các dự án cần bàn giao nhanh như cải tạo phòng trọ hoặc chuẩn bị đón khách thuê mới.",
    "SC-24FB36M":
        "Điều hòa Casper SC-24FB36M là model công suất lớn nhất trong dòng máy thường của Casper, đạt 23.900 BTU, phù hợp cho không gian rất rộng như phòng họp, cửa hàng, nhà xưởng nhỏ cần làm lạnh nhanh diện tích lớn.\n## Công suất lớn nhất dòng máy thường\nVới gần 24.000 BTU (tương đương 2.5HP), SC-24FB36M là lựa chọn phù hợp cho các không gian mở rộng trên 30m² như phòng họp công ty, showroom, cửa hàng kinh doanh hoặc nhà xưởng nhỏ cần làm lạnh nhanh một diện tích lớn mà không phải lắp nhiều máy công suất nhỏ.\n## Chế độ Turbo hỗ trợ làm lạnh nhanh\nChế độ Turbo giúp máy làm lạnh nhanh hơn trong những ngày nắng nóng cao điểm, đặc biệt hữu ích với không gian thương mại cần làm mát tức thời khi mở cửa đón khách vào buổi sáng.\n## Máy thường, tối ưu chi phí cho công suất lớn\nViệc không trang bị Inverter giúp SC-24FB36M có mức giá thấp hơn đáng kể so với dòng Inverter cùng công suất — phù hợp với các không gian kinh doanh chỉ bật điều hòa trong giờ hoạt động, không chạy liên tục 24/7.\n## Dàn đồng nguyên chất cho độ bền lâu dài\nVới công suất lớn, dàn trao đổi nhiệt bằng đồng nguyên chất phủ Gold Fin đóng vai trò quan trọng trong việc đảm bảo hiệu suất làm lạnh ổn định và độ bền của máy khi vận hành với tần suất cao trong môi trường thương mại.\n## Cần đội ngũ lắp đặt chuyên nghiệp\nVới công suất lớn, việc lắp đặt dàn nóng, đi đường ống gas và tính toán vị trí treo dàn lạnh cần được thực hiện bởi đội ngũ kỹ thuật có kinh nghiệm để đảm bảo hiệu quả làm lạnh tối ưu cho toàn bộ không gian. Điện Máy Xuân Son hỗ trợ khảo sát thực tế trước khi lắp đặt cho các model công suất lớn.\n## Cân nhắc lắp nhiều máy nhỏ hay một máy công suất lớn\nVới không gian rất rộng trên 30m², một số khách hàng phân vân giữa lắp một máy công suất lớn như SC-24FB36M hay chia thành hai máy công suất vừa. Ưu điểm của một máy công suất lớn là tiết kiệm chi phí lắp đặt ban đầu và đơn giản hóa việc bảo trì, nhưng nhược điểm là nếu máy hỏng sẽ mất mát toàn bộ khả năng làm lạnh của không gian, trong khi lắp nhiều máy nhỏ vẫn còn máy dự phòng hoạt động.\n## Điện năng tiêu thụ cần lưu ý khi kinh doanh\nVới công suất lớn hoạt động trong giờ kinh doanh, chủ cửa hàng nên tính toán kỹ chi phí điện hàng tháng, đặc biệt nếu dùng biểu giá điện kinh doanh có mức giá cao hơn hộ gia đình. Việc bảo trì định kỳ, vệ sinh lưới lọc bụi thường xuyên cũng giúp máy vận hành hiệu quả và tiết kiệm điện hơn.\nCasper SC-24FB36M là giải pháp làm lạnh tiết kiệm chi phí cho các không gian thương mại, kinh doanh cần công suất lớn mà không đòi hỏi công nghệ Inverter.",
    "JC-12IU36":
        "Điều hòa Casper JC-12IU36 là phiên bản công suất lớn hơn trong dòng ProAir Inverter, đạt 12.000 BTU, phù hợp cho phòng ngủ rộng hoặc phòng khách nhỏ cần làm mát nhanh mà vẫn tiết kiệm điện nhờ công nghệ biến tần.\n## Công nghệ Advanced Inverter cho phòng rộng hơn\nVới công suất lớn hơn model 9.000 BTU, JC-12IU36 vẫn giữ nguyên ưu điểm tiết kiệm điện của công nghệ Inverter — máy nén tự động điều chỉnh công suất theo nhiệt độ thực tế trong phòng thay vì chạy hết công suất liên tục, giúp giảm đáng kể hóa đơn tiền điện hàng tháng so với máy thường cùng công suất.\n## Phù hợp phòng 15-20m²\nCông suất 12.000 BTU (1.5HP) đáp ứng tốt nhu cầu làm lạnh cho phòng ngủ lớn, phòng khách căn hộ chung cư hoặc phòng làm việc có diện tích 15-20m² — lớn hơn một chút so với phòng ngủ tiêu chuẩn.\n## Chế độ Turbo và dàn đồng chống ăn mòn\nTương tự các model cùng dòng, máy được trang bị chế độ Turbo làm lạnh nhanh trong 30 giây và dàn đồng nguyên chất phủ Gold Fin chống ăn mòn, phù hợp với điều kiện thời tiết nóng ẩm tại Việt Nam.\n## Vận hành êm ái, ít tiếng ồn\nNhờ máy nén Inverter, JC-12IU36 vận hành êm hơn đáng kể so với dòng máy thường SC cùng công suất, phù hợp lắp đặt cho phòng ngủ hoặc phòng làm việc cần yên tĩnh.\n## Bảo hành dài hạn 3 năm toàn máy, 12 năm máy nén\nChính sách bảo hành của Casper cho dòng Inverter giúp khách hàng an tâm sử dụng lâu dài, hạn chế phát sinh chi phí sửa chữa trong những năm đầu.\n## Tính toán công suất phù hợp trước khi mua\nMột sai lầm phổ biến là chọn công suất điều hòa chỉ dựa theo diện tích phòng mà quên tính đến các yếu tố khác như hướng nắng, số người thường xuyên trong phòng, trần nhà cao hay thấp. Với phòng hướng Tây có nắng chiều gay gắt hoặc trần nhà cao trên 3m, nên ưu tiên công suất 12.000 BTU như JC-12IU36 thay vì mức 9.000 BTU phổ thông dù diện tích phòng chỉ khoảng 13-14m².\n## Chi phí lắp đặt và phụ kiện đi kèm\nNgoài giá máy, khách hàng nên dự trù thêm chi phí ống đồng, dây điện nếu khoảng cách giữa dàn lạnh và dàn nóng xa hơn tiêu chuẩn 3-4m đi kèm máy. Điện Máy Xuân Son luôn báo giá minh bạch phần phát sinh này trước khi lắp đặt để khách hàng chủ động ngân sách.\nNếu gia đình bạn cần một chiếc điều hòa Inverter công suất lớn hơn mức phổ thông 9.000 BTU mà vẫn giữ được mức giá hợp lý, Casper JC-12IU36 là lựa chọn đáng cân nhắc.\n## Vệ sinh và bảo trì định kỳ\nĐể duy trì hiệu suất làm lạnh và độ bền lâu dài, nên vệ sinh lưới lọc bụi của dàn lạnh khoảng 2-3 tháng một lần, đặc biệt trong mùa sử dụng cao điểm. Việc này giúp máy tiết kiệm điện hơn vì lưới lọc bám bụi sẽ cản luồng gió, khiến máy nén phải hoạt động vất vả hơn để đạt nhiệt độ cài đặt.",
    "QH-09IU36A":
        "Điều hòa Casper QH-09IU36A là dòng 2 chiều Inverter, vừa làm mát mùa hè vừa sưởi ấm mùa đông, công suất 10.000 BTU lạnh và 8.530 BTU sưởi, phù hợp cho các gia đình muốn dùng một máy quanh năm thay vì sắm riêng thiết bị sưởi vào mùa lạnh.\n## Dùng được quanh năm, không cần thiết bị sưởi riêng\nVới chức năng 2 chiều, QH-09IU36A vừa làm mát vào mùa hè vừa chuyển sang chế độ sưởi ấm vào mùa đông chỉ bằng một nút bấm trên điều khiển. Đây là giải pháp tiết kiệm không gian và chi phí hơn so với việc mua thêm quạt sưởi hoặc máy sưởi riêng cho mùa lạnh, đặc biệt phù hợp với các tỉnh miền Bắc và miền Trung có mùa đông rõ rệt.\n## Công nghệ Inverter tiết kiệm điện\nMáy nén biến tần giúp duy trì nhiệt độ ổn định ở cả hai chế độ làm mát và sưởi ấm, tiết kiệm điện hơn đáng kể so với các dòng 2 chiều không Inverter.\n## Phù hợp phòng ngủ, phòng làm việc nhỏ\nCông suất lạnh 10.000 BTU phù hợp phòng dưới 15m². Riêng công suất sưởi 8.530 BTU vẫn đủ giữ ấm hiệu quả cho không gian tương đương vào những ngày lạnh sâu.\n## Dàn đồng nguyên chất, phủ Gold Fin chống ăn mòn\nGiống các model cùng dòng, máy sử dụng dàn trao đổi nhiệt bằng đồng nguyên chất, giúp tăng độ bền khi vận hành cả hai chiều nóng-lạnh quanh năm.\n## Bảo hành 3 năm toàn máy, 12 năm máy nén\nChính sách bảo hành dài hạn của Casper áp dụng cho dòng Inverter 2 chiều, giúp khách hàng an tâm sử dụng liên tục cả bốn mùa trong năm.\n## Lưu ý khi sử dụng chế độ sưởi\nKhi chuyển sang chế độ sưởi vào mùa đông, nên đóng kín cửa phòng để giữ nhiệt hiệu quả, tương tự như khi dùng chế độ làm mát. Lưu ý chế độ sưởi bằng bơm nhiệt (heat pump) như trên QH-09IU36A sẽ giảm hiệu quả khi nhiệt độ ngoài trời xuống quá thấp, dưới khoảng 5°C, đây là đặc điểm chung của công nghệ 2 chiều chứ không riêng gì Casper.\n## So sánh chi phí với việc mua riêng máy sưởi\nMột máy sưởi dầu hoặc quạt sưởi công suất tương đương thường có giá vài trăm nghìn đến hơn một triệu đồng, cộng thêm chi phí điện khi dùng riêng vào mùa đông. Đầu tư vào điều hòa 2 chiều như QH-09IU36A giúp gộp chung hai nhu cầu làm mát và sưởi ấm vào một thiết bị duy nhất, tối ưu hơn về lâu dài dù giá mua ban đầu cao hơn máy 1 chiều thường.\nNếu gia đình bạn sống ở khu vực có mùa đông lạnh và muốn tiết kiệm chi phí bằng cách dùng một thiết bị cho cả hai mùa, Casper QH-09IU36A là lựa chọn đáng để đầu tư.",
    "QH-18IU36A":
        "Điều hòa Casper QH-18IU36A là dòng 2 chiều Inverter cao cấp nhất trong dải sản phẩm treo tường của Casper, công suất 18.000 BTU, tích hợp công nghệ i-Saving tiết kiệm điện và cảm biến I-Feel thông minh, phù hợp phòng khách rộng cần dùng quanh năm.\n## Công nghệ i-Saving tiết kiệm điện tới 30%\nQH-18IU36A được trang bị công nghệ i-Saving giúp tối ưu hoạt động của máy nén Inverter, tiết kiệm điện năng tới khoảng 30% so với chế độ vận hành thông thường — đáng kể với công suất lớn phải chạy nhiều giờ mỗi ngày cho phòng khách rộng.\n## Cảm biến I-Feel tự động điều chỉnh theo vị trí người dùng\nĐiểm nổi bật của model này là cảm biến I-Feel, giúp máy nhận diện nhiệt độ tại vị trí người dùng đang ngồi hoặc đứng thay vì chỉ đo nhiệt độ gần dàn lạnh, từ đó điều chỉnh luồng gió và công suất chính xác hơn, mang lại cảm giác mát đều và thoải mái hơn trong toàn bộ không gian phòng.\n## Công suất lớn, sưởi ấm mùa đông làm mát mùa hè\nVới 18.000 BTU cho cả hai chiều, model này phù hợp phòng khách, phòng họp rộng cần dùng quanh năm, đặc biệt hữu ích tại các khu vực có mùa đông lạnh cần công suất sưởi lớn.\n## Dàn đồng nguyên chất, độ bền cao khi vận hành liên tục\nDo phải hoạt động cả hai chiều nóng-lạnh quanh năm thay vì chỉ theo mùa như máy 1 chiều, dàn đồng nguyên chất phủ Gold Fin chống ăn mòn giúp đảm bảo độ bền lâu dài cho model công suất lớn này.\n## Bảo hành dài hạn, xứng đáng với phân khúc cao cấp\nCasper áp dụng chính sách bảo hành 3 năm toàn máy, 12 năm máy nén, tương xứng với vị trí là model cao cấp nhất trong dòng 2 chiều Inverter của hãng.\n## Xứng đáng đầu tư cho không gian sử dụng thường xuyên\nVới mức giá cao nhất trong dòng treo tường của Casper, QH-18IU36A phù hợp nhất khi lắp cho không gian sử dụng điều hòa gần như quanh năm — nơi giá trị tiết kiệm điện từ công nghệ i-Saving và độ chính xác của cảm biến I-Feel thực sự phát huy tác dụng, thay vì chỉ dùng vài tháng hè như nhiều hộ gia đình khác.\n## So với các thương hiệu Nhật Bản cùng phân khúc\nSo với các dòng 2 chiều Inverter cao cấp của Daikin hay Mitsubishi cùng công suất, QH-18IU36A có mức giá dễ tiếp cận hơn đáng kể trong khi vẫn sở hữu những công nghệ tiết kiệm điện và cảm biến thông minh tương đương, phù hợp với khách hàng ưu tiên hiệu quả sử dụng trên từng đồng chi phí bỏ ra.\nQH-18IU36A phù hợp với những gia đình có phòng khách rộng, mong muốn trải nghiệm công nghệ tiên tiến nhất trong tầm giá của Casper mà vẫn tiết kiệm hơn đáng kể so với các thương hiệu cao cấp Nhật Bản.",
    "QC-09IU36A":
        "Điều hòa Casper QC-09IU36A là dòng Inverter phổ thông công suất 9.500 BTU, mang đến mức giá dễ tiếp cận cho những gia đình muốn chuyển từ máy thường sang dùng công nghệ biến tần tiết kiệm điện mà không phải đầu tư quá nhiều.\n## Inverter tiết kiệm điện ở mức giá phổ thông\nQC-09IU36A thuộc phân khúc Inverter giá rẻ nhất trong dải sản phẩm Casper, giúp những gia đình có ngân sách vừa phải vẫn tiếp cận được công nghệ tiết kiệm điện mà trước đây chỉ có ở các dòng cao cấp hơn. Đây là lựa chọn phù hợp để nâng cấp từ máy thường lên Inverter mà không phải chi thêm quá nhiều so với dòng SC không Inverter.\n## Công suất 9.500 BTU phù hợp phòng ngủ tiêu chuẩn\nCông suất nhỉnh hơn một chút so với mức 9.000 BTU phổ biến, phù hợp phòng ngủ, phòng làm việc dưới 15m², kể cả những phòng có hướng nắng chiếu trực tiếp cần công suất làm lạnh dư dả hơn.\n## Dàn đồng nguyên chất, độ bền theo thời gian\nMáy sử dụng dàn trao đổi nhiệt bằng đồng nguyên chất, giúp tản nhiệt hiệu quả và bền bỉ hơn so với dàn nhôm giá rẻ thường thấy ở một số thương hiệu khác.\n## Remote điều khiển trực quan, dễ sử dụng\nBộ điều khiển từ xa của Casper được thiết kế đơn giản, dễ sử dụng cho mọi lứa tuổi trong gia đình, từ người lớn tuổi đến trẻ nhỏ.\n## Bảo hành chính hãng, hỗ trợ lắp đặt tận nơi\nSản phẩm được bảo hành theo chính sách chính hãng Casper tại Việt Nam. Điện Máy Xuân Son hỗ trợ khảo sát, lắp đặt và hướng dẫn sử dụng miễn phí ngay sau khi giao hàng.\n## Khác biệt so với dòng JC cùng công suất\nQC-09IU36A và JC-09IU36 đều là dòng Inverter 9.000 BTU của Casper nhưng thuộc hai phân dòng sản phẩm khác nhau về thiết kế và một số tính năng phụ trợ. Về hiệu quả làm lạnh và tiết kiệm điện, cả hai đều sử dụng chung công nghệ biến tần lõi nên gần như tương đương nhau, khách hàng có thể chọn theo mức giá và thiết kế phù hợp sở thích hơn là quá đặt nặng khác biệt kỹ thuật.\n## Thời gian bảo hành và chi phí bảo trì\nCũng như các model Inverter khác của Casper, QC-09IU36A được bảo hành 3 năm toàn máy và 12 năm máy nén. Chi phí bảo trì định kỳ (vệ sinh dàn lạnh, dàn nóng, bơm gas nếu cần) nên thực hiện 6 tháng đến 1 năm một lần để duy trì hiệu suất làm lạnh tối ưu và tiết kiệm điện tốt nhất.\nCasper QC-09IU36A phù hợp với những ai muốn trải nghiệm công nghệ Inverter lần đầu với mức chi phí đầu tư ở mức thấp nhất có thể trong phân khúc này.\n## Tư vấn và hỗ trợ sau bán hàng\nĐiện Máy Xuân Son hỗ trợ tư vấn chọn công suất phù hợp trước khi mua, tránh tình trạng chọn sai công suất khiến máy chạy quá tải hoặc lãng phí điện năng. Sau khi lắp đặt, đội ngũ kỹ thuật hướng dẫn sử dụng điều khiển, các chế độ tiết kiệm điện cơ bản để khách hàng khai thác tối đa hiệu quả của máy.",
    # -- Nagakawa (bổ sung) --
    "NS-C12R2T30":
        "Công suất lớn hơn cho phòng vừa, giá cạnh tranh trong phân khúc máy "
        "thường.\n"
        "## Phù hợp phòng cho thuê, nhà trọ\n"
        "Mức giá phải chăng khiến model này được nhiều chủ nhà trọ lựa chọn lắp "
        "đặt số lượng lớn.",
    "NS-C18R2T30":
        "Công suất lớn cho phòng khách rộng, giá cạnh tranh trong phân khúc máy "
        "thường.\n"
        "## Giải pháp tiết kiệm cho không gian lớn\n"
        "Phù hợp cửa hàng, văn phòng nhỏ cần làm lạnh diện tích lớn mà không "
        "muốn đầu tư quá nhiều.",
    "NS-C24R2U86":
        "Công suất lớn nhất dòng thường, phù hợp không gian rất rộng.\n"
        "## Bảo hành máy nén 10 năm\n"
        "Chính sách bảo hành dài hạn cho máy nén dù ở phân khúc giá thường, giúp "
        "khách hàng an tâm hơn.",
    "NIS-C12R2U51":
        "Inverter công suất vừa, tiết kiệm điện, phù hợp phòng 15-20m².\n"
        "## Bảo hành máy nén 10 năm\n"
        "Chính sách bảo hành dài hạn hiếm có ở phân khúc giá rẻ, giúp khách hàng "
        "an tâm hơn khi lựa chọn.",
    "NIS-C24R2U51":
        "Inverter công suất mạnh nhất dòng 1 chiều, phù hợp không gian rất "
        "rộng.\n"
        "## Phù hợp không gian rộng, giá vẫn cạnh tranh\n"
        "So với các thương hiệu lớn cùng công suất, đây là lựa chọn tiết kiệm "
        "chi phí đáng cân nhắc.",
    "NIS-A12R2T29":
        "2 chiều Inverter công suất vừa, sưởi ấm mùa đông làm mát mùa hè.\n"
        "## Lựa chọn kinh tế cho máy 2 chiều\n"
        "Giúp gia đình có ngân sách vừa phải vẫn sở hữu được máy điều hòa dùng "
        "quanh năm.",
    # -- Midea --
    "MSFQ-09CRN8":
        "Máy thường giá tốt của Midea, phù hợp phòng ngủ nhỏ.\n"
        "## Bảo hành máy nén 5 năm\n"
        "Chính sách bảo hành dài hơn nhiều thương hiệu cùng phân khúc giá, giúp "
        "khách hàng an tâm sử dụng.",
    "MSFQ-12CRN8":
        "Công suất lớn hơn cho phòng vừa, giá tốt trong phân khúc máy thường.\n"
        "## Phù hợp gia đình ngân sách vừa phải\n"
        "Mức giá dễ tiếp cận nhưng vẫn đảm bảo bảo hành máy nén dài hạn.",
    "MSFQ-24CRN8":
        "Công suất lớn nhất dòng thường, phù hợp không gian rất rộng.\n"
        "## Chế độ Turbo làm lạnh nhanh\n"
        "Giúp máy hạ nhiệt độ phòng nhanh chóng trong những ngày nắng nóng cao "
        "điểm.",
    "MSCE-10CRFN8":
        "Inverter tiết kiệm điện, thương hiệu phổ biến dễ tìm phụ tùng.\n"
        "## Cân bằng giá thành và tiết kiệm điện\n"
        "Phù hợp gia đình muốn chuyển sang Inverter mà không phải chi quá nhiều.",
    "MSCE-13CRFN8":
        "Inverter công suất lớn hơn, phù hợp phòng 16-23m².\n"
        "## Tiết kiệm điện cho phòng vừa\n"
        "Công suất phù hợp phòng ngủ lớn hoặc phòng khách nhỏ, tiết kiệm điện "
        "lâu dài.",
    "MSCE-19CRFN8":
        "Inverter công suất lớn cho phòng khách rộng, tiết kiệm điện.\n"
        "## Phù hợp không gian 24-35m²\n"
        "Công suất 18.000 BTU đáp ứng tốt nhu cầu làm lạnh cho phòng khách rộng.",
    "MSAFBU-10HRDN8":
        "2 chiều sưởi ấm mùa đông làm mát mùa hè, giá hợp lý.\n"
        "## Dùng được quanh năm\n"
        "Chức năng sưởi giúp gia đình không cần mua thêm thiết bị sưởi riêng vào "
        "mùa lạnh.",
    "MSAFBU-13HRDN8":
        "2 chiều công suất vừa, sưởi ấm mùa đông làm mát mùa hè.\n"
        "## Phù hợp phòng 15-20m²\n"
        "Công suất đáp ứng tốt nhu cầu 2 chiều cho phòng ngủ hoặc phòng khách "
        "nhỏ.",
    # -- Mitsubishi Heavy --
    "SRK/SRC09CTR-S5":
        "Thương hiệu Nhật Bản bền bỉ, phù hợp gia đình muốn máy chạy ổn định "
        "nhiều năm.\n"
        "## Độ bền theo tiêu chuẩn Nhật Bản\n"
        "Mitsubishi Heavy nổi tiếng với độ bền cao, ít hỏng vặt trong quá trình "
        "sử dụng lâu dài.",
    "SRK/SRC12CT-S5":
        "Công suất lớn hơn, phù hợp phòng khách vừa, thương hiệu Nhật Bản bền "
        "bỉ.\n"
        "## Phù hợp phòng 15-20m²\n"
        "Công suất 12.000 BTU đáp ứng tốt nhu cầu làm lạnh cho phòng ngủ lớn "
        "hoặc phòng khách nhỏ.",
    "SRK/SRC18CS-S5":
        "Công suất lớn cho phòng khách rộng, thương hiệu Nhật Bản bền bỉ.\n"
        "## Phù hợp không gian dưới 30m²\n"
        "Công nghệ 3D auto giúp luồng gió phân bố đều khắp phòng.",
    "SRK/SRC24CS-S5":
        "Công suất lớn nhất dòng thường, phù hợp không gian rất rộng.\n"
        "## Phù hợp không gian dưới 40m²\n"
        "Công suất mạnh mẽ đáp ứng nhu cầu làm lạnh cho phòng họp, cửa hàng "
        "lớn.",
    "SRK10YZP-W5":
        "Inverter Nhật Bản tiết kiệm điện, làm lạnh nhanh, vận hành êm ái.\n"
        "## Vận hành êm, phù hợp phòng ngủ\n"
        "Công nghệ DC PAM Inverter giúp máy hoạt động êm ái, không gây tiếng ồn "
        "khi ngủ ban đêm.",
    "SRK13YZP-W5":
        "Inverter công suất lớn hơn, phù hợp phòng khách vừa, thương hiệu Nhật "
        "Bản bền bỉ.\n"
        "## Tiết kiệm điện cho không gian lớn hơn\n"
        "Công suất 12.000 BTU phù hợp phòng 15-20m², vẫn giữ được khả năng tiết "
        "kiệm điện.",
    "SRK18YZP-W5":
        "Inverter công suất lớn cho phòng khách rộng, công nghệ DC PAM Inverter "
        "tiết kiệm điện.\n"
        "## Phù hợp không gian dưới 30m²\n"
        "Công nghệ tự làm sạch giúp máy luôn sạch sẽ, hạn chế nấm mốc tích tụ.",
    "SRK/SRC25ZSPS-W5":
        "2 chiều Inverter Nhật Bản, sưởi ấm mùa đông làm mát mùa hè, công nghệ "
        "Jet Flow.\n"
        "## Công nghệ Jet Flow phân phối gió nhanh\n"
        "Giúp luồng khí lạnh/nóng lan tỏa nhanh khắp phòng, rút ngắn thời gian "
        "đạt nhiệt độ mong muốn.",
    # -- Mitsubishi Electric --
    "MS-JS25VF":
        "Dòng phổ thông của Mitsubishi Electric, làm lạnh nhanh cho phòng nhỏ.\n"
        "## Thương hiệu Nhật Bản uy tín\n"
        "Mitsubishi Electric là một trong những thương hiệu điều hòa cao cấp "
        "được ưa chuộng tại Việt Nam.",
    "MS-JS35VF":
        "Công suất lớn hơn dòng phổ thông, phù hợp phòng khách vừa.\n"
        "## Phù hợp phòng 15-20m²\n"
        "Công suất 12.000 BTU đáp ứng tốt nhu cầu làm lạnh cho phòng ngủ lớn "
        "hoặc phòng khách nhỏ.",
    "MS-JS50VF":
        "Công suất lớn cho phòng khách rộng, làm lạnh nhanh, luồng gió thổi "
        "xa.\n"
        "## Phù hợp không gian trên 25m²\n"
        "Luồng gió thổi xa và rộng giúp làm lạnh đều khắp phòng lớn.",
    "MSY/MUY-JA50VF":
        "Inverter công suất lớn cho phòng khách rộng, tiết kiệm điện vượt "
        "trội.\n"
        "## Phù hợp không gian trên 25m²\n"
        "Công suất 18.000 BTU Inverter đáp ứng tốt nhu cầu làm lạnh nhanh cho "
        "phòng lớn.",
    "MSZ/MUZ-HT35VF":
        "2 chiều Inverter công suất vừa, sưởi ấm mùa đông làm mát mùa hè.\n"
        "## Phù hợp phòng 15-20m²\n"
        "Công suất đáp ứng tốt nhu cầu 2 chiều cho phòng ngủ lớn hoặc phòng "
        "khách nhỏ.",
    # -- Sumikura (biến thể OSAKA khai báo trước để khớp đúng, tránh trùng tiền tố) --
    "APS/APO-092 OSAKA":
        "Inverter tiết kiệm điện, giá cạnh tranh, linh kiện nhập khẩu Malaysia.\n"
        "## Dòng Inverter giá tốt\n"
        "OSAKA là dòng Inverter phổ thông của Sumikura, tiết kiệm điện hơn đáng "
        "kể so với máy thường cùng công suất.",
    "APS/APO-120 OSAKA":
        "Inverter công suất lớn hơn, phù hợp phòng 15-20m².\n"
        "## Tiết kiệm điện cho phòng vừa\n"
        "Công suất 12.000 BTU Inverter phù hợp phòng ngủ lớn hoặc phòng khách "
        "nhỏ.",
    "APS/APO-092":
        "Giá rẻ, phù hợp phòng nhỏ, linh kiện nhập khẩu Malaysia.\n"
        "## Lựa chọn tiết kiệm chi phí\n"
        "Sumikura là thương hiệu giá rẻ phù hợp gia đình muốn tối ưu ngân sách "
        "đầu tư ban đầu.",
    "APS/APO-120":
        "Công suất lớn hơn cho phòng vừa, vẫn giữ mức giá cạnh tranh.\n"
        "## Phù hợp phòng cho thuê, nhà trọ\n"
        "Mức giá phải chăng khiến model này được nhiều chủ nhà trọ lựa chọn lắp "
        "đặt số lượng lớn.",
    "APS/APO-180":
        "Công suất lớn cho phòng khách rộng, giá cạnh tranh trong phân khúc máy "
        "thường.\n"
        "## Giải pháp tiết kiệm cho không gian lớn\n"
        "Phù hợp cửa hàng, văn phòng nhỏ cần làm lạnh diện tích lớn mà không "
        "muốn đầu tư quá nhiều.",
    "APS/APO-240":
        "Công suất lớn nhất dòng thường, phù hợp không gian rất rộng.\n"
        "## Phù hợp phòng 35-40m²\n"
        "Công suất 24.000 BTU đáp ứng tốt nhu cầu làm lạnh cho không gian rất "
        "rộng.",
    "APS/APO-H092":
        "2 chiều sưởi ấm mùa đông làm mát mùa hè, phù hợp phòng nhỏ.\n"
        "## Dùng được quanh năm\n"
        "Chức năng sưởi giúp gia đình không cần mua thêm thiết bị sưởi riêng "
        "vào mùa lạnh.",
    "APS/APO-H120":
        "2 chiều công suất vừa, sưởi ấm mùa đông làm mát mùa hè.\n"
        "## Phù hợp phòng 15-20m²\n"
        "Công suất đáp ứng tốt nhu cầu 2 chiều cho phòng ngủ hoặc phòng khách "
        "nhỏ.",
    # -- Gree --
    "BD9CN":
        "Làm lạnh nhanh, giá hợp lý, phù hợp phòng ngủ nhỏ.\n"
        "## Công nghệ làm lạnh nhanh\n"
        "Gree được biết đến với khả năng làm lạnh nhanh, phù hợp những ngày "
        "nắng nóng cao điểm.",
    "BD12CN":
        "Công suất lớn hơn cho phòng vừa, giá tốt trong phân khúc máy thường.\n"
        "## Phù hợp phòng 15-20m²\n"
        "Công suất 12.000 BTU đáp ứng tốt nhu cầu làm lạnh cho phòng ngủ lớn "
        "hoặc phòng khách nhỏ.",
    "BD18CN":
        "Công suất lớn cho phòng khách rộng, đèn LED hiển thị nhiệt độ.\n"
        "## Cảm biến I-Feel thông minh\n"
        "Giúp máy tự động điều chỉnh nhiệt độ theo vị trí người dùng trong "
        "phòng.",
    "BD9CI":
        "Inverter tiết kiệm điện, bảo hành máy nén dài hạn.\n"
        "## Bảo hành máy nén dài hạn\n"
        "Chính sách bảo hành máy nén lên đến 10 năm giúp khách hàng an tâm sử "
        "dụng.",
    "BD12CI":
        "Inverter công suất lớn hơn, làm lạnh nhanh gấp 3 lần, phù hợp phòng "
        "vừa.\n"
        "## Làm lạnh nhanh cho phòng vừa\n"
        "Công suất 12.000 BTU phù hợp phòng khách nhỏ hoặc phòng ngủ lớn.",
    "BD9HI":
        "2 chiều Inverter sưởi ấm mùa đông làm mát mùa hè, bảo hành máy nén dài "
        "hạn.\n"
        "## Máy nén bảo hành lên đến 10 năm\n"
        "Chính sách bảo hành dài hạn cho máy nén giúp khách hàng an tâm khi đầu "
        "tư dòng 2 chiều.",
    "BD12HI":
        "2 chiều Inverter công suất vừa, sưởi ấm mùa đông làm mát mùa hè.\n"
        "## Phù hợp phòng 15-20m²\n"
        "Công suất đáp ứng tốt nhu cầu 2 chiều cho phòng ngủ lớn hoặc phòng "
        "khách nhỏ.",
    "COSMO12CI":
        "Thiết kế sang trọng đường cong mềm mại, Inverter tiết kiệm điện tới "
        "60%.\n"
        "## Thiết kế cao cấp khác biệt\n"
        "Dòng Cosmo có ngoại hình sang trọng hơn dòng phổ thông, phù hợp không "
        "gian nội thất hiện đại.",
    # -- Sharp --
    "AH-X10CEW":
        "Công nghệ J-tech Inverter tiết kiệm điện tới 60%, thương hiệu Nhật Bản "
        "quen thuộc.\n"
        "## Công nghệ J-tech Inverter\n"
        "Giúp máy nén hoạt động hiệu quả hơn, tiết kiệm điện đáng kể so với "
        "công nghệ Inverter thông thường.",
    "AH-X13CEW":
        "Inverter công suất lớn hơn, làm lạnh nhanh, tiết kiệm điện cho phòng "
        "vừa.\n"
        "## Có thể chỉnh nhiệt độ thấp tới 14°C\n"
        "Phù hợp những ngày nắng nóng gay gắt cần làm lạnh sâu và nhanh.",
    "AH-X18CEW":
        "Inverter công suất lớn cho phòng khách rộng, làm lạnh nhanh.\n"
        "## Phù hợp không gian rộng\n"
        "Công suất 18.000 BTU đáp ứng tốt nhu cầu làm lạnh nhanh cho phòng "
        "khách hoặc cửa hàng nhỏ.",
    "AH-X10DEW":
        "J-tech Inverter, Plasmacluster khử khuẩn, tiết kiệm điện tới 65%.\n"
        "## Công nghệ Plasmacluster Ion\n"
        "Giúp khử mùi, diệt khuẩn trong không khí, mang lại không gian sống "
        "trong lành hơn.",
    "AH-X13DEW":
        "J-tech Inverter công suất lớn hơn, Plasmacluster khử khuẩn, làm lạnh "
        "nhanh hơn 28%.\n"
        "## Làm lạnh nhanh hơn 28%\n"
        "Công nghệ Super Jet giúp hạ nhiệt độ phòng nhanh chóng chỉ trong vài "
        "phút.",
    "AH-XP10DSW":
        "Plasmacluster Ion khử khuẩn 3 bước, J-tech Inverter tiết kiệm điện.\n"
        "## Khử khuẩn 3 bước\n"
        "Công nghệ Plasmacluster Ion tác động lên vi khuẩn qua 3 giai đoạn, "
        "mang lại không khí sạch hơn.",
    "AH-XP13DSW":
        "Plasmacluster Ion công suất lớn hơn, khử khuẩn diệt mùi hiệu quả.\n"
        "## Phù hợp phòng 15-20m²\n"
        "Công suất 12.000 BTU đáp ứng tốt nhu cầu làm lạnh cho phòng vừa.",
    "AH-XP10WHW":
        "Tích hợp AIoT điều khiển từ xa qua điện thoại, J-tech Inverter tiết "
        "kiệm điện.\n"
        "## Điều khiển từ xa qua smartphone\n"
        "Cho phép bật/tắt, chỉnh nhiệt độ từ xa, tiện lợi khi muốn làm mát "
        "phòng trước khi về nhà.",
    # -- Comfee --
    "CFS-09FGY":
        "Điều hòa Comfee CFS-09FGY là dòng máy lạnh phổ thông công suất 9.000 BTU, không trang bị Inverter, đến từ thương hiệu Comfee — nhánh giá trị của tập đoàn Midea. Đây là lựa chọn giá tốt cho những gia đình cần làm mát cơ bản cho phòng ngủ, phòng làm việc nhỏ mà không đòi hỏi nhiều tính năng phức tạp.\n## Thương hiệu Comfee thuộc tập đoàn Midea\nComfee là thương hiệu con của Midea — một trong những tập đoàn sản xuất thiết bị điện lạnh lớn nhất thế giới, nên dù định vị giá rẻ, sản phẩm vẫn thừa hưởng nền tảng công nghệ và dây chuyền sản xuất đạt chuẩn quốc tế. Đây là điểm khác biệt so với nhiều thương hiệu giá rẻ trôi nổi khác trên thị trường.\n## Máy thường, giá thành cạnh tranh nhất phân khúc\nKhông có Inverter giúp CFS-09FGY có mức giá thuộc nhóm thấp nhất trong các thương hiệu điều hòa hiện có tại Điện Máy Xuân Son, phù hợp với người mua ưu tiên chi phí đầu tư ban đầu hơn là tiết kiệm điện dài hạn.\n## Phù hợp phòng ngủ, phòng làm việc dưới 15m²\nCông suất 9.000 BTU (2,64kW) đáp ứng tốt nhu cầu làm mát cho không gian dưới 15m², phù hợp phòng ngủ cá nhân, phòng trọ hoặc phòng làm việc tại nhà.\n## Gas lạnh R32 thân thiện môi trường\nMáy sử dụng gas R32 — loại môi chất lạnh hiện đại, hiệu suất làm lạnh cao hơn và ít gây hại tầng ozone hơn so với gas R22 thế hệ cũ, đồng thời tiêu thụ ít gas hơn cho cùng hiệu quả làm lạnh.\n## Nên chọn máy thường hay Inverter?\nNếu gia đình chỉ bật điều hòa vài tiếng mỗi tối để ngủ, CFS-09FGY là lựa chọn hợp lý vì chênh lệch tiền điện so với Inverter không đáng kể trong thời gian sử dụng ngắn. Nếu dùng liên tục cả ngày, nên cân nhắc dòng CFS-10VGX Inverter cùng hãng để tiết kiệm điện về lâu dài.\n## Bảo hành chính hãng\nSản phẩm được bảo hành chính hãng, Điện Máy Xuân Son hỗ trợ lắp đặt và tư vấn sử dụng miễn phí ngay sau khi mua.\nNếu bạn cần một chiếc điều hòa giá tốt cho phòng nhỏ với ngân sách hạn chế, Comfee CFS-09FGY là lựa chọn đáng cân nhắc để tối ưu chi phí đầu tư ban đầu.\n## Thiết kế đơn giản, dễ vệ sinh bảo trì\nDàn lạnh của CFS-09FGY có thiết kế mặt nạ phẳng, ít góc cạnh, giúp việc lau chùi bụi bẩn bám bên ngoài trở nên dễ dàng hơn. Lưới lọc bụi có thể tháo lắp nhanh chóng để vệ sinh định kỳ mà không cần dụng cụ chuyên dụng hay gọi thợ hỗ trợ.\n## Độ ồn và vị trí lắp đặt phù hợp\nVì là máy thường không Inverter, CFS-09FGY sẽ có tiếng ồn rõ hơn một chút mỗi khi máy nén bật lại so với dòng Inverter, nên cân nhắc không lắp quá sát đầu giường nếu người dùng nhạy cảm với tiếng ồn khi ngủ. Dàn nóng nên đặt nơi thoáng, tránh các góc tường kín gió làm giảm hiệu quả tản nhiệt.",
    "CFS-12FGY":
        "Điều hòa Comfee CFS-12FGY là phiên bản công suất lớn hơn trong dòng máy thường của Comfee, đạt 12.000 BTU (3,52kW), phù hợp cho phòng ngủ rộng hoặc phòng khách nhỏ cần làm lạnh nhanh với chi phí đầu tư hợp lý.\n## Công suất lớn hơn cho phòng 15-20m²\nSo với model 9.000 BTU cùng dòng, CFS-12FGY đáp ứng tốt hơn cho các không gian rộng hơn phòng ngủ tiêu chuẩn, phù hợp phòng khách căn hộ chung cư hoặc phòng làm việc có diện tích 15-20m².\n## Máy thường, tối ưu chi phí cho công suất lớn\nViệc không trang bị Inverter giúp CFS-12FGY giữ mức giá cạnh tranh hơn đáng kể so với dòng Inverter cùng công suất, phù hợp các không gian không sử dụng điều hòa liên tục cả ngày.\n## Thương hiệu Comfee — nhánh giá trị của Midea\nLà thương hiệu con của tập đoàn Midea, Comfee thừa hưởng nền tảng công nghệ sản xuất điều hòa lâu năm, mang đến sản phẩm có độ tin cậy tốt dù ở phân khúc giá phải chăng.\n## Gas R32 hiệu suất cao\nMáy sử dụng gas lạnh R32 hiện đại, hiệu suất làm lạnh cao hơn thế hệ gas cũ, giúp máy nén hoạt động hiệu quả hơn với cùng lượng điện tiêu thụ.\n## Lắp đặt và bảo trì đơn giản\nVới thiết kế đơn giản của dòng máy thường, việc lắp đặt CFS-12FGY diễn ra nhanh chóng, thường chỉ mất khoảng 2-3 giờ cho một bộ hoàn chỉnh. Nên vệ sinh lưới lọc bụi định kỳ 2-3 tháng một lần để duy trì hiệu quả làm lạnh tốt nhất.\n## Phù hợp mô hình cho thuê, kinh doanh nhỏ\nMức giá phải chăng khiến CFS-12FGY phù hợp cho các chủ nhà trọ, chung cư mini cần lắp đặt số lượng lớn mà vẫn tối ưu được ngân sách đầu tư ban đầu cho từng phòng.\nComfee CFS-12FGY là lựa chọn hợp lý cho những ai cần công suất lớn hơn mức phổ thông mà không muốn chi thêm cho công nghệ Inverter, đặc biệt phù hợp với các không gian không sử dụng điều hòa liên tục.\n## So sánh với model 9.000 BTU cùng dòng\nSo với CFS-09FGY, phiên bản 12.000 BTU này có mức giá cao hơn một khoảng vừa phải nhưng đổi lại công suất làm lạnh lớn hơn đáng kể, phù hợp hơn cho phòng có diện tích lớn hoặc hướng nắng gắt. Nếu không chắc chắn về diện tích thực tế, nên chọn công suất lớn hơn một chút để tránh tình trạng máy phải chạy hết công suất liên tục mà vẫn không đủ mát.\n## Khả năng chịu tải trong điều kiện nắng nóng\nVới công suất 12.000 BTU, máy vẫn duy trì được hiệu quả làm lạnh ổn định ngay cả trong những ngày nắng nóng cao điểm của mùa hè miền Bắc, khi nhiệt độ ngoài trời có thể vượt 38-40°C liên tục nhiều ngày.",
    "CFS-10VGX":
        "Điều hòa Comfee CFS-10VGX là dòng Inverter công suất 9.350 BTU (2,74kW), trang bị hệ thống lọc kép Dual Filtration, mang đến giải pháp làm mát tiết kiệm điện với mức giá dễ tiếp cận hơn nhiều thương hiệu Inverter khác trên thị trường.\n## Công nghệ Inverter tiết kiệm điện\nMáy nén biến tần giúp CFS-10VGX duy trì nhiệt độ phòng ổn định mà không cần bật tắt liên tục như máy thường, tiết kiệm điện năng đáng kể cho những gia đình sử dụng điều hòa từ 6 tiếng mỗi ngày trở lên.\n## Hệ thống lọc kép Dual Filtration\nĐiểm nổi bật của CFS-10VGX là hệ thống lọc kép, giúp loại bỏ triệt để bụi bẩn và các hạt nhỏ trong không khí qua hai lớp lọc liên tiếp, mang lại không khí trong lành hơn cho phòng ngủ hoặc phòng làm việc, đặc biệt hữu ích với gia đình có trẻ nhỏ hoặc người dễ dị ứng bụi.\n## Phù hợp phòng dưới 15m²\nCông suất 9.350 BTU nhỉnh hơn một chút so với mức phổ thông 9.000 BTU, phù hợp phòng ngủ, phòng làm việc dưới 15m², kể cả các phòng có hướng nắng cần công suất làm lạnh dư dả hơn một chút.\n## Vận hành êm ái nhờ công nghệ Inverter\nSo với dòng máy thường CFS-09FGY, CFS-10VGX vận hành êm hơn đáng kể nhờ máy nén biến tần không phải bật tắt đột ngột, phù hợp lắp đặt cho phòng ngủ cần yên tĩnh vào ban đêm.\n## Gas R32, thân thiện môi trường\nMáy sử dụng gas lạnh R32 hiện đại, hiệu suất làm lạnh cao và ít tác động đến môi trường hơn so với các loại gas thế hệ cũ.\n## Giá cạnh tranh trong phân khúc Inverter\nSo với các thương hiệu Inverter khác cùng công suất, CFS-10VGX có mức giá dễ tiếp cận hơn đáng kể nhờ lợi thế sản xuất quy mô lớn của tập đoàn Midea, giúp nhiều gia đình tiếp cận được công nghệ tiết kiệm điện mà không phải chi quá nhiều.\nComfee CFS-10VGX phù hợp với những ai muốn có máy Inverter tiết kiệm điện kèm khả năng lọc không khí tốt hơn, với mức giá vẫn nằm trong tầm ngân sách phổ thông.\n## Thời gian hoàn vốn khi nâng cấp lên Inverter\nVới mức chênh lệch giá không quá lớn so với máy thường cùng công suất, CFS-10VGX thường hoàn lại phần chênh lệch này sau khoảng 1-2 năm sử dụng liên tục nhờ tiền điện tiết kiệm được, sau đó là khoản lãi ròng cho những năm sử dụng tiếp theo.\n## Độ bền và tuổi thọ máy nén Inverter\nMáy nén biến tần trên CFS-10VGX được thiết kế để khởi động êm ái thay vì giật cục như máy thường, giúp giảm hao mòn cơ khí theo thời gian, góp phần kéo dài tuổi thọ tổng thể của thiết bị nếu được bảo trì đúng cách.\n## Lưu ý khi chọn mua\nTrước khi quyết định, khách hàng nên xác định rõ nhu cầu sử dụng thực tế: nếu phòng thường xuyên đóng kín cửa và bật điều hòa cả ngày, CFS-10VGX sẽ phát huy tối đa ưu điểm tiết kiệm điện; còn nếu chỉ dùng vài tiếng buổi tối, hiệu quả tiết kiệm sẽ ít rõ rệt hơn nhưng máy vẫn vận hành êm ái và có khả năng lọc không khí tốt hơn máy thường.",
    "CFS-13VGX":
        "Điều hòa Comfee CFS-13VGX là dòng Inverter công suất 12.000 BTU (3,52kW), phù hợp cho phòng ngủ lớn hoặc phòng khách nhỏ cần làm mát hiệu quả và tiết kiệm điện hơn so với máy thường cùng công suất.\n## Công suất lớn hơn, vẫn giữ ưu điểm Inverter\nVới 12.000 BTU, CFS-13VGX đáp ứng tốt nhu cầu làm lạnh cho không gian 15-20m², lớn hơn đáng kể so với phòng ngủ tiêu chuẩn, trong khi vẫn giữ nguyên lợi thế tiết kiệm điện của công nghệ biến tần so với dòng máy thường CFS-12FGY.\n## Hệ thống lọc kép Dual Filtration\nCũng như các model Inverter khác cùng hãng, CFS-13VGX trang bị hệ thống lọc kép giúp loại bỏ bụi bẩn hiệu quả hơn, mang lại không khí trong lành cho không gian sử dụng.\n## Tiết kiệm điện đáng kể khi dùng thường xuyên\nVới công suất lớn hơn, khoản tiền điện tiết kiệm được từ công nghệ Inverter càng rõ rệt hơn so với model 9.000 BTU, đặc biệt khi phòng khách hoặc phòng ngủ sử dụng điều hòa liên tục nhiều giờ mỗi ngày.\n## Vận hành êm ái, phù hợp phòng ngủ\nMáy nén biến tần giúp CFS-13VGX vận hành êm hơn đáng kể so với máy thường, hạn chế tiếng ồn gây khó chịu khi ngủ vào ban đêm, đặc biệt quan trọng với phòng ngủ có trẻ nhỏ.\n## Gas R32 và thiết kế tiết kiệm không gian\nMáy sử dụng gas lạnh R32 hiện đại, kết hợp thiết kế dàn lạnh gọn gàng, dễ dàng lắp đặt trong nhiều kiểu không gian nội thất khác nhau mà không chiếm quá nhiều diện tích tường.\n## Chi phí hợp lý so với các thương hiệu lớn\nNhờ lợi thế sản xuất của tập đoàn Midea, CFS-13VGX có mức giá cạnh tranh hơn đáng kể so với các thương hiệu Inverter lớn cùng công suất, phù hợp với khách hàng muốn tối ưu chi phí mà vẫn có đầy đủ tính năng tiết kiệm điện.\nComfee CFS-13VGX là lựa chọn hợp lý cho gia đình cần công suất Inverter lớn hơn mức phổ thông mà vẫn giữ được ngân sách đầu tư ở mức vừa phải.\n## Phù hợp phòng khách căn hộ chung cư\nVới công suất 12.000 BTU, CFS-13VGX là một trong những lựa chọn phổ biến để lắp cho phòng khách căn hộ chung cư có diện tích vừa phải, nơi vừa cần đủ mát vừa không muốn tiếng ồn máy nén ảnh hưởng đến sinh hoạt chung của gia đình.\n## Bảo hành và dịch vụ hậu mãi\nSản phẩm được bảo hành chính hãng theo tiêu chuẩn của Comfee tại Việt Nam. Điện Máy Xuân Son hỗ trợ tư vấn công suất phù hợp trước khi mua và hướng dẫn sử dụng các chế độ tiết kiệm điện sau khi lắp đặt hoàn tất.\n## Kết hợp với rèm cửa, cách nhiệt để tăng hiệu quả\nĐể CFS-13VGX phát huy tối đa hiệu quả tiết kiệm điện, nên kết hợp thêm rèm cản nắng cho các cửa sổ hướng Tây hoặc hướng Nam, hạn chế nhiệt hấp thụ vào phòng khiến máy phải hoạt động vất vả hơn để duy trì nhiệt độ cài đặt.",
    "CFS-18VGX":
        "Điều hòa Comfee CFS-18VGX là dòng Inverter công suất lớn 18.000 BTU (5,28kW), phù hợp cho phòng khách rộng, phòng họp nhỏ hoặc cửa hàng kinh doanh cần làm lạnh nhanh mà vẫn tiết kiệm điện.\n## Công suất lớn, phù hợp không gian rộng\nVới 18.000 BTU, CFS-18VGX đủ sức làm lạnh hiệu quả cho các không gian trên 25m² như phòng khách, phòng họp công ty hoặc cửa hàng diện tích vừa, lớn hơn nhiều so với các model phổ thông 9.000-12.000 BTU.\n## Công nghệ Inverter tiết kiệm điện cho công suất lớn\nVới công suất lớn, ưu điểm tiết kiệm điện của công nghệ Inverter càng phát huy rõ rệt hơn so với các dòng máy thường cùng công suất, giúp giảm đáng kể hóa đơn tiền điện hàng tháng nếu sử dụng thường xuyên trong không gian thương mại hoặc gia đình đông người.\n## Hệ thống lọc kép cho không khí sạch hơn\nMáy trang bị hệ thống lọc kép Dual Filtration, phù hợp với không gian đông người sử dụng như phòng khách gia đình nhiều thế hệ hoặc phòng họp công ty, giúp không khí luôn trong lành.\n## Vận hành êm ái dù công suất lớn\nNhờ máy nén biến tần, CFS-18VGX vận hành êm hơn đáng kể so với các dòng máy thường công suất tương đương, phù hợp cả không gian cần sự yên tĩnh như phòng họp hay phòng khách gia đình.\n## Điện 1 pha tiêu chuẩn\nDù công suất lớn, máy vẫn sử dụng điện 1 pha thông thường, không yêu cầu nâng cấp hệ thống điện phức tạp, thuận tiện cho hầu hết các hộ gia đình và cửa hàng nhỏ.\n## Cần khảo sát trước khi lắp đặt\nVới công suất lớn, nên khảo sát thực tế không gian trước khi lắp đặt để đảm bảo hiệu quả làm lạnh tối ưu, đặc biệt với các phòng có trần cao hoặc nhiều cửa kính hấp thụ nhiệt. Điện Máy Xuân Son hỗ trợ khảo sát miễn phí trước khi báo giá.\nComfee CFS-18VGX là giải pháp làm lạnh công suất lớn tiết kiệm điện, phù hợp cho cả nhu cầu gia đình lẫn kinh doanh nhỏ với mức đầu tư hợp lý hơn so với các thương hiệu cao cấp.\n## So sánh chi phí vận hành với việc lắp hai máy nhỏ\nMột số khách hàng cân nhắc lắp hai máy công suất vừa thay vì một máy 18.000 BTU. Ưu điểm của một máy công suất lớn là tiết kiệm chi phí lắp đặt ban đầu, đường ống, nhân công, đồng thời dễ bảo trì hơn vì chỉ có một dàn nóng, một dàn lạnh cần kiểm tra định kỳ thay vì hai bộ riêng biệt.\n## Khả năng mở rộng cho không gian kinh doanh\nVới các cửa hàng có kế hoạch mở rộng diện tích trong tương lai, công suất 18.000 BTU của CFS-18VGX vẫn còn dư địa hoạt động ổn định ngay cả khi lượng khách ra vào tăng lên, giúp doanh nghiệp không phải đầu tư lại thiết bị sớm.",
    "CFS-25VGX":
        "Điều hòa Comfee CFS-25VGX là model công suất lớn nhất trong dòng Inverter treo tường của Comfee, đạt 24.000 BTU (7,03kW), phù hợp cho không gian rất rộng như phòng họp lớn, showroom hoặc nhà xưởng nhỏ cần làm lạnh nhanh diện tích lớn mà vẫn tiết kiệm điện.\n## Công suất lớn nhất dòng Inverter Comfee\nVới gần 24.000 BTU, CFS-25VGX phù hợp cho các không gian mở rộng trên 30m², đáp ứng nhu cầu làm lạnh cho phòng họp công ty, showroom trưng bày hoặc nhà xưởng nhỏ mà không cần lắp nhiều máy công suất nhỏ.\n## Tiết kiệm điện vượt trội nhờ Inverter công suất lớn\nVới không gian thương mại sử dụng điều hòa nhiều giờ trong ngày, công nghệ Inverter trên CFS-25VGX giúp tiết kiệm điện đáng kể so với máy thường cùng công suất — khoản chênh lệch này càng lớn khi công suất máy càng cao và thời gian sử dụng càng dài.\n## Hệ thống lọc kép cho không gian đông người\nMáy trang bị hệ thống lọc kép Dual Filtration, phù hợp không gian đông người qua lại như showroom, phòng họp, giúp duy trì chất lượng không khí tốt hơn trong môi trường có nhiều người sử dụng.\n## Vận hành ổn định cho nhu cầu thương mại\nMáy nén biến tần giúp CFS-25VGX duy trì nhiệt độ ổn định ngay cả khi không gian có lượng người ra vào liên tục, tránh tình trạng nhiệt độ dao động lớn gây khó chịu cho người sử dụng.\n## Chi phí đầu tư hợp lý so với thương hiệu cao cấp\nNhờ lợi thế sản xuất quy mô của Midea, CFS-25VGX có mức giá cạnh tranh hơn đáng kể so với các thương hiệu Inverter cao cấp cùng công suất, phù hợp cho doanh nghiệp vừa và nhỏ muốn tối ưu chi phí đầu tư thiết bị.\n## Lắp đặt chuyên nghiệp cho công suất lớn\nVới công suất lớn nhất trong dòng sản phẩm, việc lắp đặt CFS-25VGX cần đội ngũ kỹ thuật có kinh nghiệm để tính toán vị trí dàn nóng, đường ống gas phù hợp, đảm bảo hiệu quả làm lạnh tối ưu cho toàn bộ không gian. Điện Máy Xuân Son hỗ trợ khảo sát và lắp đặt tận nơi cho các model công suất lớn.\nComfee CFS-25VGX là giải pháp làm lạnh tiết kiệm điện cho không gian thương mại rộng, mang đến hiệu quả tương đương các thương hiệu cao cấp với mức đầu tư hợp lý hơn.\n## Điện 1 pha hay 3 pha cho công suất lớn\nỞ mức công suất 24.000 BTU, CFS-25VGX vẫn sử dụng điện 1 pha tiêu chuẩn thay vì yêu cầu điện 3 pha như một số dòng công suất tương đương của thương hiệu khác, giúp việc lắp đặt thuận tiện hơn cho các công trình chưa có sẵn hệ thống điện 3 pha.\n## Đầu tư dài hạn cho doanh nghiệp\nVới các doanh nghiệp vừa và nhỏ, việc đầu tư một máy công suất lớn tiết kiệm điện như CFS-25VGX ngay từ đầu thường tối ưu hơn về tổng chi phí sở hữu trong 5-7 năm sử dụng, so với việc mua máy giá rẻ không Inverter rồi phải chịu hóa đơn tiền điện cao hơn mỗi tháng.",
    "CFS-10VGP":
        "Điều hòa Comfee CFS-10VGP là phiên bản nâng cấp của dòng Inverter CFS-10VGX, bổ sung khả năng kết nối WiFi điều khiển qua điện thoại, công suất 9.350 BTU, phù hợp cho những ai muốn trải nghiệm điều hòa thông minh với mức giá vẫn hợp lý.\n## Điều khiển từ xa qua ứng dụng smartphone\nĐiểm khác biệt lớn nhất của CFS-10VGP so với CFS-10VGX là khả năng kết nối WiFi, cho phép bật/tắt máy, chỉnh nhiệt độ, hẹn giờ ngay trên điện thoại thông qua ứng dụng dù đang ở bất cứ đâu — rất tiện lợi để bật máy làm mát trước khi về đến nhà.\n## Công nghệ Inverter tiết kiệm điện\nCũng như CFS-10VGX, model này sử dụng máy nén biến tần giúp duy trì nhiệt độ ổn định và tiết kiệm điện hơn đáng kể so với máy thường cùng công suất, đặc biệt hiệu quả với các gia đình sử dụng điều hòa nhiều giờ mỗi ngày.\n## Hệ thống lọc kép Dual Filtration\nMáy được trang bị hệ thống lọc kép giúp loại bỏ bụi bẩn qua hai lớp lọc, mang lại không khí sạch hơn cho không gian sử dụng, đặc biệt phù hợp gia đình có trẻ nhỏ hoặc người có vấn đề về hô hấp.\n## Phù hợp phòng dưới 15m², tiện lợi cho người bận rộn\nCông suất 9.350 BTU phù hợp phòng ngủ, phòng làm việc dưới 15m². Với khả năng điều khiển từ xa, đây là lựa chọn lý tưởng cho người đi làm cả ngày, muốn phòng đã mát sẵn khi vừa về đến nhà mà không cần bật máy quá sớm gây lãng phí điện.\n## Cài đặt và kết nối WiFi đơn giản\nViệc kết nối máy với ứng dụng điều khiển từ xa được thiết kế đơn giản, chỉ cần vài bước quét mã QR và kết nối WiFi gia đình, không đòi hỏi kiến thức kỹ thuật phức tạp.\n## Giá hợp lý cho tính năng thông minh\nSo với nhiều dòng điều hòa WiFi của các thương hiệu lớn, CFS-10VGP có mức giá dễ tiếp cận hơn đáng kể trong khi vẫn có đầy đủ tính năng điều khiển từ xa cơ bản.\nComfee CFS-10VGP phù hợp với những gia đình hiện đại muốn trải nghiệm tiện ích điều khiển thông minh mà không phải trả thêm quá nhiều chi phí so với dòng Inverter thường.\n## Hẹn giờ và lịch trình thông minh\nNgoài bật/tắt từ xa, ứng dụng điều khiển còn cho phép cài đặt lịch hẹn giờ theo từng ngày trong tuần, ví dụ tự động bật máy trước giờ tan làm hoặc tắt máy sau một khoảng thời gian nhất định khi cả nhà đã ngủ say, giúp tối ưu điện năng tiêu thụ mà không cần nhớ thao tác thủ công mỗi ngày.\n## Phù hợp cả người lớn tuổi trong nhà\nDù có thêm tính năng WiFi, CFS-10VGP vẫn giữ điều khiển hồng ngoại truyền thống đi kèm, nên các thành viên lớn tuổi trong gia đình không quen dùng smartphone vẫn có thể sử dụng máy bình thường như một chiếc điều hòa thông thường.",
    # -- Samsung --
    "AR40H09D0BTNSV":
        "Digital Inverter 8 cực tiết kiệm điện tới 68% so với máy thường.\n"
        "## Bộ lọc 3-Care Filter\n"
        "Loại bỏ tới 99% một số vi khuẩn, virus có hại trong không khí, phù hợp "
        "gia đình có trẻ nhỏ.",
    "AR40H12D0BTNSV":
        "Công suất lớn hơn cho phòng vừa, Digital Inverter tiết kiệm điện.\n"
        "## Làm lạnh nhanh trong 30 phút\n"
        "Công nghệ làm lạnh nhanh giúp hạ nhiệt độ phòng chỉ trong thời gian "
        "ngắn.",
    "AR70H18D1BWNSV":
        "Công suất lớn cho phòng khách rộng, lọc không khí 3-Care Filter.\n"
        "## Phù hợp không gian rộng\n"
        "Công suất 18.000 BTU đáp ứng tốt nhu cầu làm lạnh nhanh cho phòng khách "
        "hoặc cửa hàng nhỏ.",
    "AR60H24D1MWNSV":
        "Công suất lớn nhất dòng 1 chiều, làm lạnh nhanh cho không gian rộng.\n"
        "## Vận hành êm, tiết kiệm điện\n"
        "Digital Inverter giúp máy vận hành êm ái, tiết kiệm điện đáng kể khi "
        "dùng lâu dài.",
    "AR40H09C1AMNSV":
        "2 chiều Digital Inverter, sưởi ấm mùa đông làm mát mùa hè.\n"
        "## Làm lạnh 2 giai đoạn\n"
        "Công nghệ two-stage cooling giúp máy đạt nhiệt độ mong muốn nhanh hơn.",
    "AR40H12C1AMNSV":
        "2 chiều công suất vừa, tiết kiệm điện, phù hợp phòng 15-20m².\n"
        "## Thiết kế gọn, dễ vệ sinh\n"
        "Cánh gió tháo lắp dễ dàng, thuận tiện khi vệ sinh bảo trì định kỳ.",
    "AR40H18C1AMNSV":
        "2 chiều công suất lớn, làm lạnh/sưởi nhanh, vận hành êm.\n"
        "## Phù hợp không gian rộng\n"
        "Công suất 18.000 BTU đáp ứng tốt nhu cầu 2 chiều cho phòng khách rộng.",
    "AR24ASHZAWKNSV":
        "2 chiều công suất mạnh nhất, phù hợp không gian rất rộng.\n"
        "## Phù hợp không gian dưới 40m²\n"
        "Chế độ làm lạnh/sưởi nhanh với tốc độ quạt cao nhất giúp đạt nhiệt độ "
        "mong muốn nhanh chóng.",
    # -- Toshiba --
    "RAS-H10S5KCV2G-V":
        "Hybrid Inverter tiết kiệm điện 35%, công nghệ Plasma Ion khử khuẩn.\n"
        "## Công nghệ Magic Coil chống bám bụi\n"
        "Lớp phủ đặc biệt trên dàn lạnh giúp hạn chế bám bụi bẩn, dễ vệ sinh "
        "hơn.",
    "RAS-H13S5KCV2G-V":
        "Công suất lớn hơn, Hybrid Inverter tiết kiệm điện, phù hợp phòng vừa.\n"
        "## Công nghệ lọc khí IAQ\n"
        "Giúp loại bỏ mùi và các hạt bụi mịn, mang lại không khí trong lành hơn.",
    "RAS-H18S5KCV2G-V":
        "Công suất lớn cho phòng khách rộng, công nghệ IAQ lọc không khí.\n"
        "## Phù hợp không gian rộng\n"
        "Công suất 18.000 BTU đáp ứng tốt nhu cầu làm lạnh nhanh cho phòng khách "
        "hoặc cửa hàng nhỏ.",
    "RAS-H24S5KCV2G-V":
        "Công suất lớn nhất dòng 1 chiều, chế độ Power Cooling làm lạnh cực "
        "nhanh.\n"
        "## Công nghệ Ultrafresh thanh lọc không khí\n"
        "Giúp loại bỏ bụi bẩn, vi khuẩn, mang lại không gian sống trong lành "
        "hơn.",
    "RAS-H10P2KCVG-V":
        "Chế độ Hi Power làm lạnh cực nhanh, công nghệ Magic Coil chống bám "
        "bụi.\n"
        "## Công nghệ Hybrid PAM/PWM\n"
        "Kết hợp hai công nghệ điều khiển giúp tối ưu hiệu suất vận hành và "
        "tiết kiệm điện.",
    "RAS-H10S3KV":
        "2 chiều Hybrid Inverter, sưởi ấm mùa đông làm mát mùa hè, tiết kiệm "
        "điện tới 50%.\n"
        "## Máy nén biến tần tiết kiệm điện\n"
        "Công nghệ biến tần giúp máy nén hoạt động hiệu quả hơn, tiết kiệm điện "
        "đáng kể.",
    "RAS-H13S3KV":
        "2 chiều công suất vừa, công nghệ kháng khuẩn khử mùi.\n"
        "## Hệ thống khử khuẩn, khử mùi\n"
        "Giúp không khí trong phòng luôn sạch, hạn chế vi khuẩn và mùi khó "
        "chịu.",
    "RAS-H18S3KV":
        "2 chiều công suất lớn, tự làm sạch bộ lọc.\n"
        "## Chức năng tự làm sạch bộ lọc\n"
        "Giúp duy trì hiệu suất làm lạnh ổn định, giảm công vệ sinh bảo trì "
        "định kỳ.",
    # ================== ĐIỀU HÒA ÂM TRẦN ==================
    # -- Daikin --
    "FCNQ18MV1":
        "Âm trần 4 hướng thổi giúp làm lạnh đều khắp phòng, không có điểm "
        "nóng.\n"
        "## Phù hợp văn phòng vừa\n"
        "Công suất 18.000 BTU đáp ứng tốt nhu cầu làm lạnh cho phòng họp, "
        "showroom dưới 30m².",
    "FCNQ26MV1":
        "Công suất lớn hơn, phù hợp phòng họp, showroom diện tích lớn.\n"
        "## Bảo hành chính hãng Thái Lan\n"
        "Sản phẩm nhập khẩu nguyên chiếc, đảm bảo chất lượng đồng bộ theo tiêu "
        "chuẩn Daikin.",
    "FCNQ36MV1":
        "Công suất mạnh, bảo hành máy nén 4 năm, phù hợp không gian thương "
        "mại rộng.\n"
        "## Bảo hành máy nén dài hạn\n"
        "Chính sách bảo hành máy nén lên đến 4 năm giúp doanh nghiệp an tâm "
        "đầu tư lâu dài.",
    # -- Panasonic --
    "S-19PU1H5B":
        "Nhập khẩu Malaysia, làm lạnh đều 4 hướng cho văn phòng vừa.\n"
        "## Thương hiệu Nhật Bản uy tín\n"
        "Panasonic là lựa chọn quen thuộc cho các không gian văn phòng, "
        "showroom cần độ bền cao.",
    "S-25PU1H5B":
        "Công suất lớn hơn, phù hợp phòng họp, showroom cỡ vừa.\n"
        "## Phù hợp không gian dưới 40m²\n"
        "Công suất 25.000 BTU đáp ứng tốt nhu cầu làm lạnh cho phòng họp, "
        "showroom cỡ vừa.",
    "S-36PU1H5B":
        "Công suất lớn, công nghệ nanoeX lọc không khí, điện 3 pha.\n"
        "## Công nghệ nanoeX khử khuẩn\n"
        "Giúp không khí trong phòng luôn sạch, phù hợp không gian đông người "
        "như phòng họp, nhà hàng.",
    # -- LG --
    "ZTNQ18GPLA1":
        "Inverter tiết kiệm điện, 4 hướng thổi đều, vận hành êm.\n"
        "## Động cơ BLDC vận hành êm\n"
        "Giúp giảm tiếng ồn, phù hợp không gian văn phòng cần yên tĩnh.",
    "ZTNQ24GNLA1":
        "Công suất lớn hơn, Inverter tiết kiệm điện, phù hợp phòng họp.\n"
        "## Tiết kiệm điện với công nghệ Inverter\n"
        "Giúp giảm đáng kể chi phí điện năng khi vận hành liên tục nhiều giờ "
        "mỗi ngày.",
    "ZTNQ36GNLA1":
        "Công suất lớn, quạt Turbo Fan động cơ BLDC tiết kiệm điện.\n"
        "## Máy nén Twin Rotary\n"
        "Giúp máy vận hành ổn định, bền bỉ khi hoạt động công suất lớn liên "
        "tục.",
    # -- Funiki --
    "CC18MMC1":
        "Giá tốt trong phân khúc âm trần, 4 hướng thổi, phù hợp văn phòng "
        "nhỏ.\n"
        "## Lựa chọn kinh tế cho văn phòng nhỏ\n"
        "Mức giá phải chăng phù hợp doanh nghiệp mới, quán ăn, cửa hàng nhỏ.",
    "CC24MMC1":
        "Công suất lớn hơn, phù hợp không gian dưới 40m².\n"
        "## Cánh gió chống bám bụi\n"
        "Thiết kế cánh gió hạn chế bám bụi, giữ dàn lạnh sạch lâu hơn.",
    "CIC36MMC":
        "Inverter tiết kiệm điện, cảm biến Follow Me tự động điều chỉnh.\n"
        "## Cảm biến Follow Me thông minh\n"
        "Tự động điều chỉnh nhiệt độ theo vị trí người dùng trong phòng, mang "
        "lại cảm giác thoải mái hơn.",
    # -- Mitsubishi Heavy --
    "FDT50CNZ-W5":
        "Thương hiệu Nhật Bản bền bỉ, bơm nước ngưng tích hợp, cảm biến hồng "
        "ngoại.\n"
        "## Bơm nước ngưng tích hợp sẵn\n"
        "Giúp việc lắp đặt thoát nước dễ dàng hơn, không cần lắp thêm thiết bị "
        "phụ trợ.",
    "FDT70CNZ-W5":
        "Công suất lớn hơn, phù hợp phòng họp, showroom vừa.\n"
        "## Cảm biến hồng ngoại tiết kiệm điện\n"
        "Tự động điều chỉnh công suất khi phòng không có người, giúp tiết "
        "kiệm điện năng.",
    "FDT100CNZ-W5":
        "Công suất lớn, phù hợp không gian thương mại rộng.\n"
        "## Phù hợp nhà hàng, showroom lớn\n"
        "Công suất 34.000 BTU đáp ứng tốt nhu cầu làm lạnh cho không gian "
        "thương mại rộng.",
    # -- Midea --
    "MCD1-18CRN8":
        "Giá cạnh tranh trong phân khúc âm trần, phù hợp văn phòng vừa.\n"
        "## Lựa chọn tiết kiệm chi phí\n"
        "Mức giá phải chăng phù hợp doanh nghiệp muốn tối ưu ngân sách đầu tư "
        "ban đầu.",
    "MCFO-25CRN8":
        "Công suất lớn hơn, phù hợp phòng họp, showroom cỡ vừa.\n"
        "## Phù hợp phòng họp cỡ vừa\n"
        "Công suất 24.000 BTU đáp ứng tốt nhu cầu làm lạnh cho phòng họp, "
        "showroom.",
    "MCFO-36CRN8":
        "Công suất lớn, phù hợp không gian thương mại rộng.\n"
        "## Giải pháp cho không gian lớn\n"
        "Phù hợp nhà hàng, showroom, văn phòng lớn cần làm lạnh diện tích "
        "rộng.",
    # -- Casper --
    "CC-18FS35":
        "Nhập khẩu Thái Lan, phù hợp văn phòng, phòng họp vừa.\n"
        "## Nhập khẩu chính hãng Thái Lan\n"
        "Đảm bảo chất lượng đồng bộ, linh kiện chính hãng từ nhà máy.",
    "CC-24FS35":
        "Công suất lớn hơn, luồng gió mạnh, phù hợp không gian rộng hơn.\n"
        "## Luồng gió mạnh, làm lạnh nhanh\n"
        "Lưu lượng gió lớn giúp làm lạnh nhanh cho không gian rộng hơn.",
    "CC-36FS35":
        "Công suất lớn, máy nén đôi, phù hợp không gian dưới 60m².\n"
        "## Máy nén đôi (Twin Rotary)\n"
        "Giúp máy vận hành ổn định, bền bỉ khi hoạt động công suất lớn liên "
        "tục.",
    # -- Nagakawa --
    "NT-C18R1T20":
        "Giá tốt, 4 hướng thổi làm lạnh nhanh, phù hợp văn phòng vừa.\n"
        "## Lựa chọn kinh tế cho văn phòng\n"
        "Mức giá phải chăng phù hợp doanh nghiệp vừa và nhỏ.",
    "NT-C24R1T20":
        "Công suất lớn hơn, phù hợp không gian dưới 50m².\n"
        "## Phù hợp không gian dưới 50m²\n"
        "Công suất 24.000 BTU đáp ứng tốt nhu cầu làm lạnh cho phòng họp, "
        "showroom vừa.",
    "NT-C36R1T20":
        "Công suất lớn, điện 3 pha, phù hợp không gian thương mại rộng.\n"
        "## Điện 3 pha ổn định cho công suất lớn\n"
        "Phù hợp lắp đặt tại các không gian thương mại có sẵn nguồn điện 3 "
        "pha.",
    # -- Sumikura --
    "APC/APO-180":
        "Giá tốt, nhập khẩu Malaysia, phù hợp văn phòng vừa.\n"
        "## Lựa chọn tiết kiệm chi phí\n"
        "Mức giá phải chăng phù hợp doanh nghiệp muốn tối ưu ngân sách đầu tư "
        "ban đầu.",
    "APC/APO-240":
        "Công suất lớn hơn, 4 hướng thổi, phù hợp phòng họp.\n"
        "## Phù hợp phòng họp, showroom\n"
        "Công suất 24.000 BTU đáp ứng tốt nhu cầu làm lạnh cho phòng họp, "
        "showroom vừa.",
    "APC/APO-360":
        "Công suất lớn, phù hợp không gian thương mại rộng.\n"
        "## Giải pháp cho không gian lớn\n"
        "Phù hợp nhà hàng, showroom, văn phòng lớn cần làm lạnh diện tích "
        "rộng.",
    # -- Samsung --
    "AC052TN1DKC":
        "Công nghệ WindFree phân tán khí lạnh nhẹ nhàng qua 10.000 lỗ nhỏ.\n"
        "## Công nghệ WindFree độc quyền\n"
        "Phân tán khí lạnh nhẹ nhàng thay vì thổi trực tiếp, tránh cảm giác "
        "lạnh đột ngột khó chịu.",
    "AC071TN1DKC":
        "Công suất lớn hơn, Digital Inverter tiết kiệm điện tới 55%.\n"
        "## Digital Inverter tiết kiệm điện\n"
        "Giúp giảm đáng kể hóa đơn tiền điện khi vận hành liên tục nhiều giờ "
        "mỗi ngày.",
    "AC100TN4DKC":
        "Công suất lớn, tích hợp ion hóa khử khuẩn khử mùi.\n"
        "## Công nghệ ion hóa khử khuẩn\n"
        "Giúp không khí trong phòng luôn sạch, khử mùi hiệu quả cho không "
        "gian đông người.",
    # -- Gree --
    "GCC18S6IA":
        "8 hướng thổi với cánh quạt 3D, bảo hành 3 năm.\n"
        "## Cánh quạt 3D 8 hướng thổi\n"
        "Giúp luồng khí lạnh phân bố đều khắp phòng, không có điểm nóng.",
    "GCC24S6IA":
        "Công suất lớn hơn, 8 hướng thổi đều khắp phòng.\n"
        "## Bảo hành chính hãng 3 năm\n"
        "Chính sách bảo hành dài hạn giúp doanh nghiệp an tâm đầu tư lâu dài.",
    "GCC36S6IA":
        "Công suất lớn, điện 3 pha, phù hợp không gian thương mại rộng.\n"
        "## Điện 3 pha ổn định cho công suất lớn\n"
        "Phù hợp lắp đặt tại các không gian thương mại có sẵn nguồn điện 3 "
        "pha.",
    # ================== ĐIỀU HÒA NỐI ỐNG GIÓ ==================
    # -- Daikin --
    "FBFC50DVM9":
        "Giấu kín trên trần, phù hợp nhà hàng, spa cỡ vừa.\n"
        "## Thương hiệu Nhật Bản uy tín\n"
        "Daikin là lựa chọn hàng đầu cho các không gian thương mại cần độ bền "
        "và hiệu suất cao.",
    "FDMNQ30MV1":
        "Công suất lớn, ống dẫn dài tới 50m, phù hợp không gian thương mại.\n"
        "## Ống dẫn dài tới 50m\n"
        "Linh hoạt lắp đặt cho các công trình có khoảng cách xa giữa dàn lạnh "
        "và dàn nóng.",
    "FBA125BVMA9":
        "Công suất mạnh, Inverter, phù hợp nhà hàng, showroom rộng dưới "
        "75m².\n"
        "## Bảo hành máy nén 5 năm\n"
        "Chính sách bảo hành dài hạn giúp doanh nghiệp an tâm đầu tư cho "
        "không gian lớn.",
    # -- Panasonic --
    "S-1821PF3H":
        "Tích hợp bơm nước ngưng, phù hợp căn hộ, văn phòng nhỏ.\n"
        "## Bơm nước ngưng tích hợp sẵn\n"
        "Giúp việc lắp đặt thoát nước dễ dàng hơn, không cần lắp thêm thiết "
        "bị phụ trợ.",
    "S-2430PF3H":
        "Công suất lớn hơn, lọc khí nanoeX, phù hợp không gian dưới 40m².\n"
        "## Công nghệ nanoeX khử khuẩn\n"
        "Giúp không khí trong phòng luôn sạch, phù hợp không gian đông "
        "người.",
    "S-3448PF3H":
        "Công suất lớn cho không gian thương mại dưới 50m².\n"
        "## Phù hợp không gian thương mại vừa\n"
        "Công suất 34.000 BTU đáp ứng tốt nhu cầu làm lạnh cho nhà hàng, "
        "showroom.",
    # -- Mitsubishi Heavy --
    "FDUM50CNZ-W5":
        "Thương hiệu Nhật Bản bền bỉ, tích hợp bơm nước ngưng.\n"
        "## Bơm nước ngưng tích hợp sẵn\n"
        "Giúp việc lắp đặt thoát nước dễ dàng hơn tại các công trình có địa "
        "hình phức tạp.",
    "FDUM70CNZ-W5":
        "Công suất lớn hơn, cửa gió linh hoạt, làm lạnh nhanh.\n"
        "## Cửa gió linh hoạt\n"
        "Cho phép bố trí luồng gió phù hợp với thiết kế trần của từng công "
        "trình.",
    "FDUM100CNZ-W5":
        "Công suất lớn, phù hợp không gian thương mại rộng.\n"
        "## Phù hợp nhà hàng, showroom lớn\n"
        "Công suất 34.000 BTU đáp ứng tốt nhu cầu làm lạnh cho không gian "
        "thương mại rộng.",
    # -- LG --
    "ZBNQ18GL2D1":
        "Thẩm mỹ cao, cửa gió bố trí linh hoạt, phù hợp không gian dưới "
        "30m².\n"
        "## Tính thẩm mỹ cao\n"
        "Thiết kế giấu kín trên trần, cửa gió linh hoạt giúp không gian gọn "
        "gàng, sang trọng hơn.",
    "ZBNQ24GL3D1":
        "Công suất lớn hơn, thiết kế mỏng gọn, phù hợp không gian dưới "
        "40m².\n"
        "## Thiết kế mỏng gọn\n"
        "Dễ dàng lắp đặt trong trần thả có độ cao hạn chế.",
    "ZBNQ36GM3A0":
        "Công suất lớn, phù hợp không gian dưới 60m².\n"
        "## Phù hợp không gian rộng\n"
        "Công suất 36.000 BTU đáp ứng tốt nhu cầu làm lạnh cho không gian "
        "thương mại rộng.",
    # -- Samsung --
    "AC052TNLDKC":
        "Thiết kế gọn nhẹ, dễ lắp đặt, Inverter tiết kiệm điện.\n"
        "## Thiết kế gọn nhẹ\n"
        "Giúp việc lắp đặt dễ dàng hơn tại các công trình có không gian trần "
        "hạn chế.",
    "AC071TNMDKC":
        "Công suất lớn hơn, tính thẩm mỹ cao cho nội thất.\n"
        "## Tính thẩm mỹ cao\n"
        "Thiết kế giấu kín trên trần phù hợp không gian nội thất hiện đại, "
        "sang trọng.",
    "AC100TNMDKC":
        "Công suất lớn, phù hợp không gian thương mại rộng.\n"
        "## Phù hợp không gian thương mại rộng\n"
        "Công suất 34.000 BTU đáp ứng tốt nhu cầu làm lạnh cho showroom, nhà "
        "hàng lớn.",
    # -- Midea --
    "MTCE-18CRFN8":
        "Giá cạnh tranh, phù hợp căn hộ, văn phòng nhỏ.\n"
        "## Lựa chọn tiết kiệm chi phí\n"
        "Mức giá phải chăng phù hợp doanh nghiệp muốn tối ưu ngân sách đầu "
        "tư ban đầu.",
    "MTCE-24CRFN8":
        "Công suất lớn hơn, làm lạnh nhanh, giá hợp lý.\n"
        "## Phù hợp không gian vừa\n"
        "Công suất 24.000 BTU đáp ứng tốt nhu cầu làm lạnh cho văn phòng, "
        "cửa hàng vừa.",
    "MTCE-36CRFN8":
        "Công suất lớn, vận hành êm, phù hợp không gian thương mại.\n"
        "## Vận hành êm ái\n"
        "Mức độ ồn thấp giúp phù hợp không gian văn phòng, nhà hàng cần yên "
        "tĩnh.",
    # -- Casper --
    "DC-18IS35":
        "Nhập khẩu Thái Lan, phù hợp không gian dưới 30m².\n"
        "## Nhập khẩu chính hãng Thái Lan\n"
        "Đảm bảo chất lượng đồng bộ, linh kiện chính hãng từ nhà máy.",
    "DC-24IS35":
        "Công suất lớn hơn, phù hợp không gian rộng hơn.\n"
        "## Bơm nước ngưng công suất lớn\n"
        "Bơm nước ngưng đạt độ cao 1200mm, phù hợp nhiều kiểu lắp đặt trần "
        "khác nhau.",
    "DC-36IS35":
        "Công suất lớn, phù hợp không gian 50-60m².\n"
        "## Tiết kiệm điện 30-50%\n"
        "Công nghệ Inverter giúp tiết kiệm điện đáng kể so với máy thường "
        "cùng công suất.",
    # -- Gree --
    "GDC18S6IA":
        "Inverter tiết kiệm điện, cửa gió hồi linh hoạt.\n"
        "## Thiết kế cửa gió hồi linh hoạt\n"
        "Giúp việc lắp đặt phù hợp với nhiều kiểu bố trí trần khác nhau.",
    "GDC24S6IA":
        "Công suất lớn hơn, vận hành ổn định.\n"
        "## Tự chẩn đoán lỗi thông minh\n"
        "Giúp phát hiện sự cố nhanh chóng, thuận tiện cho việc bảo trì sửa "
        "chữa.",
    "GDC36S6IA":
        "Công suất lớn, phù hợp không gian thương mại.\n"
        "## Bảo hành chính hãng 3 năm\n"
        "Chính sách bảo hành dài hạn giúp doanh nghiệp an tâm đầu tư lâu "
        "dài.",
    # -- Sumikura --
    "ACS/APO-180":
        "Giá tốt, nhập khẩu Malaysia, phù hợp văn phòng vừa.\n"
        "## Lựa chọn tiết kiệm chi phí\n"
        "Mức giá phải chăng phù hợp doanh nghiệp muốn tối ưu ngân sách đầu "
        "tư ban đầu.",
    "ACS/APO-280":
        "Công suất lớn hơn, phù hợp không gian thương mại vừa.\n"
        "## Phù hợp không gian thương mại vừa\n"
        "Công suất 28.000 BTU đáp ứng tốt nhu cầu làm lạnh cho showroom, văn "
        "phòng vừa.",
    "ACS/APO-360":
        "Công suất lớn, phù hợp không gian thương mại rộng.\n"
        "## Giải pháp cho không gian lớn\n"
        "Phù hợp nhà hàng, showroom, văn phòng lớn cần làm lạnh diện tích "
        "rộng.",
    # -- Nagakawa --
    "NB-C18R1A18":
        "Cửa gió linh hoạt, thẩm mỹ cao, phù hợp căn hộ cao cấp.\n"
        "## Thẩm mỹ cao cho căn hộ cao cấp\n"
        "Thiết kế giấu kín trên trần, cửa gió linh hoạt phù hợp không gian "
        "nội thất sang trọng.",
    "NB-C24R1A18":
        "Công suất lớn hơn, phù hợp không gian rộng hơn.\n"
        "## Phù hợp không gian rộng hơn\n"
        "Công suất 24.000 BTU đáp ứng tốt nhu cầu làm lạnh cho căn hộ, văn "
        "phòng vừa.",
    "NB-C36R1A18":
        "Công suất lớn, phù hợp căn hộ cao cấp, không gian thương mại.\n"
        "## Phù hợp không gian thương mại rộng\n"
        "Công suất 36.000 BTU đáp ứng tốt nhu cầu làm lạnh cho không gian "
        "rộng.",

    # ==================== TỦ ĐỨNG ====================
    # -- Daikin --
    "FVA71AMVM":
        "Inverter tiết kiệm điện, phù hợp phòng khách, showroom vừa.\n"
        "## Bảo hành máy nén 5 năm\n"
        "Chính sách bảo hành dài hạn giúp khách hàng an tâm sử dụng lâu "
        "dài.",
    "FVC85AV1V":
        "Công suất lớn hơn, cảm biến nhiệt độ kép, phù hợp không gian rộng hơn.\n"
        "## Cảm biến nhiệt độ kép\n"
        "Giúp máy đo nhiệt độ chính xác hơn, duy trì nhiệt độ phòng ổn "
        "định.",
    "FVC100AV1V":
        "Công suất lớn, điện 3 pha, phù hợp không gian thương mại rộng.\n"
        "## Điện 3 pha ổn định cho công suất lớn\n"
        "Phù hợp lắp đặt tại các không gian thương mại có sẵn nguồn điện 3 "
        "pha.",
    # -- LG --
    "ZPNQ24GS1A0":
        "Dual Inverter tiết kiệm điện tới 60%, thổi gió xa 20m.\n"
        "## Dual Inverter tiết kiệm điện\n"
        "Công nghệ biến tần kép giúp tiết kiệm điện tới 60% so với máy "
        "thường.",
    "ZPNQ30GT3A1":
        "Công suất lớn hơn, thổi gió 4 hướng, tầm xa 20m.\n"
        "## Thổi gió xa 20 mét\n"
        "Giúp làm lạnh nhanh và đều khắp không gian rộng.",
    "ZPNQ36GR5A0":
        "Công suất lớn, chế độ Power Cooling làm lạnh nhanh.\n"
        "## Chế độ Power Cooling\n"
        "Tự động hạ nhiệt độ xuống 18°C giúp làm lạnh nhanh chóng khi cần "
        "thiết.",
    # -- Panasonic --
    "S-21PB3H5":
        "Inverter tiết kiệm điện, thổi gió 4 hướng xa 7m.\n"
        "## Thổi gió 4 hướng\n"
        "Giúp luồng khí lạnh phân bố đều khắp phòng, không có điểm nóng.",
    "S-24PB3H5":
        "Công suất lớn hơn, công nghệ nanoeX thế hệ 2.\n"
        "## Công nghệ nanoeX thế hệ 2\n"
        "Giúp khử khuẩn, khử mùi hiệu quả hơn phiên bản trước.",
    "S-34PB3H5":
        "Công suất lớn, thổi gió xa 4 hướng, làm lạnh nhanh.\n"
        "## Làm lạnh nhanh, thổi gió xa\n"
        "Phù hợp không gian rộng cần làm lạnh nhanh chóng.",
    # -- Mitsubishi Heavy --
    "FDF71CR-S5":
        "Thương hiệu Nhật Bản bền bỉ, phù hợp phòng khách, showroom vừa.\n"
        "## Độ bền theo tiêu chuẩn Nhật Bản\n"
        "Mitsubishi Heavy nổi tiếng với độ bền cao, ít hỏng vặt trong quá "
        "trình sử dụng lâu dài.",
    "FSHY/FCHY-2801":
        "Sản xuất tại Việt Nam, công suất lớn hơn, giá hợp lý.\n"
        "## Sản xuất tại Việt Nam\n"
        "Giúp giá thành hợp lý hơn so với các dòng nhập khẩu nguyên chiếc.",
    "FDF125CR-S5":
        "Công suất lớn, thổi gió mạnh, phù hợp không gian tới 70m².\n"
        "## Phù hợp không gian tới 70m²\n"
        "Công suất 45.000 BTU đáp ứng tốt nhu cầu làm lạnh cho không gian "
        "rộng.",
    # -- Midea --
    "MFPA-24CRN1":
        "Giá cạnh tranh, đèn LED hiển thị, phù hợp phòng khách.\n"
        "## Lọc khí ion bạc\n"
        "Giúp khử mùi hiệu quả, mang lại không khí trong lành hơn.",
    "MFPA-28CRN1":
        "Công suất lớn hơn, lọc khí ion bạc khử mùi.\n"
        "## Phù hợp không gian 35-51m²\n"
        "Công suất 28.000 BTU đáp ứng tốt nhu cầu làm lạnh cho phòng khách "
        "rộng.",
    "MFJJ2-50CRN1":
        "Công suất lớn, điện 3 pha, phù hợp không gian thương mại.\n"
        "## Điện 3 pha ổn định cho công suất lớn\n"
        "Phù hợp lắp đặt tại các không gian thương mại có sẵn nguồn điện 3 "
        "pha.",
    # -- Samsung --
    "AC030BNPDKC":
        "Inverter tiết kiệm điện, thổi gió xa 20m, 4 hướng.\n"
        "## Thổi gió xa 20 mét\n"
        "Giúp làm lạnh nhanh và đều khắp không gian rộng.",
    "AC036BNPDKC":
        "Công suất lớn hơn, phù hợp không gian rộng hơn.\n"
        "## Công nghệ Inverter tiết kiệm điện\n"
        "Giúp giảm đáng kể hóa đơn tiền điện khi vận hành liên tục.",
    "AC048BNPDKC":
        "Công suất lớn, bảng điều khiển cảm ứng, tiết kiệm điện 30-50%.\n"
        "## Bảng điều khiển cảm ứng hiện đại\n"
        "Thiết kế tối giản, dễ sử dụng, phù hợp không gian nội thất hiện "
        "đại.",
    # -- Gree --
    "GVC24AM-K6NNC7B":
        "Bảo hành máy nén 5 năm, thổi gió nhanh 4 hướng.\n"
        "## Bảo hành máy nén 5 năm\n"
        "Chính sách bảo hành dài hạn giúp khách hàng an tâm sử dụng lâu "
        "dài.",
    "GVC30AMXH-K6NNC7B":
        "Công suất lớn hơn, điều khiển qua WiFi smartphone.\n"
        "## Điều khiển qua smartphone\n"
        "Cho phép bật/tắt, hẹn giờ từ xa qua ứng dụng trên điện thoại.",
    "GVC42ALXH-M6NNC7B":
        "Công suất lớn, điện 3 pha, phù hợp không gian thương mại.\n"
        "## Điện 3 pha ổn định cho công suất lớn\n"
        "Phù hợp lắp đặt tại các không gian thương mại có sẵn nguồn điện 3 "
        "pha.",
    # -- Sumikura --
    "APF/APO-210/CL-A":
        "Giá tốt, nhập khẩu Malaysia, chức năng hút ẩm độc lập.\n"
        "## Chức năng hút ẩm độc lập\n"
        "Giúp kiểm soát độ ẩm trong phòng mà không cần bật chế độ làm "
        "lạnh.",
    "APF/APO-280/CL-A":
        "Công suất lớn hơn, màn hình LCD hiển thị.\n"
        "## Màn hình LCD hiển thị\n"
        "Giúp theo dõi nhiệt độ, chế độ hoạt động dễ dàng hơn.",
    "APF/APO-360/CL-A":
        "Công suất lớn, thiết kế gọn, vận hành 1 pha dù công suất cao.\n"
        "## Vận hành 1 pha dù công suất cao\n"
        "Không cần nâng cấp hệ thống điện 3 pha, tiết kiệm chi phí lắp "
        "đặt.",
    # -- Funiki --
    "FC27MMC1":
        "Giá tốt, chế độ Powerful làm lạnh nhanh, tự khởi động lại sau mất điện.\n"
        "## Tự khởi động lại sau mất điện\n"
        "Giúp máy hoạt động trở lại bình thường mà không cần cài đặt lại "
        "sau khi mất điện.",
    "FC36MMC1":
        "Công suất lớn hơn, thiết kế gọn gàng.\n"
        "## Chế độ Powerful làm lạnh nhanh\n"
        "Giúp hạ nhiệt độ phòng nhanh chóng trong những ngày nắng nóng cao "
        "điểm.",
    "FC50MMC1":
        "Công suất lớn, vận hành 3 pha, hệ thống lọc khí diệt khuẩn.\n"
        "## Hệ thống lọc khí diệt khuẩn\n"
        "Giúp không khí trong phòng luôn sạch, phù hợp không gian đông "
        "người.",
    # -- Casper --
    "FC-18TL22":
        "Giá tốt, thổi gió xa 15m, phù hợp phòng khách nhỏ.\n"
        "## Thổi gió xa 15 mét\n"
        "Giúp làm lạnh nhanh và đều khắp phòng khách.",
    "FC-24FS36":
        "Công suất lớn hơn, thổi gió 4 hướng, phù hợp phòng 22-43m².\n"
        "## Thổi gió 4 hướng\n"
        "Giúp luồng khí lạnh phân bố đều khắp phòng, không có điểm nóng.",
    "FC-42FS36":
        "Công suất lớn, điện 3 pha, phù hợp không gian 44-65m².\n"
        "## Điện 3 pha ổn định cho công suất lớn\n"
        "Phù hợp lắp đặt tại các không gian thương mại có sẵn nguồn điện 3 "
        "pha.",
    # -- Nagakawa --
    "NP-C24R1K58":
        "Giá tốt, chế độ đảo gió tự động, dàn đồng mạ vàng chống ăn mòn.\n"
        "## Dàn đồng mạ vàng chống ăn mòn\n"
        "Giúp tăng độ bền, kéo dài tuổi thọ sản phẩm trong môi trường ẩm.",
    "NP-C28R1K58":
        "Công suất lớn hơn, tích hợp ionizer khử khuẩn.\n"
        "## Tích hợp Ionizer khử khuẩn\n"
        "Giúp không khí trong phòng sạch hơn, hạn chế vi khuẩn, nấm mốc.",
    "NP-C50R1K58":
        "Công suất lớn, điện 3 pha, phù hợp không gian 80-90m².\n"
        "## Phù hợp không gian 80-90m²\n"
        "Công suất 50.000 BTU đáp ứng tốt nhu cầu làm lạnh cho phòng họp, "
        "nhà hàng lớn.",

    # ==================== MÁY GIẶT ====================
    # -- Electrolux --
    "EWF9023P5WC":
        "Công nghệ UltraMix hòa tan bột giặt trước khi giặt, kháng khuẩn hiệu quả.\n"
        "## Công nghệ UltraMix\n"
        "Hòa tan bột giặt hoàn toàn trước khi đưa vào lồng giặt, giúp giặt "
        "sạch đều mà không lo cặn bột giặt bám trên vải.",
    "EWF1024D3WC":
        "Công suất lớn hơn, tiết kiệm nước, phù hợp gia đình đông người.\n"
        "## Tiết kiệm nước vượt trội\n"
        "Cảm biến tự động điều chỉnh lượng nước theo khối lượng đồ giặt, "
        "giúp tiết kiệm chi phí sinh hoạt.",
    "EWW9024P3WC":
        "Giặt sấy 2 trong 1, hơi nước diệt khuẩn, tiện lợi không cần phơi.\n"
        "## Giặt sấy 2 trong 1\n"
        "Không cần máy sấy riêng, phù hợp căn hộ chung cư diện tích nhỏ "
        "hoặc gia đình bận rộn.",
    # -- LG --
    "FB1209S5W":
        "AI DD Inverter tiết kiệm điện, vận hành êm ái.\n"
        "## AI DD Inverter\n"
        "Tự động nhận diện chất liệu vải và điều chỉnh chuyển động giặt "
        "phù hợp, bảo vệ vải và tiết kiệm điện.",
    "FX1410N5W":
        "Công suất lớn hơn, hơi nước diệt khuẩn 99.9%.\n"
        "## Giặt hơi nước diệt khuẩn\n"
        "Hơi nước ở nhiệt độ cao giúp loại bỏ vi khuẩn, mạt bụi và khử mùi "
        "hiệu quả trên quần áo.",
    "FX1412N5G":
        "Công suất lớn, phù hợp gia đình đông người.\n"
        "## Phù hợp gia đình đông người\n"
        "Dung tích 12kg đáp ứng tốt nhu cầu giặt khối lượng lớn mỗi lần, "
        "tiết kiệm thời gian.",
    # -- Toshiba --
    "AW-M905BV(MK)":
        "Công nghệ Fuzzy Logic tự động cân đồ giặt, giá tốt.\n"
        "## Công nghệ Fuzzy Logic\n"
        "Tự động nhận biết khối lượng và độ bẩn của đồ giặt để tối ưu "
        "lượng nước và thời gian giặt.",
    "TW-T23BU110UWV(MG)":
        "Real Inverter tiết kiệm điện, công nghệ Greatwave.\n"
        "## Real Inverter tiết kiệm điện\n"
        "Động cơ biến tần thực giúp vận hành êm ái, bền bỉ và tiết kiệm "
        "điện năng lâu dài.",
    "TW-BL115A2V(SS)":
        "Siêu bọt khí nano UFB, giặt hơi nước, điều khiển qua WiFi.\n"
        "## Siêu bọt khí nano UFB\n"
        "Bọt khí siêu nhỏ thấm sâu vào từng sợi vải, giúp giặt sạch cả "
        "những vết bẩn cứng đầu.",
    # -- Samsung --
    "WA12CG5886BVSV":
        "Công suất lớn 12kg, Digital Inverter bền bỉ.\n"
        "## Digital Inverter bền bỉ\n"
        "Động cơ biến tần Digital Inverter được bảo hành dài hạn, vận "
        "hành êm ái và tiết kiệm điện.",
    "WW10DG6U34LESV":
        "AI Control tự động tối ưu chu trình giặt theo khối lượng đồ.\n"
        "## AI Control thông minh\n"
        "Tự động phân tích khối lượng và độ bẩn để chọn chu trình giặt "
        "phù hợp nhất.",
    "WW11CGP44DSHSV":
        "Công nghệ Ecobubble hòa tan bọt khí giúp giặt sạch nhanh ở nhiệt độ thấp.\n"
        "## Công nghệ Ecobubble\n"
        "Bọt khí giúp bột giặt thấm sâu vào vải nhanh hơn, giặt sạch hiệu "
        "quả ngay cả ở nước lạnh.",
    # -- Panasonic --
    "NA-F90A9DRV":
        "Công nghệ Active Foam tạo bọt siêu mịn, kháng khuẩn ion bạc.\n"
        "## Công nghệ Active Foam\n"
        "Tạo bọt siêu mịn giúp bột giặt thấm nhanh vào sợi vải, giặt sạch "
        "hiệu quả hơn.",
    "NA-FD10VR1BV":
        "TD Inverter, công nghệ WaterBazooka đánh bay vết bẩn cứng đầu.\n"
        "## Công nghệ WaterBazooka\n"
        "Tia nước áp lực cao đánh thẳng vào vết bẩn trước khi giặt, tăng "
        "hiệu quả làm sạch.",
    "NA-V90FR1BVT":
        "AI Smart Wash, diệt khuẩn bằng tia UV và ion bạc Blue Ag+.\n"
        "## Diệt khuẩn Blue Ag+ và tia UV\n"
        "Kết hợp ion bạc và tia cực tím giúp loại bỏ vi khuẩn trên lồng "
        "giặt, giữ máy luôn sạch sẽ.",
    # -- Casper --
    "WT-75NG1":
        "Nhỏ gọn, giá tốt, phù hợp phòng trọ, gia đình ít người.\n"
        "## Nhỏ gọn, tiết kiệm diện tích\n"
        "Thiết kế nhỏ gọn phù hợp không gian hạn chế như phòng trọ, căn "
        "hộ nhỏ.",
    "WF-D8VWR1":
        "Tiết kiệm điện nước, vận hành êm ái.\n"
        "## Tiết kiệm điện nước\n"
        "Cảm biến tự động điều chỉnh lượng nước và điện năng theo khối "
        "lượng đồ giặt.",
    "WF-95VG5":
        "Công suất lớn hơn, phù hợp gia đình đông người.\n"
        "## Phù hợp gia đình đông người\n"
        "Dung tích 9.5kg đáp ứng tốt nhu cầu giặt khối lượng lớn mỗi lần.",
    # -- Sharp --
    "ES-Y75HV-S":
        "Công nghệ Fuzzy Logic, có khóa trẻ em an toàn.\n"
        "## Khóa trẻ em an toàn\n"
        "Ngăn trẻ nhỏ vô tình mở nắp hoặc thay đổi cài đặt trong khi máy "
        "đang vận hành.",
    "ES-Y90HV-S":
        "J-Tech Inverter, lồng giặt kép cánh cá heo giặt sạch nhẹ nhàng.\n"
        "## Lồng giặt kép cánh cá heo\n"
        "Thiết kế lồng giặt đặc biệt giúp đảo đều quần áo, giặt sạch mà "
        "không làm xoắn rối vải.",
    "ES-FK1054PV-S":
        "J-Tech Inverter, giặt hơi nước diệt khuẩn.\n"
        "## J-Tech Inverter bền bỉ\n"
        "Động cơ biến tần công nghệ Nhật Bản giúp vận hành êm ái, tiết "
        "kiệm điện và bền bỉ lâu dài.",
    # -- Funiki --
    "HWM T685ABG":
        "Lồng giặt 6 cánh, chức năng i-Clean tự vệ sinh lồng giặt.\n"
        "## Chức năng i-Clean\n"
        "Tự động vệ sinh lồng giặt định kỳ, hạn chế nấm mốc và mùi hôi.",
    "HWM F895ADG":
        "15 chương trình giặt, công nghệ Hygiene Care+ diệt khuẩn.\n"
        "## Hygiene Care+\n"
        "Công nghệ diệt khuẩn giúp quần áo sạch sẽ, an toàn cho cả gia "
        "đình có trẻ nhỏ.",
    "HWM F8125ADG":
        "Công suất lớn 12.5kg, phù hợp gia đình đông người.\n"
        "## Phù hợp gia đình đông người\n"
        "Dung tích 12.5kg đáp ứng tốt nhu cầu giặt khối lượng lớn, tiết "
        "kiệm thời gian giặt nhiều lần.",
    # -- AQUA --
    "AQW-S72CT.H2":
        "Lồng inox chống gỉ, khóa trẻ em, giá tốt.\n"
        "## Lồng inox chống gỉ\n"
        "Chất liệu inox bền bỉ, chống gỉ sét, tăng tuổi thọ sản phẩm "
        "trong quá trình sử dụng lâu dài.",
    "AQD-A852J.BK":
        "Inverter tiết kiệm điện, giặt hơi nước, phun sương thông minh.\n"
        "## Phun sương thông minh\n"
        "Công nghệ phun sương giúp làm ẩm đều quần áo trước khi giặt, "
        "tăng hiệu quả làm sạch.",
    "AQD-A1102J.BK":
        "Inverter BLDC, 15 chương trình giặt, công nghệ Refresh.\n"
        "## Công nghệ Refresh làm mới quần áo\n"
        "Giúp làm mới, khử mùi quần áo mà không cần giặt lại toàn bộ, "
        "tiết kiệm thời gian.",
    # -- Sumikura --
    "SKWFID-78P1":
        "DD Inverter tiết kiệm điện, vận hành êm ái.\n"
        "## DD Inverter vận hành êm ái\n"
        "Động cơ truyền động trực tiếp giúp giảm tiếng ồn và độ rung khi "
        "vận hành.",
    "SKWFID-95P1":
        "14 chương trình giặt thông minh, công suất lớn hơn.\n"
        "## 14 chương trình giặt thông minh\n"
        "Đa dạng chương trình giặt phù hợp với nhiều loại vải và mức độ "
        "bẩn khác nhau.",
    "SKWFID-108P1":
        "Công suất lớn, phù hợp gia đình đông người.\n"
        "## Phù hợp gia đình đông người\n"
        "Dung tích 10.8kg đáp ứng tốt nhu cầu giặt khối lượng lớn mỗi lần.",

    # ==================== BÌNH NÓNG LẠNH ====================
    # -- Ariston --
    "Vitaly 15":
        "Thanh đốt lõi đồng bền bỉ, cách nhiệt mật độ cao, giá tốt.\n"
        "## Thanh đốt lõi đồng bền bỉ\n"
        "Chất liệu đồng dẫn nhiệt tốt, làm nóng nhanh và có tuổi thọ cao "
        "hơn thanh đốt thường.",
    "SL3 20R":
        "Tráng men Titan chống bám cặn, chống giật ELCB an toàn.\n"
        "## Tráng men Titan chống bám cặn\n"
        "Lớp men Titan giúp hạn chế cặn bám trong lòng bình, kéo dài "
        "tuổi thọ và giữ nước nóng sạch hơn.",
    "SL3 30 TOP WIFI VN":
        "Điều khiển từ xa qua WiFi, đạt chuẩn 5 sao tiết kiệm điện.\n"
        "## Điều khiển từ xa qua WiFi\n"
        "Cho phép bật bình nóng lạnh từ xa trước khi về nhà, tiết kiệm "
        "thời gian chờ nước nóng.",
    # -- Rossi --
    "BLS15SQ":
        "Tráng men kim cương, chống giật ELCB, giá rẻ.\n"
        "## Tráng men kim cương\n"
        "Lớp men kim cương chống ăn mòn, giúp bình bền hơn trong môi "
        "trường nước cứng.",
    "RST20SQ":
        "Dòng Smart, tráng men kim cương, công suất vừa cho gia đình nhỏ.\n"
        "## Dòng Smart tiện lợi\n"
        "Thiết kế hiện đại, dễ lắp đặt, phù hợp căn hộ chung cư và nhà "
        "phố.",
    "RAM30SL":
        "Kiểu bình ngang, tráng men kim cương, phù hợp lắp trên trần thấp.\n"
        "## Kiểu bình ngang tiết kiệm không gian\n"
        "Phù hợp lắp đặt ở những vị trí trần thấp hoặc không gian hẹp "
        "phía trên khu vực tắm.",
    # -- Ferroli --
    "QQ Evo 15 ME":
        "Tráng men Titan, dây điện ELCB chống giật.\n"
        "## Dây điện tích hợp ELCB\n"
        "Thiết bị chống giật ELCB gắn liền dây nguồn giúp ngắt điện tức "
        "thời khi có rò rỉ, đảm bảo an toàn.",
    "QQ Evo 30 AE":
        "Chống bám cặn, rơ le chống cháy khô bảo vệ thanh đốt.\n"
        "## Rơ le chống cháy khô\n"
        "Tự động ngắt điện khi bình cạn nước, bảo vệ thanh đốt khỏi hư "
        "hỏng do cháy khô.",
    "AQUA 80SEH":
        "Dung tích lớn 80L, kiểu bình ngang, phù hợp gia đình đông người.\n"
        "## Dung tích lớn cho gia đình đông người\n"
        "Dung tích 80 lít đáp ứng đủ nhu cầu nước nóng cho nhiều phòng "
        "tắm cùng lúc.",
    # -- Panasonic --
    "DH-15HBM":
        "Lõi inox bền bỉ, tiết kiệm điện, hàng nhập khẩu Malaysia.\n"
        "## Lõi bình bằng inox\n"
        "Chất liệu inox chống gỉ sét, bền bỉ hơn so với lõi thép tráng "
        "men thông thường.",
    "DH-20HBM":
        "Công suất lớn hơn, lõi inox tiết kiệm điện.\n"
        "## Tiết kiệm điện năng\n"
        "Công nghệ cách nhiệt của Panasonic giúp giữ nhiệt lâu, giảm số "
        "lần bật lại máy sưởi.",
    "DH-30HBM":
        "Dung tích lớn, lõi inox, phù hợp gia đình đông người.\n"
        "## Phù hợp gia đình đông người\n"
        "Dung tích 30 lít đáp ứng tốt nhu cầu sử dụng nước nóng liên tục "
        "của gia đình nhiều thành viên.",
    # -- Funiki --
    "ECO 15":
        "Lõi tráng Titanium, chống giật ELCB, công nghệ Nano bạc kháng khuẩn.\n"
        "## Công nghệ Nano bạc kháng khuẩn\n"
        "Giúp hạn chế vi khuẩn phát triển trong lòng bình, nước nóng "
        "sạch và an toàn hơn.",
    "ECO 20":
        "Công suất lớn hơn, lõi tráng Titanium chống ăn mòn.\n"
        "## Lõi tráng Titanium\n"
        "Lớp phủ Titanium giúp chống ăn mòn, kéo dài tuổi thọ bình trong "
        "môi trường nước cứng.",
    "VI50L":
        "Kiểu bình tròn dung tích lớn 50L, phù hợp gia đình đông người.\n"
        "## Dung tích lớn 50L\n"
        "Phù hợp gia đình đông người hoặc nhà có nhiều phòng tắm sử dụng "
        "cùng lúc.",
    # -- Midea --
    "D15-25VA":
        "Thiết kế thanh lịch, công nghệ lọc nước kháng khuẩn.\n"
        "## Công nghệ lọc nước kháng khuẩn\n"
        "Giúp nước nóng đầu ra sạch hơn, hạn chế vi khuẩn và tạp chất.",
    "D30-25VA1":
        "Màn hình LED hiển thị nhiệt độ, dung tích lớn hơn.\n"
        "## Màn hình LED hiển thị nhiệt độ\n"
        "Giúp người dùng theo dõi chính xác nhiệt độ nước, chủ động "
        "điều chỉnh phù hợp.",
    "D30-25EVA":
        "Điều khiển từ xa, lõi tráng Titan, hẹn giờ làm nóng.\n"
        "## Hẹn giờ làm nóng từ xa\n"
        "Cho phép cài đặt lịch làm nóng nước tự động theo giờ sinh hoạt "
        "của gia đình.",
    # -- Casper --
    "EH-20TH11":
        "Thanh đốt lõi đồng, chống giật ELCB kép, hàng nhập khẩu Thái Lan.\n"
        "## Chống giật ELCB kép\n"
        "Hai lớp bảo vệ chống giật giúp tăng độ an toàn khi sử dụng, đặc "
        "biệt phù hợp nhà có trẻ nhỏ.",
    "SH-20TH11":
        "Tráng men kim cương, cách nhiệt mật độ cao.\n"
        "## Cách nhiệt mật độ cao\n"
        "Lớp cách nhiệt dày giúp giữ nước nóng lâu hơn, giảm số lần bật "
        "lại bình.",
    "SH-30TH11":
        "Dung tích lớn hơn, tráng men kim cương, chống giật ELCB kép.\n"
        "## Tráng men kim cương chống ăn mòn\n"
        "Giúp lòng bình bền hơn, hạn chế rỉ sét trong quá trình sử dụng "
        "lâu dài.",
    # -- Kangaroo --
    "KG68A2":
        "Kiểu bình chữ nhật, màn hình hiển thị nhiệt độ, hàng Việt Nam.\n"
        "## Kiểu bình chữ nhật gọn gàng\n"
        "Thiết kế chữ nhật tối ưu không gian lắp đặt, phù hợp phòng tắm "
        "hiện đại.",
    "KG69A2":
        "Cùng dung tích, thiết kế biến thể, màn hình hiển thị nhiệt độ.\n"
        "## Màn hình hiển thị nhiệt độ\n"
        "Giúp người dùng dễ dàng theo dõi và điều chỉnh nhiệt độ nước "
        "phù hợp.",
    "KG68A3":
        "Dung tích lớn hơn, phù hợp gia đình đông người.\n"
        "## Bảo hành bình 10 năm\n"
        "Chính sách bảo hành dài hạn cho lõi bình giúp khách hàng an "
        "tâm sử dụng lâu dài.",
    # -- Atlantic --
    "SWH15AM/AC":
        "Dòng ACCESS, lòng bình tráng men kim cương.\n"
        "## Dòng ACCESS tráng men kim cương\n"
        "Lớp men kim cương giúp chống ăn mòn, tăng độ bền cho lòng bình "
        "trong môi trường nước cứng.",
    "SWH15AM":
        "Rơ le chống cháy khô điện trở, hàng nhập khẩu Thái Lan, thương hiệu Pháp.\n"
        "## Rơ le chống cháy khô điện trở\n"
        "Tự động ngắt điện khi bình cạn nước, bảo vệ thanh đốt và tăng "
        "độ an toàn.",
    "SWH30AM/AC":
        "Dung tích lớn hơn, tráng men kim cương, tiết kiệm điện.\n"
        "## Đạt chuẩn châu Âu\n"
        "Sản phẩm thương hiệu Pháp, thiết kế và sản xuất theo tiêu "
        "chuẩn chất lượng châu Âu.",
    # -- Sơn Hà --
    "SWAT SW15VO":
        "Thanh đốt gia nhiệt kép, làm nóng nhanh, hàng Việt Nam.\n"
        "## Thanh đốt gia nhiệt kép\n"
        "Hai thanh đốt hoạt động luân phiên giúp làm nóng nước nhanh "
        "hơn và tăng độ bền.",
    "SWAT SW20VO":
        "Công suất lớn hơn, thanh đốt gia nhiệt kép bền bỉ.\n"
        "## Bền bỉ với thời gian\n"
        "Thương hiệu Sơn Hà có kinh nghiệm lâu năm trong ngành thép "
        "không gỉ, đảm bảo độ bền cho lòng bình.",
    "SWAT SW30VO":
        "Dung tích lớn, giữ nhiệt tiết kiệm điện.\n"
        "## Giữ nhiệt tiết kiệm điện\n"
        "Lớp cách nhiệt dày giúp giữ nước nóng lâu, giảm số lần bật lại, "
        "tiết kiệm điện năng.",

    # ==================== TỦ LẠNH ====================
    # -- Funiki --
    "FR-51DSU":
        "Tủ lạnh mini 1 cánh, nhỏ gọn, phù hợp phòng trọ, ký túc xá.\n"
        "## Nhỏ gọn cho không gian hạn chế\n"
        "Thiết kế mini phù hợp phòng trọ, ký túc xá hoặc làm tủ lạnh phụ "
        "trong văn phòng.",
    "FR-125CI.1":
        "Dung tích vừa, 2 cánh, phù hợp gia đình nhỏ.\n"
        "## Phù hợp gia đình nhỏ\n"
        "Dung tích 120 lít đáp ứng đủ nhu cầu bảo quản thực phẩm cho gia "
        "đình 2-3 người.",
    "HR T6209TDG":
        "Dung tích lớn hơn, 2 cánh, ngăn đông riêng biệt.\n"
        "## Ngăn đông riêng biệt\n"
        "Thiết kế 2 cánh tách biệt ngăn đông và ngăn mát, thuận tiện sắp "
        "xếp thực phẩm.",
    "FRI-166ISU":
        "Công nghệ Inverter tiết kiệm điện, 2 cánh.\n"
        "## Công nghệ Inverter tiết kiệm điện\n"
        "Máy nén biến tần giúp vận hành êm ái và tiết kiệm điện năng hơn "
        "so với máy thường.",
    # -- LG --
    "LOB16BGM":
        "1 cánh, dung tích 195L, thiết kế sang trọng.\n"
        "## Thiết kế sang trọng, tiết kiệm không gian\n"
        "Kiểu dáng 1 cánh gọn gàng, phù hợp gia đình ít người hoặc không "
        "gian bếp nhỏ.",
    "LTB26BLM":
        "2 cánh, dung tích 266L, phù hợp gia đình vừa.\n"
        "## Phù hợp gia đình vừa\n"
        "Dung tích 266 lít đáp ứng tốt nhu cầu bảo quản thực phẩm cho gia "
        "đình 3-4 người.",
    "LTB33BLG":
        "Dung tích lớn hơn, 2 cánh, phù hợp gia đình đông người.\n"
        "## Dung tích lớn cho gia đình đông người\n"
        "Dung tích 335 lít phù hợp gia đình nhiều thành viên hoặc nhu cầu "
        "tích trữ thực phẩm lớn.",
    "GR-B256JDS":
        "Side by side 519L, thiết kế 2 cánh mở song song sang trọng.\n"
        "## Thiết kế Side by Side sang trọng\n"
        "Hai cánh mở song song tiện lợi lấy đồ, phù hợp không gian bếp "
        "hiện đại rộng rãi.",
    # -- Casper --
    "RO-45PB":
        "Tủ lạnh mini 45L, 1 cánh, nhỏ gọn giá rẻ.\n"
        "## Nhỏ gọn giá rẻ\n"
        "Phù hợp phòng trọ, văn phòng hoặc làm tủ lạnh phụ trong gia "
        "đình.",
    "RT-230PB":
        "2 cánh, dung tích 218L, phù hợp gia đình nhỏ.\n"
        "## Phù hợp gia đình nhỏ\n"
        "Dung tích 218 lít đáp ứng nhu cầu bảo quản thực phẩm hàng ngày "
        "cho gia đình ít người.",
    "RT-258VG":
        "Dung tích lớn hơn, 2 cánh, phù hợp gia đình vừa.\n"
        "## Phù hợp gia đình vừa\n"
        "Dung tích 240 lít phù hợp gia đình 3-4 người sử dụng hàng ngày.",
    "RT-368VG":
        "Dung tích lớn, 2 cánh, phù hợp gia đình đông người.\n"
        "## Dung tích lớn cho gia đình đông người\n"
        "Dung tích 337 lít đáp ứng tốt nhu cầu tích trữ thực phẩm cho gia "
        "đình nhiều thành viên.",
    # -- Electrolux --
    "ETB2100MG":
        "Công nghệ Inverter NutriFresh, ngăn rau củ MarketFresh.\n"
        "## Hệ thống NutriFresh Inverter\n"
        "Giúp duy trì nhiệt độ ổn định, giữ thực phẩm tươi lâu hơn và "
        "tiết kiệm điện.",
    "ETB3200PE-RVN":
        "Dung tích lớn hơn, 2 cánh, phù hợp gia đình vừa.\n"
        "## Phù hợp gia đình vừa\n"
        "Dung tích 320 lít đáp ứng tốt nhu cầu bảo quản thực phẩm cho gia "
        "đình nhiều thành viên.",
    "ETM4407SD-RVN":
        "3 cánh, dung tích lớn, ngăn đựng đa dạng cho gia đình đông người.\n"
        "## Thiết kế đa ngăn tiện lợi\n"
        "3 cánh với nhiều ngăn riêng biệt giúp sắp xếp và bảo quản thực "
        "phẩm khoa học hơn.",
    # -- Panasonic --
    "NR-BS62GWVN":
        "Side by Side 532L, dung tích lớn, thiết kế sang trọng.\n"
        "## Dung tích lớn 532 lít\n"
        "Phù hợp gia đình đông người hoặc nhu cầu tích trữ thực phẩm số "
        "lượng lớn.",
    # -- Midea --
    "HS-65SN":
        "Tủ lạnh mini 58L, 1 cánh, dễ dàng điều chỉnh nhiệt độ.\n"
        "## Thiết kế nhỏ gọn tiện dụng\n"
        "Phù hợp phòng trọ, ký túc xá hoặc làm tủ lạnh phụ trong gia "
        "đình.",
    "MRD-160FWG":
        "2 cánh, dung tích 130L, công nghệ không đóng tuyết.\n"
        "## Công nghệ không đóng tuyết\n"
        "Quạt gió lưu thông giúp làm lạnh đều, hạn chế đóng tuyết trong "
        "ngăn đông.",
    "MRD-255FWES":
        "Dung tích lớn hơn, đèn LED, có ngăn rau củ riêng.\n"
        "## Đèn LED chiếu sáng tiết kiệm điện\n"
        "Hệ thống đèn LED tiêu thụ ít điện năng và tỏa nhiệt thấp hơn đèn "
        "sợi đốt truyền thống.",
    "MRD-333FWES":
        "Dung tích lớn, điều chỉnh nhiệt độ điện tử, kệ kính cường lực.\n"
        "## Điều chỉnh nhiệt độ điện tử\n"
        "Giúp cài đặt nhiệt độ chính xác và dễ dàng hơn so với núm vặn "
        "cơ.",

    # ==================== GIA DỤNG ====================
    # -- Quạt trần Panasonic --
    "F-60MZ2":
        "3 cánh, 5 mức tốc độ gió, giá tốt cho phòng khách.\n"
        "## 5 mức tốc độ gió\n"
        "Dễ dàng điều chỉnh luồng gió phù hợp với nhu cầu sử dụng theo "
        "từng thời điểm trong ngày.",
    "F-56MZG-GO":
        "4 cánh, thiết kế hiện đại, vận hành êm ái.\n"
        "## Thiết kế 4 cánh hiện đại\n"
        "Tạo luồng gió mát đều khắp phòng, phù hợp không gian phòng "
        "khách, phòng ngủ rộng.",
    "F-60UFN":
        "Motor DC tiết kiệm điện, tích hợp đèn LED chiếu sáng.\n"
        "## Motor DC tiết kiệm điện\n"
        "Động cơ DC tiêu thụ điện năng thấp hơn đáng kể so với motor AC "
        "truyền thống, vận hành êm ái.",
    # -- Quạt cây Panasonic --
    "F-307KHB":
        "Nhỏ gọn, 3 mức tốc độ, giá tốt.\n"
        "## Nhỏ gọn, dễ di chuyển\n"
        "Thiết kế thân quạt gọn nhẹ, dễ dàng di chuyển và cất giữ khi "
        "không sử dụng.",
    "F-409KB":
        "Điều khiển từ xa tiện lợi, sải cánh lớn hơn.\n"
        "## Điều khiển từ xa tiện lợi\n"
        "Cho phép bật tắt, chỉnh tốc độ từ xa mà không cần đứng dậy.",
    "F-407WGO":
        "Tích hợp đèn ngủ, phù hợp phòng ngủ.\n"
        "## Tích hợp đèn ngủ\n"
        "Đèn ngủ built-in tiện lợi cho phòng ngủ, không cần thêm thiết "
        "bị chiếu sáng phụ.",
    # -- Nồi cơm điện Midea --
    "MR-GM10SA":
        "Dung tích nhỏ, giá rẻ, phù hợp 1-2 người.\n"
        "## Phù hợp gia đình ít người\n"
        "Dung tích 1 lít vừa đủ cho 1-2 người ăn, tiết kiệm điện năng "
        "khi nấu lượng cơm nhỏ.",
    "MR-CM18SQ":
        "Dung tích 1.8L, lòng nồi phủ chống dính siêu bền.\n"
        "## Lòng nồi chống dính siêu bền\n"
        "Lớp phủ chống dính giúp cơm không bị cháy dính đáy nồi, dễ "
        "dàng vệ sinh sau khi nấu.",
    "MB-FC5019":
        "Lòng nồi hoàng kim đáy tổ ong, chống dính dày 2.0mm cao cấp.\n"
        "## Lòng nồi hoàng kim đáy tổ ong\n"
        "Cấu trúc đáy tổ ong giúp truyền nhiệt đều hơn, cơm chín đều và "
        "dẻo ngon hơn.",
    # -- Bếp Hòa Phát --
    "HPC F11A2":
        "Bếp hồng ngoại đơn, 5 chế độ nấu thông minh.\n"
        "## 5 chế độ nấu thông minh\n"
        "Tích hợp sẵn các chế độ nấu phù hợp nhiều món ăn, dễ sử dụng "
        "cho người mới.",
    "HPC F12A2":
        "Bếp hồng ngoại đơn, 8 mức điều chỉnh công suất.\n"
        "## 8 mức điều chỉnh công suất\n"
        "Cho phép tinh chỉnh nhiệt độ phù hợp với từng món ăn, từ hầm "
        "ninh đến chiên xào.",
    "HPC D11A2":
        "Bếp từ đơn, mặt kính cường lực, màn hình LED.\n"
        "## Mặt kính cường lực chịu nhiệt\n"
        "Bề mặt kính chịu lực, chịu nhiệt tốt, dễ vệ sinh sau khi nấu.",
    "HPC D12A2":
        "Bếp từ đơn, làm nóng nhanh, tiết kiệm điện hơn bếp gas.\n"
        "## Làm nóng nhanh, tiết kiệm điện\n"
        "Công nghệ từ trường làm nóng trực tiếp đáy nồi, tiết kiệm điện "
        "hơn bếp hồng ngoại.",
    "HPC D13A2":
        "Bếp từ đơn, 8 chức năng nấu thông minh, giá tốt.\n"
        "## 8 chức năng nấu thông minh\n"
        "Tích hợp sẵn các chế độ nấu phù hợp nhiều món ăn, dễ sử dụng "
        "cho người mới.",
    # -- Máy lọc không khí --
    "MC30VVM-A":
        "Cảm biến PM2.5, lọc 3 lớp, phù hợp không gian nhỏ.\n"
        "## Cảm biến PM2.5 thông minh\n"
        "Tự động nhận biết mức độ ô nhiễm không khí và điều chỉnh công "
        "suất lọc phù hợp.",
    "FP-J30E-A":
        "Công nghệ ion Plasmacluster, lọc HEPA, chế độ HAZE.\n"
        "## Công nghệ ion Plasmacluster\n"
        "Ion âm dương giúp khử mùi, ức chế vi khuẩn và nấm mốc trong "
        "không khí.",
    "AP151MBA1":
        "Thiết kế mini, motor Dual Inverter, cảm biến PM1.0.\n"
        "## Motor Dual Inverter bền bỉ\n"
        "Động cơ biến tần kép vận hành êm ái, tiết kiệm điện và có độ "
        "bền cao.",
    "AX40R3020WU":
        "Lọc 99.97% bụi mịn cho diện tích 40m², điều khiển qua app.\n"
        "## Điều khiển qua ứng dụng smartphone\n"
        "Cho phép bật tắt, theo dõi chất lượng không khí từ xa qua điện "
        "thoại.",
    "AP-250MAH":
        "Lọc HEPA, màn hình LED hiển thị, giá tốt cho phòng 30m².\n"
        "## Giá tốt cho phòng 30m²\n"
        "Phù hợp phòng ngủ, phòng khách cỡ vừa với chi phí đầu tư hợp "
        "lý.",

    # ==================== TIVI ====================
    # -- Casper --
    "32HN5000":
        "Tivi Casper 32HN5000 là lựa chọn tivi 32 inch độ phân giải HD dành cho những ai "
        "cần một chiếc tivi xem truyền hình cơ bản, gọn nhẹ và tiết kiệm chi phí. Với kích "
        "thước màn hình 32 inch, sản phẩm phù hợp làm tivi phòng ngủ, phòng bếp, phòng trọ "
        "hoặc làm tivi phụ trong nhà có nhiều phòng. Đây là dòng sản phẩm chính hãng Casper, "
        "nhập khẩu và phân phối tại Việt Nam với chế độ bảo hành 24 tháng rõ ràng.\n"
        "## Hình ảnh HD rõ nét, đủ dùng cho nhu cầu cơ bản\n"
        "Casper 32HN5000 sử dụng tấm nền HD cho hình ảnh rõ nét ở khoảng cách xem gần, phù "
        "hợp với diện tích phòng nhỏ như phòng ngủ hay phòng làm việc. Công nghệ xử lý hình "
        "ảnh giúp màu sắc hiển thị tự nhiên, độ tương phản ổn định khi xem các kênh truyền "
        "hình cáp, đầu thu kỹ thuật số hoặc kết nối qua đầu HDMI ngoài. Với người dùng chỉ "
        "có nhu cầu xem thời sự, phim truyền hình, giải trí cơ bản mà không cần các ứng "
        "dụng xem phim trực tuyến, đây là mức độ hình ảnh hoàn toàn đáp ứng tốt.\n"
        "## Thiết kế gọn nhẹ, dễ lắp đặt ở mọi không gian\n"
        "Với khung viền mỏng và trọng lượng nhẹ, tivi Casper 32 inch này dễ dàng treo tường "
        "hoặc đặt trên kệ tivi mà không chiếm nhiều diện tích. Đây là kích thước tivi phổ "
        "biến nhất cho phòng ngủ hoặc phòng có diện tích khiêm tốn, khoảng cách xem lý "
        "tưởng từ 1,2 đến 2 mét. Thiết kế chân đế chắc chắn giúp tivi đứng vững, hạn chế "
        "rung lắc khi sử dụng lâu dài.\n"
        "## Giá thành hợp lý, phù hợp trang bị cho nhiều phòng\n"
        "Đây là mẫu tivi có mức giá dễ tiếp cận nhất trong dải sản phẩm Casper hiện có tại "
        "Điện Máy Xuân Son, phù hợp với các gia đình muốn trang bị tivi cho nhiều phòng "
        "cùng lúc mà không cần đầu tư quá nhiều cho mỗi chiếc. Đây cũng là lựa chọn quen "
        "thuộc cho nhà trọ, ký túc xá, hoặc làm quà tặng tân gia với mức đầu tư vừa phải "
        "nhưng vẫn đảm bảo chất lượng hình ảnh ổn định.\n"
        "## Bảo hành chính hãng, an tâm sử dụng lâu dài\n"
        "Sản phẩm được phân phối chính hãng với chế độ bảo hành 24 tháng, đổi mới trong "
        "thời gian đầu nếu có lỗi từ nhà sản xuất. Đội ngũ kỹ thuật của Điện Máy Xuân Son "
        "hỗ trợ lắp đặt, treo tường tận nơi tại khu vực nội thành, giúp khách hàng an tâm "
        "sử dụng ngay sau khi mua mà không mất thêm chi phí phát sinh.\n"
        "## Có nên chọn tivi thường thay vì tivi thông minh?\n"
        "Nhiều khách hàng phân vân giữa tivi thường và tivi thông minh (smart TV) khi mua "
        "mới. Nếu gia đình đã có sẵn đầu thu kỹ thuật số, đầu Android TV Box hoặc chỉ xem "
        "truyền hình cáp thông thường, một chiếc tivi HD như 32HN5000 hoàn toàn đáp ứng đủ "
        "nhu cầu mà không cần trả thêm chi phí cho tính năng smart ít dùng đến. Đây cũng là "
        "lý do dòng sản phẩm này vẫn được nhiều gia đình lựa chọn dù thị trường đã có nhiều "
        "lựa chọn tivi thông minh giá tương đương.\n"
        "Nếu bạn đang tìm một chiếc tivi 32 inch giá tốt, hình ảnh rõ nét cho nhu cầu xem "
        "cơ bản hàng ngày, Casper 32HN5000 là lựa chọn đáng cân nhắc. Liên hệ hotline của "
        "Điện Máy Xuân Son để được tư vấn và báo giá lắp đặt nhanh nhất.",
    "32HG5000":
        "Tivi Casper 32HG5000 là dòng tivi thông minh 32 inch chạy hệ điều hành Android "
        "9.0, mang đến khả năng truy cập kho ứng dụng giải trí trực tuyến ngay trên tivi mà "
        "không cần thêm thiết bị Android TV Box rời. Với độ phân giải 2K HDR, sản phẩm cho "
        "hình ảnh sắc nét hơn hẳn so với dòng tivi thường cùng kích thước, phù hợp cho "
        "phòng khách nhỏ hoặc phòng ngủ muốn có trải nghiệm giải trí đầy đủ.\n"
        "## Hệ điều hành Android 9.0 tích hợp Google Assistant\n"
        "Điểm khác biệt lớn nhất của 32HG5000 so với dòng tivi phổ thông là khả năng cài "
        "đặt và sử dụng trực tiếp các ứng dụng xem phim, nghe nhạc, giải trí phổ biến ngay "
        "trên tivi. Trợ lý ảo Google Assistant tích hợp sẵn cho phép tìm kiếm nội dung, "
        "điều khiển tivi bằng giọng nói, giúp thao tác nhanh hơn so với việc dùng điều "
        "khiển bấm nút truyền thống. Đây là tính năng đặc biệt hữu ích với người lớn tuổi "
        "hoặc trẻ nhỏ trong nhà.\n"
        "## Bộ xử lý hình ảnh 2K HDR cho màu sắc sống động\n"
        "Công nghệ HDR giúp mở rộng dải tương phản, làm nổi bật chi tiết ở cả vùng sáng và "
        "vùng tối trong cùng một khung hình, mang lại trải nghiệm xem phim và các nội dung "
        "độ nét cao chân thực hơn. So với dòng HD thông thường, 32HG5000 cho hình ảnh có "
        "chiều sâu và màu sắc rực rỡ hơn rõ rệt, đặc biệt khi xem nội dung trên các nền "
        "tảng xem phim trực tuyến.\n"
        "## Phù hợp không gian phòng ngủ, phòng làm việc\n"
        "Kích thước 32 inch vẫn giữ nguyên tính gọn nhẹ, dễ treo tường hoặc đặt bàn, nhưng "
        "được nâng cấp thêm khả năng kết nối thông minh — phù hợp cho những ai muốn một "
        "chiếc tivi vừa xem truyền hình vừa giải trí trực tuyến mà không cần sắm thêm thiết "
        "bị rời. Đây cũng là lựa chọn tốt để làm tivi phụ có đầy đủ tính năng smart trong "
        "nhà đã có tivi lớn ở phòng khách.\n"
        "## Kết nối đa dạng, dễ sử dụng\n"
        "Tivi hỗ trợ kết nối WiFi trực tiếp, cổng HDMI và USB đầy đủ để mở rộng thêm các "
        "thiết bị ngoại vi như loa ngoài, đầu thu kỹ thuật số hoặc ổ cứng di động. Giao "
        "diện Android quen thuộc, dễ thao tác ngay cả với người mới lần đầu sử dụng tivi "
        "thông minh.\n"
        "## Có nên nâng cấp từ tivi HD lên bản Android?\n"
        "So với dòng tivi HD thường cùng kích thước, 32HG5000 có mức giá nhỉnh hơn nhưng bù "
        "lại là khả năng giải trí đa dạng hơn hẳn — không cần mua thêm Android TV Box rời, "
        "tiết kiệm được một khoản chi phí và bớt dây cắm lằng nhằng phía sau tivi. Đây là "
        "lựa chọn hợp lý cho các gia đình trẻ, có nhu cầu xem phim, nghe nhạc trực tuyến "
        "thường xuyên. Với những gia đình chỉ xem truyền hình cáp thông thường, dòng tivi "
        "HD phổ thông vẫn là lựa chọn tiết kiệm hơn.\n"
        "Với mức giá vẫn thuộc phân khúc phổ thông nhưng đã có đầy đủ tính năng smart TV, "
        "Casper 32HG5000 là bước nâng cấp hợp lý cho gia đình muốn trải nghiệm giải trí "
        "hiện đại hơn. Điện Máy Xuân Son có sẵn hàng chính hãng, hỗ trợ giao lắp và bảo "
        "hành 24 tháng.",
    "43FG5000":
        "Tivi Casper 43FG5000 sở hữu màn hình 43 inch cùng hệ điều hành Android 9.0 và bộ "
        "xử lý hình ảnh 2K HDR, là lựa chọn cân bằng giữa kích thước và chi phí cho phòng "
        "khách gia đình vừa và nhỏ. Đây là mẫu tivi được nhiều gia đình lựa chọn làm tivi "
        "chính vì vừa đủ lớn để xem thoải mái, vừa không chiếm quá nhiều diện tích phòng "
        "khách căn hộ chung cư.\n"
        "## Bộ xử lý hình ảnh 2K HDR tối ưu từng khung hình\n"
        "Công nghệ HDR trên 43FG5000 giúp tối ưu hóa độ sáng và độ tương phản theo từng "
        "cảnh quay, mang lại hình ảnh có chiều sâu hơn so với các dòng tivi không có HDR. "
        "Với kích thước 43 inch, sự khác biệt về độ chi tiết hình ảnh càng rõ ràng hơn khi "
        "xem ở khoảng cách gần trong phòng khách căn hộ.\n"
        "## Android 9.0 — giải trí đa nền tảng ngay trên tivi\n"
        "Hệ điều hành Android quen thuộc cho phép cài thêm ứng dụng xem phim, nghe nhạc "
        "trực tuyến mà không cần đầu thu rời. Kho ứng dụng đa dạng, cùng khả năng tìm kiếm "
        "bằng giọng nói qua Google Assistant giúp cả gia đình dễ dàng tìm nội dung yêu "
        "thích mà không mất nhiều thao tác.\n"
        "## Kích thước 43 inch — vừa vặn cho phòng khách chung cư\n"
        "Đây là kích thước được xem là \"vừa đủ\" cho phần lớn phòng khách căn hộ tại Việt "
        "Nam, phù hợp khoảng cách xem từ 2 đến 3 mét. Tivi không quá lớn để gây choáng "
        "ngợp không gian nhưng vẫn đủ diện tích hiển thị để xem phim, thể thao rõ nét cùng "
        "cả gia đình.\n"
        "## Thiết kế hiện đại, viền mỏng\n"
        "Khung viền mỏng giúp tivi có tính thẩm mỹ cao khi đặt trong phòng khách, kết hợp "
        "chân đế chắc chắn hoặc có thể treo tường tùy theo bố trí nội thất. Cổng kết nối "
        "HDMI, USB đầy đủ để mở rộng thêm thiết bị âm thanh, đầu thu ngoài khi cần.\n"
        "## So sánh 43 inch với các kích thước lân cận\n"
        "Nhiều khách hàng phân vân giữa 43 inch và 50 inch khi chọn mua tivi cho phòng "
        "khách. Với diện tích phòng dưới 15m², 43 inch là lựa chọn cân đối hơn, tránh tình "
        "trạng ngồi quá gần màn hình lớn gây mỏi mắt khi xem lâu. Ngược lại, nếu phòng "
        "khách rộng trên 18m², nên cân nhắc các phiên bản 50 inch hoặc 55 inch trong cùng "
        "dòng UG6000 để có trải nghiệm xem tốt hơn. Điện Máy Xuân Son luôn tư vấn kỹ về "
        "khoảng cách và diện tích phòng trước khi khách hàng chốt kích thước, tránh trường "
        "hợp mua tivi không phù hợp không gian sử dụng thực tế.\n"
        "## Lắp đặt và bảo quản\n"
        "Tivi nên được đặt ở nơi khô ráo, tránh ánh nắng chiếu trực tiếp vào màn hình gây "
        "chói và giảm tuổi thọ tấm nền. Khi treo tường, nên chọn giá treo phù hợp với "
        "chuẩn lỗ vít của Casper để đảm bảo an toàn, tránh tự lắp đặt nếu không có kinh "
        "nghiệm vì tivi có trọng lượng và kích thước lớn hơn các dòng 32 inch thông "
        "thường.\n"
        "Casper 43FG5000 phù hợp với các gia đình đang tìm một chiếc tivi smart 43 inch giá "
        "hợp lý, hình ảnh rõ nét cho phòng khách vừa và nhỏ. Điện Máy Xuân Son cung cấp "
        "hàng chính hãng, bảo hành 24 tháng và hỗ trợ giao lắp tận nơi.",
    "50UG6000":
        "Tivi Casper 50UG6000 nâng cấp lên độ phân giải 4K HDR với kích thước màn hình 50 "
        "inch, mang lại trải nghiệm hình ảnh sắc nét vượt trội so với các dòng 2K HDR cùng "
        "thương hiệu. Đây là lựa chọn phù hợp cho phòng khách rộng, nơi cần một chiếc tivi "
        "đủ lớn để cả gia đình cùng xem phim, thể thao mà vẫn giữ được độ chi tiết hình ảnh "
        "ở khoảng cách xa.\n"
        "## Bộ xử lý hình ảnh 4K HDR tối ưu màu sắc\n"
        "Độ phân giải 4K cho mật độ điểm ảnh cao gấp 4 lần Full HD, giúp hình ảnh sắc nét "
        "ngay cả khi xem gần màn hình lớn. Kết hợp công nghệ HDR, tivi tự động tối ưu độ "
        "sáng và màu sắc theo từng cảnh, làm nổi bật chi tiết ở cả vùng sáng chói và vùng "
        "tối sâu — điều mà các dòng tivi độ phân giải thấp hơn khó tái hiện được.\n"
        "## Phù hợp không gian phòng khách rộng\n"
        "Với kích thước 50 inch, khoảng cách xem lý tưởng từ 2,5 đến 3,5 mét, đây là lựa "
        "chọn cân bằng cho các phòng khách có diện tích từ 15-20m² trở lên. Kích thước này "
        "đủ lớn để tạo cảm giác như đang xem tại rạp chiếu phim mini ngay tại nhà, đặc biệt "
        "phù hợp khi kết hợp thêm loa ngoài hoặc dàn âm thanh.\n"
        "## Android 9.0 và Google Assistant tích hợp\n"
        "Hệ điều hành Android 9.0 mang đến kho ứng dụng phong phú cho nhu cầu xem phim, "
        "nghe nhạc trực tuyến, cùng khả năng điều khiển bằng giọng nói qua Google "
        "Assistant. Việc tìm kiếm nội dung, chuyển kênh hay mở ứng dụng trở nên nhanh chóng "
        "hơn, phù hợp với mọi thành viên trong gia đình kể cả người lớn tuổi.\n"
        "## Thiết kế hiện đại, dễ dàng bố trí\n"
        "Khung viền mỏng đồng bộ với các dòng tivi Casper khác, có thể treo tường để tiết "
        "kiệm diện tích hoặc đặt chân đế vững chắc trên kệ tivi. Cổng kết nối đầy đủ hỗ trợ "
        "đầu thu, loa ngoài và các thiết bị giải trí khác.\n"
        "## Nên chọn 4K hay 2K HDR cho phòng khách?\n"
        "Với màn hình từ 43 inch trở lên, chênh lệch độ nét giữa 2K và 4K bắt đầu rõ ràng "
        "hơn, đặc biệt khi ngồi ở khoảng cách gần theo khuyến nghị. Nếu ngân sách cho phép, "
        "chọn thẳng bản 4K HDR như 50UG6000 sẽ giúp tivi không bị lỗi thời nhanh khi các "
        "nội dung truyền hình, phim ảnh ngày càng chuyển sang chuẩn 4K phổ biến hơn. Đây "
        "cũng là khoản đầu tư dùng được lâu dài hơn so với việc mua tivi độ phân giải thấp "
        "rồi phải nâng cấp lại sau vài năm.\n"
        "Casper 50UG6000 là lựa chọn hợp lý cho gia đình muốn nâng cấp lên tivi 4K mà vẫn "
        "giữ mức chi phí hợp lý so với các thương hiệu cao cấp. Điện Máy Xuân Son có sẵn "
        "hàng chính hãng, bảo hành 24 tháng, hỗ trợ giao lắp tận nơi nội thành Hà Nội.",
    "55UG6000":
        "Tivi Casper 55UG6000 là phiên bản 55 inch trong dòng 4K HDR của Casper, phù hợp "
        "cho phòng khách gia đình có diện tích rộng rãi hoặc những ai yêu thích trải "
        "nghiệm xem phim với màn hình lớn. Cùng nền tảng Android 9.0 và độ phân giải 4K "
        "như phiên bản 50 inch, sản phẩm mang lại cảm giác điện ảnh rõ nét hơn nhờ kích "
        "thước màn hình lớn hơn.\n"
        "## Màn hình lớn 55 inch — trải nghiệm điện ảnh tại gia\n"
        "Với kích thước 55 inch, tivi phù hợp không gian phòng khách từ 18-25m² trở lên, "
        "khoảng cách xem lý tưởng từ 2,8 đến 4 mét. Đây là kích thước được nhiều gia đình "
        "lựa chọn khi muốn có trải nghiệm xem phim, bóng đá tại nhà gần giống với rạp "
        "chiếu, đặc biệt phù hợp cho các buổi tụ họp gia đình đông người.\n"
        "## 4K HDR cho hình ảnh chi tiết, chân thực\n"
        "Độ phân giải 4K kết hợp HDR giúp tái hiện chi tiết hình ảnh sắc nét dù màn hình "
        "lớn, tránh tình trạng vỡ hạt hay mờ nhòe thường gặp ở các dòng tivi độ phân giải "
        "thấp khi phóng to kích thước màn hình. Màu sắc được xử lý sống động, tương phản "
        "tốt giữa vùng sáng và vùng tối.\n"
        "## Android 9.0 tích hợp Google Assistant\n"
        "Hệ điều hành Android quen thuộc cho phép cài đặt các ứng dụng xem phim, nghe nhạc "
        "trực tuyến phổ biến, cùng khả năng tìm kiếm và điều khiển bằng giọng nói. Đây là "
        "tính năng giúp cả gia đình dễ dàng chuyển đổi giữa xem truyền hình thông thường và "
        "giải trí trực tuyến mà không cần thêm thiết bị.\n"
        "## Thiết kế sang trọng, phù hợp phòng khách hiện đại\n"
        "Khung viền mỏng, kiểu dáng hiện đại giúp tivi trở thành điểm nhấn trong phòng "
        "khách. Có thể treo tường để tối ưu không gian hoặc đặt chân đế tùy theo bố trí nội "
        "thất từng gia đình.\n"
        "## Khoảng cách xem lý tưởng cho tivi 55 inch\n"
        "Một sai lầm thường gặp là đặt tivi quá gần hoặc quá xa so với vị trí ngồi xem. Với "
        "55 inch, khoảng cách 2,8-4 mét là mức lý tưởng để mắt tiếp nhận trọn vẹn khung "
        "hình mà không phải đảo mắt liên tục hay ngồi quá xa làm mất chi tiết hình ảnh. Khi "
        "tư vấn lắp đặt, đội ngũ kỹ thuật của Điện Máy Xuân Son sẽ đo đạc thực tế phòng "
        "khách để gợi ý độ cao treo tường phù hợp, tránh trường hợp tivi đặt quá cao gây "
        "mỏi cổ khi xem lâu.\n"
        "## Bảo dưỡng tivi màn hình lớn đúng cách\n"
        "Để giữ độ bền và chất lượng hình ảnh lâu dài, nên lau màn hình bằng khăn mềm, "
        "khô, tránh dùng khăn ướt hoặc hóa chất tẩy rửa mạnh có thể làm hỏng lớp phủ chống "
        "chói trên bề mặt. Vị trí đặt tivi cũng nên thoáng khí phía sau để tản nhiệt tốt, "
        "hạn chế kê sát tường hoặc nhét trong tủ kín gây nóng máy khi sử dụng liên tục "
        "trong thời gian dài.\n"
        "Nếu bạn đang tìm một chiếc tivi 55 inch 4K với mức giá hợp lý hơn so với các "
        "thương hiệu cao cấp, Casper 55UG6000 là lựa chọn đáng cân nhắc. Điện Máy Xuân Son "
        "cung cấp hàng chính hãng, bảo hành 24 tháng, hỗ trợ giao lắp treo tường tận nơi.",
    "65UG6000":
        "Tivi Casper 65UG6000 là mẫu tivi có kích thước lớn nhất trong dòng 4K HDR của "
        "Casper, hướng đến các gia đình có phòng khách rộng hoặc mong muốn sở hữu một "
        "chiếc tivi kích cỡ ấn tượng cho không gian giải trí tại nhà. Với 65 inch màn hình "
        "cùng độ phân giải 4K, đây là lựa chọn phù hợp thay thế máy chiếu trong các buổi "
        "xem phim, xem thể thao gia đình.\n"
        "## Kích thước 65 inch cho không gian phòng khách rộng\n"
        "Phù hợp với phòng khách từ 25m² trở lên, khoảng cách xem lý tưởng từ 3,2 mét trở "
        "ra. Đây là kích thước lý tưởng cho các gia đình nhiều thế hệ cùng sinh hoạt chung, "
        "hoặc những không gian phòng khách liền bếp có diện tích mở, cần tivi đủ lớn để "
        "nhìn rõ từ nhiều góc trong nhà.\n"
        "## 4K HDR — độ nét cao dù màn hình lớn\n"
        "Với diện tích hiển thị lớn, độ phân giải 4K là yếu tố bắt buộc để đảm bảo hình "
        "ảnh không bị vỡ hạt. Công nghệ HDR tối ưu từng khung hình giúp màu sắc sống động, "
        "chi tiết rõ ràng ở cả cảnh tối và cảnh sáng, mang lại trải nghiệm gần với rạp "
        "chiếu phim.\n"
        "## Android 9.0 và Google Assistant\n"
        "Nền tảng Android quen thuộc cho phép truy cập kho ứng dụng giải trí phong phú, "
        "cùng khả năng điều khiển giọng nói tiện lợi. Với màn hình lớn, việc xem nội dung "
        "độ phân giải cao trên các nền tảng trực tuyến càng phát huy hiệu quả rõ rệt.\n"
        "## Lắp đặt và vận chuyển cần lưu ý\n"
        "Với kích thước lớn, khách hàng nên cân nhắc vị trí lắp đặt và lối đi khi vận "
        "chuyển vào nhà. Điện Máy Xuân Son hỗ trợ đội ngũ giao hàng, lắp đặt chuyên "
        "nghiệp, đảm bảo tivi được treo tường hoặc kê chắc chắn, an toàn ngay sau khi "
        "giao.\n"
        "## Kết hợp âm thanh để trọn vẹn trải nghiệm\n"
        "Với màn hình lớn 65 inch, nhiều gia đình lựa chọn kết hợp thêm loa thanh (soundbar) "
        "hoặc dàn âm thanh rời để bù lại độ vang mà loa tích hợp trong tivi khó tái hiện "
        "được ở không gian phòng khách rộng. Cổng kết nối HDMI ARC trên tivi cho phép kết "
        "nối loa ngoài đơn giản chỉ với một dây cáp, không cần điều khiển riêng cho từng "
        "thiết bị. Đây là gợi ý hữu ích nếu bạn muốn nâng cấp trải nghiệm xem phim, xem "
        "bóng đá tại nhà lên một mức mới.\n"
        "## Phù hợp không gian kinh doanh, phòng họp\n"
        "Ngoài sử dụng gia đình, kích thước 65 inch còn được nhiều cửa hàng, quán cà phê, "
        "phòng họp doanh nghiệp lựa chọn để trình chiếu, xem sự kiện thể thao đông người "
        "hoặc làm màn hình thuyết trình. Độ phân giải 4K đảm bảo chữ và hình ảnh vẫn sắc "
        "nét dù đứng quan sát từ khoảng cách xa hơn so với sử dụng trong gia đình.\n"
        "Casper 65UG6000 phù hợp với gia đình yêu thích trải nghiệm xem phim màn hình lớn "
        "mà không muốn đầu tư vào các thương hiệu cao cấp hơn. Sản phẩm chính hãng, bảo "
        "hành 24 tháng, được Điện Máy Xuân Son hỗ trợ giao lắp tận nơi.",
    # -- Sony --
    "KDL-32R300C":
        "Tivi Sony KDL-32R300C là mẫu tivi LED 32 inch độ phân giải HD, mang thương hiệu "
        "Sony nổi tiếng về độ bền và chất lượng hiển thị ổn định. Đây là lựa chọn phù hợp "
        "cho những ai ưu tiên uy tín thương hiệu Nhật Bản, cần một chiếc tivi kích thước "
        "nhỏ gọn cho phòng ngủ hoặc phòng làm việc với độ tin cậy cao trong quá trình sử "
        "dụng lâu dài.\n"
        "## Công nghệ hiển thị LED ổn định từ Sony\n"
        "Sony là thương hiệu có bề dày kinh nghiệm trong lĩnh vực công nghệ hình ảnh, và "
        "KDL-32R300C thừa hưởng công nghệ xử lý hình ảnh giúp màu sắc hiển thị chân thực, "
        "độ sáng đồng đều trên toàn màn hình. Đây là điểm khác biệt dễ nhận thấy so với các "
        "dòng tivi phổ thông cùng phân khúc giá.\n"
        "## Kích thước 32 inch nhỏ gọn, đa năng\n"
        "Phù hợp làm tivi phòng ngủ, phòng bếp hoặc phòng làm việc nhờ kích thước nhỏ gọn, "
        "dễ treo tường hoặc đặt trên kệ. Đây cũng là lựa chọn phổ biến để làm tivi phụ "
        "trong các gia đình đã có tivi lớn ở phòng khách, hoặc trang bị cho phòng khách "
        "sạn, homestay nhờ độ bền cao và thương hiệu uy tín.\n"
        "## Độ bền và độ tin cậy — thế mạnh của thương hiệu Sony\n"
        "Nhiều người dùng chọn Sony không chỉ vì chất lượng hình ảnh mà còn vì độ bền vượt "
        "trội theo thời gian, ít gặp lỗi vặt so với các thương hiệu phổ thông khác. Đây là "
        "yếu tố quan trọng với những ai muốn đầu tư một lần và sử dụng lâu dài mà không "
        "phải sửa chữa, thay thế thường xuyên.\n"
        "## Kết nối cơ bản, dễ sử dụng\n"
        "Tivi được trang bị cổng kết nối HDMI, USB tiêu chuẩn, tương thích tốt với đầu thu "
        "kỹ thuật số, đầu ghi hình hoặc các thiết bị giải trí khác. Giao diện điều khiển "
        "đơn giản, phù hợp với mọi lứa tuổi sử dụng.\n"
        "## Vì sao nhiều gia đình vẫn ưu tiên thương hiệu Sony?\n"
        "Trên thị trường hiện có rất nhiều lựa chọn tivi giá rẻ với thông số tương tự, "
        "nhưng thương hiệu Sony vẫn được nhiều khách hàng lớn tuổi hoặc gia đình có kinh "
        "nghiệm mua sắm điện tử tin tưởng nhờ lịch sử lâu năm về chất lượng và dịch vụ hậu "
        "mãi. Với những ai từng sử dụng sản phẩm Sony trước đây, đây thường là lựa chọn "
        "được ưu tiên hàng đầu khi thay tivi mới, kể cả ở phân khúc phổ thông như "
        "KDL-32R300C.\n"
        "## Lựa chọn phù hợp cho phòng cho thuê, homestay\n"
        "Nhờ độ bền cao và ít gặp lỗi vặt, dòng tivi này cũng thường được các chủ nhà "
        "trọ, chung cư mini hay homestay lựa chọn trang bị vì không cần bảo trì thường "
        "xuyên trong quá trình cho thuê dài hạn. Đây là yếu tố giúp tiết kiệm chi phí sửa "
        "chữa phát sinh về sau so với các dòng tivi giá rẻ không rõ nguồn gốc.\n"
        "Nếu bạn đang tìm một chiếc tivi 32 inch từ thương hiệu uy tín Nhật Bản với mức giá "
        "hợp lý, Sony KDL-32R300C là lựa chọn đáng tin cậy. Điện Máy Xuân Son cung cấp hàng "
        "chính hãng, bảo hành 24 tháng, hỗ trợ giao lắp tận nơi.",
    "KD-55A1":
        "Tivi Sony KD-55A1 sử dụng công nghệ màn hình OLED cao cấp với độ phân giải 4K "
        "HDR, đại diện cho dòng sản phẩm cao cấp của Sony dành cho những khách hàng yêu "
        "cầu chất lượng hình ảnh ở mức tốt nhất. Với kích thước 55 inch, đây là lựa chọn lý "
        "tưởng cho phòng khách hiện đại, đặc biệt phù hợp với những ai đam mê xem phim, "
        "chơi game hoặc thưởng thức nội dung độ phân giải cao.\n"
        "## Công nghệ màn hình OLED — màu đen sâu tuyệt đối\n"
        "Khác với tivi LED thông thường cần đèn nền chiếu sáng toàn màn hình, mỗi điểm ảnh "
        "trên tấm nền OLED có thể tự phát sáng và tắt độc lập. Điều này cho phép hiển thị "
        "màu đen tuyệt đối tại những điểm ảnh cần tối, mang lại độ tương phản vượt trội mà "
        "công nghệ LED khó đạt được. Đây là lý do các dòng tivi OLED thường được giới yêu "
        "phim ảnh và chuyên gia hình ảnh đánh giá cao.\n"
        "## 4K HDR kết hợp bộ xử lý hình ảnh Sony\n"
        "Sony nổi tiếng với các bộ xử lý hình ảnh độc quyền, giúp tối ưu màu sắc, độ nét và "
        "chuyển động mượt mà ngay cả trong các cảnh hành động nhanh. Kết hợp cùng độ phân "
        "giải 4K và công nghệ HDR, KD-55A1 mang lại trải nghiệm hình ảnh chân thực, chi "
        "tiết ở cả vùng sáng và vùng tối trong cùng khung hình.\n"
        "## Phù hợp phòng khách hiện đại, không gian giải trí cao cấp\n"
        "Kích thước 55 inch cân bằng giữa diện tích hiển thị và không gian lắp đặt, phù "
        "hợp phòng khách từ 18-25m². Thiết kế mỏng, sang trọng của Sony giúp tivi trở "
        "thành điểm nhấn nội thất, phù hợp với những không gian sống hiện đại, tối giản.\n"
        "## Trải nghiệm âm thanh và kết nối cao cấp\n"
        "Các dòng OLED cao cấp của Sony thường đi kèm công nghệ âm thanh phát ra trực tiếp "
        "từ màn hình, tạo cảm giác âm thanh đồng bộ với hình ảnh đang hiển thị — một điểm "
        "khác biệt so với loa rời truyền thống. Cổng kết nối HDMI hỗ trợ đầy đủ cho các "
        "thiết bị giải trí như đầu Blu-ray, máy chơi game hay dàn âm thanh rời.\n"
        "## Có đáng đầu tư vào OLED so với 4K LED thông thường?\n"
        "Chênh lệch giá giữa dòng OLED và LED 4K cùng kích thước là điều khiến nhiều khách "
        "hàng cân nhắc. Tuy nhiên, với những ai thường xuyên xem phim vào buổi tối, ưu "
        "tiên chất lượng hình ảnh hơn diện tích màn hình, khoản chênh lệch này hoàn toàn "
        "xứng đáng nhờ độ tương phản và màu đen sâu mà công nghệ LED khó tái hiện được. Đây "
        "là lý do các rạp chiếu phim tại gia cao cấp và người dùng chuyên về hình ảnh gần "
        "như luôn ưu tiên lựa chọn OLED khi ngân sách cho phép.\n"
        "Sony KD-55A1 phù hợp với khách hàng muốn đầu tư vào một chiếc tivi cao cấp thực "
        "sự, ưu tiên chất lượng hình ảnh hàng đầu hơn là mức giá. Điện Máy Xuân Son cung "
        "cấp hàng chính hãng, bảo hành 24 tháng, tư vấn và hỗ trợ giao lắp tận nơi.",
    "KD-65A1":
        "Tivi Sony KD-65A1 là phiên bản 65 inch trong dòng OLED cao cấp của Sony, mang đến "
        "trải nghiệm điện ảnh tại nhà với màn hình lớn kết hợp công nghệ hiển thị hàng đầu. "
        "Đây là lựa chọn dành cho những gia đình có phòng khách rộng, mong muốn sở hữu một "
        "chiếc tivi vừa có kích thước ấn tượng vừa đảm bảo chất lượng hình ảnh ở đẳng cấp "
        "cao nhất.\n"
        "## Màn hình OLED 65 inch — đắm chìm trong từng khung hình\n"
        "Với diện tích hiển thị lớn, ưu điểm màu đen sâu và độ tương phản của công nghệ "
        "OLED càng được phát huy rõ rệt, đặc biệt khi xem phim trong phòng thiếu sáng vào "
        "buổi tối. Mỗi điểm ảnh tự phát sáng độc lập giúp hình ảnh có chiều sâu, không bị "
        "hiện tượng \"bệt màu\" thường gặp ở các tấm nền LED giá rẻ khi phóng to kích "
        "thước.\n"
        "## 4K HDR và công nghệ xử lý hình ảnh độc quyền Sony\n"
        "Bộ xử lý hình ảnh của Sony được đánh giá cao trong việc tái tạo màu sắc tự nhiên, "
        "xử lý chuyển động mượt mà và giảm nhiễu hạt ngay cả với nội dung có độ phân giải "
        "thấp hơn 4K gốc. Đây là công nghệ giúp KD-65A1 luôn hiển thị hình ảnh sắc nét dù "
        "nguồn phát khác nhau, từ truyền hình cáp đến các nền tảng xem phim trực tuyến độ "
        "nét cao.\n"
        "## Phù hợp không gian phòng khách lớn, phòng chiếu phim gia đình\n"
        "Kích thước 65 inch phù hợp phòng khách từ 25m² trở lên, khoảng cách xem từ 3,2 "
        "mét. Đây là lựa chọn được nhiều gia đình yêu thích khi muốn tạo không gian giải "
        "trí tại nhà tương đương phòng chiếu phim mini, đặc biệt khi kết hợp thêm dàn âm "
        "thanh rời.\n"
        "## Đầu tư dài hạn cho trải nghiệm giải trí cao cấp\n"
        "Tivi OLED cao cấp thường có mức giá cao hơn đáng kể so với dòng LED, nhưng đổi "
        "lại là chất lượng hình ảnh vượt trội và độ bền được Sony bảo chứng qua nhiều năm "
        "trên thị trường. Đây là khoản đầu tư phù hợp với gia đình xem đây là thiết bị "
        "giải trí trung tâm, sử dụng thường xuyên trong thời gian dài.\n"
        "## Lưu ý khi lắp đặt tivi OLED kích thước lớn\n"
        "Tấm nền OLED có cấu tạo mỏng nhẹ hơn LED truyền thống nhưng cũng cần được lắp đặt "
        "cẩn thận để tránh va đập trong quá trình vận chuyển. Điện Máy Xuân Son khuyến "
        "nghị khách hàng sử dụng dịch vụ giao lắp chuyên nghiệp thay vì tự vận chuyển, đặc "
        "biệt với kích thước 65 inch cần ít nhất hai người hỗ trợ khi di chuyển. Vị trí "
        "treo tường cũng nên tránh gần cửa sổ có ánh nắng chiếu trực tiếp để bảo vệ độ bền "
        "màu sắc của tấm nền theo thời gian.\n"
        "Sony KD-65A1 là lựa chọn hàng đầu cho những ai tìm kiếm trải nghiệm xem phim tại "
        "nhà đẳng cấp nhất hiện có tại Điện Máy Xuân Son. Sản phẩm chính hãng, bảo hành 24 "
        "tháng, đội ngũ kỹ thuật hỗ trợ vận chuyển và lắp đặt tận nơi an toàn cho tivi kích "
        "thước lớn.",
}


def seed_if_empty():
    with get_conn() as c:
        if c.execute("SELECT COUNT(*) FROM categories").fetchone()[0] > 0:
            return
        cat_ids = {}
        for order, (name, icon) in enumerate(SEED_CATEGORIES):
            slug = unique_slug(c, "categories", name)
            cur = c.execute(
                "INSERT INTO categories (name, slug, icon, sort_order) VALUES (?,?,?,?)",
                (name, slug, icon, order),
            )
            cat_ids[name] = cur.lastrowid
        brand_ids = {}
        for name in SEED_BRANDS:
            slug = unique_slug(c, "brands", name)
            cur = c.execute("INSERT INTO brands (name, slug) VALUES (?,?)", (name, slug))
            brand_ids[name] = cur.lastrowid
        for i, (cat, brand, name, price, sale, short_desc, specs, warranty) in enumerate(SEED_PRODUCTS):
            slug = unique_slug(c, "products", name)
            specs_json = json.dumps([{"k": k, "v": v} for k, v in specs], ensure_ascii=False)
            c.execute(
                """INSERT INTO products
                   (name, slug, category_id, brand_id, price, sale_price, image,
                    short_desc, description, specs, warranty_months, in_stock,
                    is_featured, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    name, slug, cat_ids[cat], brand_ids.get(brand), price, sale,
                    CATEGORY_BRAND_IMAGES.get((cat, brand), ""),
                    short_desc, short_desc, specs_json, warranty, 1,
                    1 if i % 3 == 0 else 0, datetime.utcnow().isoformat(),
                ),
            )
            best_match = None
            for model_code, article_text in PRODUCT_ARTICLES.items():
                if model_code in name and (best_match is None or len(model_code) > len(best_match[0])):
                    best_match = (model_code, article_text)
            if best_match:
                c.execute(
                    "UPDATE products SET description = ? WHERE slug = ?",
                    (best_match[1], slug),
                )
        if c.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 0:
            for title, excerpt, content in SEED_ARTICLES:
                slug = unique_slug(c, "articles", title)
                c.execute(
                    """INSERT INTO articles (title, slug, image, excerpt, content,
                       category, published, created_at) VALUES (?,?,?,?,?,?,?,?)""",
                    (title, slug, "", excerpt, content, "Kiến thức tiêu dùng", 1,
                     datetime.utcnow().isoformat()),
                )


def load_settings() -> dict:
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        merged = dict(DEFAULT_SETTINGS)
        merged.update(data)
        return merged
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT_SETTINGS)


def save_settings(data: dict):
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.replace("đ", "d").replace("Đ", "D")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text or "muc"


def unique_slug(conn, table: str, base: str, exclude_id: int | None = None) -> str:
    slug = slugify(base)
    candidate = slug
    i = 2
    while True:
        q = f"SELECT id FROM {table} WHERE slug = ?"
        params = [candidate]
        if exclude_id is not None:
            q += " AND id != ?"
            params.append(exclude_id)
        row = conn.execute(q, params).fetchone()
        if not row:
            return candidate
        candidate = f"{slug}-{i}"
        i += 1


# --------------------------------------------------------------- categories

def list_categories(conn=None):
    if conn is not None:
        return conn.execute(
            "SELECT * FROM categories ORDER BY sort_order, name"
        ).fetchall()
    with get_conn() as c:
        return c.execute("SELECT * FROM categories ORDER BY sort_order, name").fetchall()


def get_category_by_slug(slug: str):
    with get_conn() as c:
        return c.execute("SELECT * FROM categories WHERE slug = ?", (slug,)).fetchone()


def get_category(cat_id: int):
    with get_conn() as c:
        return c.execute("SELECT * FROM categories WHERE id = ?", (cat_id,)).fetchone()


def create_category(name: str, icon: str = "", sort_order: int = 0):
    with get_conn() as c:
        slug = unique_slug(c, "categories", name)
        cur = c.execute(
            "INSERT INTO categories (name, slug, icon, sort_order) VALUES (?, ?, ?, ?)",
            (name, slug, icon, sort_order),
        )
        return cur.lastrowid


def update_category(cat_id: int, name: str, icon: str, sort_order: int):
    with get_conn() as c:
        slug = unique_slug(c, "categories", name, exclude_id=cat_id)
        c.execute(
            "UPDATE categories SET name=?, slug=?, icon=?, sort_order=? WHERE id=?",
            (name, slug, icon, sort_order, cat_id),
        )


def delete_category(cat_id: int):
    with get_conn() as c:
        c.execute("DELETE FROM categories WHERE id = ?", (cat_id,))


# -------------------------------------------------------------------- brands

def list_brands():
    with get_conn() as c:
        return c.execute("SELECT * FROM brands ORDER BY name").fetchall()


def list_brands_for_category(category_slug):
    with get_conn() as c:
        return c.execute(
            """SELECT DISTINCT b.* FROM brands b
               JOIN products p ON p.brand_id = b.id
               JOIN categories c ON c.id = p.category_id
               WHERE c.slug = ?
               ORDER BY b.name""",
            (category_slug,),
        ).fetchall()



def list_brands_for_search(q):
    with get_conn() as c:
        return c.execute(
            """SELECT DISTINCT b.* FROM brands b
               JOIN products p ON p.brand_id = b.id
               WHERE p.name LIKE ?
               ORDER BY b.name""",
            (f"%{q}%",),
        ).fetchall()


def get_brand(brand_id: int):
    with get_conn() as c:
        return c.execute("SELECT * FROM brands WHERE id = ?", (brand_id,)).fetchone()


def get_brand_by_name(name: str):
    with get_conn() as c:
        return c.execute("SELECT * FROM brands WHERE name = ?", (name,)).fetchone()


def create_brand(name: str, logo: str = ""):
    with get_conn() as c:
        slug = unique_slug(c, "brands", name)
        cur = c.execute("INSERT INTO brands (name, slug, logo) VALUES (?, ?, ?)", (name, slug, logo))
        return cur.lastrowid


def update_brand(brand_id: int, name: str, logo: str | None = None):
    with get_conn() as c:
        slug = unique_slug(c, "brands", name, exclude_id=brand_id)
        if logo is not None:
            c.execute("UPDATE brands SET name=?, slug=?, logo=? WHERE id=?", (name, slug, logo, brand_id))
        else:
            c.execute("UPDATE brands SET name=?, slug=? WHERE id=?", (name, slug, brand_id))


def update_brand_logo(brand_id: int, logo: str):
    with get_conn() as c:
        c.execute("UPDATE brands SET logo=? WHERE id=?", (logo, brand_id))


def delete_brand(brand_id: int):
    with get_conn() as c:
        c.execute("DELETE FROM brands WHERE id = ?", (brand_id,))


# ----------------------------------------------------------------- products

PRODUCT_SELECT = """
SELECT p.*, c.name AS category_name, c.slug AS category_slug,
       b.name AS brand_name
FROM products p
JOIN categories c ON c.id = p.category_id
LEFT JOIN brands b ON b.id = p.brand_id
"""


def list_products(category_slug=None, brand_id=None, featured=None, q=None,
                   sort="new", page=1, per_page=12, loai=None, duoi=None, xuat_xu=None,
                   on_sale=None):
    where = []
    params = []
    if category_slug:
        where.append("c.slug = ?")
        params.append(category_slug)
    if brand_id:
        where.append("p.brand_id = ?")
        params.append(brand_id)
    if featured is not None:
        where.append("p.is_featured = ?")
        params.append(1 if featured else 0)
    if on_sale:
        where.append("p.sale_price IS NOT NULL AND p.sale_price < p.price")
    if q:
        where.append("p.name LIKE ?")
        params.append(f"%{q}%")
    if loai:
        where.append("p.specs LIKE ?")
        params.append(f"%{loai}%")
    if xuat_xu:
        where.append("p.specs LIKE ?")
        params.append(f"%{xuat_xu}%")
    if duoi:
        where.append("COALESCE(p.sale_price, p.price) <= ?")
        params.append(duoi)
    sql = PRODUCT_SELECT
    if where:
        sql += " WHERE " + " AND ".join(where)
    order = {
        "new": "p.created_at DESC",
        "price_asc": "COALESCE(p.sale_price, p.price) ASC",
        "price_desc": "COALESCE(p.sale_price, p.price) DESC",
        "name": "p.name ASC",
        "discount": "(1.0 - (p.sale_price * 1.0 / p.price)) DESC",
    }.get(sort, "p.created_at DESC")
    count_sql = "SELECT COUNT(*) FROM (" + sql + ")"
    sql += f" ORDER BY {order} LIMIT ? OFFSET ?"
    with get_conn() as c:
        total = c.execute(count_sql, params).fetchone()[0]
        rows = c.execute(sql, params + [per_page, (page - 1) * per_page]).fetchall()
    return rows, total


def search_products_for_chat(query: str, limit: int = 8):
    """Tìm sản phẩm liên quan tới câu hỏi của khách (theo tên/hãng/danh mục/mô tả
    ngắn) để ghim chatbot vào đúng dữ liệu thật đang bán, tránh bịa sản phẩm."""
    words = [w for w in re.split(r"\s+", query.strip()) if len(w) > 1]
    if not words:
        return []
    where_parts = []
    params: list = []
    for w in words[:6]:
        where_parts.append(
            "(p.name LIKE ? OR b.name LIKE ? OR c.name LIKE ? OR p.short_desc LIKE ?)"
        )
        params += [f"%{w}%"] * 4
    sql = PRODUCT_SELECT + " WHERE " + " OR ".join(where_parts) + \
        " ORDER BY p.is_featured DESC, p.created_at DESC LIMIT ?"
    params.append(limit)
    with get_conn() as c:
        return c.execute(sql, params).fetchall()


def get_product_by_slug(slug: str):
    with get_conn() as c:
        return c.execute(PRODUCT_SELECT + " WHERE p.slug = ?", (slug,)).fetchone()


def get_product(product_id: int):
    with get_conn() as c:
        return c.execute(PRODUCT_SELECT + " WHERE p.id = ?", (product_id,)).fetchone()


def related_products(category_slug: str, exclude_id: int, limit: int = 4):
    with get_conn() as c:
        return c.execute(
            PRODUCT_SELECT + " WHERE c.slug = ? AND p.id != ? ORDER BY p.created_at DESC LIMIT ?",
            (category_slug, exclude_id, limit),
        ).fetchall()


def create_product(data: dict) -> int:
    with get_conn() as c:
        slug = unique_slug(c, "products", data["name"])
        cur = c.execute(
            """INSERT INTO products
               (name, slug, category_id, brand_id, price, sale_price, image,
                short_desc, description, specs, warranty_months, in_stock,
                is_featured, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                data["name"], slug, data["category_id"], data.get("brand_id"),
                data["price"], data.get("sale_price"), data.get("image", ""),
                data.get("short_desc", ""), data.get("description", ""),
                json.dumps(data.get("specs", []), ensure_ascii=False),
                data.get("warranty_months", 12), data.get("in_stock", 1),
                data.get("is_featured", 0), datetime.utcnow().isoformat(),
            ),
        )
        return cur.lastrowid


def update_product(product_id: int, data: dict):
    with get_conn() as c:
        slug = unique_slug(c, "products", data["name"], exclude_id=product_id)
        fields = [
            "name=?", "slug=?", "category_id=?", "brand_id=?", "price=?",
            "sale_price=?", "short_desc=?", "description=?", "specs=?",
            "warranty_months=?", "in_stock=?", "is_featured=?",
        ]
        params = [
            data["name"], slug, data["category_id"], data.get("brand_id"),
            data["price"], data.get("sale_price"), data.get("short_desc", ""),
            data.get("description", ""),
            json.dumps(data.get("specs", []), ensure_ascii=False),
            data.get("warranty_months", 12), data.get("in_stock", 1),
            data.get("is_featured", 0),
        ]
        if data.get("image"):
            fields.append("image=?")
            params.append(data["image"])
        params.append(product_id)
        c.execute(f"UPDATE products SET {', '.join(fields)} WHERE id=?", params)


def delete_product(product_id: int):
    with get_conn() as c:
        c.execute("DELETE FROM products WHERE id = ?", (product_id,))


def list_all_products_admin():
    with get_conn() as c:
        return c.execute(PRODUCT_SELECT + " ORDER BY p.created_at DESC").fetchall()


def _price_filter_where(category_id=None, brand_id=None):
    where, params = [], []
    if category_id:
        where.append("category_id = ?")
        params.append(category_id)
    if brand_id:
        where.append("brand_id = ?")
        params.append(brand_id)
    sql = (" WHERE " + " AND ".join(where)) if where else ""
    return sql, params


def count_products_for_filter(category_id=None, brand_id=None) -> int:
    sql, params = _price_filter_where(category_id, brand_id)
    with get_conn() as c:
        return c.execute(f"SELECT COUNT(*) FROM products{sql}", params).fetchone()[0]


def bulk_adjust_price(category_id=None, brand_id=None, delta: int = 0) -> int:
    if not delta:
        return 0
    sql, params = _price_filter_where(category_id, brand_id)
    with get_conn() as c:
        cur = c.execute(
            "UPDATE products SET price = price + ?, "
            "sale_price = CASE WHEN sale_price IS NOT NULL THEN sale_price + ? ELSE NULL END"
            + sql,
            [delta, delta] + params,
        )
        return cur.rowcount


def get_products_by_ids(ids: list[int]):
    if not ids:
        return []
    with get_conn() as c:
        placeholders = ",".join("?" * len(ids))
        rows = c.execute(PRODUCT_SELECT + f" WHERE p.id IN ({placeholders})", ids).fetchall()
    by_id = {row["id"]: row for row in rows}
    return [by_id[i] for i in ids if i in by_id]


# --------------------------------------------------------------------- leads

def create_lead(name: str, phone: str, product_id=None, note: str = ""):
    with get_conn() as c:
        cur = c.execute(
            "INSERT INTO leads (name, phone, product_id, note, status, created_at) "
            "VALUES (?,?,?,?, 'moi', ?)",
            (name, phone, product_id, note, datetime.utcnow().isoformat()),
        )
        return cur.lastrowid


def list_leads():
    with get_conn() as c:
        return c.execute(
            """SELECT l.*, p.name AS product_name FROM leads l
               LEFT JOIN products p ON p.id = l.product_id
               ORDER BY l.created_at DESC"""
        ).fetchall()


def update_lead_status(lead_id: int, status: str):
    with get_conn() as c:
        c.execute("UPDATE leads SET status=? WHERE id=?", (status, lead_id))


def counts():
    with get_conn() as c:
        return {
            "products": c.execute("SELECT COUNT(*) FROM products").fetchone()[0],
            "categories": c.execute("SELECT COUNT(*) FROM categories").fetchone()[0],
            "leads_new": c.execute(
                "SELECT COUNT(*) FROM leads WHERE status='moi'"
            ).fetchone()[0],
            "articles": c.execute("SELECT COUNT(*) FROM articles").fetchone()[0],
            "articles_pending": c.execute(
                "SELECT COUNT(*) FROM articles WHERE published = 0"
            ).fetchone()[0],
        }


def list_pending_articles(limit: int = 5):
    with get_conn() as c:
        return c.execute(
            "SELECT * FROM articles WHERE published = 0 ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()


# ------------------------------------------------------------------ articles

def list_articles(limit=None, published_only=True):
    sql = "SELECT * FROM articles"
    if published_only:
        sql += " WHERE published = 1"
    sql += " ORDER BY created_at DESC"
    params = []
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    with get_conn() as c:
        return c.execute(sql, params).fetchall()


def list_articles_admin():
    with get_conn() as c:
        return c.execute("SELECT * FROM articles ORDER BY created_at DESC").fetchall()


def get_article_by_slug(slug: str):
    with get_conn() as c:
        return c.execute("SELECT * FROM articles WHERE slug = ?", (slug,)).fetchone()


def get_article(article_id: int):
    with get_conn() as c:
        return c.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()


def create_article(data: dict) -> int:
    with get_conn() as c:
        slug = unique_slug(c, "articles", data["title"])
        cur = c.execute(
            """INSERT INTO articles (title, slug, image, excerpt, content, category,
               published, meta_title, meta_description, keyword, related_product_ids,
               created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                data["title"], slug, data.get("image", ""), data.get("excerpt", ""),
                data.get("content", ""), data.get("category", "Kiến thức tiêu dùng"),
                data.get("published", 1), data.get("meta_title", ""),
                data.get("meta_description", ""), data.get("keyword", ""),
                data.get("related_product_ids", ""), datetime.utcnow().isoformat(),
            ),
        )
        return cur.lastrowid


def update_article(article_id: int, data: dict):
    with get_conn() as c:
        slug = unique_slug(c, "articles", data["title"], exclude_id=article_id)
        fields = ["title=?", "slug=?", "excerpt=?", "content=?", "category=?", "published=?",
                   "meta_title=?", "meta_description=?", "keyword=?", "related_product_ids=?"]
        params = [
            data["title"], slug, data.get("excerpt", ""), data.get("content", ""),
            data.get("category", "Kiến thức tiêu dùng"), data.get("published", 1),
            data.get("meta_title", ""), data.get("meta_description", ""),
            data.get("keyword", ""), data.get("related_product_ids", ""),
        ]
        if data.get("image"):
            fields.append("image=?")
            params.append(data["image"])
        params.append(article_id)
        c.execute(f"UPDATE articles SET {', '.join(fields)} WHERE id=?", params)


def delete_article(article_id: int):
    with get_conn() as c:
        c.execute("DELETE FROM articles WHERE id = ?", (article_id,))


# --------------------------------------------------------------- content_queue

def list_queue():
    with get_conn() as c:
        return c.execute(
            """SELECT q.*, c.name AS category_name, a.slug AS article_slug
               FROM content_queue q
               LEFT JOIN categories c ON c.id = q.category_id
               LEFT JOIN articles a ON a.id = q.article_id
               ORDER BY q.created_at DESC"""
        ).fetchall()


def create_queue_item(data: dict) -> int:
    with get_conn() as c:
        cur = c.execute(
            """INSERT INTO content_queue (category_id, product_ids, keyword, content_type,
               notes, status, created_at) VALUES (?,?,?,?,?,'cho_xu_ly',?)""",
            (
                data.get("category_id"), data.get("product_ids", ""), data["keyword"],
                data.get("content_type", "huong_dan"), data.get("notes", ""),
                datetime.utcnow().isoformat(),
            ),
        )
        return cur.lastrowid


def update_queue_item(queue_id: int, data: dict):
    with get_conn() as c:
        fields, params = [], []
        for col in ("status", "article_id", "error"):
            if col in data:
                fields.append(f"{col}=?")
                params.append(data[col])
        if not fields:
            return
        params.append(queue_id)
        c.execute(f"UPDATE content_queue SET {', '.join(fields)} WHERE id=?", params)


def delete_queue_item(queue_id: int):
    with get_conn() as c:
        c.execute("DELETE FROM content_queue WHERE id = ?", (queue_id,))


def next_pending_queue_item():
    with get_conn() as c:
        return c.execute(
            "SELECT * FROM content_queue WHERE status='cho_xu_ly' ORDER BY created_at LIMIT 1"
        ).fetchone()


def queue_generated_count_since(iso_since: str) -> int:
    with get_conn() as c:
        return c.execute(
            """SELECT COUNT(*) FROM content_queue q
               JOIN articles a ON a.id = q.article_id
               WHERE q.status='da_tao' AND a.created_at >= ?""",
            (iso_since,),
        ).fetchone()[0]


def seed_queue_from_categories() -> int:
    with get_conn() as c:
        existing_cats = {
            row["category_id"] for row in c.execute(
                "SELECT DISTINCT category_id FROM content_queue WHERE category_id IS NOT NULL"
            )
        }
        cats = c.execute("SELECT * FROM categories ORDER BY sort_order, name").fetchall()
        added = 0
        for cat in cats:
            if cat["id"] in existing_cats:
                continue
            products = c.execute(
                PRODUCT_SELECT + " WHERE p.category_id = ? ORDER BY p.created_at DESC LIMIT 2",
                (cat["id"],),
            ).fetchall()
            product_ids = ",".join(str(p["id"]) for p in products)
            c.execute(
                """INSERT INTO content_queue (category_id, product_ids, keyword, content_type,
                   notes, status, created_at) VALUES (?,?,?,?,?,'cho_xu_ly',?)""",
                (
                    cat["id"], product_ids,
                    f"{cat['name']} loại nào tốt, nên mua loại nào",
                    "huong_dan",
                    "Chủ đề gợi ý tự động — sửa từ khóa lại cho sát nhu cầu thật trước khi để"
                    " hệ thống viết bài.",
                    datetime.utcnow().isoformat(),
                ),
            )
            added += 1
        return added
