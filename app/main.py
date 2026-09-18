#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Where to Travel — FastAPI 应用"""
import json
import os
import hmac
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request, Depends, Cookie, HTTPException, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.core.config import BASE_DIR
from app.core.db import connect, init_db
from app.services import auth as auth_svc
from app.services import analytics as ana
from app.services import itinerary as itin_svc
from app.services import conversation as convo_svc
from app.services import motivation as mot_svc
from app.services import narrative as nar_svc
from app.services import recommend as rec_svc

app = FastAPI(title="Where to Travel")

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "app" / "static")),
          name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


@app.on_event("startup")
def _startup():
    init_db()
    # 后台清理匿名会话（每小时一次）
    import threading

    def _loop():
        import time
        while True:
            time.sleep(3600)
            try:
                convo_svc._anon_cleanup()
            except Exception:
                pass

    threading.Thread(target=_loop, daemon=True).start()


# ── 当前用户（可选，未登录返回 None）──

def current_user_optional(wtt_auth: str = Cookie(default=None)):
    """从签名 cookie 解析当前用户；未登录返回 None（不拦截）"""
    uid = auth_svc.parse_token(wtt_auth) if wtt_auth else None
    return auth_svc.get_user(uid) if uid else None


def require_user(user=Depends(current_user_optional)):
    """需要登录的接口用这个"""
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    return user


# ---------------- 页面 ----------------

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    # Starlette 新版签名：TemplateResponse(request, name, context)
    return templates.TemplateResponse(request, "index.html")


# ---------------- 认证 ----------------

@app.post("/api/auth/register")
async def register(request: Request, response: Response):
    body = await request.json()
    try:
        user = auth_svc.register(body.get("email", ""), body.get("password", ""),
                                 body.get("nickname", ""))
    except auth_svc.AuthError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    ana.track(ana.EV_USER_REGISTER, user_id=user["id"], email=user["email"])
    _set_auth_cookie(response, user["id"])
    return {"user": user}


@app.post("/api/auth/login")
async def login(request: Request, response: Response):
    body = await request.json()
    try:
        user = auth_svc.login(body.get("email", ""), body.get("password", ""))
    except auth_svc.AuthError as e:
        return JSONResponse({"error": str(e)}, status_code=401)

    ana.track(ana.EV_USER_LOGIN, user_id=user["id"], email=user["email"])
    _set_auth_cookie(response, user["id"])
    return {"user": user}


@app.post("/api/auth/logout")
async def logout(response: Response):
    response.delete_cookie(auth_svc.COOKIE_NAME, path="/")
    return {"ok": True}


@app.get("/api/auth/me")
def me(user=Depends(current_user_optional)):
    return {"user": user}


@app.delete("/api/auth/account")
async def delete_account(request: Request, response: Response,
                         user=Depends(require_user)):
    """删除账号（级联删会话与事件）—— 隐私要求"""
    body = await request.json()
    try:
        auth_svc.delete_user(user["id"], body.get("password", ""))
    except auth_svc.AuthError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    response.delete_cookie(auth_svc.COOKIE_NAME, path="/")
    return {"ok": True}


def _set_auth_cookie(response: Response, user_id: str):
    response.set_cookie(
        key=auth_svc.COOKIE_NAME,
        value=auth_svc.make_token(user_id),
        max_age=auth_svc.COOKIE_MAX_AGE,
        httponly=True,          # 防 XSS 读取
        samesite="lax",
        path="/",
    )


# ---------------- API ----------------

