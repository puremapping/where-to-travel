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

-- ── 用户系统（v0.4）──

-- 注册用户
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    email         TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    nickname      TEXT,
    created_at    TEXT NOT NULL,
    last_login    TEXT
);

-- 会话（只有登录用户的会落库；匿名会话在内存）
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    user_id     TEXT,              -- 历史遗留会话为 NULL
    created_at  TEXT,
    ended_at    TEXT,
    turn_count  INTEGER DEFAULT 0,
    profile     TEXT,              -- JSON：画像
    motivations TEXT,              -- JSON：动机
    itinerary   TEXT               -- JSON：行程
);

-- 行为事件（长期分析的核心）
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT,
    user_id     TEXT,
    event_type  TEXT NOT NULL,
    payload     TEXT,              -- JSON
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_attr_name ON attractions(name);
CREATE INDEX IF NOT EXISTS idx_crowd_name ON crowd_index(name);
"""

# 索引依赖 sessions.user_id，必须等 _migrate 补列之后再建
INDEXES_AFTER_MIGRATE = """
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_events_user ON events(user_id);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_time ON events(created_at);
"""


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        # 1. 建表（IF NOT EXISTS，已有的跳过）
        conn.executescript(SCHEMA)
        # 2. 补列（给老库加 user_id 等）
        _migrate(conn)
        # 3. 建依赖新列的索引
        conn.executescript(INDEXES_AFTER_MIGRATE)


def _migrate(conn):
    """给已有库补列（SQLite 的 ALTER TABLE ADD COLUMN 是安全操作）"""
    def cols(table):
        return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}

    s = cols("sessions")
    for name, decl in (
        ("user_id", "TEXT"),
        ("ended_at", "TEXT"),
        ("turn_count", "INTEGER DEFAULT 0"),
    ):
        if name not in s:
            conn.execute(f"ALTER TABLE sessions ADD COLUMN {name} {decl}")


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
