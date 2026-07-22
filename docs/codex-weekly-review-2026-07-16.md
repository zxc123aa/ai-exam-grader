# Codex 使用周度复盘记忆 - 2026-07-16

checked_at: 2026-07-16  
scope: 2026-07-09 23:34 至 2026-07-16 23:34  
memory_type: engineering_review, collaboration_rule, failure_case, implementation_lesson

## 估算口径

本记录基于本地 Codex 会话 JSONL、`.codex/.agents` 缓存、当前项目最近 7 天文件变更和项目产物统计。时间不是精确计时器结果，而是用 Codex 事件时间戳估算：

- 相邻事件间隔小于 30 分钟视为同一工作窗口；
- 15 分钟断点估算约 49.3 小时；
- 30 分钟断点主口径约 53.4 小时；
- 60 分钟断点约 64.2 小时。

结论：最近 7 天属于高强度 Codex 使用，主项目为 `ai-exam-grader` 批卷系统。

## 总览

### 主要投入分布

| 项目 | 估算投入 | 判断 |
| --- | ---: | --- |
| ai-exam-grader 批卷系统、试卷识别、OCR、批改流 | 约 37-40 小时 | 主项目，占 70%-75% |
| 服务器、Claude/Pomo、模型中转站、模型供应商配置 | 约 10-13 小时 | 次主线，占 20%-25% |
| 文档校正、仿射变换、版面分割算法调研 | 约 4-6 小时 | 属于主项目子模块 |
| 自动化浏览器插件、临时任务、桌面环境 | 约 1-3 小时 | 低投入 |
| SFICS skill / 科研写作技能更新 | 约 0.5 小时内 | 少量痕迹 |

### 本地证据概况

- Codex/Agents 相关近期文件约 5397 个。
- 项目目录 `/mnt/d/songtan/ai-exam-grader` 最近 7 天内生成或修改文件约 1472 个。
- 主要项目产物集中在：
  - `data/uploads`
  - `outputs/ocr-ground-truth`
  - `outputs/scan-validation`
  - `outputs/document-normalizer`
  - `frontend/src`
  - `backend/app`
  - `参考算法/源码`
  - `参考算法/evaluation`

## ai-exam-grader 批卷系统复盘

### 本周做过的事

1. 前后端启动、调试和接口联通。
2. 模型供应商和中转站接入：
   - Gemini
   - GPT-5.6 sol / terra luna
   - Kimi
   - Grok
   - Claude / Pomo / Fluxnode
3. 批量导入卷子工作流：
   - 科目、学生、卷子绑定；
   - 一张卷子多张图片/PDF；
   - 页码前后切换；
   - 页面顺序调整。
4. 模板标注、题目识别、学生答案识别。
5. 标准答案流程：
   - 从学生卷/模板卷提取题目；
   - 用 GPT-5.6 sol 整理标准答案；
   - 支持上传答案文档。
6. 参考源码迁移：
   - 保留原 JS/Node 技术路线；
   - 对齐参考源码中的版面分割、旋转、OCR、并发识别逻辑。
7. 全卷 OCR 评估：
   - 建立 gold 数据；
   - 对比参考算法和当前算法；
   - 加入关键点准确率、字符准确率、自动放行率、错误放行等指标。
8. 针对 Q17、Q20、Q21、Q22 进行重点修正：
   - Q17 单独识别；
   - Q20 草稿与正式答案分离；
   - Q21 阻断 `100N` / `600N` 类模型幻觉；
   - Q22 证据一致性判断。

### 当前关键产物

- `outputs/ocr-ground-truth/physics-2021-2022-b/full-paper-selective-final-merged/summary.md`
- `outputs/ocr-ground-truth/physics-2021-2022-b/full-paper-selective-final-merged/summary.json`
- `data/golden/physics-2021-2022-b/printed_questions_gold.md`
- `data/golden/physics-2021-2022-b/student_answer_text_gold.json`
- `docs/document-normalizer-spec.md`
- `docs/question-answer-workflow-spec.md`
- `docs/template-answer-grading-plan.md`
- `docs/progress-summary.md`
- `docs/decision-log.md`

