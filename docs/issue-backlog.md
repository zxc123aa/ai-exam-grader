# Issue 草稿池

本文档是本地 issue 队列。编号使用 `AEG-XXX`，后续可以迁移到 GitHub Issues 和 Milestones。

## 状态说明

- `Backlog`：已记录，尚未开始。
- `Ready`：信息充足，可直接执行。
- `In Progress`：正在处理。
- `Done`：已完成并通过验收。
- `Blocked`：存在外部阻塞。

## 周期 0：项目初始化与技术底座

### AEG-001 初始化 Full Stack FastAPI Template 技术底座

- 类型：Feature
- 优先级：P0
- 状态：Done
- 所属周期：周期 0
- 目标：创建可运行的前后端 Monorepo，作为后续业务开发基础。
- 验收标准：
  - 本地可以启动前端和后端。
  - 后端 API 文档可以访问。
  - Docker Compose 可以启动基础服务。
  - 默认测试可以运行。

### AEG-002 清理模板示例业务并建立项目命名

- 类型：Task
- 优先级：P0
- 状态：Done
- 所属周期：周期 0
- 目标：删除模板中无关示例业务，替换为 AI Exam Grader 项目命名。
- 验收标准：
  - 示例业务入口被移除或隐藏。
  - 前端标题、后端服务名、README 和配置命名统一。
  - 登录和基础认证能力保留。

### AEG-003 配置 PostgreSQL、Redis 和 Dramatiq

- 类型：Feature
- 优先级：P0
- 状态：In Progress
- 所属周期：周期 0
- 目标：建立数据库和后台任务基础设施。
- 验证：已通过 Windows Docker CLI 启动 PostgreSQL 18 和 Redis 7；后端测试任务 API 在测试环境通过。Worker 容器端到端仍随全量 compose build 后续验证。
- 验收标准：
  - PostgreSQL 可以被后端访问。
  - Redis 可以作为任务队列依赖启动。
  - Dramatiq Worker 可以执行测试任务。
  - 本地开发环境有明确启动命令。

### AEG-004 定义文件存储目录与坐标系统

- 类型：Design
- 优先级：P0
- 状态：Done
- 所属周期：周期 0
- 目标：明确试卷原图、页面图、裁剪图、批注导出文件的存储规则，以及归一化坐标约定。
- 验收标准：
  - 文档说明文件 key 和目录规范。
  - 坐标系统采用归一化页面坐标。
  - 说明原图坐标、模板坐标、裁剪图坐标之间的转换关系。
  - 后续数据模型可以引用该规范。

### AEG-005 定义核心数据模型草案

- 类型：Design
- 优先级：P0
- 状态：Done
- 所属周期：周期 0
- 目标：定义考试、模板、学生答卷、识别结果、判分结果、批注和审核记录的基础模型。
- 验收标准：
  - 模型覆盖 `plan.md` 第 8 节的数据对象。
  - 每个模型包含主键、归属关系、状态字段和审计字段。
  - 模板、答案、批注相关模型保留坐标字段。
  - 草案可转化为 SQLModel 和 Alembic migration。

### AEG-006 建立开发启动、测试、日志和错误处理规范

- 类型：Task
- 优先级：P1
- 状态：Done
- 所属周期：周期 0
- 目标：让后续开发有统一的本地启动、测试、日志和异常处理约定。
- 验收标准：
  - README 中包含本地启动命令。
  - 后端测试命令明确。
  - 前端测试或检查命令明确。
  - 日志格式和错误响应格式有基础规范。

### AEG-007 建立第三方许可证清单

- 类型：Compliance
- 优先级：P1
- 状态：Done
- 所属周期：周期 0
- 目标：记录直接依赖和参考项目的许可证，降低后续商业发布风险。
- 验收标准：
  - 建立 `THIRD_PARTY_LICENSES` 或同等文档。
  - 记录 Full Stack FastAPI Template、React Konva、PaddleOCR、OpenCV、pypdfium2、OMRChecker、MakeACopy。
  - 标记直接依赖、参考实现和后期参考的不同使用方式。
  - 对无许可证或许可证不明确项目给出处理策略。

