#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Where to Travel — FastAPI 应用"""
import json
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.core.config import BASE_DIR
from app.core.db import connect, init_db
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


# ---------------- 页面 ----------------

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    # Starlette 新版签名：TemplateResponse(request, name, context)
    return templates.TemplateResponse(request, "index.html")


# ---------------- API ----------------

@app.post("/api/chat")
async def chat(request: Request):
    """多轮对话入口

    用户说一句 → 返回 AI 回复 + 更新后的画像 + 可能的工具调用。
    AI 可以请求生成行程或提议修改，真正的执行由服务端做。
    """
    body = await request.json()
    text = (body.get("text") or "").strip()
    sid = body.get("session_id") or None
    if not text:
        return JSONResponse({"error": "说点什么吧"}, status_code=400)

    # 取当前行程（让 AI 看得见右侧）
    current_itinerary = None
    if sid:
        with connect() as conn:
            row = conn.execute(
                "SELECT itinerary FROM sessions WHERE id=?", (sid,)).fetchone()
        if row and row["itinerary"]:
            try:
                current_itinerary = json.loads(row["itinerary"])
            except json.JSONDecodeError:
                pass

    try:
        conv = convo_svc.chat(sid, text, current_itinerary=current_itinerary)
    except Exception as e:
        return JSONResponse({"error": f"对话失败: {e}"}, status_code=500)

    sid = conv.session_id
    result = {
        "session_id": sid,
        "reply": conv.messages[-1]["content"],
        "profile": convo_svc.public_profile(conv.profile),
        "summary": convo_svc.profile_summary(conv.profile),
        "turn": conv.turn,
        "ready": conv.ready,
        "tool_calls": conv.tool_calls,
    }

    # 处理工具调用
    for tc in conv.tool_calls:
        name = tc.get("name")
        args = tc.get("args") or {}

        if name == "generate_itinerary":
            # AI 判断该生成了 → 直接执行
            try:
                d = _do_generate_itinerary(sid, args.get("hours"))
                result["itinerary"] = d
                result["action"] = "generate"
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


def _load_profile(sid):
    """从会话取画像"""
    if not sid:
        return {}
    conv = convo_svc.load_session(sid)
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


def _do_generate_itinerary(sid, hours_override=None, exclude=None):
    """生成行程并存入会话，返回行程 dict"""
    profile = _load_profile(sid)
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
        with connect() as conn:
            conn.execute("UPDATE sessions SET itinerary=? WHERE id=?",
                         (json.dumps(d, ensure_ascii=False), sid))
    return d


@app.post("/api/itinerary")
async def make_itinerary(request: Request):
    """生成行程（显式接口，兼容旧调用）"""
    body = await request.json()
    sid = body.get("session_id")
    if not sid:
        sid = uuid.uuid4().hex[:12]
        with connect() as conn:
            conn.execute(
                "INSERT INTO sessions (id,created_at,profile,motivations,itinerary) "
                "VALUES (?,?,?,?,?)",
                (sid, datetime.now().isoformat(), "{}", "{}", "{}"))

    hours = body.get("hours")
    try:
        hours = int(hours) if hours else None
    except (ValueError, TypeError):
        hours = None

    d = _do_generate_itinerary(sid, hours)
    d["session_id"] = sid
    return d


@app.post("/api/itinerary/modify")
async def modify_itinerary(request: Request):
    """落实行程修改（用户确认后调用）

    body: {session_id, action, target}
    """
    body = await request.json()
    sid = body.get("session_id")
    action = body.get("action")
    target = body.get("target")

    if not sid or not action:
        return JSONResponse({"error": "缺少 session_id 或 action"},
                            status_code=400)

    with connect() as conn:
        row = conn.execute("SELECT itinerary FROM sessions WHERE id=?",
                           (sid,)).fetchone()
    if not row or not row["itinerary"]:
        return JSONResponse({"error": "当前没有行程可修改"}, status_code=400)

    try:
        cur = json.loads(row["itinerary"])
    except json.JSONDecodeError:
        return JSONResponse({"error": "行程数据损坏"}, status_code=500)

    profile = _load_profile(sid)
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
