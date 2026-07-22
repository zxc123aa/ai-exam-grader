# 空白卷重建、标准答案与评分闭环计划

> 历史方案。题目主数据、答案版本和后续实施以 `docs/question-answer-workflow-spec.md` 为准。

更新时间：2026-07-08

## 目标

项目主线调整为模板驱动：

```text
空白卷重建 -> 标准答案制作 -> 学生答卷配准 -> 学生答案识别 -> AI/规则评分 -> 教师复核 -> 批注导出
```

当前系统已经具备上传、分页预览、手工题区标定、学生答卷上传、题区裁剪、OCR 初稿和教师复核页。下一阶段要补齐缺失的标准答案和评分规则层，否则手写识别和自动评分无法形成可靠闭环。

## 当前基础

已完成能力：

- `ExamDocument` 已区分 `blank_exam` 和 `answer_key`，但答案卷尚未参与自动解析。
- `ExamRegion` 已保存空白卷模板题区，使用归一化页面坐标。
- `StudentSubmission` 已保存学生答卷和配准状态。
- `SubmissionAnnotation` 已保存题区级 OCR 文本、分数、满分、评语和复核状态。
- Worker 已能按 `ExamRegion` 裁剪学生答卷题区，并写入 OCR draft。
- 复核页已能查看整页、题区裁剪图、OCR draft，并手工保存分数/评语。

缺口：

- 没有一等标准答案模型。
- 没有逐题满分、参考答案、评分点和评分规则的管理入口。
- Worker 处理任务无法把 OCR 结果和标准答案结合生成评分草稿。
- 复核页只能手动填写分数/评语，不能展示标准答案或 AI 建议。

## 阶段设计

### 1. 空白卷重建

目标：把老师上传或拍摄的空白卷变成可复用模板。

输入：

- 空白卷 PDF、JPG、PNG。
- 手机拍摄照片，后续通过扫描预处理生成 PDF/page images。

处理：

- 页面预览和分页。
- 扫描预处理：裁边、透视矫正、增强、双页拆分和质量门禁。
- 印刷文字 OCR。
- 题区候选分割：`layout_ocr_anchor_v1` 优先，`layout_projection_v0` 作为 fallback。
- 教师确认题区，正式保存为 `ExamRegion`。

验收：

- 每道需要评分的题都存在一个确认后的 `ExamRegion`。
- 自动候选不得直接落库，必须由教师确认。
- 对 `scan_quality=review` 的页面，进入 OCR/评分前必须可被教师确认。

### 2. 标准答案制作

目标：为每个已确认题区建立评分依据。

第一版入口：

- 手动录入为主。
- 每条标准答案绑定一个可评分 `ExamRegion`。
- 第一版可评分题区定义为 `region_type=question` 的 `ExamRegion`；如果后续要把题干区和答题区分开，需要先新增 `scoring_unit` 概念，不能让标准答案随意绑定 `answer_area/header/other`。
- 每个可评分题区最多一条标准答案。

建议数据：

- `exam_id`
- `exam_region_id`
- `answer_text`
- `max_score`
- `rubric_text`
- `scoring_points`，JSON 数组，第一版最小结构固定为 `{id, description, points, required}`
- `status`：`draft`、`ready`
- `created_at`、`updated_at`

`scoring_points` 示例：

```json
[
  {
    "id": "point-1",
    "description": "写出关键公式",
    "points": 2,
    "required": true
  }
]
```

第一版不做：

- 不要求答案卷 OCR 自动解析。
- 不要求 AI 自动生成标准答案。
- 不支持未绑定题区的独立题号答案。

验收：

- 教师可以在答案工作台看到全部题区。
- 教师可以逐题保存答案、满分和评分规则。
- 未填写标准答案的题区在工作台和复核页都有明确提示。

### 3. 学生答卷配准和裁剪

目标：把学生答卷映射到空白卷模板题区。

第一版继续沿用当前能力：

- 学生上传 PDF/图片，或通过手机照片预处理生成 PDF。
- 教师确认同版式配准，当前可继续使用 identity homography。
- Worker 按 `ExamRegion` 裁剪学生答题区域。