### AEG-008 Docker 环境验收周期 0

- 类型：Verification
- 优先级：P0
- 状态：In Progress
- 所属周期：周期 0
- 目标：在具备 Docker 的环境中验证完整技术底座。
- 进展：Windows Docker CLI 可用，PostgreSQL 和 Redis 容器已启动并 healthy。
- 阻塞：后端镜像 build 拉取 `python:3.13` 时 Docker Hub 网络超时；全量 `docker compose up --build` 尚未完成。
- 验收标准：
  - `docker compose up --build` 可以启动前端、后端、PostgreSQL、Redis、Worker。
  - 前端登录页可以访问。
  - 后端 OpenAPI 可以访问。
  - 管理员可以登录。
  - 考试 API、文件上传 API 和测试任务 API 可用。
  - Worker 可以将测试任务推进到 `succeeded`。

### AEG-009 后端集成测试验收

- 类型：Verification
- 优先级：P0
- 状态：Done
- 所属周期：周期 0
- 目标：在 PostgreSQL 可用的环境中运行后端测试。
- 验证：`bash scripts/tests-start.sh` 已通过，71 passed，coverage 91%。
- 验收标准：
  - `docker compose exec -T backend bash scripts/tests-start.sh` 通过。
  - Exam、StoredFile、ProcessingTask 相关测试通过。
  - 登录、用户管理和私有测试用户 API 未回归。

## 后续待拆

## 周期 1：人工试卷标定基础能力

### AEG-010 创建考试 Web 工作流

- 类型：Feature
- 优先级：P0
- 状态：Done
- 所属周期：周期 1
- 目标：教师可以在 Web 端创建一场考试，作为后续上传空白卷、标定题区和判分的业务容器。
- 验收标准：
  - `/exams` 页面提供创建考试入口。
  - 可填写标题、科目和年级。
  - 创建成功后考试列表自动刷新。
  - 前端构建和 lint 通过。

### AEG-011 上传空白试卷文件并关联考试

- 类型：Feature
- 优先级：P0
- 状态：Done
- 所属周期：周期 1
- 目标：教师可以给指定考试上传已有 PDF/JPG/PNG 空白试卷文件。
- 验收标准：
  - 后端提供 `POST /api/v1/exams/{exam_id}/files`。
  - 上传文件落入统一 StoredFile 存储规则。
  - 新增 ExamDocument 关联考试和文件。
  - 前端每场考试可以打开文件弹窗并上传空白试卷。

### AEG-012 查看考试文件记录

- 类型：Feature
- 优先级：P0
- 状态：Done
- 所属周期：周期 1
- 目标：教师可以查看某场考试已上传的文件记录，确认文件名、类型和大小。
- 验收标准：
  - 后端提供 `GET /api/v1/exams/{exam_id}/files`。
  - 返回文件记录和嵌套 StoredFile 元数据。
  - 前端文件弹窗显示已上传文件列表。

### AEG-013 数据库迁移与集成测试验收

- 类型：Verification
- 优先级：P0
- 状态：Done
- 所属周期：周期 1
- 目标：在 PostgreSQL/Docker 可用环境验证 ExamDocument migration 和后端 API 测试。
- 验证：PostgreSQL 容器 healthy；`bash scripts/prestart.sh` 已执行 Alembic 到 `c2a8e1b4d903`；`bash scripts/tests-start.sh` 已通过，71 passed，coverage 91%。
- 验收标准：
  - Alembic 可以升级到 `b7d4c6e8f901`。
  - `test_upload_exam_file` 通过。
  - `test_read_exam_files` 通过。
  - 已有登录、用户、考试、文件和任务测试未回归。

### AEG-014 空白试卷页面预览与手工标定画布

- 类型：Feature
- 优先级：P0
- 状态：Done
- 所属周期：周期 1
- 目标：把上传的 PDF/JPG/PNG 渲染成可查看页面，并允许教师手工框选题区。
- 验收标准：
  - 图片空白卷可以在 Web 页面预览。已完成。
  - 页面坐标采用既定归一化坐标。已完成后端模型和图片画布。
  - 支持创建题区矩形并保存。已完成图片画布最小版本。
  - 支持删除已保存题区。已完成。
  - 支持移动、缩放题区矩形。已完成。
  - 支持修改题区标签。已完成。
  - PDF 首页渲染为可标定页面。已完成。

