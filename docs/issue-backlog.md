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

### AEG-024 教师复核页和结构化批注最小闭环

- 类型：Feature
- 优先级：P0
- 状态：Done
- 所属周期：周期 6 前置
- 目标：在 OCR/AI 判分接入前，先建立教师可以查看学生答卷、选择模板题区、录入分数/评语/复核状态的工作台。
- 验证：`pytest tests/api/routes/test_exams.py -q` 已通过，32 passed；`bash scripts/tests-start.sh` 已通过，84 passed，coverage 91%；`PYTHONPATH=backend python3 scripts/smoke-openapi.py` 已通过，19 paths；`npm run --workspace frontend lint` 和 `npm run --workspace frontend build` 已通过；`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/snap/bin/chromium npx playwright test tests/exams.spec.ts --project=chromium --reporter=line` 已通过，4 passed。
- 验收标准：
  - 新增 `SubmissionAnnotation` 数据模型和 Alembic migration。已完成。
  - 后端提供批注列表、创建、更新和删除 API。已完成。
  - 批注保存题区归属、页面、归一化坐标、分数、满分、评语和复核状态。已完成。
  - 前端提供学生答卷 Review 入口。已完成。
  - 复核页可显示答卷页图、模板题区叠加和题区列表。已完成。
  - 教师可选择题区并保存结构化分数/评语/状态。已完成。
  - 当前不做自由手绘批注和题区拖拽微调，后续在复核页继续增强。已明确。

### AEG-025 学生答卷处理任务占位管线

- 类型：Feature
- 优先级：P0
- 状态：Done
- 所属周期：周期 3/4 前置
- 目标：先建立学生答卷处理任务入口和可追踪输出，让后续自动配准、裁题、OCR、判分能挂到同一条任务管线。
- 验证：`pytest tests/api/routes/test_exams.py -q` 已通过，33 passed；`bash scripts/tests-start.sh` 已通过，85 passed，coverage 90%；`PYTHONPATH=backend python3 scripts/smoke-openapi.py` 已通过，20 paths；`npm run --workspace frontend lint` 和 `npm run --workspace frontend build` 已通过；`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/snap/bin/chromium npx playwright test tests/exams.spec.ts --project=chromium --reporter=line` 已通过，4 passed。
- 验收标准：
  - 后端提供 `POST /api/v1/exams/{exam_id}/submissions/{submission_id}/processing-tasks`。已完成。
  - 任务 `input_ref` 记录 exam、submission 和 pipeline 标识。已完成。
  - Worker 支持 `student_submission_processing` 占位流程。已完成。
  - 占位流程为未批注模板题区生成 `needs_review` 批注草稿。已完成。
  - 任务 `output_ref` 记录 registration、region crops、OCR、grading 阶段占位状态。已完成。
  - 复核页可触发处理任务、展示任务状态/进度，并刷新批注列表。已完成。
  - 本地环境同步执行任务，非 local 环境保留 Dramatiq 入队。已完成。

### AEG-027 题区裁剪产物和复核页裁剪预览

- 类型：Feature
- 优先级：P0
- 状态：Done
- 所属周期：周期 3/6 前置
- 目标：让学生答卷处理任务实际产出每个模板题区的裁剪 PNG，并在教师复核页展示当前题区的证据图。
- 验证：`pytest backend/tests/api/routes/test_exams.py -q` 已通过，34 passed；`PYTHONPATH=backend python3 scripts/smoke-openapi.py` 已通过，22 paths；`npm run --workspace frontend lint` 和 `npm run --workspace frontend build` 已通过；`bash scripts/tests-start.sh` 已通过，88 passed，coverage 90%；`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/snap/bin/chromium npx playwright test tests/exams.spec.ts --project=chromium --reporter=line` 已通过，5 passed。
- 验收标准：
  - Worker 为每个 `ExamRegion` 生成实际 PNG 裁剪产物。已完成。
  - 裁剪产物写入统一上传目录下的派生文件路径。已完成。
  - 处理任务 `output_ref.region_crops` 记录题区、页码、尺寸、坐标和 storage key。已完成。
  - 后端提供受保护的批注裁剪图读取接口，不使用 URL token。已完成。
  - 复核页在选中题区时显示对应裁剪预览。已完成。
  - Playwright 覆盖处理任务后显示裁剪预览。已完成。
  - 后续把 `output_ref` 中的裁剪产物索引迁移为专门表或 JSONB 查询优化。

