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
- 状态：Done
- 所属周期：周期 0
- 验证：已通过 Windows Docker CLI 启动 PostgreSQL 18 和 Redis 7；后端测试任务 API 在测试环境通过。2026-08-07 起 staging（`服务器部署/compose.staging.yml`）以容器方式长期运行 PostgreSQL、Redis 与 dramatiq worker，识别与批改批次均由 worker 实际执行，Worker 端到端已验证。
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
- 状态：Done
- 所属周期：周期 0
- 目标：在具备 Docker 的环境中验证完整技术底座。
- 验证：2026-08-07 staging 已用 `服务器部署/compose.staging.yml` 完成全栈容器构建与启动（db、redis、backend、worker、frontend、reference-algorithm），公网入口 `https://app.dianfandig.com` 可登录使用。
- 备注：本地开发 override（Traefik、Adminer、Mailcatcher）仍未做过完整 `docker compose up --build` 验收，见 AEG-020 备注。
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

## 题目确认与答案版本工作流

### AEG-040 工作流 Spec、状态机和迁移基线
- 类型：Design
- 优先级：P0
- 状态：Done
- 验收：Spec、决策记录、迁移顺序和 DoD 完整；migration `c7d9e1f3a526` 已通过升降级。

### AEG-041 ExamQuestion 与多区域关联
- 类型：Feature
- 优先级：P0
- 状态：Done
- 验收：一道题可关联多个区域，考试内 question_key 唯一，旧区域可回填；区域明确关联试卷文件。

### AEG-042 题目识别任务与确认工作区
- 类型：Feature
- 优先级：P0
- 状态：Done
- 验收：Node 结果只写草稿，人工确认后生成题目主数据；页面显示考生作答、置信度与分阶段耗时。

### AEG-043 不可变答案版本与历史迁移
- 类型：Feature
- 优先级：P0
- 状态：Done
- 验收：现有答案迁移为 revision 1，发布版本不可修改；旧版更新/删除接口拒绝已发布答案。

### AEG-044 GPT-5.6 SOL 解题生成
- 类型：Feature
- 优先级：P0
- 状态：Done
- 验收：根据确认题目并发生成结构化答案草稿并记录 provider、model、耗时和网关返回的 Token 用量；网关未返回时不伪造。

### AEG-045 答案文档导入与匹配
- 类型：Feature
- 优先级：P0
- 状态：Done
- 验收：支持 matched/conflict/unmatched，未经确认不得生成答案修订。

### AEG-046 评分准则确认与答案发布
- 类型：Feature
- 优先级：P0
- 状态：Done
- 验收：标准答案、总体规则、评分点合计全部校验后才能发布不可变答案修订。

### AEG-047 批改绑定题目与答案修订
- 类型：Feature
- 优先级：P0
- 状态：Done
- 验收：创建批改批次时锁定 revision map；新 GradingItem 保存 question_id 和 answer_revision_id，多区域题目只生成一个评分项。

### AEG-048 E2E、回滚和历史兼容验收
- 类型：Verification
- 优先级：P0
- 状态：Done
- 验收：迁移升降级与旧数据回填通过；后端 118 passed；前端 lint/build 通过；动态 Playwright 2 passed。

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
- 状态：Done
- 所属周期：周期 0/1 验收补齐
- 目标：验证 Docker Compose 全量构建、后端、前端、数据库、Redis 和 worker 在容器环境中完整运行。
- 验证：以 staging 为准。`服务器部署/deploy-staging.sh <sha> build` 完成镜像构建，`app` 阶段启动全栈；`/api/v1/utils/health/ready` 校验数据库、Redis 和存储；worker 容器实际承载识别与批改批次。
- 备注：验收对象是 `服务器部署/compose.staging.yml`，不是本地 `compose.yml` + `compose.override.yml`。后者会发布开发端口并启动本地 Traefik，仍未做过一次完整构建验收；生产与试运行部署必须显式指定 Compose 文件。
- 验收标准：
  - Compose 可以启动前端、后端、PostgreSQL、Redis、Worker。已完成（staging）。
  - 后端 health check 和 OpenAPI 可访问。已完成。
  - 前端登录页可访问并能登录管理员。已完成。
  - Worker 可以将任务推进到完成态。已完成。

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
- 进展：已新增软质量门禁，预处理结果输出 `quality_status=pass|review` 和 `quality_warnings[]`；模板卷/答案卷保存到 `ExamDocument.preprocessing_*`，学生答卷保存到配准 metadata；前端已显示质量分、中文 warning、原图保留状态、页面策略和总耗时。
- 验证：扫描专项测试 12 passed；考试 API 44 passed；全量后端 125 passed；真实 `material/2.jpg` API 上传与 Playwright 页面展示均已通过。
- 验收标准：
  - 预处理结果必须带结构化质量状态和 warnings。已完成第一版。
  - 模糊、低置信度中缝、半页 fallback、页面比例异常、边缘疑似裁切必须能触发 review。已完成第一版。
  - 前端能显示 scan quality 和 warning。已完成。
  - review 结果进入 OCR/判分前必须可被教师确认。待完成。
  - 真实失败样例能沉淀为回归记录。已完成首个双页真实样例，后续继续扩展样本集。

### AEG-033 扫描引擎 V2 独立服务与可插拔架构

- 类型：Architecture
- 优先级：P0
- 状态：In Progress
- 所属周期：周期 3 前置 / 扫描稳定性阶段
- 目标：停止继续堆 OpenCV 补丁，建立可替换扫描引擎边界，支持后续 Paddle 文档预处理、页面 polygon 分割模型或移动端扫描 SDK 接入。
- 进展：已升级为 `SCAN_ENGINE=opencv_v1|scan_http|hybrid_v2`。`hybrid_v2` 先做 OpenCV 页面候选与独立 Homography，歧义时调用 Gemini 3.5 Flash 页面 polygon 并做几何校验/反馈重试，再逐页调用 Paddle DocPreprocessor 做方向与 UVDoc 展开；内部 HTTP 显式禁用系统代理。真实双页样例发现 UVDoc 输出清晰度损失约一半，现已通过 72% 清晰度保留门槛拒绝退化结果，并回退到 Homography。
- 决策：OpenCV v1 保留为 baseline/fallback；模型能力先复用现有 `ocr-service` 容器，避免重复构建 Paddle 镜像。后续负载上来后再拆独立服务。
- 验收标准：
  - 默认 `hybrid_v2` 不破坏现有手机照片转 PDF 流程，并保留 `opencv_v1` 回退。已完成。
  - `scan_http` 能通过 HTTP 返回页面图、质量状态和 split metadata。已完成 fake 回归。
  - `ocr-service` 能提供 `/ocr` 和 `/preprocess`。已完成 Docker 实机验证。
  - 真实 Paddle 文档预处理对双页图片必须逐页调用。已在 `material/2.jpg` 完成验证。
  - 页面 polygon 模型输出必须经过页数、覆盖率、中心间距、凸性和重叠率门控。已完成。

