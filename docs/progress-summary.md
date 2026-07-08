# 进度摘要

更新时间：2026-07-08

## 当前阶段

周期 1 到周期 4 前置能力衔接：Web 上传、PDF/图片分页预览、手工题区标定、学生答卷上传、答卷预览、模板题区叠加、单题裁剪接口、配准状态记录、人工确认流程、教师复核页、结构化批注、学生答卷处理任务管线、真实题区裁剪产物、OCR 初稿字段/服务接口、手机照片预处理后端入口、PaddleOCR GPU 独立服务、题目区域候选分割接口和标定页候选草稿导入已实现。下一阶段主线调整为“空白卷重建 -> 标准答案制作 -> 学生答卷配准 -> 学生答案识别 -> 评分草稿 -> 教师复核”。真实自动配准 homography、标准答案工作台、AI 判分和批注 PDF 导出仍待后续周期接入。

## 已完成

- 本地仓库已初始化，当前分支为 `main`。
- 远程 `origin` 已配置为 `https://github.com/zxc123aa/ai-exam-grader.git`。
- 远程 `main` 已建立；本地另保留 `local-with-workflows` 分支用于后续恢复 GitHub Actions。
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
- Alembic migration 已升级到 `d4f9a2b7c601`。
- 后端集成测试脚本已通过：`bash scripts/tests-start.sh`，80 passed，coverage 90%。
- 前端检查和构建已通过：`npm run --workspace frontend lint`、`npm run --workspace frontend build`。
- OpenAPI smoke 路径存在性检查已通过，包含考试文件、标定区域、学生答卷和分页图片预览路径。
- Playwright 标定交互测试已补齐：创建考试、上传空白卷、进入标定页、拖框保存、重命名和删除题区。
- Playwright 学生答卷 smoke 已补齐：创建考试、上传学生答卷、显示配准占位状态并预览答卷页图。
- Playwright Chromium E2E 已通过：`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/snap/bin/chromium npx playwright test --project=chromium --reporter=line`，56 passed。
- 已新增 StudentSubmission 模型和 API：上传学生答卷、列出答卷、读取单份答卷、按页获取答卷图片。
- `/exams` 页面已新增 Submissions 入口，支持学生姓名/编号、PDF/JPG/PNG 答卷上传、列表和预览。
- 已新增学生答卷模板题区接口：读取答卷对应的 ExamRegion 列表，并可按单个题区导出裁剪 PNG。
- 学生答卷预览已支持按模板题区叠加显示，当前使用同页归一化坐标，不做自动透视配准。
- 已新增学生答卷配准状态模型和 API：可记录 `pending`、`manual_confirmed`、`failed`，保存质量分、备注、homography 和确认时间。
- 学生答卷列表已支持人工确认/失败标记，人工确认后答卷进入 `ready_for_review`，失败后进入 `registration_failed`。
- Alembic migration 已升级到 `e8c3b2a1f904`。
- 后端完整测试已通过：`bash scripts/tests-start.sh`，82 passed，coverage 90%。
- OpenAPI smoke 路径存在性检查已通过，包含 17 个关键路径。
- Playwright 考试流程 smoke 已通过：`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/snap/bin/chromium npx playwright test tests/exams.spec.ts --project=chromium --reporter=line`，4 passed。
- 已新增 SubmissionAnnotation 模型和 API：支持按学生答卷保存题区级复核状态、分数、满分、评语和归一化坐标。
- 已新增 `/exams/$examId/submissions/$submissionId/review` 教师复核页：左侧查看答卷和模板题区叠加，右侧选择题区并保存分数/评语/状态。
- Alembic migration 已升级到 `f3b1d0c9a742`。
- 后端完整测试已通过：`bash scripts/tests-start.sh`，84 passed，coverage 91%。
- OpenAPI smoke 路径存在性检查已通过，包含 19 个关键路径。
- Playwright 考试流程 smoke 已覆盖复核页批注保存：`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/snap/bin/chromium npx playwright test tests/exams.spec.ts --project=chromium --reporter=line`，4 passed。
- 已新增学生答卷处理任务入口：`POST /api/v1/exams/{exam_id}/submissions/{submission_id}/processing-tasks`。
- Worker 已新增 `student_submission_processing` 占位流程：读取模板题区，为未批注题区生成待复核批注草稿，并记录配准、裁题、OCR、判分阶段占位输出。
- 复核页已新增 Run Processing 按钮，可触发处理任务、显示任务状态/进度，并在任务完成后刷新批注列表。
- 本地 `ENVIRONMENT=local` 下处理任务同步执行，避免无 worker 时阻塞本地开发和 E2E；非 local 环境保留 Dramatiq 入队和 fallback。
- 后端完整测试已通过：`bash scripts/tests-start.sh`，85 passed，coverage 90%。
- OpenAPI smoke 路径存在性检查已通过，包含 20 个关键路径。
- Playwright 考试流程 smoke 已覆盖处理任务触发、占位批注生成和人工保存：`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/snap/bin/chromium npx playwright test tests/exams.spec.ts --project=chromium --reporter=line`，4 passed。
- 已新增手机照片预处理服务：使用 OpenCV 检测试卷边界、透视矫正、增强、按双页试卷拆页并导出 PDF。
- 已新增 `POST /api/v1/exams/{exam_id}/submissions/preprocess-photo`：上传 JPG/PNG 手机照片后生成处理后的 PDF，并直接登记为 `StudentSubmission`。
- 学生答卷弹窗已新增 Convert photo 入口，可从 Web 上传手机照片并生成 `*-preprocessed.pdf` 学生答卷。
- OpenAPI smoke 路径存在性检查已通过，包含 21 个关键路径。
- 后端考试路由测试已通过：`pytest backend/tests/api/routes/test_exams.py -q`，34 passed。
- Playwright 考试流程 smoke 已覆盖手机照片转 PDF 上传入口：`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/snap/bin/chromium npx playwright test tests/exams.spec.ts --project=chromium --reporter=line`，5 passed。
- 扫描预处理已补充真实样本验收：`materials/English/test1.jpg` 识别为双页并按中缝拆分，`materials/English/writing.jpg` 保持单页。
- 扫描预处理脚本已改为复用后端服务实现，避免 API 和实验脚本算法漂移。
- 后端完整测试已通过：`bash scripts/tests-start.sh`，88 passed，coverage 90%。
- Worker 已开始为每个模板题区生成实际 PNG 裁剪产物，保存到 `derived/submissions/{submission_id}/regions/{region_id}.png`。
- 学生答卷处理任务 `output_ref` 已记录 `region_crops` 明细，包括题区、页码、尺寸、坐标来源和存储 key。
- 已新增受保护批注裁剪图接口：`GET /api/v1/exams/{exam_id}/submissions/{submission_id}/annotations/{annotation_id}/crop`。
- 教师复核页已显示当前题区裁剪预览，处理任务完成后会刷新批注和裁剪图缓存。
- OpenAPI client 与 smoke 检查已同步新增批注裁剪图路径。
- 后端考试路由测试已通过：`pytest backend/tests/api/routes/test_exams.py -q`，34 passed。
- OpenAPI smoke 路径存在性检查已通过，包含 22 个关键路径。
- 前端检查和构建已通过：`npm run --workspace frontend lint`、`npm run --workspace frontend build`。
- 后端完整测试已通过：`bash scripts/tests-start.sh`，88 passed，coverage 90%。
- Playwright 考试流程 smoke 已覆盖处理任务后题区裁剪预览：`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/snap/bin/chromium npx playwright test tests/exams.spec.ts --project=chromium --reporter=line`，5 passed。
- 已新增批注 OCR 字段：`ocr_text`、`ocr_confidence`、`ocr_status`、`ocr_engine`，并补充 Alembic migration。
- 已新增可插拔 OCR 服务接口，默认 `OCR_ENGINE=disabled`，后续可配置为 `tesseract` 或替换为 PaddleOCR/云 OCR。
- Worker 已在题区裁剪后执行 OCR draft 阶段，并将 OCR 状态写入 `SubmissionAnnotation` 与任务 `output_ref.ocr_results`。
- 教师复核页已新增 OCR draft 区，显示当前题区 OCR 状态、引擎和识别文本。
- 后端考试路由测试已通过：`pytest backend/tests/api/routes/test_exams.py -q`，34 passed。
- 后端完整测试已通过：`bash scripts/tests-start.sh`，90 passed，coverage 90%。
- OpenAPI smoke 路径存在性检查已通过，包含 22 个关键路径。
- 前端检查和构建已通过：`npm run --workspace frontend lint`、`npm run --workspace frontend build`。
- Playwright 考试流程 smoke 已覆盖 OCR 状态显示：`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/snap/bin/chromium npx playwright test tests/exams.spec.ts --project=chromium --reporter=line`，5 passed。
- 已确认本机具备 RTX 5060 Laptop 8GB、NVIDIA Driver 596.49、WSL2 可见 CUDA 13.2，适合 PaddleOCR GPU cu130 独立服务方案。
- 已新增 `ocr-service`：NVIDIA CUDA 13.0 Ubuntu 22.04 镜像 + Python 3.10 + `paddlepaddle-gpu==3.3.0` cu130 + PaddleOCR，提供 `/health` 和 `/ocr`。
- 已新增 compose `ocr-gpu` profile 和后端 `OCR_ENGINE=paddle_http` 适配，Worker 可通过 HTTP 调用独立 OCR 服务。
- 已新增部署记录：`docs/ocr-paddle-gpu-cu130.md`。
- 已通过 Docker GPU 验证：`nvidia/cuda:13.0.0-base-ubuntu22.04 nvidia-smi` 可见 RTX 5060 Laptop。
- 已构建并启动 `ocr-service`，`GET /health` 返回 `paddleocr-gpu-cu130`，容器状态 healthy。
- 已在容器内验证 Paddle：`paddlepaddle-gpu==3.3.0`、`gpu:0`、`paddle.utils.run_check()` 通过。
- 已用 `materials/English/processed/test1/page_1_left.jpg` 调 `/ocr`，返回真实试卷文本，平均置信度约 `0.989`。
- 已补充 Worker 回归测试，覆盖 `OCR_ENGINE=paddle_http` 时把 Paddle HTTP OCR 结果写入批注 OCR 字段。
- 后端完整测试已通过：`bash scripts/tests-start.sh`，92 passed，coverage 90%。
- 已新增 opt-in Playwright PaddleOCR 复核页 E2E，用真实试卷 JPG 创建模板、上传学生答卷、进入教师复核页并触发 Run Processing。
- 教师复核页真实 PaddleOCR 流程已通过：`E2E_PADDLE_OCR=1 PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/snap/bin/chromium npx playwright test tests/exams.spec.ts -g "PaddleOCR draft appears" --project=chromium --reporter=line`，2 passed。
- 已完成物理卷 OCR 第一批评估：`materials/physics/1.jpg`、`materials/physics/2.jpg`，覆盖 4 个页级样本和 11 个题区样本，结果记录在 `docs/physics-ocr-evaluation.md`。
- 已新增 `scripts/evaluate_physics_ocr.py`，可复现物理卷页/题区裁剪、PaddleOCR 全量评估和 Kimi K2.7 抽样评估。
- 物理卷评估发现并修复扫描预处理新失败样例：`1.jpg` 原先只检测到左页、右页漏检；现在可通过 relaxed spread 检测输出双页。`2.jpg` 已补充内容保护边距和中缝空白带纠偏，避免顶部题干被裁掉或右页混入左页内容。
- Kimi K2.7 调用已验证可用于题区级 fallback：综合题/实验题对公式和单位恢复优于 PaddleOCR，但整页调用耗时高且可能返回空 final text。
- 扫描预处理回归已补充暗右页双页、暗顶部内容保留合成样本；后端完整测试已通过：`bash scripts/tests-start.sh`，94 passed，coverage 88%。
- 扫描预处理已进入稳定性阶段：新增 `docs/scan-preprocessing-stability-plan.md`，后端结果已带 `quality_status=pass|review` 和 `quality_warnings[]`，API metadata 已写入 `registration_homography.quality`。
- 扫描引擎 V2 骨架已开始落地：新增 `SCAN_ENGINE=opencv_v1|scan_http`，复用现有 `ocr-service` Paddle GPU 容器提供 `/preprocess`，后端 scan HTTP adapter 和 fake HTTP 回归测试已补齐；OpenCV v1 保留为默认 baseline。实机验证显示 Paddle DocPreprocessor 可作为单页矫正模块，但不是双页拆分器。
- 已新增题目区域候选分割只读接口：`GET /api/v1/exams/{exam_id}/files/{document_id}/region-candidates`，当前 `layout_projection_v0` 通过版面投影和连通区域生成候选框，供后续教师确认或 AI 模板建立流程使用；它不会自动写入正式 `ExamRegion`。
- 标定页已接入 Detect regions：候选框以虚线草稿显示，教师点击候选后仍需手动 Save Region 才会写入正式题区；Playwright 已覆盖“检测候选 -> 选择候选 -> 保存题区”流程。
- 已新增题目候选分割真实样本评估：`scripts/evaluate_question_segmentation.py` 和 `docs/question-segmentation-evaluation.md`。7 个英语/物理单页样本结果为 `0 pass / 1 review / 6 fail`，主要失败是 `dominant_whole_page_candidate` 整页误框。
- 已新增 `layout_ocr_anchor_v1` 第一版：`ocr-service /ocr` 现在返回 `raw.lines[]` 文本框，后端可用题号 anchor 生成候选框，标定页可在 Projection / OCR anchor 之间切换。OCR anchor 真实样本评估见 `docs/question-segmentation-ocr-anchor-evaluation.md`，结果为 `3 pass / 3 review / 1 fail`。
- 已新增主线计划文档：`docs/template-answer-grading-plan.md`，明确先重建空白卷模板，再制作标准答案，最后进行题区级识别、评分草稿和教师复核。