### AEG-028 OCR 初稿字段、服务接口和复核页展示

- 类型：Feature
- 优先级：P0
- 状态：Done
- 所属周期：周期 4 前置
- 目标：在接入真实 OCR 引擎前，先建立题区级 OCR 结果的数据结构、处理任务接口和教师复核页展示位置。
- 验证：`pytest backend/tests/api/routes/test_exams.py -q` 已通过，34 passed；`bash scripts/tests-start.sh` 已通过，90 passed，coverage 90%；`PYTHONPATH=backend python3 scripts/smoke-openapi.py` 已通过，22 paths；`npm run --workspace frontend lint` 和 `npm run --workspace frontend build` 已通过；`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/snap/bin/chromium npx playwright test tests/exams.spec.ts --project=chromium --reporter=line` 已通过，5 passed。
- 验收标准：
  - `SubmissionAnnotation` 保存 OCR 文本、置信度、状态和引擎。已完成。
  - Alembic migration 可把现有批注表升级到 OCR 字段结构。已完成。
  - Worker 在题区裁剪后执行 OCR draft 阶段。已完成。
  - 默认环境不依赖外部 OCR 二进制，未配置时返回 `not_configured` 且任务不失败。已完成。
  - 处理任务 `output_ref.ocr_results` 记录每个题区 OCR 状态。已完成。
  - 复核页显示 OCR draft 状态、引擎和文本区域。已完成。
  - 后续配置真实 OCR 引擎，并基于真实样本评估识别质量。

### AEG-029 PaddleOCR GPU cu130 独立 OCR 服务

- 类型：Feature
- 优先级：P0
- 状态：Done
- 所属周期：周期 4
- 目标：基于本机 RTX 5060 Laptop 和 CUDA 13.2 驱动，新增独立 PaddleOCR GPU cu130 服务，让 Worker 可通过 HTTP 获取真实 OCR 文本。
- 验证：已通过 PowerShell PATH workaround 调 Windows Docker CLI；`docker run --rm --gpus all nvidia/cuda:13.0.0-base-ubuntu22.04 nvidia-smi` 可见 RTX 5060 Laptop；`docker compose --profile ocr-gpu up -d ocr-service` 启动后 `/health` 返回 `paddleocr-gpu-cu130`；容器内 `paddle.utils.run_check()` 通过；`POST /ocr` 对 `materials/English/processed/test1/page_1_left.jpg` 返回真实试卷文本，平均置信度约 `0.989`；后端测试覆盖 Worker 将 Paddle HTTP OCR 结果写入 `SubmissionAnnotation`。
- 验收标准：
  - `docker run --rm --gpus all nvidia/cuda:13.0.0-base-ubuntu22.04 nvidia-smi` 通过。已完成。
  - `docker compose --profile ocr-gpu up --build ocr-service` 可启动。已完成。
  - `GET /health` 返回 `paddleocr-gpu-cu130`。已完成。
  - `POST /ocr` 对真实题区 PNG/JPG 返回 `text` 和 `confidence`。已完成。
  - Worker 设置 `OCR_ENGINE=paddle_http` 后将真实 `ocr_text` 写入 `SubmissionAnnotation`。已完成，当前以 HTTP fake 回归测试锁定写入链路。

### AEG-030 教师复核页 PaddleOCR 真实流程验收

