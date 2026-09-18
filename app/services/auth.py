#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
认证服务

设计要点：
  - 密码：标准库 pbkdf2_hmac（20 万次迭代），不引 bcrypt/passlib
  - 会话凭证：签名 cookie（hmac），不引 JWT 库
  - 匿名：不落库，不签发 cookie
"""
import hashlib
import hmac
import os
import re
import time
import uuid
from datetime import datetime
from typing import Optional

from app.core.config import SECRET_KEY
from app.core.db import connect

COOKIE_NAME = "wtt_auth"
COOKIE_MAX_AGE = 30 * 24 * 3600        # 30 天
PBKDF2_ROUNDS = 200_000

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ── 密码 ──

def hash_password(password: str, salt: bytes = None) -> str:
    salt = salt or os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS)
    return f"{salt.hex()}:{dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, dk_hex = stored.split(":")
        salt = bytes.fromhex(salt_hex)
    except (ValueError, AttributeError):
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS)
    return hmac.compare_digest(dk.hex(), dk_hex)


# ── Cookie 签名 ──

def make_token(user_id: str) -> str:
    """user_id.timestamp.signature"""
    ts = str(int(time.time()))
    msg = f"{user_id}.{ts}"
    sig = hmac.new(SECRET_KEY.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return f"{msg}.{sig}"


def parse_token(token: str) -> Optional[str]:
    """验证签名，返回 user_id；无效返回 None"""
    if not token:
        return None
    parts = token.split(".")
    if len(parts) != 3:
        return None
    user_id, ts, sig = parts
    msg = f"{user_id}.{ts}"
    expect = hmac.new(SECRET_KEY.encode(), msg.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expect):
        return None
    # 过期检查
    try:
        if time.time() - int(ts) > COOKIE_MAX_AGE:
            return None
    except ValueError:
        return None
    return user_id


# ── 用户 CRUD ──

class AuthError(Exception):
    pass


def register(email: str, password: str, nickname: str = "") -> dict:
    email = (email or "").strip().lower()
    if not EMAIL_RE.match(email):
        raise AuthError("邮箱格式不正确")
    if len(password or "") < 6:
        raise AuthError("密码至少 6 位")

    with connect() as conn:
        exists = conn.execute(
            "SELECT id FROM users WHERE email=?", (email,)).fetchone()
        if exists:
            raise AuthError("该邮箱已注册")

        uid = uuid.uuid4().hex[:16]
        now = datetime.now().isoformat()
        conn.execute(
            "INSERT INTO users (id,email,password_hash,nickname,created_at,last_login) "
            "VALUES (?,?,?,?,?,?)",
            (uid, email, hash_password(password), nickname or email.split("@")[0],
             now, now))
    return {"id": uid, "email": email, "nickname": nickname or email.split("@")[0]}


def login(email: str, password: str) -> dict:
    email = (email or "").strip().lower()
    with connect() as conn:
        row = conn.execute(
            "SELECT id,email,password_hash,nickname FROM users WHERE email=?",
            (email,)).fetchone()
    if not row or not verify_password(password, row["password_hash"]):
        raise AuthError("邮箱或密码不正确")

    with connect() as conn:
        conn.execute("UPDATE users SET last_login=? WHERE id=?",
                     (datetime.now().isoformat(), row["id"]))
    return {"id": row["id"], "email": row["email"], "nickname": row["nickname"]}


def get_user(user_id: str) -> Optional[dict]:
    if not user_id:
        return None
    with connect() as conn:
        row = conn.execute(
            "SELECT id,email,nickname,created_at,last_login FROM users WHERE id=?",
            (user_id,)).fetchone()
    return dict(row) if row else None


def delete_user(user_id: str, password: str) -> None:
    """删除账号（级联删会话与事件）——隐私要求"""
    with connect() as conn:
        row = conn.execute("SELECT password_hash FROM users WHERE id=?",
                           (user_id,)).fetchone()
        if not row or not verify_password(password, row["password_hash"]):
            raise AuthError("密码不正确")
        conn.execute("DELETE FROM events WHERE user_id=?", (user_id,))
        conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        conn.execute("DELETE FROM users WHERE id=?", (user_id,))
