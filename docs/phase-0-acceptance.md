# 周期 0 验收清单

更新时间：2026-06-30

## 当前结论

周期 0 技术底座的代码骨架已完成，进入外部环境验收阶段。当前机器未安装 Docker，因此容器启动、PostgreSQL 集成测试和 Worker 端到端验证仍未完成。

## 已在当前环境验证

- `python3 -m py_compile` 通过关键后端模块语法检查。
- `python3 scripts/smoke-openapi.py` 可检查 OpenAPI 中是否包含核心周期 0 端点。
- `npm run --workspace frontend lint` 通过，仅有 Biome schema 版本提示。
- `npm run --workspace frontend build` 通过。
- 前端路由已从 `/items` 收敛为 `/exams`。
- 前端 OpenAPI client 已从当前后端 schema 重新生成，包含 `ExamsService`、`FilesService` 和 `TasksService`。

## 待在 Docker 环境验证

1. 执行 `docker compose up --build`。
2. 打开前端：`http://localhost:5173`。
3. 打开后端 OpenAPI：`http://localhost:8000/docs`。
4. 使用 `.env` 默认管理员登录：
   - Email：`admin@example.com`
   - Password：`changethis`
5. 创建测试考试：`POST /api/v1/exams/`。
6. 上传测试文件：`POST /api/v1/files/upload`。
7. 创建测试任务：`POST /api/v1/tasks/test`。
8. 确认 Worker 将任务状态推进到 `succeeded`。
9. 执行后端测试：`docker compose exec -T backend bash scripts/tests-start.sh`。
10. 执行端到端测试：`docker compose run --rm playwright bunx playwright test`。

## 验收判定

- 代码骨架：通过。
- 前端构建：通过。
- OpenAPI 静态 smoke：通过后可标记。
- Docker 启动：待验证。
- 后端集成测试：待验证。
- Worker 端到端：待验证。

周期 0 可进入周期 1 规划，但在正式开发前应优先完成 Docker 环境验收，避免后续业务开发建立在未验证的基础服务上。