- 类型：Verification
- 优先级：P0
- 状态：Done
- 所属周期：周期 4
- 目标：在本地同时启动后端、前端和 `ocr-service`，从教师复核页触发处理任务，确认真实题区裁剪图经过 PaddleOCR 后显示 OCR draft 文本。
- 验证：本地后端以 `OCR_ENGINE=paddle_http OCR_HTTP_URL=http://localhost:8010/ocr` 启动，前端 Vite 启动，`E2E_PADDLE_OCR=1 PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/snap/bin/chromium npx playwright test tests/exams.spec.ts -g "PaddleOCR draft appears" --project=chromium --reporter=line` 已通过，2 passed。测试使用 `materials/English/processed/test1/page_1_left.jpg` 作为真实模板和学生答卷样本，复核页 Run Processing 后 OCR draft 显示 `paddleocr-gpu-cu130` 和真实试卷文本。
- 验收标准：
  - 后端以 `OCR_ENGINE=paddle_http` 和正确 `OCR_HTTP_URL` 启动。已完成。
  - 复核页 Run Processing 后，选中题区能看到 `ocr_status=succeeded` 和 PaddleOCR 文本。已完成。
  - 记录至少 3 个题区的识别质量和失败样例。后续并入 AEG-031 扩大样本评估。
  - 若低置信度或题区切分问题明显，形成图像增强/自动配准/云 OCR fallback 的后续 issue。后续并入 AEG-031。

### AEG-031 PaddleOCR 题区级质量评估和低置信度策略

- 类型：Verification
- 优先级：P1
- 状态：In Progress
- 所属周期：周期 4
- 目标：使用更多真实题区裁剪样本评估 PaddleOCR 在选择题、填空题、主观题和低清晰度手机照片上的表现，明确低置信度时是否需要图像增强、Kimi/云 OCR fallback 或人工优先策略。
- 进展：已完成物理卷第一批评估，见 `docs/physics-ocr-evaluation.md`。样本覆盖 `materials/physics/1.jpg`、`materials/physics/2.jpg`，生成 4 个页级样本和 11 个题区样本；PaddleOCR 全量跑通，Kimi K2.7 对 3 个代表题区/页做高 token 复测。
- 结论：PaddleOCR 适合作为快速 baseline；Kimi K2.7 对综合题、公式、单位恢复更好，但不适合整页无差别 OCR，应限制在题区级 fallback。建议先以 `0.90` 作为 PaddleOCR 低置信度 fallback 实验阈值。
- 验收标准：
  - 至少覆盖 3 份试卷、10 个题区裁剪样本。已覆盖 1 份物理卷、11 个题区，仍需扩到 3 份。
  - 记录每个样本的 `ocr_text`、`ocr_confidence`、题区类型和人工判断。已完成第一批。
  - 给出低置信度阈值建议。已形成初始建议：`0.90`。
  - 形成后续图像增强、自动配准或云 OCR fallback issue。已形成 Kimi 题区级 fallback 方向，仍需实现 issue。

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

### AEG-021 手机扫描成 PDF 能力后端入口

- 类型：Feature
- 优先级：P1
- 状态：Done
- 所属周期：周期 3 前置 / 后续 App 采集周期
- 目标：建立“扫描王”类后端受控入口，即手机拍摄试卷后自动裁边、矫正、增强、拆页并导出 PDF，再登记为学生答卷。
- 进展：已新增 OpenCV 预处理服务、`POST /api/v1/exams/{exam_id}/submissions/preprocess-photo` 和学生答卷弹窗 Convert photo 入口；合成手机照片用例已验证可生成两页 PDF 并走现有分页预览接口。
- 验证：`pytest backend/tests/api/routes/test_exams.py -q` 已通过，34 passed；`PYTHONPATH=backend python3 scripts/smoke-openapi.py` 已通过，21 paths；`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/snap/bin/chromium npx playwright test tests/exams.spec.ts --project=chromium --reporter=line` 已通过，5 passed。
- 决策：先以后端 API 形式接入 Web MVP；移动 App 和更完整的拍照交互后置。预处理输出仍进入 `StudentSubmission`，配准、OCR、判分继续复用后续处理任务管线。
- 验收标准：
  - 后端接受 JPG/PNG 手机照片上传。已完成。
  - 后端完成试卷区域检测、透视矫正、增强、双页拆分和 PDF 生成。已完成最小版本。
  - 生成的 PDF 保存为 StoredFile，并创建 StudentSubmission。已完成。
  - 生成的学生答卷可以复用现有分页预览接口。已完成。
  - 前端学生答卷上传弹窗提供“手机照片转 PDF”入口。已完成。
  - 使用真实样本继续验收页面边界、中缝拆分、阴影和旋转鲁棒性。转入后续优化项。

