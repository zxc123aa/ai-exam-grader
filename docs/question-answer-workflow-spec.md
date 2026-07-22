# 题目确认、标准答案生成与评分准则工作流 Spec

状态：Implemented  
更新时间：2026-07-14  
实现区间：AEG-040 至 AEG-048

## 目标流程

```text
上传题目源页面（空白卷优先；无空白卷时可用一份代表学生卷）
-> 题目识别 -> 题目人工确认
-> GPT-5.6 SOL 解题 / 上传答案文档
-> 答案匹配与人工确认 -> 评分准则确认
-> 发布不可变答案版本 -> 批改锁定答案版本
```

AI 结果只能生成草稿。未经教师确认，不得写入正式题目、正式答案或最终成绩。
如果题目源来自学生卷，考生手写内容只能作为 `student_answer_text`
旁证展示，不得并入正式题干或标准答案。

## 模型约束

- `ExamQuestion` 是题目主数据，考试内 `question_key` 唯一。
- `ExamQuestionRegion` 支持一道题关联多个题块，记录顺序和角色。
- `QuestionRecognitionRun/Item` 保存 Node 参考算法原始结果、耗时和人工修订。
- `AnswerPreparationRun/Item` 统一承载模型解题和答案文档导入。
- `StandardAnswerRevision` 是不可变快照；`StandardAnswer` 只指向当前版本。
- `GradingItem` 保存实际使用的 `question_id` 和 `answer_revision_id`。
- 图片保存在文件存储中，数据库只保存引用；分值使用定点精度。

## 状态机

题目：`draft -> confirmed`。  
答案准备项：`queued -> running -> matched|conflict|unmatched|failed -> confirmed`。  
答案修订：`draft -> published`；published 记录不可原地修改。  
任务：`queued -> running -> completed|completed_with_errors|failed`。

## 接口

```text
POST /exams/{id}/question-recognition-runs
GET  /exams/{id}/question-recognition-runs/{run_id}/items
PATCH /exams/{id}/question-recognition-items/{item_id}
POST /exams/{id}/question-recognition-runs/{run_id}/confirm

POST /exams/{id}/answer-preparation-runs
GET  /exams/{id}/answer-preparation-runs/{run_id}/items
PATCH /exams/{id}/answer-preparation-items/{item_id}
POST /exams/{id}/answer-preparation-runs/{run_id}/confirm

POST /exams/{id}/standard-answers/publish
GET  /exams/{id}/standard-answers/revisions
```

默认答案模型为 `pomoai / gpt-5.6-sol`，但 provider/model 必须保存到运行记录并允许配置。题目 OCR 唯一实现为 `参考算法/源码` 的 Node.js + sharp 服务。

## 页面

- `/exams/{id}/marking`：只处理转正、分割和区域确认。
- `/exams/{id}/questions`：OCR 结果、题干/选项修订和题目确认。
- `/exams/{id}/answers`：模型解题、答案文档导入、冲突处理、评分准则和发布。

## 迁移策略

1. 先增加新表和 nullable 外键。
2. 由现有 `ExamRegion` 回填 `ExamQuestion` 和关联表。
3. 由现有 `StandardAnswer` 生成 revision 1。
4. 新任务优先写新结构，旧结构保留双读。
5. 历史数据验收后再收紧约束；本阶段不删除旧字段。

## Definition of Done

- migration 可升级且可降级，旧数据不丢失。
- API 权限、状态转换、冲突和不可变约束有测试。
- 前端可完成题目确认、两种答案来源、修订和发布。
- 新批改记录保存 `question_id` 与 `answer_revision_id`。
- Playwright 不硬编码题号、题数、角度或模型答案。
- Issue 必须记录 migration、提交、测试结果和截图/trace 才能标记 Done。

## 进度

| Issue | 内容 | 状态 | 验收证据 |
| --- | --- | --- | --- |
| AEG-040 | Spec、状态机和迁移基线 | Done | `c7d9e1f3a526`、升降级验收 |
| AEG-041 | ExamQuestion 与多区域关联 | Done | `ExamQuestionRegion`、文件级区域归属、旧数据回填 |
| AEG-042 | 题目识别与确认页面 | Done | `/questions`、Node `/api/process`、真实置信度与分阶段耗时 |
| AEG-043 | 不可变答案版本与迁移 | Done | revision 1 回填、发布后无修改/删除入口 |
| AEG-044 | GPT-5.6 SOL 解题生成 | Done | `pomoai / gpt-5.6-sol` 并发草稿任务 |
| AEG-045 | 答案文档导入与匹配 | Done | `matched/conflict/unmatched`、答案文件上传与整理 |
| AEG-046 | 评分准则确认与发布 | Done | 分值合计校验、人工确认、不可变发布 |
| AEG-047 | 批改绑定题目/答案版本 | Done | 创建批次锁定 revision，`GradingItem` 双外键 |
| AEG-048 | E2E、回滚和历史兼容验收 | Done | 118 tests、前端 build、Playwright 2 passed、迁移升降级 |

## 变更日志

- 2026-07-14：建立 v1 Spec，替代旧的单区域、可变答案设计作为后续实现依据。
- 2026-07-14：完成 v1 实现；迁移、API、前端、批改锁定和动态浏览器验收全部通过。

## 验收证据

- Alembic：`a6b8c0d2e415 -> c7d9e1f3a526`；旧答案回填、downgrade、re-upgrade 均通过。
- 后端：临时 PostgreSQL 全量 `pytest -q`，`118 passed`。
- 静态检查：本次涉及后端文件 Ruff 全通过；前端 Biome 检查与 `npm run build` 通过。
- Playwright：`tests/question-answer-workflow-live.spec.ts`，Chromium `2 passed (9.0s)`，包含真实后端批次只读验收和完整交互验收。
- 截图：`/tmp/real-question-recognition.png`、`/tmp/question-answer-workflow.png`。
- 真实恢复批次：两份物理卷识别 22 题，总耗时 70.25 秒，方向 11.36 秒、版面 11.67 秒、裁切 0.25 秒、OCR 55.72 秒，平均置信度 94.77%。不同中转站时段的模型延迟会明显波动。