## 进行中

- 周期 4 下一块能力：优先补齐标准答案数据模型、答案工作台和评分草稿输入，不再直接从 OCR 跳到 AI 判分。
- 题目区域自动分割仍处在候选阶段：`layout_ocr_anchor_v1` 已明显改善整页误框，但仍有写作页无题号漏检、物理页过切和题号误锚定问题，不能自动落库。

## 下一步

1. 实现标准答案数据模型与 API：每条标准答案绑定一个已确认且 `region_type=question` 的 `ExamRegion`，保存参考答案、满分、评分点和评分规则。
2. 新增标准答案工作台：教师按题区录入答案、满分和评分点，未填写题区需要明确提示。
3. 扩展学生答卷处理任务：有标准答案时生成独立评分草稿字段，无标准答案时只生成 OCR draft 并标记待补答案。
4. 扩展教师复核页：显示标准答案、评分规则、OCR draft、建议分和建议评语；教师确认后才写入最终分数/评语。
5. 前端显示扫描预处理 `scan_quality` 和 warnings，`review` 结果进入 OCR/判分前必须可被教师确认。
6. 继续迭代 `layout_ocr_anchor_v1`：补写作/大答题区 fallback、减少物理页过切，并把真实样本 pass/review/fail 作为质量门禁。
7. 接入 Kimi 题区级 fallback，先以 PaddleOCR `confidence < 0.90` 作为实验触发线。
8. 将当前人工确认的 identity homography 替换为可插拔自动配准结果。
9. 设计批注 PDF 导出，把教师最终复核结果回写到卷面。