### AEG-026 扫描预处理真实样本鲁棒性增强

- 类型：Hardening
- 优先级：P1
- 状态：In Progress
- 所属周期：周期 3 前置 / 后续 App 采集周期
- 目标：基于真实手机拍摄样本增强页面边界检测、中缝拆分、阴影/褶皱处理和失败提示。
- 进展：后端服务已输出拆分策略、中缝比例、置信度、页面 x 范围等元数据；本地实验脚本已改为复用后端服务；`test1.jpg` 双页样本当前识别中缝比例约 0.50，`writing.jpg` 识别为单页。物理卷 `materials/physics/1.jpg` 暴露的左页单独检测、右页漏检问题已通过 relaxed spread 检测修复；`materials/physics/2.jpg` 暴露的顶部题干裁切问题已通过内容保护边距修复，中缝偏左问题已通过空白带纠偏修复。
- 验证：`pytest backend/tests/services/test_exam_photo_preprocessing.py backend/tests/api/routes/test_exams.py -q` 已通过，36 passed；`pytest backend/tests/services/test_exam_photo_preprocessing.py backend/tests/api/routes/test_exams.py::test_preprocess_student_submission_photo_creates_pdf_submission -q` 已通过，5 passed；`bash scripts/tests-start.sh` 已通过，94 passed，coverage 88%。真实物理样本 `materials/physics/1.jpg` 已验证可输出双页，`materials/physics/2.jpg` 已验证可保留顶部题干并保持双页输出。
- 验收标准：
  - 用 `materials/English/test1.jpg` 等真实样本建立非提交回归记录。已完成第一批。
  - 双页试卷尽量按真实中缝拆分，而不是固定 50%。已完成第一版中心邻域中缝检测和回退策略。
  - 横向双页只检测到半页时，能通过 relaxed spread 或半页 fallback 避免漏页。已完成第一版。
  - 纸面顶部低对比/阴影导致检测框压低时，能保留顶部题干。已完成第一版内容保护边距。
  - 单页/双页检测有明确输出和错误提示。已完成输出元数据；错误提示仍待增强。
  - 处理失败时前端给出可理解的失败反馈，不生成半成品学生答卷。

### AEG-032 扫描预处理质量门禁与稳定性阶段

- 类型：Hardening
- 优先级：P0
- 状态：In Progress
- 所属周期：周期 3 前置 / 后续 App 采集周期
- 目标：扫描预处理先建立质量门禁和可复核闭环，避免裁题、漏页、混页结果静默进入 OCR/判分。
- 计划文档：`docs/scan-preprocessing-stability-plan.md`
- 进展：已新增软质量门禁，预处理结果输出 `quality_status=pass|review` 和 `quality_warnings[]`；API 已写入 `registration_homography.quality`，`registration_notes` 已包含 `scan_quality=...`；本地脚本已输出质量状态和 warning。
- 验证：`pytest backend/tests/services/test_exam_photo_preprocessing.py -q` 已通过，5 passed；`pytest backend/tests/api/routes/test_exams.py::test_preprocess_student_submission_photo_creates_pdf_submission -q` 已通过，1 passed。
- 验收标准：
  - 预处理结果必须带结构化质量状态和 warnings。已完成第一版。
  - 模糊、低置信度中缝、半页 fallback、页面比例异常、边缘疑似裁切必须能触发 review。已完成第一版。
  - 前端能显示 scan quality 和 warning。待完成。
  - review 结果进入 OCR/判分前必须可被教师确认。待完成。
  - 真实失败样例能沉淀为回归记录。待扩展。

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
