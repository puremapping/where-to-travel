#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Where to Travel — 数据库层（SQLite）"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.core.config import DB_PATH

SCHEMA = """
-- 景点
CREATE TABLE IF NOT EXISTS attractions (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    level       TEXT,              -- 5A/4A/3A...
    district    TEXT,
    address     TEXT,
    phone       TEXT,
    postcode    TEXT,
    lon         REAL,              -- GCJ-02
    lat         REAL,
    ticket_free INTEGER,           -- 是否免费
    price_high  REAL,              -- 旺季价
    price_low   REAL,              -- 淡季价
    context     TEXT,              -- 用于 embedding 的描述
    embedding   BLOB               -- 向量（可选，后补）
);

-- 交通（来自平台「等级景区交通信息」）
CREATE TABLE IF NOT EXISTS transport (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    attraction_name TEXT NOT NULL,
    district    TEXT,
    level       TEXT,
    metro       TEXT,
    bus         TEXT,
    highway     TEXT,
    branch_road TEXT,
    airport     TEXT,
    railway     TEXT,
    town        TEXT
);

-- 景区饱和指数（实时人流）
CREATE TABLE IF NOT EXISTS crowd_index (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    saturation  REAL,
    ts          TEXT
);

-- 会话（一次对话的动机采集结果）
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    created_at  TEXT,
    profile     TEXT,              -- JSON：同伴/时长/预算等
    motivations TEXT,              -- JSON：动机标签与强度
    itinerary   TEXT               -- JSON：生成的行程
);

CREATE INDEX IF NOT EXISTS idx_attr_name ON attractions(name);
CREATE INDEX IF NOT EXISTS idx_crowd_name ON crowd_index(name);
"""


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    print(f"数据库已初始化: {DB_PATH}")