### AEG-034 题目区域自动候选分割

- 类型：Feature
- 优先级：P0
- 状态：In Progress
- 所属周期：周期 2 / AI 一键建立试卷模板
- 目标：在空白试卷页面上自动给出题目区域候选框，减少教师手工框选成本，但正式 `ExamRegion` 仍必须由教师确认后保存。
- 进展：已新增 `layout_projection_v0` 后端候选分割服务和只读接口 `GET /api/v1/exams/{exam_id}/files/{document_id}/region-candidates`；候选结果包含归一化坐标、置信度、标签和 engine；接口不写入正式题区。标定页已接入 Detect regions，候选框以虚线草稿显示，教师点击候选后仍需 Save Region 才会写入正式题区。已新增真实样本评估脚本和报告，7 个英语/物理单页样本结果为 `0 pass / 1 review / 6 fail`。
- 决策：当前阶段只做候选草稿，不做盲自动落库。`layout_projection_v0` 只能保留为 fallback；生产级准确切题应结合 OCR layout、题号 anchor 或页面区域分割模型，而不是继续堆 OpenCV 特例补丁。
- 验证：`pytest tests/api/routes/test_exams.py::test_read_exam_region_candidates -q` 已通过；`uv run ruff check app/models.py app/services/question_segmentation.py app/api/routes/exams.py tests/api/routes/test_exams.py` 已通过；`PYTHONPATH=backend python3 scripts/smoke-openapi.py` 已通过，23 paths；`bash scripts/tests-start.sh` 已通过，99 passed，coverage 88%；`npm run --workspace frontend lint` 和 `npm run --workspace frontend build` 已通过；`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/snap/bin/chromium npx playwright test tests/exams.spec.ts -g "suggested regions" --project=chromium --reporter=line` 已通过，2 passed；`PYTHONPATH=backend python3 scripts/evaluate_question_segmentation.py` 已生成评估报告。
- 验收标准：
  - 空白卷页面能返回稳定的候选题区列表。已完成第一版。
  - 候选题区不得自动创建或覆盖正式 `ExamRegion`。已完成。
  - OpenAPI smoke 覆盖候选接口。已完成。
  - 标定页能将候选框作为草稿导入，并由教师确认后保存。已完成第一版。
  - 在真实物理卷、英语卷等样本上形成候选质量评估和失败样例集。已完成第一版。
  - 基于 OCR layout 和题号 anchor 生成下一版候选框。待完成。

### AEG-035 OCR layout + 题号 anchor 题目候选分割

- 类型：Feature
- 优先级：P0
- 状态：In Progress
- 所属周期：周期 2 / AI 一键建立试卷模板
- 目标：在 `layout_projection_v0` 真实样本失败后，新增基于 OCR 文本框、题号 anchor、栏边界和纵向空白带的 `layout_ocr_anchor_v1`，生成更接近真实题目边界的候选框。
- 背景：`docs/question-segmentation-evaluation.md` 显示当前投影算法在 7 个真实单页样本上 `0 pass / 1 review / 6 fail`，主要是整页误框。继续调 OpenCV 膨胀参数收益有限。
- 进展：已扩展 `ocr-service /ocr`，返回 `raw.lines[]` 文本、置信度、box 和 polygon；后端新增 `layout_ocr_anchor_v1`，候选接口支持 `engine=layout_ocr_anchor_v1`；标定页已可在 Projection / OCR anchor 间切换。第一版真实样本评估 `3 pass / 3 review / 1 fail`，见 `docs/question-segmentation-ocr-anchor-evaluation.md`。
- 设计方向：
  - OCR 层先复用 `ocr-service`，优先获取文本框和文本行，而不是只取 plain text。
  - 题号 anchor 支持中文/英文/数字题号形态，例如 `1.`、`1、`、`一、`、`第1题`。
  - 候选框由相邻题号 anchor 的 y 区间、同栏边界和页面空白带共同约束。
  - 输出仍是草稿候选，不自动落库，继续由教师确认保存。
- 当前问题：
  - 写作页/大答题区没有题号 anchor 时会返回 0 个候选。
  - 物理页可能把小题号、步骤编号或选项编号误当题号，导致过切。
  - 当前前端默认仍是 Projection，OCR anchor 需要教师手动选择；后续应在 OCR 服务可用时推荐 OCR anchor。
- 验收标准：
  - 至少覆盖 `docs/question-segmentation-evaluation.md` 中的英语/物理样本。已完成第一版。
  - 相比 `layout_projection_v0`，真实多题页面不再出现整页单候选作为主要输出。已完成第一版。
  - 生成可复现评估报告，记录 pass/review/fail 和失败样例。已完成第一版。
  - 标定页可选择 `layout_ocr_anchor_v1` 候选结果，教师确认后保存正式题区。已完成第一版。
  - 将 OCR anchor 评估从 `3 pass / 3 review / 1 fail` 提升到无 fail。待完成。

### AEG-036 标准答案数据模型与 API

- 类型：Feature
- 优先级：P0
- 状态：Done
- 所属周期：周期 4 / 标准答案与评分闭环
- 目标：新增一等标准答案模型，按已确认 `ExamRegion` 保存参考答案、满分和评分规则，为后续评分草稿提供依据。
- 验证：已提交 `1f3951b Add standard answer API`；`pytest tests/api/routes/test_exams.py -q` 通过，`PYTHONPATH=backend python3 scripts/smoke-openapi.py` 通过，前端 OpenAPI client 已同步生成。
- 计划文档：`docs/template-answer-grading-plan.md`
- 设计方向：
  - 第一版标准答案必须绑定 `region_type=question` 的 `ExamRegion`，不支持未标定题区的独立题号答案。
  - 如果题干区和答题区后续需要分开建模，先新增 `scoring_unit`，不在第一版混用 `answer_area/header/other`。
  - 每个题区最多一条标准答案，避免同一题出现多个评分依据。
  - 字段至少覆盖参考答案、满分、评分规则文本、评分点 JSON、状态和更新时间。
  - `scoring_points` 第一版最小结构固定为 `{id, description, points, required}`。
  - API 归属在考试下，沿用现有考试权限边界。