## 风险与阻塞

- GitHub token 缺少 `workflow` scope，远程 `main` 暂未包含 `.github/workflows`；恢复前需要 `gh auth refresh -h github.com -s workflow`。
- WSL 内 `docker` 命令未进 PATH，但 Windows Docker CLI 可通过 `/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe` 使用。
- 后端容器 build 拉取 `python:3.13` 时遇到 Docker Hub 网络超时；数据库和 Redis 容器已可用。
- 当前 Ubuntu 26.04 环境不被 Playwright 官方浏览器下载支持，测试使用系统 Chromium：`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/snap/bin/chromium`。
- 密码重置 E2E 需要 Mailcatcher，并要求本地后端以 `SMTP_HOST=localhost SMTP_PORT=1025 SMTP_TLS=false SMTP_SSL=false` 启动。
- 第三方依赖许可证清单已建立，但商业化前必须持续维护。
- OpenAPI 生成器把 multipart 文件字段生成为 `string` 类型，前端当前在上传组件内做了局部类型转换；后续可统一优化生成配置。
- 文件预览已改为 authenticated fetch 获取 blob/object URL，后端文件内容和分页图片接口只接受 `Authorization: Bearer ...`，避免把长期 token 拼进 URL。
- Playwright 本地运行需要后端已启动，且 dev DB 中存在 `.env` 的 `FIRST_SUPERUSER`；本轮已补建 `admin@example.com` 本地测试账号。
- 批注裁剪图当前从最新处理任务的 JSON `output_ref.region_crops` 查找；MVP 可用，后续数据量上来后应迁移为可索引的派生产物表或 JSONB 查询。
- OCR 服务默认仍是 `disabled`，需要部署环境显式设置 `OCR_ENGINE=paddle_http` 和 `OCR_HTTP_URL` 后，Worker 才会产出真实 `ocr_text`。
- WSL 调 Windows Docker CLI 时仍建议把 `C:\Program Files\Docker\Docker\resources\bin` 加入 Windows PATH；当前已用 PowerShell PATH workaround 完成 GPU OCR 验证。

## 最近决策

- 第一阶段优先 Web 系统，移动 App 后置。
- 第一阶段仍优先 Web 系统；手机“扫描王”能力先以后端受控入口和实验服务推进，不阻塞主线。
- 学生答卷采集先走 Web 上传；手机拍照裁边、矫正、增强、合并 PDF 已进入 Web 端受控入口，后续继续增强鲁棒性。
- 采用模板驱动流程，不做无模板整卷盲识别。
- 第一版标准答案采用教师手动录入，并且必须绑定已确认且 `region_type=question` 的 `ExamRegion`。
- AI 结果作为建议和草稿，教师保留最终确认权。
- AI 建议分和教师最终分必须分字段保存，不能用最终 `score/comment/status` 承载未确认建议。
- 客观题优先规则和 OCR，主观题再调用视觉大模型。
- 所有识别、判分和批注结果必须保留卷面坐标。
