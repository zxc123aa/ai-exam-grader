# 点凡阅卷（DIANFAN）

[![Test Backend](https://github.com/zxc123aa/ai-exam-grader/actions/workflows/test-backend.yml/badge.svg)](https://github.com/zxc123aa/ai-exam-grader/actions/workflows/test-backend.yml)
[![Test Frontend](https://github.com/zxc123aa/ai-exam-grader/actions/workflows/test-frontend.yml/badge.svg)](https://github.com/zxc123aa/ai-exam-grader/actions/workflows/test-frontend.yml)
[![Lint Backend](https://github.com/zxc123aa/ai-exam-grader/actions/workflows/lint-backend.yml/badge.svg)](https://github.com/zxc123aa/ai-exam-grader/actions/workflows/lint-backend.yml)

点凡阅卷是一个面向学校和教育机构的多租户 SaaS 批卷平台：试卷扫描、模板标定、自动判分、人工复核、成绩发布和学情分析。仓库名 `ai-exam-grader` 是早期项目名，正式品牌名为「点凡阅卷」。

教师主流程已端到端打通：导入（拍照/扫描/PDF，手机照片自动预处理）→ 模板区域标定与校正 → 题目识别（Gemini）→ 标准答案与评分点 → 批量批改（Gemini 转录手写答案 + LLM 评分，客观题走规则引擎）→ 人工复核（含跨页续题合并）→ 成绩发布（不可变快照）→ 成绩总览与学情分析。

## 文档入口

- [项目记忆与产品原则](AGENTS.md)：品牌、第一设计原则、术语规范、视觉规范、角色模型。
- [完整开发计划](plan.md)：立项方案、产品目标、技术架构、开发周期和风险控制。
- [任务拆解](docs/task-breakdown.md)：将总计划拆成可执行 Epic 和阶段验收目标。
- [进度摘要](docs/progress-summary.md)：记录当前阶段、已完成事项、进行中任务、风险和下一步。
- [Issue 草稿池](docs/issue-backlog.md)：本地 issue 队列，后续可迁移到 GitHub Issues。
- [决策记录](docs/decision-log.md)：记录关键产品和技术决策。
- [模板、标准答案与评分闭环计划](docs/template-answer-grading-plan.md)：记录“空白卷重建 -> 标准答案 -> 学生答案识别评分”的主线方案。
- [生产运行手册](docs/production-operations.md)：生产基线、上线流程、商业运营闭环、OSS 迁移、备份恢复、告警与故障处置。
- [渠道运营手册](docs/provider-relay-operations.md)：模型中转渠道的接入与运维口径。
- [开发指南](development.md)：本地启动、pre-commit、CI 检查与本地复现方式。
- [第三方许可证清单](THIRD_PARTY_LICENSES.md)：记录直接依赖和参考项目的许可证。

## 当前状态

- **教师批卷闭环**：考试创建与文件导入（多页 PDF/拍照追加）、模板区域标定（含续页区域）、题目识别与确认、标准答案版本管理与发布、批量/单份批改（可重试失败项）、按题横批工作台与人工复核（OCR 草稿 + 建议评分 + 裁切图对照）、成绩发布、成绩汇总与学情分析。
- **批改管线**：视觉模型（默认 Gemini）按题区裁切图转录学生答案；客观题由规则引擎判分，主观题由 LLM 依据转录文本 + 标准答案 + 评分点判分；识别不合格时安全门直接拦截自动判分，低置信度结果进入人工复核。
- **多租户与协作**：平台侧与学校侧共 7 档角色，数据按学校隔离；教师任教档案、按班分配批卷、教师间考试互见开关。
- **商业化**：年度套餐与答卷加量包、订单与微信支付/银行转账、发票与退款、答卷额度与 Token 积分双轨计费、学校用量风控；平台侧有「订单与财务」工作台（学校端自助下单界面仍待补齐）。
- **模型运营**：模型渠道控制面（凭证加密、模型映射、路由版本发布与回滚、健康熔断、上游对账）+ 面向学校的公开模型目录，学校看不到真实供应链。
- **试运行环境**：`https://app.dianfandig.com`（staging，单机部署，见 `服务器部署/`）。
- **基础设施**：PostgreSQL、Redis、Dramatiq Worker、本地或 OSS 文件存储、OCR 服务（可选 GPU profile）、Node 参考算法服务、存活与就绪探针。
- 示例素材：`materials/physics/` 收录了一套物理试卷原始照片与预处理结果，可用于走通全流程。

## 本地开发

配置从仓库根的 `.env` 读取（已不在版本库内），先从模板复制：

```bash
cp .env.example .env   # 至少修改 SECRET_KEY、POSTGRES_PASSWORD、FIRST_SUPERUSER_PASSWORD
docker compose up --build
```

常用入口：

- 前端：http://localhost:5173
- 后端 API：http://localhost:8000
- OpenAPI：http://localhost:8000/docs
- Adminer：http://localhost:8080
- MailCatcher：http://localhost:1080

首个平台超管账号由 `.env` 的 `FIRST_SUPERUSER` 和 `FIRST_SUPERUSER_PASSWORD` 创建；公开注册默认关闭，其他账号一律由管理员创建。

本地文件上传默认保存到 `data/uploads`；Docker Compose 中挂载到容器内 `/app/data/uploads`。生产与试运行环境必须单独生成强随机密钥，不要复制开发配置。

## 检查与测试

CI 会在每个 PR 上运行后端 lint、后端测试、前端检查和 workflow 审计。本地复现方式、所需环境变量，以及为什么 mypy/ty 和 Playwright live 用例暂不进门禁，见[开发指南](development.md#ci-检查与本地复现)。

最小检查（`.env` 就位后）：

```bash
uv run ruff check backend/app backend/tests
PYTHONPATH=backend uv run python scripts/smoke-openapi.py
npm ci && (cd frontend && npx biome ci . && npx tsc -p tsconfig.build.json && npx vite build)
```

## 下一步

- 扩大真实班级规模的批改验证（数百份量级），观察识别准确率、耗时与模型成本。
- 补齐商业化闭环：学校端自助购课界面、outbox 真实投递、微信退款真实链路。
- 题目自动分割收口（当前真实样本 `3 pass / 3 review / 1 fail`）与扫描质量门禁的教师确认闭环。
- 复核效率优化：批量通过、按题型筛选、键盘快捷键；成绩与批注导出（Excel/PDF）。
- 正式商用前按生产运行手册补齐多实例、RDS/Redis 高可用与私有 OSS。