@app.post("/api/chat")
async def chat(request: Request, user=Depends(current_user_optional)):
    """多轮对话入口

    用户说一句 → 返回 AI 回复 + 更新后的画像 + 可能的工具调用。
    AI 可以请求生成行程或提议修改，真正的执行由服务端做。

    ⚠️ 匿名（未登录）会话不落库，刷新即丢。
    """
    body = await request.json()
    text = (body.get("text") or "").strip()
    sid = body.get("session_id") or None
    if not text:
        return JSONResponse({"error": "说点什么吧"}, status_code=400)

    uid = user["id"] if user else None

    # 取当前行程（让 AI 看得见右侧）
    # chat 内部会从对应存储（DB / 内存）载入 conv，但也需要单独传给 LLM
    current_itinerary = _load_itinerary(sid, uid) if sid else None

    try:
        conv = convo_svc.chat(sid, text, current_itinerary=current_itinerary,
                              user_id=uid)
    except Exception as e:
        return JSONResponse({"error": f"对话失败: {e}"}, status_code=500)

    sid = conv.session_id

    # 记录行为事件（登录用户才记）
    ana.track(ana.EV_MESSAGE_SENT, sid, uid,
              turn=conv.turn, text_len=len(text))
    if conv.turn == 1:
        ana.track(ana.EV_SESSION_START, sid, uid)

    result = {
        "session_id": sid,
        "reply": conv.messages[-1]["content"],
        "profile": convo_svc.public_profile(conv.profile),
        "summary": convo_svc.profile_summary(conv.profile),
        "turn": conv.turn,
        "ready": conv.ready,
        "tool_calls": conv.tool_calls,
        "logged_in": bool(uid),
    }

    # 处理工具调用
    for tc in conv.tool_calls:
        name = tc.get("name")
        args = tc.get("args") or {}

        if name == "generate_itinerary":
            try:
                d = _do_generate_itinerary(sid, args.get("hours"), user_id=uid)
                result["itinerary"] = d
                result["action"] = "generate"
                ana.track(ana.EV_ITINERARY_GENERATED, sid, uid,
                          stops_count=len(d.get("stops", [])),
                          motivation=d.get("motivation"),
                          hours=d.get("hours"))
            except Exception as e:
                result["action_error"] = f"生成失败: {e}"

        elif name == "propose_modify_itinerary":
            # 只是提议 → 前端展示确认按钮，等用户点
            result["proposal"] = {
                "action": args.get("action"),
                "target": args.get("target"),
                "reason": args.get("reason"),
            }

    return result


@app.get("/api/session/{session_id}")
def get_session(session_id: str):
    """取回会话（刷新页面后续聊）"""
    conv = convo_svc.load_session(session_id)
    if not conv:
        return JSONResponse({"error": "会话不存在"}, status_code=404)
    return {
        "session_id": conv.session_id,
        "messages": conv.messages,
        "profile": convo_svc.public_profile(conv.profile),
        "summary": convo_svc.profile_summary(conv.profile),
        "turn": conv.turn,
        "ready": conv.ready,
    }


@app.post("/api/recommend")
async def recommend(request: Request):
    """按动机推荐景区"""
    body = await request.json()
    mot = body.get("motivation") or "探索/新奇"
    intensity = int(body.get("intensity") or 3)
    top_k = int(body.get("top_k") or 8)

    items = rec_svc.recommend(mot, intensity, top_k)
    return {"motivation": mot, "items": [i.to_dict() for i in items]}


def _load_profile(sid, user_id=None):
    """从会话取画像"""
    if not sid:
        return {}
    conv = convo_svc.load_session(sid, user_id)
    return convo_svc.public_profile(conv.profile) if conv else {}


def _build_candidates(profile):
    """按画像构造候选景区列表（推荐 + 排除 avoid + 必去置顶）"""
    mot = profile.get("primary") or "探索/新奇"
    try:
        intensity = int(profile.get("primary_intensity") or 3)
    except (ValueError, TypeError):
        intensity = 3

    items = rec_svc.recommend(mot, intensity, top_k=25)

    avoid = [str(a) for a in (profile.get("avoid") or [])]
    must = [str(m) for m in (profile.get("must_see") or [])]
    if avoid:
        items = [i for i in items
                 if not any(a in i.name or i.name in a for a in avoid)]
    if must:
        def _is_must(item):
            return any(m in item.name or item.name in m for m in must)
        items.sort(key=lambda x: (not _is_must(x), -x.score))

    with connect() as conn:
        metro_map = {r["attraction_name"]: r["metro"] or ""
                     for r in conn.execute(
                         "SELECT attraction_name, metro FROM transport")}

    return [(i.name, i.level, i.district, i.address, i.lon, i.lat,
             i.crowd, metro_map.get(i.name, ""), i.reasons) for i in items]


