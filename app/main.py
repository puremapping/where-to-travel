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
    """对话入口：接收用户自然语言 → 挖掘动机 → 返回动机画像

    这是 PRD 的 Travel for What 环节。
    """
    body = await request.json()
    text = (body.get("text") or "").strip()
    if not text:
        return JSONResponse({"error": "请输入你的旅行想法"}, status_code=400)

    try:
        mot = mot_svc.analyze(text)
    except Exception as e:
        return JSONResponse({"error": f"动机分析失败: {e}"}, status_code=500)

    return {
        "motivation": mot.to_dict(),
        "summary": mot.summary(),
        "available": list(mot_svc.MOTIVATIONS.keys()),
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


@app.post("/api/itinerary")
async def make_itinerary(request: Request):
    """生成一日行程"""
    body = await request.json()
    mot = body.get("motivation") or "探索/新奇"
    intensity = int(body.get("intensity") or 3)
    hours = body.get("hours")
    hours = int(hours) if hours else None

    # 1. 推荐
    items = rec_svc.recommend(mot, intensity, top_k=20)
    cand = [(i.name, i.level, i.district, i.address, i.lon, i.lat,
             i.crowd, None, i.reasons) for i in items]

    # 补地铁信息
    with connect() as conn:
        metro_map = {r["attraction_name"]: r["metro"] or ""
                     for r in conn.execute("SELECT attraction_name, metro FROM transport")}
    cand = [(c[0], c[1], c[2], c[3], c[4], c[5], c[6],
             metro_map.get(c[0], ""), c[8]) for c in cand]

    # 2. 编排
    it = itin_svc.build_itinerary(cand, mot, hours)
    d = it.to_dict()

    # 3. LLM 叙述 + 评估
    try:
        d["narrative"] = nar_svc.narrate(d, mot)
        d["assessment"] = nar_svc.assess(d)
    except Exception as e:
        d["narrative"] = ""
        d["assessment"] = {"intensity": "中", "strength": "", "suggestion": f"（叙述生成失败: {e}）"}

    # 4. 存库
    sid = uuid.uuid4().hex[:12]
    with connect() as conn:
        conn.execute(
            "INSERT INTO sessions (id,created_at,profile,motivations,itinerary) "
            "VALUES (?,?,?,?,?)",
            (sid, datetime.now().isoformat(),
             json.dumps({"hours": hours}, ensure_ascii=False),
             json.dumps({"primary": mot, "intensity": intensity}, ensure_ascii=False),
             json.dumps(d, ensure_ascii=False)))

    d["session_id"] = sid
    return d


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