### 最终 OCR 指标快照

来自 `outputs/ocr-ground-truth/physics-2021-2022-b/full-paper-selective-final-merged/summary.md`：

| 指标 | 结果 |
| --- | ---: |
| 关键点准确率 | 100%，42/42 |
| 题目通过率 | 100%，22/22 |
| 可自动批改题数 | 19/22 |
| 自动放行精度 | 100% |
| 禁止自动放行逃逸 | 0 |
| 字符准确率，所有可评分状态 | 93.26% |
| 字符准确率，人工确认项 | 95.89% |
| 总耗时 | 221.9 秒 |
| 模型请求数 | 63 次 |

### 重复劳动和低效步骤

1. 早期没有先建立 gold 标准答案和全卷指标，导致很多修复只围绕单题、单截图、单现象，无法判断整体是否真的变好。
2. OCR 和版面识别未稳定时过早推进业务 UI、数据库、模型选择和批改流程，导致返工。
3. 技术路线曾一度漂移到 Python/OpenCV 方向，但用户明确要求按参考源码和原 JS/Node 技术栈执行。
4. “禁止硬编码”约束进入流程太晚，后续需要反复追问硬编码和通用性。
5. 模型识别问题和版面框选问题混在一起，部分问题本质是框选不准，却被提示词、模型或规则补救复杂化。
6. 单题修复太多，全卷回归太晚；直到明确要求“准确率每次都要汇报”后流程才开始收敛。

## 模型供应商和中转站配置复盘

### 做过的事

本周反复配置和验证：

- Gemini 3.5 Flash 多模态；
- GPT-5.6 sol、GPT-5.6 terra luna、GPT-5.5；
- Claude opus、fable、sonnet、haiku；
- Grok 4.5；
- Kimi k2.7-code、k2.7-code-highspeed、k2.6、k2.5；
- Fluxnode 多 key；
- Pomo 中转站；
- Claude Code native binary 修复；
- `.env` 和模型 provider/base_url/model_id 配置。

### 记忆规则

模型配置必须区分 `provider` 和 `model_id`。同一个模型在不同中转站/提供者上的性能、可用性、视觉能力、错误率和延迟都可能不同，不能只按模型名记录。

建议维护 `docs/model-provider-matrix.md`，字段至少包括：

- provider
- base_url
- model_id
- 用途
- 是否视觉
- 是否可用
- 最近测试时间
- 测试耗时
- 错误信息
- 备注

禁止在文档中打印 API key。

## 文档校正和版面分割复盘

### 做过的事

围绕“把卷子摆正”和“版面框选更准”调研和验证：

- Scanic
- jscanify
- opencvjs-document-scanner
- react-perspective-cropper
- DocTr++

生成过校正验证图和结果：

- `outputs/document-normalizer/validation-material-1/`
- `outputs/scan-validation/`
- `outputs/layout-validation/21-22-boundary-effect.png`

### 低效点

1. 目标曾从“框选准”扩大成“完整文档扫描系统”，引入边界检测、角点 UI、双页裁剪、质量分、曲面展开等外围问题。
2. 质量分没有始终绑定题块框选和 OCR 准确率，导致“质量分”本身不能证明最终效果。
3. 算法调研没有一开始形成统一 A/B 基准：同一张卷子、同一指标、同一输出目录。

### 记忆规则

文档校正方案只有在能提升以下最终指标时才算有效：

- 校正后图片；
- 角点坐标；
- 全卷题块图；
- 题块框选通过率；
- OCR 字符准确率；
- 总耗时。

单独的视觉观感或质量分不能作为通过依据。

## 前后端工作流复盘

### 做过的事

- 上传卷子时绑定多张图片/PDF；
- 支持上一页/下一页；
- 支持调整顺序；
- 模板标注；
- 识别题目；
- 汇总题目；
- 生成标准答案；
- 上传答案文档；
- 数据库结构设计；
- 增加用户账号；
- 加缓存清理 hook；
- 后端识别服务和测试。

### 低效点

