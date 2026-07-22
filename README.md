# AI Exam Grader

AI Exam Grader 是一个面向教师的试卷扫描、模板标定、自动判分、人工复核和批注导出的 Web 系统。

主流程已端到端打通：导入（拍照/扫描/PDF，手机照片自动预处理）→ 模板区域标定与校正 → 题目识别（Gemini）→ 标准答案与评分点 → 批量批改（Gemini 转录手写答案 + LLM 评分，客观题走规则引擎）→ 人工复核（含跨页续题合并）→ 成绩总览（分班统计）。

## 文档入口

- [完整开发计划](plan.md)：立项方案、产品目标、技术架构、开发周期和风险控制。
- [任务拆解](docs/task-breakdown.md)：将总计划拆成可执行 Epic 和阶段验收目标。
- [进度摘要](docs/progress-summary.md)：记录当前阶段、已完成事项、进行中任务、风险和下一步。
- [Issue 草稿池](docs/issue-backlog.md)：本地 issue 队列，后续可迁移到 GitHub Issues。
- [决策记录](docs/decision-log.md)：记录关键产品和技术决策。
- [模板、标准答案与评分闭环计划](docs/template-answer-grading-plan.md)：记录“空白卷重建 -> 标准答案 -> 学生答案识别评分”的主线方案。
- [第三方许可证清单](THIRD_PARTY_LICENSES.md)：记录直接依赖和参考项目的许可证。

## 当前状态

- 已打通：考试创建与文件导入（多页 PDF/拍照追加）、模板区域标定（含续页区域）、题目识别与确认、标准答案版本管理与发布、批量/单份批改（可重试失败项）、人工复核（OCR 草稿 + AI 评分草稿 + 裁切图对照）、成绩汇总与待复核队列。
- 批改管线：视觉模型（默认 Gemini）按题区裁切图转录学生答案；客观题由规则引擎判分，主观题由 LLM 依据转录文本 + 标准答案 + 评分点判分；低置信度结果进入人工复核。
- 示例素材：`materials/physics/` 收录了一套物理试卷原始照片与预处理结果，可用于走通全流程。
- 基础设施：PostgreSQL、Redis、Dramatiq Worker、本地文件存储、OCR 服务（可选 GPU profile）。

## 本地开发

推荐使用 Docker Compose：

```bash
docker compose up --build
```

常用入口：

- 前端：http://localhost:5173
- 后端 API：http://localhost:8000
- OpenAPI：http://localhost:8000/docs
- Adminer：http://localhost:8080

默认管理员账号来自 `.env`：

- Email：`admin@example.com`
- Password：`changethis`

本地文件上传默认保存到 `data/uploads`；Docker Compose 中挂载到容器内 `/app/data/uploads`。

无 Docker 环境下可执行轻量检查：

```bash
python3 scripts/smoke-openapi.py
npm run --workspace frontend lint
npm run --workspace frontend build
```

## 下一步

- 扩大真实班级规模的批改验证（数百份量级），观察识别准确率与成本。
- 复核效率优化：批量通过、按题型筛选、键盘快捷键。
- 成绩导出（Excel/PDF）与批注导出。
