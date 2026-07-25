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