### AEG-016 考试文件上传安全与事务一致性

- 类型：Hardening
- 优先级：P1
- 状态：Done
- 所属周期：周期 1
- 来源：审核 agent。
- 目标：修正考试文件上传的服务端安全边界和数据一致性风险。
- 验收标准：
  - 后端限制考试文件仅允许 PDF/JPG/PNG。
  - 后端限制单文件大小，超过限制返回 413。
  - 后端校验文件签名与声明类型一致。
  - 考试文件上传在一个事务内创建 StoredFile 和 ExamDocument。
  - 事务失败时清理已写入的磁盘文件。
  - superuser 为他人考试上传时，业务文件 owner 绑定考试 owner。
  - 补充非法类型、跨用户 403、superuser 代上传 owner 归属测试。

### AEG-017 PDF 页面渲染和多页标定

- 类型：Feature
- 优先级：P0
- 状态：Done
- 所属周期：周期 1
- 目标：将 PDF 空白卷转换为可标定页面，并支持多页题区坐标。
- 验收标准：
  - PDF 至少首页可以渲染为图片或 canvas。已完成。
  - 多页 PDF 可以选择页码。已完成。
  - 题区保存时记录 `page_number`。已完成。
  - 文件预览不绕过权限控制。已完成。
  - 上传阶段拒绝无法解析的伪 PDF，避免落库后预览 500。已完成。

### AEG-018 标定画布 Playwright 交互覆盖

- 类型：Verification
- 优先级：P1
- 状态：Done
- 所属周期：周期 1
- 目标：为手工标定页面补齐端到端交互 smoke，避免画布拖拽、保存、重命名和删除回归。
- 验证：`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/snap/bin/chromium npx playwright test tests/exams.spec.ts --project=chromium --reporter=line` 已通过，4 passed。
- 验收标准：
  - 创建考试后可以上传空白卷。
  - 可以进入 `/exams/$examId/marking`。
  - 可以拖拽创建题区并保存。
  - 可以选中、重命名和删除已保存题区。

### AEG-019 学生答卷上传、登记和预览最小闭环

- 类型：Feature
- 优先级：P0
- 状态：Done
- 所属周期：周期 3 前置
- 目标：在真实模板配准和 OCR 前，先建立学生答卷上传、归属、登记信息和页面预览能力。
- 验证：后端 `bash scripts/tests-start.sh` 已通过，80 passed，coverage 90%；全量 Playwright Chromium 已通过，56 passed。
- 验收标准：
  - 新增 StudentSubmission 数据模型和 Alembic migration。已完成。
  - 后端提供上传、列表、读取单份答卷和按页预览接口。已完成。
  - 上传复用 PDF/JPG/PNG 类型、签名、大小和伪 PDF 校验。已完成。
  - 跨用户访问和 superuser 代上传归属行为与考试文件一致。已完成。
  - 前端提供 Submissions 入口，支持学生姓名/编号、文件上传、状态显示和预览。已完成。
  - 当前状态为配准占位，真实自动配准、OCR 判分和批注导出后续实现。

### AEG-022 学生答卷模板题区叠加和单题裁剪接口

- 类型：Feature
- 优先级：P0
- 状态：Done
- 所属周期：周期 3 前置
- 目标：在真实自动配准前，先用已标定模板题区对学生答卷做同页叠加，并提供单题裁剪 PNG 接口。
- 验证：`pytest tests/api/routes/test_exams.py -q` 已通过，28 passed；`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/snap/bin/chromium npx playwright test tests/exams.spec.ts --project=chromium --reporter=line` 已通过，4 passed。
- 验收标准：
  - 后端可读取某份学生答卷对应考试的模板题区，支持按页过滤。已完成。
  - 后端可按 `ExamRegion` 从学生答卷同页裁剪 PNG。已完成。
  - 裁剪接口继续使用 `Authorization: Bearer`，不把 token 放 URL。已完成。
  - 前端答卷预览可显示模板题区叠加层。已完成。
  - 当前不做自动 homography；默认学生卷已和模板同页同坐标系。已明确。