- 验收标准：
  - 后端存在标准答案 SQLModel、Alembic migration 和 CRUD API。已完成。
  - 可按考试读取全部标准答案，并可按题区创建/更新/删除。已完成。
  - 跨用户不能读取或修改他人考试的标准答案。已完成。
  - 删除题区或考试时，相关标准答案不会留下孤立脏数据。已完成。

### AEG-037 标准答案工作台

- 类型：Feature
- 优先级：P0
- 状态：Done
- 所属周期：周期 4 / 标准答案与评分闭环
- 目标：新增教师可用的标准答案工作台，按模板题区录入答案、满分和评分规则。
- 验证：新增 `/exams/$examId/answers`；`npm run --workspace frontend lint`、`npm run --workspace frontend build` 通过；`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/snap/bin/chromium ../node_modules/.bin/playwright test exams.spec.ts -g "Can prepare a standard answer" --project chromium` 通过。
- 计划文档：`docs/template-answer-grading-plan.md`
- 设计方向：
  - 入口放在考试列表或考试操作区，与 Marking、Submissions 并列。
  - 左侧展示已确认题区列表和答案完成状态。
  - 右侧展示空白卷页面预览、选中题区高亮、参考答案、满分和评分规则编辑区。
  - 未标定题区时提示先进入标定页。
- 验收标准：
  - 教师可以逐题保存标准答案、满分和评分规则。已完成。
  - 已保存、未保存、草稿状态在题区列表中清晰可见。已完成。
  - 切换题区不会丢失已保存内容。已完成。
  - 前端 OpenAPI client 与类型已同步生成。已完成。

### AEG-038 基于标准答案的评分草稿接入

- 类型：Feature
- 优先级：P0
- 状态：In Progress
- 所属周期：周期 4 / 标准答案与评分闭环
- 目标：扩展学生答卷处理任务，把题区 OCR 结果、裁剪图和标准答案结合，生成教师可复核的建议分和评语。
- 进展：后端评分草稿字段、migration 和 Worker 第一版已落地；有 ready 标准答案且 OCR 成功时写入建议分、建议评语、置信度和 reasons，无 ready 标准答案时写 `skipped_missing_answer`；标准答案更新会把旧草稿标记为 `stale`。复核页已展示标准答案和评分草稿，并支持 Apply suggestion 填入最终表单，教师仍需保存批注。
- 计划文档：`docs/template-answer-grading-plan.md`
- 设计方向：
  - 第一版以主观题评分草稿为主，不自动定稿。
  - 有标准答案时，Worker 生成建议分、建议评语和扣分点；建议结果写入 `suggested_score`、`suggested_comment`、`grading_confidence`、`grading_reasons` 和 `grading_status`，不直接覆盖教师最终 `score/comment/status`。
  - 无标准答案时，Worker 只生成 OCR draft，并在任务输出和复核页提示待补标准答案。
  - `ocr_status != succeeded` 或 `ocr_confidence < 0.90` 时，第一版只标记 `needs_review`，Kimi/视觉模型 fallback 后置。
  - 评分草稿记录 `answer_key_updated_at`；标准答案更新后，旧草稿标记为 `stale` 并要求重新处理。
  - 评分结果必须保留题区裁剪图、OCR 文本和标准答案作为证据。
- 验收标准：
  - 复核页能显示标准答案、评分规则、OCR draft、建议分和建议评语。已完成。
  - 教师保存后仍使用现有最终 `score/comment/status` 字段作为确认结果。已完成。
  - 处理任务输出能区分 `grading=succeeded|skipped_missing_answer|needs_review|stale`。部分完成：处理任务输出覆盖前三类，标准答案更新会把旧批注标为 `stale`。
  - 后端测试覆盖有标准答案、无标准答案、OCR 失败三种路径。部分完成：已覆盖有 ready 标准答案、无 ready 标准答案和 stale；OCR 失败/低置信度路径待补。

### AEG-039 答案卷 OCR / AI 生成标准答案草稿

- 类型：Research
- 优先级：P1
- 状态：Backlog
- 所属周期：周期 4 后续增强
- 目标：在手动标准答案工作台稳定后，支持上传答案卷或解析卷，自动提取标准答案草稿，并由教师确认。
- 计划文档：`docs/template-answer-grading-plan.md`
- 决策：不作为第一版阻塞项。第一版先用教师手动录入，避免答案解析质量影响评分闭环。
- 验收标准：
  - 支持 `answer_key` 文件 OCR。
  - 能把答案草稿映射到已确认 `ExamRegion`。
  - 所有 AI/OCR 提取答案必须由教师确认后才能进入评分。

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

## 周期 8：多租户商业化与工程基建

本节补记 2026-07-25（`a61a5ff`）与 2026-08-07（`0884bfd`）两次提交带来的能力。这两次提交合计约 28k 行，此前没有对应 issue 记录，状态依据代码、迁移和测试实际内容回填。

### AEG-050 多租户角色体系与数据隔离

- 类型：Feature
- 优先级：P0
- 状态：Done
- 所属周期：周期 8
- 目标：把单用户工具升级为学校维度的多租户 SaaS。
- 验收标准：
  - 平台侧（`platform_superuser`/`platform_admin`/`platform_support`）与学校侧（`school_owner`/`school_admin`/`teacher`/`student`）共 7 档角色。已完成（`platform_admin` 由迁移 `8f31c0d4a7b2` 补入）。
  - `Organization` 承载学校，`User`/`Exam`/`ClassGroup` 带 `org_id`，隔离逻辑集中在 `app/services/org_scope.py`，不可见统一 404。已完成。
  - 学校服务状态 `active`/`read_only`/`frozen`/`deleting`：`read_only` 的非 GET 返回 423，`frozen`/`deleting` 返回 403。已完成（迁移 `a8c1e4f7b902`）。
  - 教师间考试互见是学校级开关，默认关闭。已完成。
  - 测试覆盖跨校读写边界。已完成（`test_org_isolation.py`）。

### AEG-051 SaaS 计费：答卷额度与 Token 积分双轨

