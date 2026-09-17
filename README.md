# Where to Travel

> 不只告诉你「去哪」，先帮你搞清楚「为什么去」。

以 AI 对话为核心入口的旅游决策平台。通过动机挖掘（Travel for What）理解旅行本质需求，
结合北京官方开放数据与高德地图能力，输出个性化行程、可解释推荐与行程预演。

**课程作业 MVP。** 北京真实数据驱动，其他省份暂未接入。

---

## 核心差异化

| | 大众点评 | 小红书 | **Where to Travel** |
|---|---|---|---|
| 核心逻辑 | 评价驱动 | 内容种草 | **动机驱动 + 真实数据交叉** |
| 推荐粒度 | 单点商户 | 单篇笔记 | **个性化一日行程** |
| 可解释性 | 评分展示 | 弱 | **多源来源 + 置信度 + 推荐理由** |

**同样说「想放松」，一个想恢复元气的人和一个想陪家人的人，会得到完全不同的行程。**

---

## 快速开始

```bash
# 1. 环境（Python 3.13）
uv venv .venv --python 3.13
uv pip install --python .venv/Scripts/python.exe -r requirements.txt

# 2. 配置凭证
cp .env.example .env
#   编辑 .env 填入各项 key（见下方「凭证获取」）

# 3. 导入数据（仓库已含 data/wtt.db，跳过则可）
python -m app.scripts.import_data

# 4. 补景区坐标（首次需要，约 212 次高德配额）
python -m app.scripts.geocode_all

# 5. 启动
python -m uvicorn app.main:app --host 127.0.0.1 --port 8100
```

打开 http://127.0.0.1:8100

---

## 架构

```
用户输入自然语言
    ↓
[动机挖掘]  GLM-4 Flash → 七类动机 + 强度 + 约束
    ↓
[推荐引擎]  动机→偏好映射 × 真实数据（等级/人流/交通）
    ↓
[行程编排]  距离聚类 → TSP 排序 → 区收敛 → 时间预算剪枝
    ↓
[行程叙述]  GLM-4 Flash → 自然语言叙述 + 强度评估
    ↓
时间线 + Leaflet 地图 + 其他推荐
```

```
app/
├── main.py                 FastAPI 入口 + API 路由
├── core/
│   ├── config.py           配置（从 .env 读）
│   └── db.py               SQLite schema
├── services/
│   ├── llm.py              GLM 封装（含健壮 JSON 解析）
│   ├── motivation.py       动机挖掘（七类 + 约束规范化）
│   ├── recommend.py        推荐引擎（动机→偏好映射）
│   ├── itinerary.py        行程编排（聚类 + TSP + 剪枝）
│   └── narrative.py        行程叙述 + 可解释理由
├── templates/index.html
├── static/{style.css,app.js}
└── scripts/                数据导入 / 地理编码 / 测试
```

**技术栈：** FastAPI · SQLite · Jinja2 · Leaflet · GLM-4 Flash
**刻意不用：** 前后端分离构建链、Chainlit（地图需自写组件且依赖重）

---

## 数据源

| 来源 | 用途 | 状态 |
|---|---|---|
| [北京市公共数据开放平台](https://data.beijing.gov.cn) | 景区名录/门票/交通/人流 | ✅ 12 数据集 119,518 行 |
| [高德地图 Web 服务](https://lbs.amap.com) | 地理编码/路径规划 | ✅ 212 景区坐标已补 |
| VisitBeijing MCP | ~~实时人流~~ | ❌ 域名已失效，用平台数据替代 |
| 和风天气 | 天气 | ⬜ 未接入 |

**关键数据（真实，非占位）：**

| 数据集 | 条数 |
|---|---|
| 北京市等级景区信息 | 212 |
| 等级景区门票信息 | 218 |
| 等级景区交通信息 | 216 |
| **重点景区饱和指数**（实时人流） | 217（去重后） |

> 平台数据来自市文化和旅游局，实时人流用官方「重点景区饱和指数」——
> 原方案依赖的 VisitBeijing MCP 域名已 NXDOMAIN，这是替代方案。

---

## 凭证获取

<details>
<summary>北京市公共数据开放平台</summary>

1. 注册 https://data.beijing.gov.cn
2. 【用户中心 - 我的唯一码】获取 key
3. ⚠️ key 是**滚动值**，每次访问页面都会刷新并使旧值失效

**注：** 数据已随仓库提供（`data/wtt.db`），日常运行不需要此 key。
</details>

<details>
<summary>高德地图</summary>

1. https://lbs.amap.com → 控制台 → 应用管理 → 创建应用
2. **服务平台必须选「Web服务」**（不是 JS API，两者 key 不通用）
3. 配额（个人认证，日）：地理编码/路径规划 5000，**POI 搜索仅 100**
</details>

<details>
<summary>智谱 GLM</summary>

1. https://open.bigmodel.cn/
2. 实测：`glm-4-flash` 可用且最省；`glm-4.7` 可用但贵约 16 倍；5.x 系列需充值
</details>

<details>
<summary>阿里云百炼（Embedding）</summary>

1. https://bailian.console.aliyun.com/
2. ⚠️ **必须用 Workspace 专属端点**——公共端点 `dashscope.aliyuncs.com` 不被接受
3. 端点形如 `https://<WORKSPACE_ID>.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`
</details>

---

## 动机分类

| 动机 | 推荐策略倾向 |
|---|---|
| 恢复/逃离 | 自然景观、小众、低人流（**排除纪念馆等严肃场所**） |
| 连接/关系 | 交通便利、老少皆宜 |
| 探索/新奇 | 小众、非典型 |
| 表达/展示 | 视觉冲击、出片率高 |
| 成就/完成 | 5A 标志性、打卡优先 |
| 文化/沉浸 | 历史文化属性、博物馆/遗址 |
| 美食/感官 | 餐饮驱动 |

---

## 调研文档

| 文档 | 内容 |
|---|---|
| `docs/reference/PRD.md` | 产品需求文档 V1.2 |
| `docs/reference/analysis.md` | 竞品分析与学术支撑 |
| `docs/research/data-sources-report.md` | 四个数据源实测报告 |
| `docs/research/analysis-verification.md` | 竞品/论文逐条核实 |
| `docs/research/reusable-assets.md` | 开源仓库可复用性评估 |
| `docs/research/arxiv-findings.md` | arXiv 技术方案调研 |
| `docs/research/itinera-verification.md` | ITINERA 实跑验证 |

---

## 已知限制

- **仅北京**：其他省份数据未接入（PRD 规划的占位数据未做）
- **单日行程**：多日行程未实现
- **直线距离**：行程距离为球面直线估算，未走高德路径规划 API
- **时间估算粗略**：每站固定 75 分钟，未按景点类型区分
- **无用户系统**：画像与历史记录未落地（sessions 表已建但未使用）

---

## License

课程作业项目。数据来源为北京市公共数据开放平台（[开放协议](https://data.beijing.gov.cn)），
使用时需注明数据来源。行程编排思路参考 [ITINERA](https://github.com/YihongT/ITINERA)（GPL-3.0）。