def _do_generate_itinerary(sid, hours_override=None, exclude=None, user_id=None):
    """生成行程并存入会话，返回行程 dict

    ⚠️ user_id 为空 = 匿名 → 只更新内存会话，不写库
    """
    profile = _load_profile(sid, user_id)
    mot = profile.get("primary") or "探索/新奇"
    hours = hours_override or profile.get("hours")

    cand = _build_candidates(profile)
    it = itin_svc.build_itinerary(cand, mot, hours, exclude=exclude)
    d = it.to_dict()

    try:
        d["narrative"] = nar_svc.narrate(d, mot, profile=profile)
        d["assessment"] = nar_svc.assess(d)
    except Exception as e:
        d["narrative"] = ""
        d["assessment"] = {"intensity": "中", "strength": "",
                           "suggestion": f"（叙述生成失败: {e}）"}

    d["profile"] = profile
    if sid:
        if user_id:
            with connect() as conn:
                conn.execute("UPDATE sessions SET itinerary=? WHERE id=? AND user_id=?",
                             (json.dumps(d, ensure_ascii=False), sid, user_id))
        else:
            # 匿名：行程存内存会话
            conv = convo_svc._anon_get(sid)
            if conv:
                conv.itinerary = d
                convo_svc._anon_put(conv)
    return d


def _load_itinerary(sid, user_id=None):
    """取会话当前行程（含匿名内存路径）"""
    if not sid:
        return None
    if user_id:
        with connect() as conn:
            row = conn.execute(
                "SELECT itinerary FROM sessions WHERE id=? AND user_id=?",
                (sid, user_id)).fetchone()
        if row and row["itinerary"]:
            try:
                return json.loads(row["itinerary"])
            except json.JSONDecodeError:
                return None
        return None
    conv = convo_svc._anon_get(sid)
    return conv.itinerary if conv and conv.itinerary else None


@app.post("/api/itinerary")
async def make_itinerary(request: Request, user=Depends(current_user_optional)):
    """生成行程（显式接口）"""
    body = await request.json()
    sid = body.get("session_id")
    uid = user["id"] if user else None

    if not sid:
        sid = uuid.uuid4().hex[:12]
        if uid:
            with connect() as conn:
                conn.execute(
                    "INSERT INTO sessions "
                    "(id,user_id,created_at,profile,motivations,itinerary) "
                    "VALUES (?,?,?,?,?,?)",
                    (sid, uid, datetime.now().isoformat(), "{}", "{}", "{}"))
        else:
            # 匿名：建内存会话
            conv = convo_svc.Conversation(
                session_id=sid, created_at=datetime.now().isoformat())
            convo_svc._anon_put(conv)

    hours = body.get("hours")
    try:
        hours = int(hours) if hours else None
    except (ValueError, TypeError):
        hours = None

    d = _do_generate_itinerary(sid, hours, user_id=uid)
    d["session_id"] = sid
    ana.track(ana.EV_ITINERARY_GENERATED, sid, uid,
              stops_count=len(d.get("stops", [])),
              motivation=d.get("motivation"))
    return d


@app.post("/api/itinerary/modify")
async def modify_itinerary(request: Request, user=Depends(current_user_optional)):
    """落实行程修改（用户确认后调用）

    body: {session_id, action, target}
    ⚠️ 归属校验：只能改自己的会话
    """
    body = await request.json()
    sid = body.get("session_id")
    action = body.get("action")
    target = body.get("target")
    uid = user["id"] if user else None

    if not sid or not action:
        return JSONResponse({"error": "缺少 session_id 或 action"},
                            status_code=400)

    # 取行程（带归属校验）
    cur = _load_itinerary(sid, uid)
    if not cur:
        return JSONResponse({"error": "当前没有行程可修改"}, status_code=400)

    profile = _load_profile(sid, uid)
    cand = _build_candidates(profile)

    new_it = itin_svc.apply_modification(
        cur, action, target=target, candidates=cand,
        motivation=profile.get("primary") or cur.get("motivation"),
        hours=profile.get("hours") or cur.get("hours"))

    if not new_it:
        return JSONResponse({"error": "无法完成该修改（可能候选不足）"},
                            status_code=400)

    # 重新生成叙述
    try:
        new_it["narrative"] = nar_svc.narrate(
            new_it, new_it.get("motivation", ""), profile=profile)
        new_it["assessment"] = nar_svc.assess(new_it)
    except Exception:
        new_it["narrative"] = cur.get("narrative", "")
        new_it["assessment"] = cur.get("assessment", {})

    new_it["profile"] = profile
    with connect() as conn:
        conn.execute("UPDATE sessions SET itinerary=? WHERE id=?",
                     (json.dumps(new_it, ensure_ascii=False), sid))

    new_it["session_id"] = sid
    return new_it