- 类型：Feature
- 优先级：P0
- 状态：Done
- 所属周期：周期 8
- 目标：让批改消耗可计量、可预扣、可结算，并把「卖给学校的额度」与「平台上游成本」分开。
- 决策：见 `docs/decision-log.md` D-022。
- 验收标准：
  - 答卷额度：`AnswerQuotaGrant`/`Reservation`/`Allocation` + `BillableAnswerSheet`，`(org_id, exam_id, billing_identity)` 唯一保证同一份答卷只计一次费，FIFO 消耗。已完成（迁移 `c0e4a7b9d215`）。
  - Token 积分：`CreditGrant`/`Reservation`/`LedgerEntry` + `ModelUsageEvent` + `BillingRateVersion` 费率版本。已完成（迁移 `c2e4f6a8b0d1`）。
  - 批改批次创建时预扣，额度不足返回 402，积分不足进入 `awaiting_credits`；worker 结束后结算。已完成。
  - 失败批次可重试预留（迁移 `d1f5b8c2e904` 移除 `grading_run_id` 唯一约束）。已完成。
  - `python -m app.maintenance reconcile-billing` 释放异常退出遗留的预占。已完成，需按运行手册每 5 分钟调度。
  - 学校用量风控 `OrganizationUsagePolicy`（每分钟调用、并发任务、单任务与日/月上限、`risk_state`）。已完成。
  - 测试覆盖预留/结算/释放与重复计费。已完成（`test_billing.py` 9 项）。

### AEG-052 模型渠道控制面与动态路由

- 类型：Feature / Architecture
- 优先级：P0
- 状态：Done
- 所属周期：周期 8
- 目标：把模型供应从环境变量升级为可运营的控制面，支持多渠道、灰度、熔断和对账。
- 验收标准：
  - `ProviderChannel` + AES-GCM 加密凭证（AAD 绑定 channel_id）；私网地址需 allowlist，公网强制 HTTPS。已完成。
  - `ProviderModelMapping` canonical → upstream 映射与模型发现。已完成。
  - `ModelRoutePolicy`/`ModelRouteVersion`/`ModelRouteVersionTarget`：发布即冻结渠道与费率快照，可回滚。已完成（迁移 `d5f7a9c1e3b6`）。
  - 健康与熔断：连续失败置 `circuit_open_until`，成功即重置。已完成。
  - 并发与限流：Redis ZSET 分全局/学校/渠道三级槽位并限制每分钟调用；计费门禁开启时 Redis 故障 fail-closed。已完成。
  - 上游对账：`ProviderReconciliationBatch`/`Item`，支持 New API 同步比对 token 与成本。已完成（迁移 `a1c3e5f7b9d2`、`b2d4f6a8c0e1`）。
  - 用途边界：纯视觉与推理模型不得混用（`model_purpose_policy.py`，迁移 `e9a1c3d5f7b8`）。已完成。
  - 测试覆盖路由解析、凭证加密、并发槽与对账。已完成（`test_provider_channels.py` 12、`test_provider_gateway.py` 5、`test_provider_security.py` 5、`test_model_concurrency.py` 4、`test_new_api_billing.py` 2）。

### AEG-053 公开模型目录与学校选型

- 类型：Feature
- 优先级：P0
- 状态：Done
- 所属周期：周期 8
- 目标：学校能自选模型方案，但看不到真实供应链。
- 决策：见 `docs/decision-log.md` D-023。
- 验收标准：
  - `PlatformModelOffering` 公开目录 + `OrganizationModelSelection` 按 vision / reference_answer / grading 三个 scope 选型。已完成（迁移 `d4f6a8b0c2e1`）。
  - 学校侧响应只含 `display_name`、用途和说明，不含渠道、上游模型名与成本。已完成。
  - offering 发布前校验渠道映射、结构化输出能力与对应用途路由版本已发布。已完成。
  - 遗留跨用途配置已清理（迁移 `f0b2d4e6a8c1`）。已完成。
  - 测试覆盖发布校验与学校可见字段。已完成（`test_model_offerings.py` 5 项）。

### AEG-054 商业化订单与支付闭环

- 类型：Feature
- 优先级：P0
- 状态：In Progress
- 所属周期：周期 8
- 目标：学校可购买年度套餐与答卷加量包，平台可完成收款、履约、开票和退款。
- 进展：后端闭环与平台侧工作台已完成，学校端自助下单界面尚未实现。
- 验收标准：
  - 商品版本化：`PlanVersion`/`AddonSku` 先草稿后上架，历史订单保存购买时快照。已完成。
  - 订单状态机 `pending_payment → paid → fulfilled`，可至 `refunded`。已完成（迁移 `a2c4e6f8b0d3`）。
  - 幂等：订单 `idempotency_key` 唯一、支付 `provider_transaction_id` 唯一、微信回调按 `event_id` 去重、支付与履约在 advisory lock + `FOR UPDATE` 内串行。已完成（迁移 `c4e6f8a0b2d5`）。
  - 履约：套餐建合同并顺延续费（`ends_at = max(paid_at, 上一份 ends_at) + validity_days`），套餐与加量包都发放答卷额度并关联订单。已完成（迁移 `b3d5f7a9c1e4`）。
  - 一张订单最多一张发票申请与一笔退款申请；自动退款仅整单且额度未预留未消费，退款后恢复上一份仍有效合同。已完成。
  - 平台侧「订单与财务」工作台：商品维护、订单、银行转账确认、发票与退款审核。已完成（`platform_.commerce` + `CommerceOperations.tsx`）。
  - 学校端自助下单与微信扫码支付界面。**待完成**：`CommerceService.createOrder`、`payOrderWithWechat` 已生成但前端未调用。
  - 微信退款真实接口调用与对账口径。**待完成**：当前退款只推进数据库状态机。
  - 测试覆盖下单、支付、履约与退款。已完成（`test_commerce.py` 8 项）。

### AEG-055 公开注册与试用开通

- 类型：Feature
- 优先级：P1
- 状态：Done（默认关闭）
- 所属周期：周期 8
- 目标：学校可自助注册试用，不再完全依赖人工建租户。
- 验收标准：
  - `PendingOrganizationSignup` + 邮箱验证 + Cloudflare Turnstile + Redis 速率限制。已完成（迁移 `c3e5f7a9b1d2`）。
  - 验证通过后原子创建学校、`school_owner`、30 天试用合同、200 份答卷额度与保守用量策略。已完成。
  - 缺少匹配 `PUBLIC_SIGNUP_TRIAL_RATE_VERSION` 的费率版本时返回 503 且不创建租户。已完成。
  - 生产默认 `PUBLIC_SIGNUP_ENABLED=false`，启用需配置 SMTP 与 Turnstile，且 `VITE_TURNSTILE_SITE_KEY` 是构建期参数。已完成并写入 `服务器部署/新服务器登录说明.md`。
  - 测试覆盖注册、重发、验证与限流。已完成（`test_public_signup.py` 4 项 + Playwright `sign-up.spec.ts`）。

