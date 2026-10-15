# Where to Travel — session 台账

> 维护规则：接手即登记、收工即更新、按时间倒序

## 20260917_150557_2fc998

- **时间**：2026-09-17 16:36 → **2026-10-15 13:09（仍在进行）**
- **模型 / 来源**：deepseek-v4.1-flash / tui

### 做了什么

**本项目从 0 到 v0.4 的唯一主线 session**（1683 条消息，跨一个月）。

> ⚠️ 注意：这是一个**长会话**，中间经历多次上下文压缩。
> 上下文里曾残留「今天是 09-18」的过期认知，实际已到 10-15。
> 本条记录于 10-15 补写，早前阶段的时间点为事后追溯。

**1. 调研阶段（09-17）**
- 环境排障：curl 全体 000 根因是 Schannel OCSP 吊销检查（加 `--ssl-no-revoke`）
- 数据源实测：北京公共数据开放平台打通，12 数据集 119,518 行；确认 VisitBeijing MCP 域名已死
- analysis.md 15 个条目全查，发现两处数据待核实；三个开源仓库评估（思路可借、代码不可用）
- 找到 ITINERA（EMNLP 2024）并实跑验证核心算法（聚类/TSP/坐标转换）

**2. MVP 建设（09-18）**
- 技术栈定案：FastAPI + SQLite + Jinja2 + Leaflet（评估后弃用 Chainlit）
- 数据入库：212 景区 / 216 交通 / 217 人流
- 动机挖掘（七类）、推荐引擎、地理编码（212/212 成功）、行程编排
- 修两个 bug：8 小时排成 14 小时、跨区折返
- **v0.1** 端到端跑通 → PMS 初始化 → 推送 GitHub public

**3. v0.2 对话重做**
- v0.1 单轮表单太简陋 → 多轮开放对话
- 关键设计：**抽取与回复拆两次独立 LLM 调用**（合成一次时模型会「续写对话」）
- 修 5 个 LLM 行为坑，10 场景测试 9 正确 0 误判
- 前端改聊天界面（左对话 + 右画像）

**4. v0.3 对话-行程闭环**
- AI 通过 function calling 主动生成行程、能「看见」右侧行程、修改需用户确认
- 修 6 个工具调用坑；服务端校验 tool_calls 白名单
- 验收发现：浏览器缓存旧 JS（加版本号）、模型谎称有上海数据（**服务端硬拦**）
- 阿哲验收「全绿」→ 提交 v0.3

**5. v0.4 用户系统与行为分析**
- 邮箱+密码登录（pbkdf2_hmac 20 万次）、HMAC 签名 cookie
- 会话打 user_id 标签，**所有查询强制 `AND user_id=?`**
- 11 种行为事件 append-only
- `/admin` 看板 + ADMIN_TOKEN 门禁
- **阿哲定的两条硬约束**：不能强制注册（匿名可完整用）；匿名不落库 + 不存对话原文
- 6 项端到端验证全通过（匿名不落库 / 隔离 / 越权 404 / 未登录 401 / 分析 403）
- 提交 v0.4.0（09-18 18:11）

**6. 停摆与恢复（09-18 → 10-15）**
- v0.4 提交后项目停摆约一个月
- 10-15 恢复：写操作手册（README 重写）+ PMS 建制核对
- 期间发现并纠正「时间认知错误」（上下文残留 09-18，实际 10-15）

### 留下的

**新增文件（v0.4 + 手册阶段）：**
- `app/services/auth.py`、`app/services/analytics.py`
- `app/templates/admin.html`
- `docs/DESIGN-user-system.md`
- `app/scripts/test_auth.py`、`app/scripts/test_user_system_e2e.py`
- `sessions.md`（本文件，补 spec §4.2.2 缺口）

**修改：**
- `app/main.py`（认证/历史/分析路由）、`app/core/db.py`（users/events 表 + 迁移）
- `app/services/conversation.py`（匿名内存会话）、`app/static/app.js`（认证 UI 增量合并）
- `app/static/style.css`、`app/templates/index.html`（登录弹窗 + 历史抽屉）
- `README.md`（重写为操作手册）、`.pms.yml`

**踩过的坑（已记入 .pms.yml avoid）：**
- 数据库迁移顺序：`CREATE TABLE IF NOT EXISTS` 跳过已存在表 → 必须 ALTER TABLE，
  且**依赖新列的索引要放迁移之后**（否则 `no such column`）
- `fetch` 漏 `credentials: 'include'` → cookie 不发送，认不出登录用户
- Starlette 新版 `TemplateResponse(request, name, ctx)` 签名，旧签名报 `unhashable type: 'dict'`
- 别另起新 JS 文件替代旧的（会砍掉已有功能）→ 必须**增量合并**

### 状态

进行中
