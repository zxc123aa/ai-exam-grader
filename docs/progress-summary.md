# 进度摘要

更新时间：2026-06-30

## 当前阶段

周期 1 人工试卷标定基础能力：Web 上传、PDF/图片分页预览和手工题区标定骨架已实现，数据库迁移、后端集成测试和前端构建已通过。

## 已完成

- 本地仓库已初始化，当前分支为 `main`。
- 远程 `origin` 已配置为 `https://github.com/zxc123aa/ai-exam-grader.git`。
- 远程仓库当前为空，尚无 heads/tags。
- 完整开发计划已保存为 `plan.md`。
- `plan.md` 已完成初始提交：`8630de8 Initial project plan`。
- 项目文档入口、任务拆解、进度摘要、本地 issue 草稿池和决策记录已建立。
- 基于 Full Stack FastAPI Template 合并 FastAPI/React Monorepo。
- 已加入 Exam、StoredFile、ProcessingTask 最小模型和 API。
- 已接入 Redis、Dramatiq Worker 和本地上传目录配置。
- 前端已替换项目名称，并将模板 Items 入口调整为 Exams。
- 前端 OpenAPI client 已重新生成，使用正式 `ExamsService`。
- 已新增周期 0 验收清单和 OpenAPI smoke 检查脚本。
- 已建立第三方许可证清单。
- 已新增 ExamDocument 模型，用于关联考试与上传文件。
- 已新增 `POST /api/v1/exams/{exam_id}/files` 和 `GET /api/v1/exams/{exam_id}/files`。
- `/exams` 页面已支持创建考试、上传空白试卷文件、查看考试文件记录。
- 已补充周期 1 的 issue 拆解，明确“扫描王”类手机采集能力后置。
- 审核 agent 已完成一轮审查，未发现 P0；提出的上传安全、事务一致性、跨用户文件归属 P1 已修复。
- 已新增 ExamRegion 模型和区域 CRUD API，用于保存归一化题区坐标。
- 已新增 `/exams/$examId/marking` 标定页面：空白卷可分页预览，可拖拽框选题区，并可保存、删除、移动、缩放和修改标签。
- 已新增后端 PDF 渲染能力：PDF 上传时校验可解析性，返回 `page_count`，并提供按页 PNG 预览接口。
- 标定画布已支持多页 PDF 页码切换，题区保存时记录 `page_number`，页面切换时只显示当前页题区。
- 已通过 Windows Docker CLI 启动 PostgreSQL 18 和 Redis 7。
- Alembic migration 已升级到 `c2a8e1b4d903`。
- 后端集成测试脚本已通过：`bash scripts/tests-start.sh`，71 passed，coverage 91%。
- 前端检查和构建已通过：`npm run --workspace frontend lint`、`npm run --workspace frontend build`。
- OpenAPI smoke 路径存在性检查已通过，包含考试文件内容和分页图片预览路径。
- Playwright Chromium E2E 已通过：`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/snap/bin/chromium npx playwright test --project=chromium --reporter=line`，54 passed。

## 进行中

- 周期 1 下一块能力：学生答卷上传、模板配准和批注导出前的流程拆解。

## 下一步

1. 为标定页面增加 Playwright 路由/交互 smoke 测试。
2. 拆解学生答卷上传、模板配准和批注导出的最小闭环。
3. 在模板标定可用后，接学生答卷上传、配准和批注导出。
4. 继续审核 agent 循环，优先处理 P0/P1，再推进下一块功能。

## 风险与阻塞

- GitHub 远程仓库为空，需要后续首次推送本地提交。
- WSL 内 `docker` 命令未进 PATH，但 Windows Docker CLI 可通过 `/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe` 使用。
- 后端容器 build 拉取 `python:3.13` 时遇到 Docker Hub 网络超时；数据库和 Redis 容器已可用。
- 当前 Ubuntu 26.04 环境不被 Playwright 官方浏览器下载支持，测试使用系统 Chromium：`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/snap/bin/chromium`。
- 密码重置 E2E 需要 Mailcatcher，并要求本地后端以 `SMTP_HOST=localhost SMTP_PORT=1025 SMTP_TLS=false SMTP_SSL=false` 启动。
- 第三方依赖许可证清单已建立，但商业化前必须持续维护。
- OpenAPI 生成器把 multipart 文件字段生成为 `string` 类型，前端当前在上传组件内做了局部类型转换；后续可统一优化生成配置。
- 文件预览已改为 authenticated fetch 获取 blob/object URL，后端文件内容和分页图片接口只接受 `Authorization: Bearer ...`，避免把长期 token 拼进 URL。

## 最近决策

- 第一阶段优先 Web 系统，移动 App 后置。
- 第一阶段先支持已有 PDF/JPG/PNG 上传，不先实现手机“扫描王”。
- 采用模板驱动流程，不做无模板整卷盲识别。
- AI 结果作为建议和草稿，教师保留最终确认权。
- 客观题优先规则和 OCR，主观题再调用视觉大模型。
- 所有识别、判分和批注结果必须保留卷面坐标。
