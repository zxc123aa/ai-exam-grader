# AI Exam Grader

AI Exam Grader 是一个面向教师的试卷扫描、模板标定、自动判分、人工复核和批注导出的 Web 系统。

当前仓库处于周期 0 技术底座阶段：项目计划文档已建立，FastAPI/React 工程底座已初始化，基础考试、文件上传和测试任务 API 已加入。

## 文档入口

- [完整开发计划](plan.md)：立项方案、产品目标、技术架构、开发周期和风险控制。
- [任务拆解](docs/task-breakdown.md)：将总计划拆成可执行 Epic 和阶段验收目标。
- [进度摘要](docs/progress-summary.md)：记录当前阶段、已完成事项、进行中任务、风险和下一步。
- [Issue 草稿池](docs/issue-backlog.md)：本地 issue 队列，后续可迁移到 GitHub Issues。
- [决策记录](docs/decision-log.md)：记录关键产品和技术决策。
- [模板、标准答案与评分闭环计划](docs/template-answer-grading-plan.md)：记录“空白卷重建 -> 标准答案 -> 学生答案识别评分”的主线方案。
- [第三方许可证清单](THIRD_PARTY_LICENSES.md)：记录直接依赖和参考项目的许可证。
- [周期 0 验收清单](docs/phase-0-acceptance.md)：记录当前已验证项和 Docker 环境待验证项。

## 当前状态

- 阶段：周期 0 技术底座初始化。
- 已完成：本地仓库初始化，`plan.md` 初始提交，远程 `origin` 配置，FastAPI/React 模板合并。
- 已加入：PostgreSQL、Redis、Dramatiq Worker、本地文件存储、考试 API、文件上传 API、测试任务 API。
- 未开始：试卷上传业务流、PDF 渲染、模板编辑器、OCR、AI 标定和判分。

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

继续完成周期 0 验证和收尾：在具备 Docker 的环境中启动全栈服务，执行后端测试和前端构建，然后进入周期 1 的人工试卷标定能力开发。