1. UI 改动后没有每轮固定截图验收，导致用户多次指出“没有变化”“还是只有一个试卷”“目标标注在哪”。
2. “一张卷子多张图片”和“多份卷子”语义混淆。正确业务模型应是一个 `Submission` 绑定多个 `SubmissionPage`，而不是把页面误认为多份卷子。
3. OCR 未稳定时过度扩展 UI 和数据库，会增加返工成本。

### 记忆规则

前端任务必须用截图验收，尤其是上传、模板标注、页面切换、页面顺序调整类任务。截图应保存到 `outputs/ui-validation/` 或同类可追踪目录，并说明每张截图对应哪个验收点。

## 用户提示词和协作问题

### 高频低效提示词

以下提示在项目状态复杂时容易导致 Codex 自行猜测下一步：

- “继续”
- “修复”
- “Implement the plan”
- “看看效果”
- “按照之前的计划执行”

### 更好的提示结构

后续对 Codex 下任务，优先使用：

```text
背景：
当前项目状态是什么。

本轮目标：
只做一件事。

输入：
用哪些图片、文件、接口、模型。

禁止：
不能改哪些东西，不能换技术栈，不能硬编码。

验收指标：
准确率、耗时、通过率、截图、测试命令。

必须输出：
修改文件、运行命令、结果路径、失败项。
```

### OCR/算法任务推荐提示词

```text
只处理 OCR 框选准确性，不改前端、不改数据库、不改模型列表。
输入：当前这张完整物理卷。
目标：全卷 1-22 题块框选正确。
禁止：硬编码题号坐标；禁止切 Python 技术栈。
必须输出：
1. 每题题块图
2. 题块通过率
3. 字符准确率
4. 自动放行数
5. 错误放行数
6. 总耗时
7. 修改了哪些文件
```

### UI 任务推荐提示词

```text
本轮只修上传数据模型和 UI，不碰 OCR。

验收：
1. 一个学生的一份卷子可以绑定 2 张图片或 1 个 PDF
2. 页面显示为“第 1 页 / 第 2 页”，不是“两份卷子”
3. 可调整页面顺序
4. 模板标注能看到所有页
5. Playwright 截图保存到 outputs/ui-validation
6. 列出修改文件
```

## 项目不变项

后续所有相关任务应默认遵守：

1. 不允许硬编码题号坐标、页数、旋转角度或模型答案。
2. 不允许未经确认切换 Python 技术栈；当前主线优先复用参考源码和 JS/Node 技术路线。
3. OCR/题块算法每次修改必须跑全卷回归。
4. 每次 OCR 相关修改必须输出准确率、通过率、自动放行数、错误放行数、耗时和模型请求数。
5. 平均置信度不是准确率，不能作为发布门禁。
6. 模型不确定时必须进入人工复核，不能自动放行。
7. 框选问题优先修框选，不要用提示词或模型脑补掩盖。
8. 标准答案应先从识别出的完整题目建立，后续复用，不应每次重复生成。
9. 一张卷子可以由多张图片/PDF 页面组成；页面不是多份卷子。
10. 每次前端可见改动必须有截图或 Playwright 验收证据。

## 下周建议主线

下周建议只抓一个主线：

```text
主线：让当前这一份物理卷完整工作流稳定通过。
范围：上传 -> 页面绑定 -> 摆正 -> 题块识别 -> 学生答案识别 -> 标准答案 -> 批改 -> 报告。
禁止：扩展新模型、新数据集、新 UI 大改。
验收：全流程截图 + summary.md + 全卷指标。
```

推荐执行顺序：

1. 固化当前 gold 数据。
2. 固化参考算法 baseline。
3. 当前算法每次修改都和 baseline 对比。
4. 先解决题块框选，再解决文字识别。
5. 识别不确定就进入人工复核，不允许模型脑补。
6. 最后再接批改评分准则。

## 记忆处理备注

- action: insert
- reason: 这是新的工程协作复盘和项目使用规则，现有 `progress-summary.md`、`decision-log.md`、`document-normalizer-spec.md` 只覆盖开发进度和局部技术决策，没有专门记录 Codex 使用方式、协作低效和提示词规则。
- risk: 时间统计为事件窗口估算，不是精确工时。
- privacy: 未记录任何 API key、密码或 `.env` 原文。