@app.get("/api/attractions")
def list_attractions(limit: int = 50, district: str = None):
    """景区列表（调试/浏览用）"""
    sql = ("SELECT id,name,level,district,address,lon,lat,ticket_free,"
           "price_high,price_low FROM attractions WHERE 1=1")
    args = []
    if district:
        sql += " AND district LIKE ?"
        args.append(f"%{district}%")
    sql += " LIMIT ?"
    args.append(limit)

    with connect() as conn:
        rows = [dict(r) for r in conn.execute(sql, args)]
    return {"count": len(rows), "items": rows}


@app.get("/api/stats")
def stats():
    """数据统计"""
    with connect() as conn:
        out = {}
        for t in ("attractions", "transport", "crowd_index", "sessions"):
            out[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        out["attractions_with_coord"] = conn.execute(
            "SELECT COUNT(*) FROM attractions WHERE lon IS NOT NULL").fetchone()[0]
    return out


@app.get("/api/health")
def health():
    return {"ok": True}


# ---------------- 用户历史（登录用户）----------------

@app.get("/api/history")
def history(user=Depends(require_user)):
    """我的会话列表（从 DB 查，只返回该用户的）"""
    with connect() as conn:
        rows = conn.execute("""
            SELECT id, created_at, turn_count,
                   json_extract(profile, '$.primary') AS motivation,
                   CASE WHEN itinerary IS NOT NULL AND itinerary != '' AND itinerary != '{}'
                        THEN 1 ELSE 0 END AS has_itinerary
            FROM sessions
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT 50
        """, (user["id"],)).fetchall()
    return {"count": len(rows), "items": [dict(r) for r in rows]}


@app.get("/api/history/{session_id}")
def history_detail(session_id: str, user=Depends(require_user)):
    """查看某个历史会话（归属校验）"""
    with connect() as conn:
        row = conn.execute(
            "SELECT id, created_at, profile, itinerary FROM sessions "
            "WHERE id=? AND user_id=?",
            (session_id, user["id"])).fetchone()
    if not row:
        return JSONResponse({"error": "会话不存在"}, status_code=404)

    payload = json.loads(row["profile"] or "{}")
    return {
        "session_id": row["id"],
        "created_at": row["created_at"],
        "profile": convo_svc.public_profile(payload.get("profile", {})),
        "messages": payload.get("messages", []),
        "itinerary": json.loads(row["itinerary"]) if row["itinerary"] else None,
    }


@app.delete("/api/history/{session_id}")
def delete_history(session_id: str, user=Depends(require_user)):
    """删除自己的某个会话"""
    with connect() as conn:
        cur = conn.execute("DELETE FROM sessions WHERE id=? AND user_id=?",
                           (session_id, user["id"]))
    if cur.rowcount == 0:
        return JSONResponse({"error": "会话不存在"}, status_code=404)
    return {"ok": True}


# ---------------- 行为分析（内部）----------------
# ⚠️ 简易保护：靠 ADMIN_TOKEN 环境变量。未设置则禁用（避免裸奔）

@app.get("/api/analytics/report")
def analytics_report(days: int = 30, token: str = None):
    admin = os.environ.get("ADMIN_TOKEN", "")
    if not admin:
        return JSONResponse({"error": "未配置 ADMIN_TOKEN，分析接口已禁用"},
                            status_code=403)
    if not hmac.compare_digest(token or "", admin):
        return JSONResponse({"error": "token 不正确"}, status_code=403)
    return ana.report(days)


@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request):
    # Starlette 新版签名：TemplateResponse(request, name, context)
    return templates.TemplateResponse(request, "admin.html")