### AEG-056 成绩发布与学生可见性

- 类型：Feature
- 优先级：P0
- 状态：Done
- 所属周期：周期 6 / 周期 8
- 目标：教师确认后再向学生发布成绩，学生看到的是不可变快照而不是实时批注。
- 决策：见 `docs/decision-log.md` D-024。
- 验收标准：
  - `ScoreRelease`/`ScoreReleaseItem` 版本化，`(exam_id, version)` 唯一，旧版本置 `superseded`。已完成（迁移 `b9d2f5a8c013`）。
  - 发布门槛：无待复核题，且每份答卷已评题数不少于已确认题数；考试行 `FOR UPDATE` 串行化。已完成。
  - 快照优先取教师人工结果，其次取建议结果。已完成。
  - 学生端 `/students/me/*` 只能看到已发布考试与快照。已完成。
  - 测试覆盖发布门槛与学生可见范围。已完成（`test_score_releases.py` 2 项）。

### AEG-057 生产基础设施硬化

- 类型：Hardening
- 优先级：P0
- 状态：In Progress
- 所属周期：周期 7 / 周期 8
- 目标：让服务具备可部署、可探活、可限流、可恢复的生产属性。
- 进展：代码能力已具备，staging 尚未切换到高可用与对象存储。
- 验收标准：
  - 对象存储抽象 `STORAGE_BACKEND=local|oss` + 私有 OSS + 幂等迁移脚本。已完成代码，**尚未在 staging 执行迁移**。
  - 存活与就绪探针 `/api/v1/utils/health/live|ready`（ready 校验 DB、Redis、存储）。已完成。
  - 学校级任务租约 `OrganizationJobLease`（`(task_type, resource_id)` 唯一，TTL 5 分钟 + 60 秒心跳），防止跨 worker 重复执行与超并发。已完成（迁移 `f7b9d1e3a5c7`）。
  - 事务 outbox：`OutboxEvent` 与 `dispatch-outbox` 命令。已完成写入，**dispatcher 仅记录日志并标记完成，未对接邮件或财务系统**。
  - 生产配置校验（HTTPS、OSS 必填、密钥长度、微信配置完整性）。已完成（`test_config_production.py` 3 项）。
  - Web/API 与 worker 多实例、RDS 与 Redis 高可用。**待完成**，见 `docs/production-operations.md` 生产基线。

### AEG-058 Staging 试运行部署

- 类型：Verification / Ops
- 优先级：P0
- 状态：Done
- 所属周期：周期 7
- 目标：在独立服务器上跑起可对外访问的试运行环境，且不影响服务器上既有服务。
- 验收标准：
  - 独立 `compose.staging.yml` + `dianfan-staging` project + 独立网络/卷，不复用既有 AISubAPI 的数据库与 Redis。已完成。
  - 发布目录约定 `/opt/dianfan-grading/{shared,releases/<sha>,current}`，分 `config`/`infra`/`build`/`app` 阶段执行。已完成。
  - 环境文件由 `generate-staging-env.sh` 随机生成密钥，不复制开发 `.env`。已完成。
  - 公网入口 `https://app.dianfandig.com`，由服务器既有 Nginx 反代，不启动项目自带 Traefik。已完成。
  - 渠道凭据可用 `sanitize-staging.sql` 清理。已完成。
  - SSH 收敛到 `22022` + fail2ban，公网 `22` 关闭。已完成。
  - 合作伙伴运维账号 `dianfan-ops` 最小权限（仅 SSH 登录，无 sudo/Docker/数据库）。已完成。

### AEG-059 CI 流水线

- 类型：Task
- 优先级：P0
- 状态：Done
- 所属周期：周期 8
- 目标：仓库过去没有任何 CI（`.github/` 只有 dependabot 与 labeler），补上可阻断回归的自动检查。
- 决策：见 `docs/decision-log.md` D-025。
- 验证：本地以 Python 3.13.15 + PostgreSQL 16 + Redis 7 实测：后端 `338 passed, 1 skipped`、覆盖率 67%；`alembic upgrade head` 到唯一 head `c3e5f7a9b1d2`；OpenAPI 冒烟 25 paths；前端 `tsc`/`biome ci`/`vite build` 通过；`actionlint` 与 `zizmor` 无告警。
- 验收标准：
  - `lint-backend`：`ruff check` + `ruff format --check`（`app` 与 `tests`）。已完成。
  - `test-backend`：postgres + redis service 容器、迁移、pytest + coverage、OpenAPI 冒烟、覆盖率 artifact。已完成。
  - `test-frontend`：`npm ci` + `biome ci` + `tsc` + `vite build`。已完成。
  - `lint-workflows`：`zizmor` 审计。已完成。
  - Actions 全部按 commit SHA 固定，`persist-credentials: false`，workflow 级最小权限。已完成。
  - 分支保护把上述检查设为必需。**受计划限制阻塞**，见下方 AEG-064。

### AEG-064 让 CI 成为阻断门禁（分支保护）

- 类型：Ops
- 优先级：P1
- 状态：Blocked
- 所属周期：周期 8
- 背景：CI 已全绿，但目前只是提示，不能阻止红灯代码合入 `main`。
- 阻塞原因：GitHub 只在 Pro/Team/Enterprise 计划上为**私有**仓库提供分支保护与 rulesets。本仓库是个人账号下的私有仓库且为免费计划，API 直接返回 `403 Upgrade to GitHub Pro or make this repository public`。这不是权限配置问题，任何 token 都绕不过。
- 三条出路：
  1. **升级 GitHub Pro**（个人账号，约 $4/月）。升级后执行 `GH_TOKEN=<admin-token> ./scripts/setup-branch-protection.sh` 即可，无需改代码。
  2. **把仓库转到组织账号**并使用 Team 计划，适合后续多人协作时一并处理。
  3. **把仓库改为 public** 可免费获得该能力，但**不可接受**：历史提交中的 `.env` 带有真实的 `SECRET_KEY`、`FIRST_SUPERUSER_PASSWORD` 和 `POSTGRES_PASSWORD`（自 2026-06-30 起存在于 4 个提交中），公开后无法撤回。若无论如何要公开，必须先轮换这三项并重写历史。
