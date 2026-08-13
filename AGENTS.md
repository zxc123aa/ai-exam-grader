# 点凡阅卷 — 项目记忆

## 品牌
- 正式品牌名：**点凡阅卷**（曾用名：智批 AI、智阅卷）。英文小标：DIANFAN。
- 界面、文档、代码注释中新内容一律使用「点凡阅卷」。

## 产品定位与第一设计原则
面向学校/教育机构的多租户 SaaS 批卷工具。

> **做一款老师打开就会用的专业批卷工具，AI 在后台工作，界面上尽量看不见 AI。**

落实为一条总原则：**默认界面只展示老师下一步要做的事情；解释、参数和技术细节按需展开。**

- 正常结果不打扰，异常结果集中提醒（复核队列）。
- 老师每处理一道题只做一个决定：看答案 → 给分 → 自动保存并进入下一份。
- 默认"按题横批"（全班第 N 题 → 第 N+1 题），评分标准保持连续记忆。
- 评分依据默认收起；低置信度时自动展开。
- 文案说人话：写「答案字迹不清」「评分依据不足」，不写"置信度低于 0.8"。
- 模型名/服务商/并发数/OCR 引擎等技术参数**不得出现在普通老师界面**，归系统管理员设置。

## 术语规范（弱化 AI 符号）
| 不用 | 用 |
|---|---|
| AI 评分 / AI 给分 | 建议评分 |
| AI 学习建议 | 学习建议 |
| AI 采纳率 | 自动批改通过率 |
| 生成答案草稿 | 生成参考答案 |
| AI 学情分析报告 | 学情分析 |
| 置信度百分比（默认展示） | 仅低置信度时提示 |
| 魔法棒/闪光图标 | 仅保留在个别核心自动化操作上 |

## 视觉规范
- 与微信小程序端同一系统：暖白底 #FAFAF9、卡白、hairline 边（#EBEBE8）、墨色三级（#1A1A1A/#6B6B6B/#9C9C9C）、**唯一强调蓝 #2E5BFF**、语义色 #16A34A/#D97706/#DC2626 仅小面积。
- 阴影至多 `0 1px 2px rgba(0,0,0,.04)`，卡片区分主要靠边框；圆角 10px。
- 不每卡片配彩色图标（图标块统一中性灰）、信息标签用 neutral、状态才用语义色。
- 标题层级：页面级标题只在顶栏一处；每屏一个主 CTA（纯色品牌蓝）；工具操作 ghost；危险操作红字 ghost 压最右。
- 避免"卡片套卡片"：页面一个主容器，内部用分隔线和栏目标题；只有可独立操作的对象才做成卡片。

## 角色模型（多租户）
- 平台侧（org_id 为空）：`platform_superuser`（超管）、`platform_support`（运营，跨校只读）。
- 学校侧：`school_owner`（总管理员，校内全部+学校设置）、`school_admin`（管理员，管老师学生+全校只读）、`teacher`（自己的考试）、`student`（仅我的成绩）。
- 教师间考试互见是学校级开关（org.exam_sharing_enabled，默认关）。
- 账号一律管理员创建，公开注册已关闭。

## 技术要点
- 前端：React 19 + TanStack Router/Query + Tailwind v4（CSS-first token 在 `frontend/src/index.css`）+ shadcn/ui；业务组件在 `components/Common/`、图表在 `components/charts/`（recharts）。
- 后端：FastAPI + SQLModel + PostgreSQL（alembic）+ dramatiq worker + Redis；数据隔离在 `app/services/org_scope.py`。
- 批改管线：Gemini 视觉转录学生答案 → 客观题规则引擎 / 主观题 LLM 按评分点判分；低置信度进人工复核。
- 测试：后端 `cd backend && POSTGRES_DB=app_test .venv/bin/python -m pytest tests/ -q`（1 个环境基线失败：照片预处理）；前端 `npx tsc -p tsconfig.build.json` + `npx biome check --write --unsafe` + `npx playwright test`。
- 本地服务：uvicorn :8000（--reload）、vite :5173、dramatiq worker、docker（db/redis/ocr/mailcatcher）。E2E 账号 admin@example.com / changethis（platform_superuser）。

## 当前数据备注
- 演示考试「扫描流程验证-物理双页卷」（默认学校，001/002 班各 4 人，18 题满分 100）。
- 测试学校「示范二中」(code=demo2) 及 demo2.owner@example.com；学生账号 liuyuxin@example.com（绑刘雨欣）。

## Cursor Cloud specific instructions
系统依赖（uv、PostgreSQL 18、Redis 7、后端/前端依赖、`.env`）已随 VM 快照装好，启动脚本每次开机跑 `uv sync` + `npm ci` 刷新代码依赖。以下是**非显而易见的启动/运行注意事项**（容器内无 systemd，服务不会自动起）。

### 每次新 VM 手动起服务
- PostgreSQL 18（PGDG 安装，非 systemd）：`sudo pg_ctlcluster 18 main start`
- Redis 7：`sudo redis-server /etc/redis/redis.conf --daemonize yes`
- 数据库角色 `postgres` / 密码 `postgres`；库 `app`（开发）与 `app_test`（测试）已建好；`.env` 已从 `.env.example` 复制并填好本地占位密钥（`POSTGRES_PASSWORD=postgres`）。
- 迁移 + 种子（首个超管 admin@example.com / changethis）：`cd backend && uv run alembic upgrade head && uv run python app/initial_data.py`（数据随快照保留，一般只在有新迁移时重跑）。

### 开发运行命令（标准命令见 development.md / package.json）
- 后端：`cd backend && uv run fastapi dev app/main.py`（:8000）。
- Worker：`cd backend && uv run dramatiq app.worker`。注意：锁文件未含 `watchdog`，**不支持 `--watch`**（compose 里用了 `--watch`，本地加会报 `unrecognized arguments: --watch`）。
- 前端：`cd frontend && npx vite`（:5173）。容器内**没装 bun**，用 `npx vite` 代替 `bun run dev`。
- uv 装在 `~/.local/bin` 并软链到 `/usr/local/bin/uv`。

### 陷阱
- 跑后端测试用的 `POSTGRES_DB=app_test`、`EMAILS_FROM_EMAIL`、`BILLING_ENFORCEMENT_ENABLED` 等变量**不要泄漏到开发/服务进程**：后端/worker 若带着 `POSTGRES_DB=app_test` 启动会连到未播种超管的测试库，登录报 400。起服务前确保未 export 这些变量。
- 后端测试若直接用完整 `.env` 跑，`test_platform` 有 4 个系统配置用例会因 `.env` 里 `VISION_FALLBACK_MODELS=gpt-5.5` 泄漏进测试进程而失败（CI 不带 `.env` 模型变量，故绿）。要对齐 CI，跑测试时移除/注释 `.env` 的 `VISION_FALLBACK_MODELS`。测试命令见「技术要点」。
- 批改全链路（视觉/LLM 评分、Node 参考算法 :3417、GPU OCR :8010）需真实模型 Key（`.env` 的 `PROVIDER_*`），默认未配置，属**可选服务**；核心 loop（登录 / 建校 / 学校与账号管理）无需它们即可跑通。