### AEG-023 学生答卷配准状态和人工确认流程

- 类型：Feature
- 优先级：P0
- 状态：Done
- 所属周期：周期 3 前置
- 目标：在自动配准算法接入前，先建立学生答卷与模板对齐结果的状态记录、质量字段和教师人工确认入口。
- 验证：`pytest tests/api/routes/test_exams.py -q` 已通过，30 passed；`bash scripts/tests-start.sh` 已通过，82 passed，coverage 90%；`PYTHONPATH=backend python3 scripts/smoke-openapi.py` 已通过，17 paths；`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/snap/bin/chromium npx playwright test tests/exams.spec.ts --project=chromium --reporter=line` 已通过，4 passed。
- 验收标准：
  - `StudentSubmission` 保存配准状态、质量分、备注、homography 和确认时间。已完成。
  - 后端提供 `PATCH /api/v1/exams/{exam_id}/submissions/{submission_id}/registration`。已完成。
  - 人工确认后答卷状态进入 `ready_for_review`。已完成。
  - 标记失败后答卷状态进入 `registration_failed`。已完成。
  - 前端学生答卷列表可显示配准状态和质量，并支持 Confirm/Fail 操作。已完成。
  - 当前人工确认写入 identity homography，后续替换为自动配准算法输出。已明确。

### AEG-020 Docker Compose 全量构建和 Worker E2E 验收

- 类型：Verification
- 优先级：P0
- 状态：In Progress
- 所属周期：周期 0/1 验收补齐
- 目标：验证 Docker Compose 全量构建、后端、前端、数据库、Redis 和 worker 在容器环境中完整运行。
- 进展：Windows Docker CLI 可用，PostgreSQL、Redis、Mailcatcher 可启动；本地后端和 E2E 已可跑通。
- 阻塞：后端镜像 build 曾在拉取 `python:3.13` 时遇到 Docker Hub 网络超时，需在网络稳定时重试。
- 验收标准：
  - `docker compose up --build` 可以启动前端、后端、PostgreSQL、Redis、Worker。
  - 后端 health check 和 OpenAPI 可访问。
  - 前端登录页可访问并能登录管理员。
  - Worker 可以将测试任务推进到 `succeeded`。

### AEG-021 手机扫描成 PDF 能力调研与排期

- 类型：Design
- 优先级：P2
- 状态：Backlog
- 所属周期：后续 App/采集周期
- 目标：评估“扫描王”类能力，即手机拍摄试卷后自动裁边、矫正、增强并导出 PDF/图片。
- 决策：当前 Web MVP 优先支持已有 PDF/JPG/PNG 上传；手机扫描能力后置，不阻塞模板标定、学生答卷上传和批注流程。
- 验收标准：
  - 明确移动端或 Web 端采集方案。
  - 明确透视矫正、去阴影、增强、合并 PDF 的技术路线。
  - 明确与后端 StoredFile、ExamDocument 和 StudentSubmission 的接口边界。

### AEG-015 手机扫描成 PDF 能力调研与排期

- 类型：Design
- 优先级：P2
- 状态：Done
- 所属周期：后续 App/采集周期
- 目标：评估“扫描王”类能力，即手机拍摄试卷后自动裁边、矫正、增强并导出 PDF/图片。
- 决策：已并入 AEG-021 继续跟踪；当前 Web MVP 优先支持已有 PDF/JPG/PNG 上传，手机扫描能力后置。
- 验收标准：
  - 不作为周期 1/周期 3 前置能力阻塞项。已完成。
  - 后续以 AEG-021 为准继续调研。

- 周期 2：AI 一键建立试卷模板。
- 周期 3：学生答卷处理与模板配准。
- 周期 4：客观题与基础 OCR 判分。
- 周期 5：主观题和视觉大模型判分。
- 周期 6：教师复核、批注回写与导出。
- 周期 7：评测、试点和生产部署。