- 过渡期做法：合并前人工确认 PR 上四个检查为绿；`scripts/setup-branch-protection.sh --show` 可随时查看当前状态。
- 验收标准：
  - `main` 的分支保护要求 `lint-backend`、`test-backend`、`test-frontend`、`zizmor` 四个检查通过，且要求分支与 `main` 保持最新。
  - 检查名以 `--show` 输出的实际 check-run 名为准（首次在 `main` 上跑过 CI 后再核对）。
  - 禁止 force push 与删除分支。
  - 多人协作后打开 `REQUIRE_REVIEWS=1` 与 `ENFORCE_ADMINS=1`。

### AEG-060 mypy / ty 类型债清理

- 类型：Hardening
- 优先级：P2
- 状态：Backlog
- 所属周期：周期 8 后续
- 背景：`backend/scripts/lint.sh` 和 `.pre-commit-config.yaml` 都包含 mypy 与 ty，但实际 strict 模式下有 588 / 489 条告警，因此长期未被执行，也无法进 CI。
- 目标：把类型检查恢复成可阻断门禁。
- 设计方向：
  - 绝大多数告警来自 SQLModel/SQLAlchemy 表达式（`col.in_`、`order_by`、`join` 条件、`datetime` 与 `None` 比较），应优先统一用 `col()`/`cast()` 包装或补类型标注，而不是逐条 `# type: ignore`。
  - 可先对 `app/services/billing.py`、`app/api/routes/grading.py` 等高价值文件收敛，再逐步扩大。
- 验收标准：
  - 明确一份「必须干净」的文件清单并在 CI 上强制。
  - 剩余误报有集中记录的抑制策略，不散落在业务代码里。

### AEG-061 E2E 进入 CI

- 类型：Verification
- 优先级：P1
- 状态：Backlog
- 所属周期：周期 8 后续
- 背景：24 个 Playwright spec 中，live 用例需要真实模型 Key、Node 参考服务和系统 Chromium，无法直接在 CI 运行；用 `page.route` 打桩的用例只需要前端。
- 目标：把不依赖外部模型的 E2E 纳入 CI。
- 设计方向：
  - 先按依赖给 spec 分层（纯前端打桩 / 需后端 / 需模型 Key），live 用例用 `test.skip` 或 grep 标签排除。
  - 需后端的用例可在 CI 用 compose 起 db + redis + backend，再跑 Playwright；模型调用仍需打桩。
- 验收标准：
  - CI 能稳定跑通打桩层 E2E，无 flaky。
  - live 用例保留本地/手动触发入口，并在文档中写清所需环境变量。

### AEG-062 商业化闭环收尾

- 类型：Feature
- 优先级：P1
- 状态：Ready
- 所属周期：周期 8 后续
- 目标：补齐学校自助购买链路与履约副作用，让商业化不依赖平台人工代操作。
- 验收标准：
  - 学校端下单页面：选择套餐/加量包、生成订单、展示微信扫码、轮询支付结果、失败可重试。
  - `OutboxEvent` dispatcher 真正投递（至少履约与退款成功通知邮件），失败可重试并保留 `last_error`。
  - 微信退款真实接口调用与每日对账口径，按 `docs/production-operations.md` 的商业运营闭环执行。

## 周期 9：学生端终身错题本

方案文档：`docs/student-wrongbook-plan.md`。以下条目是该方案的执行拆解，阶段 A 之外的条目在形态与合规路径确认前不要开工。

### AEG-065 知识点体系与 AI 自动打标

- 类型：Feature
- 优先级：P0
- 状态：Done
- 所属周期：周期 9 阶段 A
- 背景：`ExamQuestion.knowledge_point` 是自由文本且上限 100 字符，AI 识别阶段完全不写该字段（`question_answer_workflow.py` 创建识别项时不填），只能靠教师手打，实际基本为空。没有知识点就没有失分归因聚合、掌握度和复习推荐。
- 目标：建立知识点树，并让识别阶段自动打标、教师确认时校正。
- 验收标准：
  - 新增 `KnowledgePoint` 表（学科、学段、编码、名称、父节点、别名），第一版覆盖初中物理与数学。
  - 题目识别产出「知识点 + 置信度」，低置信度不写入、留给教师。
  - 教师在确认题目界面可校正知识点，校正结果可导出用于评估 AI 打标准确率。
  - 知识点从自由文本迁移为受控引用，保留旧自由文本作为回填来源。

### AEG-066 学生逐题详情与失分原因

- 类型：Feature
- 优先级：P0
- 状态：Done
- 所属周期：周期 9 阶段 A
- 背景：学生端只有两个接口，报告只返回 `{label, score, max_score, comment}`，`suggested_comment` 被写死为 `None`、`score_source` 写死为 `"final"`；裁切图端点的 `can_see_exam` 不包含学生角色。而判分模型的评分点级证据 `{"point","matched","points","reason"}` 已经写进 `SubmissionAnnotation.grading_evidence`，只是没有暴露。注意 `grading_reasons` 装的是复核门禁信号（`low_confidence`/`unreadable`/`answer_count_mismatch`/`model_failure`/`unconfirmed_answer_evidence`），不是失分原因，**不得展示给学生**。
- 目标：让学生看到「题干、标准答案、我的作答、为什么扣分、我的手写原件」。
- 验收标准：
  - 新增学生逐题详情端点，只在成绩已发布后可见。
  - 失分原因取 `grading_evidence` 中 `matched=false` 的评分点，**不引入额外模型调用**。
  - 裁切图提供 learner 作用域的受保护访问，不复用教师端 `can_see_exam` 判定。
  - 教师自由文本评语在给学生前有脱敏或长度约束策略。
  - 前端 `my.exams_.$examId` 接通图像与失分原因（`WrongQuestionsSection` 已具备渲染能力）。

### AEG-072 发布过成绩的考试无法删除

- 类型：Bug
- 优先级：P1
- 状态：Done
- 所属周期：周期 9 阶段 A 附带
- 症状：一场考试只要发布过成绩，`DELETE /exams/{exam_id}` 就返回 500。
- 根因：`ScoreReleaseItem.submission_id` 是 `ondelete="RESTRICT"`，而 `Exam` 只对 documents/regions/submissions 建了 ORM 级联，删考试时 SQLAlchemy 先删答卷，被数据库的 RESTRICT 拒绝。DB 层面 `ScoreRelease.exam_id` 本来就是 CASCADE，属于 ORM 删除顺序问题。
- 修复：给 `Exam` 补 `score_releases` 级联关系、给 `ScoreRelease` 补 `items` 级联关系，删考试时先清成绩发布快照。单份答卷仍受 RESTRICT 保护，不会把已发布成绩删出空洞。
- 回归：`test_wrongbook_survives_exam_deletion` 同时覆盖删除成功与错题本留存。