后续增强：

- 用自动配准替换人工 identity confirmation。
- 扫描质量门禁进入前端确认。
- 配准失败时不得进入自动评分。

验收：

- 每个题区裁剪图可在复核页查看。
- 处理任务 `output_ref.region_crops` 记录裁剪产物。
- 配准未确认或失败时，评分任务应明确标记为 blocked/needs_review。

### 4. 学生答案识别

目标：只识别题区裁剪图，不做整页盲识别。

策略：

- PaddleOCR 作为快速 baseline。
- 第一版不自动调用 Kimi/视觉模型评分；当 `ocr_status != succeeded` 或 `ocr_confidence < 0.90` 时，标记为 `needs_review`，由教师复核。
- Kimi/视觉模型作为后续题区级 fallback，优先处理低置信度、公式、单位、图示密集题。
- 客观题后续单独接规则识别，例如选择题勾选、填涂、圈选。

输出：

- `ocr_text`
- `ocr_confidence`
- `ocr_status`
- `ocr_engine`
- 原始裁剪图证据

验收：

- OCR 失败不阻塞人工复核。
- 低置信度结果必须可见，不能静默当成正确答案。
- 整页 OCR 只用于辅助，不作为评分直接输入。

### 5. 评分草稿和教师复核

目标：把学生答案、标准答案和评分规则合成建议分与建议评语。

第一版评分：

- 以主观题评分草稿为主。
- AI/规则评分只写入建议字段，不直接覆盖教师最终字段。
- 建议字段与最终字段分离：`suggested_score`、`suggested_comment`、`grading_confidence`、`grading_reasons`、`grading_status`。
- 教师点击确认后，才把建议分和建议评语复制到现有 `SubmissionAnnotation.score/comment/status`。
- `SubmissionAnnotation.max_score` 可从标准答案同步，但最终确认前仍应显示为待复核。

评分输入：

- 题区裁剪图。
- OCR draft 文本。
- 标准答案 `answer_text`。
- 满分 `max_score`。
- 评分规则 `rubric_text` 和 `scoring_points`。

建议输出：

- `suggested_score`
- `suggested_comment`
- `grading_confidence`
- `grading_reasons`，包含扣分点、命中的评分点和风险提示
- `grading_status`：`not_started`、`succeeded`、`skipped_missing_answer`、`needs_review`、`stale`
- `answer_key_updated_at`，记录本次评分使用的标准答案更新时间

验收：

- 无标准答案时，Worker 只生成 OCR draft，并提示“缺少标准答案”。
- 有标准答案时，Worker 生成评分草稿，但不自动定稿。
- 标准答案更新后，旧评分草稿必须标记为 `stale`，需要重新处理后才能作为建议使用。
- 复核页显示标准答案、评分规则、OCR draft、建议分和建议评语。

## 后续代码实施顺序

1. 新增标准答案模型和 migration。
2. 新增标准答案 CRUD API。
3. 生成前端 OpenAPI client。
4. 新增标准答案工作台。
5. 扩展 Worker，把标准答案纳入处理任务输出。
6. 扩展复核页，显示标准答案和评分草稿。
7. 增加后端、前端和 Playwright 覆盖。

## 关键约束

- 模板驱动，不做无模板整卷盲识别。
- 第一版标准答案必须绑定 `region_type=question` 的 `ExamRegion`。
- 第一版标准答案由教师手动录入。
- AI/OCR 结果都是草稿，教师保留最终确认权。
- AI 建议分和教师最终分必须分字段保存，不能用 `score/comment/status` 直接承载未确认建议。
- 所有识别、评分和批注结果必须保留卷面坐标或题区裁剪证据。
- 评分能力必须允许缺省：缺标准答案、缺 OCR、低置信度都应进入人工复核。

## 近期 issue 拆解

- AEG-036：标准答案数据模型与 API。
- AEG-037：标准答案工作台。
- AEG-038：基于标准答案的评分草稿接入。
- AEG-039：答案卷 OCR/AI 生成标准答案草稿，后置。