### AEG-067 发布即快照：错题条目独立留存

- 类型：Architecture
- 优先级：P0
- 状态：Done
- 所属周期：周期 9 阶段 A
- 背景：`Exam` 删除会级联清空 documents / regions / submissions / questions / annotations / score releases；裁切图依赖 `ProcessingTask.output_ref` 或按 `ExamRegion` 实时重裁。错题本若做成教师端数据的视图，老师删一场考试，学生的「终身」错题会静默消失。
- 目标：错题本成为独立留存实体，来源可消失而错题本完整。
- 验收标准：
  - 新增 `WrongQuestionEntry`，快照题干、标准答案、评分点、学生作答、失分原因标签、教师评语、考试元数据。
  - 对 `exam_id`/`submission_id`/`annotation_id`/`question_id` 只保留 `ON DELETE SET NULL` 弱引用。
  - 裁切图在快照时复制到学习者命名空间并压缩（建议 WebP），不依赖考试与答卷生命周期。
  - 挂在成绩发布动作上异步生成；重新发布生成新条目并把旧条目标记 superseded，不原地改写。
  - 失分原因使用**有限标签集**，保证可跨考试聚合。
  - 实测单个学生年度存储量并记录，用于成本估算。

### AEG-068 终身学习者身份

- 类型：Architecture
- 优先级：P0
- 状态：Done
- 所属周期：周期 9 阶段 B
- 决策依据：D-029 学生身份走 C 端账号，与学校租户解耦。
- 背景：`Student` 是班级内实体（`UniqueConstraint(class_id, name)` 且不支持修改 `class_id`），升班等于新建档案，历史断裂；学生端兜底匹配用「当前班名 + 姓名」，旧班答卷可能查不到。同时 `get_current_user` 对每个请求执行 `assert_organization_access`，学校冻结后学生一律 403。
- 目标：身份跨班、跨学年、跨学校稳定，且不随学校租户状态失效。
- 验收标准：
  - 新增 `LearnerProfile`（锚定学生自己的登录账号，不带 org_id）与 `LearnerEnrollment`（在校经历，可多条）。已完成。
  - 转班、升学、转学通过新增 enrollment 表达，错题本连续。已完成（`test_learner_keeps_history_across_class_change`）。
  - 错题本读取只依赖 learner 身份，学校 `frozen` 不影响学生查阅历史。已完成（学生角色豁免学校服务状态门禁）。
  - 存量 `Student` 与 `{学号}@school.local` 账号有明确回填与升级路径。已完成（迁移内回填 + 首次访问自动认领孤立条目）。
  - 在校经历快照学校名与班级名，学校被删也能说清「这题是哪一年在哪个班考的」。已完成。

### AEG-069 复习闭环

- 类型：Feature
- 优先级：P1
- 状态：Backlog
- 所属周期：周期 9 阶段 C
- 目标：错题从「躺着」变成「被复习」，这是留存的真实来源。
- 验收标准：
  - 间隔重复调度（简化 SM-2，1/3/7/15/30 天），交互只问「还会不会」。
  - 考前突击清单：按学科 + 知识点错误密度 + 距上次复习时间排序，可打印 A4。
  - 相似题优先检索本校题库（`question-bank` 已跨考试），检索不到再用 LLM 生成变式题并标注「AI 生成，未经教师审核」。
  - 掌握度视图按知识点聚合，纯统计不调模型。

### AEG-070 学生端客户端形态

- 类型：Design
- 优先级：P1
- 状态：Ready
- 所属周期：周期 9 阶段 C
- 决策依据：D-028 学生端以微信小程序为主，Web 端保留。
- 待办（需要产品侧提供资产后才能开工）：
  - 微信小程序主体注册与服务类目，取得 AppID / AppSecret（工程侧无法自助完成）。
  - 微信登录：`wx.login` 换 openid/unionid，与 `LearnerProfile` 换绑，学生从此可脱离学校创建的账号。
  - 家长视角与学生视角的权限边界。
  - 视觉与 `AGENTS.md` 的小程序色板一致。
- 已就绪的前置：学生端 API 已与学校租户解耦，小程序与 Web 共用同一套 `/students/me/*` 接口。

### AEG-071 未成年人合规与数据可携带

- 类型：Compliance
- 优先级：P0
- 状态：Ready
- 所属周期：周期 9 阶段 D（但需在学生端上线前完成）
- 背景：仓库当前在未成年人同意、保留期、导出与删除方面基本空白。学生端长期留存成绩与手写影像，属于典型敏感场景。
- 验收标准：
  - 明确数据控制者与受托处理者关系，先走学校委托路径。
  - 不满十四周岁的监护人同意链路与单独处理规则。
  - 错题本导出（PDF + JSON）与删除；删除学生个人错题本不影响学校成绩档案。
  - 核实是否需要教育移动互联网应用程序备案。
  - 明确不提供「拍照搜题」，理由写入决策记录（双减意见第 15 条）。
  - 需法务确认，工程侧只负责提供能力。

### AEG-072 错题本失分点文案不说人话

- 类型：Bug
- 优先级：P1
- 状态：Backlog
- 所属周期：周期 9 阶段 B
- 背景：2026-08-13 用真实物理答卷（海口八年级期末 B 卷）本地跑完「确认题目 → 判分 → 发布成绩」后，检查学生端 `/my/wrongbook` 实际渲染的 `missed_points`，发现三处直接违反「文案说人话」。裁切图、知识点打标、按页缓存均正常，只有文案有问题。
- 具体问题：
  - `app/services/grading_rules.py` 把 Python 列表字面量写进学生可见文案：客观题失分理由渲染成「学生选择 ['A']，本评分点要求 ['B']，且包含错误选项 ['A']」，应当是「你选了 A，正确答案是 B」。
  - 评分点标题回落到内部编号：`extract_missed_points` 取 `point.id`，学生看到加粗的「p1」「p3」。评分点没有 description 时应回落到题号或「未答到的要点」，不能暴露编号。
  - `frontend/src/routes/_layout/my.wrongbook.tsx` 把「该评分点得分」当扣分展示：未命中评分点的 `points` 恒为 0，界面渲染成「-0 分」。应改为展示该评分点的满分值作为扣分，或不展示。
- 验收标准：
  - 客观题失分理由不含列表、括号等数据结构字面量。
  - 学生端不出现 `p1` 这类内部编号。
  - 未命中评分点不出现「-0 分」。

### AEG-073 客户端前处理从未真正生效，每次都静默回退服务端

- 类型：Bug
- 优先级：P1
- 状态：Done（2026-08-14 修复并实测通过）
- 所属周期：周期 9 阶段 B
- 背景：2026-08-14 合并 #24（迁移服务器端前处理至前端）后，用真实照片 `参考算法/2_试卷分析文件/material/1.jpg` 在本地跑「导入试卷 → 复核四角 → 确认四角并保存」，实测客户端 OpenCV 路径一次都没成功：命中 `upload-preprocessed` 0 次，回退 `preprocess-with-quads` 1 次，控制台报 `Client preprocessing failed, falling back to server: Error: cv.imdecode is not a function`。产物元数据 `source` 仍是 `manual_quad_document_preprocessing_v1`，即老的服务端路径。
- 根因：`frontend/public/preprocessor-worker.js` 调用了 opencv.js 不提供的 API。在真实 Worker 里运行时枚举该 worker 用到的全部 45 个 `cv.*`（WASM 就绪约 0.5 秒），只有 6 个不存在：`imdecode`、`imencode`、`IMREAD_COLOR`、`IMWRITE_JPEG_QUALITY`、`IMWRITE_PNG_COMPRESSION`（imgcodecs 模块）和 `fastNlMeansDenoisingColored`（photo 模块）。官方 opencv.js 不含这两个模块，图像编解码必须走 canvas。`preprocess()` 第一行就是 `cv.imdecode`，因此透视矫正、CLAHE 增强、去斜一行都没机会执行。
- 影响（修复前）：
  - 功能收益为零且净增开销——每个用户白下载 10.96 MB 的 `opencv.js`，再多花一次失败尝试。
  - 回退是静默的（只有一行 `console.warn`），界面结果完全正常，靠肉眼验收发现不了；必须看命中的接口或产物元数据 `source`。
  - 服务端 `upload-preprocessed` 接口（含 Gemini 转正 + PDF 打包）在此之前从未跑过真实流量。
- 修复内容（`frontend/public/preprocessor-worker.js`）：
  - 新增 `decodeToBgrMat()`：`createImageBitmap` + `OffscreenCanvas.getImageData()` → `cv.matFromImageData()` → `cvtColor(RGBA2BGR)`，与服务端 `cv2.imdecode(IMREAD_COLOR)` 的 BGR 通道序对齐。
  - `encodeJPEG()` 改用 `OffscreenCanvas.convertToBlob({ type: "image/jpeg", quality })`（quality 由服务端 0-100 口径换算为 0-1）。
  - 删除死代码 `_encodePNG()`：它同样只调用不存在的 `cv.imencode`，留着是给后人埋坑。
  - 降噪改为运行时特性检测（`denoiseSupported()`）：有 photo 模块就按服务端参数 `h=3, hColor=3, 7, 21` 跑，没有就跳过，并把结果写入 metadata `applied_denoise`。
  - `preprocess()` 与消息处理器改为异步链（canvas 编解码是异步的）。
- 同时修复的质量口径不一致（`backend/app/api/routes/exams.py`）：
  - `upload-preprocessed` 原先把 `warnings` 硬编码成 `[]`，并自造 `锐度/50` 当分数，与服务端的「1.0 − 各类告警扣分」不同量纲；同一张卷子客户端判 `pass · 100%`、服务端判 `review · 82%`，且老师看不到裁切告警。
  - 现改为调用服务端同一个 `build_quality_warnings()`（原图算 `low_sharpness`，页面算 `content_near_*_edge` 与 `page_aspect_outlier`），扣分表抽成共用的 `score_quality_warnings()`，避免两处各维护一张表。为算 `low_sharpness` 需把原图读出来解一次码，相比两次 Gemini 转正（约 10 秒）可忽略。
  - 另修正一处术语泄漏：原先把内部值 `pass` 写进 `preprocessing_status`，而前端只认 `ready/review/failed`，界面上会出现生硬的「pass」徽章。现按服务端同一规则取 `ready/review`。
  - 实测同一张照片：客户端由「pass · 100%、无告警」变为「需要复核 · 97%」并正常显示「顶部内容靠近裁切边缘」。
- 实测结果（同一张真实照片，双页摊开）：命中 `upload-preprocessed` 1 次 HTTP 200，回退 0 次，无告警；产物 `source=client_preprocessed_upload_v1`、`engine=client_opencvjs_upload_v1`、`client-scanned.pdf` 268 KB / 2 页。渲染 PDF 肉眼核对：透视矫正正确、双页拆分正确、色彩正常（无通道错位）。服务端仍按设计承担精修去斜与两页 Gemini 转正（6.1 s + 3.6 s，占接口 11.2 s 的大部分）。
- 遗留差异（未修，需单独决策）：
  - 客户端跳过了非局部均值降噪（opencv.js 无 photo 模块），产物比服务端路径略噪。h=3 属轻度降噪，且 JPEG q=92 本身有平滑作用，暂判为可接受；若要严格一致，只能在服务端补做或换带 photo 模块的 opencv.js 构建。
  - 回退仍然完全静默。客户端路径失败时应上报一次（埋点或后端日志），否则功能再坏一次同样没人知道——这次能发现纯属专门去查了命中的接口。
  - `upload-preprocessed` 仍无后端测试覆盖，回归只靠上面那条 Playwright 实况用例（需真实模型 Key）。
- 回归用例：`frontend/tests/client-preprocessing-live.spec.ts`。会自建学校/考试、上传真实照片、走完整界面流程，断言必须命中 `upload-preprocessed`、不得出现回退告警、且元数据 `source == client_preprocessed_upload_v1`。需要真实模型 Key（Gemini 转正），CI 不跑 Playwright。
- 本地环境坑：#24 新增了 `scanic` 依赖，合并前启动的 vite 进程其 `.vite/deps` 里没有它，动态 import 404 会让四角编辑器整体挂不起来（对话框显示「原图读取或后端稳定算法检测框加载失败」）。需重启开发服务器并带 `--force`。

## 状态更正

- AEG-003、AEG-008、AEG-020 的容器化验收在周期 0/1 长期停在 In Progress，实际已由 staging 部署（`compose.staging.yml` + `deploy-staging.sh`）覆盖：数据库、Redis、后端、worker、前端和 Node 参考服务均以容器运行。已在对应条目更新状态并注明验证以 staging compose 为准，本地开发 override（Traefik、Adminer、Mailcatcher）仍未做过一次完整 `docker compose up --build` 验收。
