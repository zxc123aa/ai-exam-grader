# 学生端「终身错题本」方案

状态：待决策
更新时间：2026-08-13

本文档规划点凡阅卷的学生端主线：以真实考试为数据源、自动积累、可伴随学习生涯的个人错题本与私有知识库。

## 1. 结论先说

**做，但不要照抄消费级 AI 学习 App 的形态。**

参考应用（豆包爱学一类）的首页是工具箱：拍题答疑、作业批改、AI 写作文、口算练习。它们的错题本是**副产品**，数据靠学生自己拍照录入。点凡阅卷的位置恰好相反：

| | 消费级 AI 学习 App | 点凡阅卷学生端 |
|---|---|---|
| 错题来源 | 学生自己拍照录入 | 老师已批改的真实考试，**零录入** |
| 分数可信度 | AI 自判，无权威 | 教师最终确认的成绩 |
| 是否有标准答案与评分点 | 靠题库匹配 | 本校教师发布的标准答案 + 评分点 |
| 是否知道**为什么**扣分 | 猜 | 有评分点级别的失分证据 |
| 断档风险 | 学生一懒就断 | 只要学校在用，自动累积 |
| 政策风险 | 「拍照搜题」是明令整改对象 | 教师主导，不提供搜题 |

**差异化不在功能多，而在数据来源的不可复制性。** 别人拿不到「教师批改过的、带评分点的、连续多年的真实考试逐题结果」。所以学生端的第一原则是：

> 学生不需要做任何录入动作，考完试成绩一发布，错题本自己长出来。

**依赖不是靠功能堆出来的，靠三件事**：数据只增不减（走了就没了）、主动提醒（考前自动给复习卷）、可携带（升学换校不丢）。这三件都是架构问题，不是界面问题。

## 2. 先解决三个硬约束，否则「伴随一生」是假的

以下三条都在代码里验证过，不是推测。**错题本不能做成教师端数据的视图**，必须是独立留存的实体。

### 2.1 老师删考试，学生的错题会静默消失

`Exam` 对 documents / regions / submissions 是 `cascade_delete=True`，`ExamQuestion`、`SubmissionAnnotation`、`ScoreRelease` 对上级都是 `ondelete="CASCADE"`（`backend/app/models.py`）。删一场考试，题干、答卷、批注、成绩快照全部消失。

> 对策：发布成绩时把错题**快照**进学生自己的表，题干、标准答案、评分点、学生作答、失分原因、裁切图各留一份，只保留对来源的弱引用（`ON DELETE SET NULL`）。考试被删，错题本仍完整。

### 2.2 学校欠费冻结，学生连登录都会 403

`get_current_user` 对每个请求都调用 `assert_organization_access`（`backend/app/api/deps.py`），学校 `frozen`/`deleting` 时一律 403，`read_only` 时非 GET 返回 423。学生账号挂在 `user.org_id` 上，学校停付费，学生的「终身」错题本当天就打不开。

> 对策：学习者身份与学校租户解耦。学生账号的 `org_id` 可为空，在校经历用独立的 enrollment 表表达；错题本读取只依赖 learner 身份，不走学校服务状态拦截。这同时是商业上的护城河——学生数据不随学校流失而流失。

### 2.3 升班、转学、换班，学生历史就断了

`Student` 是**班级内**实体：`UniqueConstraint("class_id", "name")`，且 `StudentUpdate` 不支持修改 `class_id`。升班在实践中等于新建一条 `Student` 再重新绑定账号，旧班的 `student_id` 不会迁移。学生端兜底匹配用的是**当前班名 + 姓名**（`students.py` 的 `find_my_submissions`），旧班答卷因此可能查不到。

> 对策：引入 `LearnerProfile` 作为跨班、跨学年、跨学校的稳定身份，锚定在**学生自己的登录账号**（手机号或微信），而不是学校建的班级档案。

## 3. 现有资产：地基比想象的好

不需要从零开始。批改管线已经持久化了错题本需要的几乎全部原料：

| 需要的东西 | 现状 | 位置 |
|---|---|---|
| 逐题得分与满分 | 已有 | `SubmissionAnnotation.score/max_score` |
| 教师最终评语 | 已有 | `ScoreReleaseItem.comment` |
| **评分点级失分证据** | **已有但学生看不到** | `SubmissionAnnotation.grading_evidence` 中 `matched=false` 的评分点项 |
| 学生作答转录 | 已有但学生看不到 | `SubmissionAnnotation.ocr_text` |
| 题干 | 已有 | `ExamQuestion.question_text` |
| 标准答案与评分点 | 已有 | `StandardAnswerRevision`（不可变） |
| 学生手写原件 | 已有 | 整页 `StoredFile` + 题区裁切 |
| 跨考试题库检索 | 已有（教师侧） | `GET /exams/question-bank`，范围是本校全部已确认题目 |

**最重要的一条**：判分模型按评分点返回 `{"point","matched","points","reason"}`，这些证据项会写进 `SubmissionAnnotation.grading_evidence`（`grading_workflow.py` 里 `*grading.get("evidence", [])` 展开），客观题规则引擎同样产出 `matched` 条目。阶段一把其中 `matched=false` 的评分点展示给学生，**不需要额外 LLM 成本**就能回答「为什么扣分」。

**不要用 `grading_reasons`**：它装的是复核门禁信号（`low_confidence`、`unreadable`、`answer_count_mismatch`、`model_failure`、`unconfirmed_answer_evidence`），描述的是系统对自己识别质量的判断，不是学生的失分原因，也不适合展示给学生。`grading_evidence` 是混合数组，既有 `{"stage": ...}` 记录也有评分点记录，读取时按是否含 `point`/`matched` 键过滤。

**最弱的一环**：知识点。`ExamQuestion.knowledge_point` 是自由文本、上限 100 字符，AI 识别阶段**完全不填**（`question_answer_workflow.py` 创建识别项时不写该字段），只能靠老师手打。没有知识点就没有归因聚合、没有掌握度、没有复习推荐——**这是错题本真正的地基，必须先补**。

## 4. 数据模型

新增表，全部与学校租户解耦：

```
LearnerProfile                 终身学习者身份
  id, user_id(unique, FK user SET NULL)
  display_name, grade_band
  status, created_at
  # 不带 org_id。学校归属通过 enrollment 表达。

LearnerEnrollment              在校经历（一个 learner 可有多条）
  id, learner_id, org_id, class_id(SET NULL), student_id(FK Student SET NULL)
  school_year, subject_scope, started_at, ended_at
  # 转班/升学/转学 = 结束旧记录 + 新增一条，历史不断

WrongQuestionEntry             错题快照（写入后不可变）
  id, learner_id, source(exam_release|manual)
  # 弱引用：来源可以消失
  exam_id / submission_id / annotation_id / question_id  ── 全部 SET NULL
  # 强快照：自带一份，不依赖来源
  exam_title, subject, grade_level, exam_date, class_name_at_time
  question_label, question_text, question_type, max_score, score
  standard_answer_text, scoring_points(JSON)
  student_answer_text
  teacher_comment
  loss_reason_tags(JSON)       ── 有限标签集，可聚合
  loss_reason_text             ── 给学生看的一句话
  crop_storage_key             ── 独立留存，见 5.2
  released_at, created_at

WrongQuestionKnowledgeLink     错题 × 知识点
  entry_id, knowledge_point_id, confidence, source(ai|teacher|student)

KnowledgePoint                 知识点树
  id, subject, grade_band, code, name, parent_id, source, aliases(JSON)

LearnerMastery                 掌握度（按知识点聚合）
  learner_id, knowledge_point_id
  attempts, wrong_count, last_wrong_at, mastery_score, updated_at

WrongQuestionReview            复习记录（间隔重复）
  id, entry_id, learner_id, reviewed_at
  result(again|hard|good|easy), interval_days, ease, next_due_at
```

设计要点：

- `WrongQuestionEntry` 是**不可变快照**，与 D-024「成绩以不可变快照发布」一致。老师改分重新发布 → 生成新 entry 并把旧的标记 superseded，不原地改写。
- 失分原因分两层：`loss_reason_tags` 是**有限标签集**（如 概念不清 / 公式用错 / 计算失误 / 单位遗漏 / 审题偏差 / 步骤缺失 / 表述不完整 / 空白未答），只有有限集合才能跨考试聚合出「你三次都栽在单位上」；`loss_reason_text` 是给学生看的自然语言。自由文本不能做统计。
- 掌握度是**派生**数据，可以随时重算，不作为唯一真相。

## 5. 关键机制

### 5.1 发布即快照

挂在成绩发布这个已有的动作上（`POST /grading/exams/{exam_id}/score-releases`）：发布成功后异步生成错题快照。判定进本的规则第一版从简：得分率低于 100% 即进本，`score == max_score` 不进；全对的考试不产生条目。

为什么挂在发布而不是批改完成：发布是教师确认的语义边界，也避免复核过程中的中间态污染学生数据。

### 5.2 裁切图必须独立留存

现在的裁切图读取是「查 `ProcessingTask.output_ref.region_crops` 的 storage_key，失败就按 `ExamRegion` 坐标实时重裁」（`exams.py` 的 crop 端点）。两条路都依赖考试和答卷还在。

错题本必须在快照时把图**复制**到学习者命名空间，例如 `learners/{learner_id}/entries/{entry_id}.webp`，并转 WebP 压缩。存储量级估算：一个学生一年约 100 道错题 × 约 50KB ≈ 5MB，1000 名学生的学校约 5GB/年——需要实测校准，但完全可承受。

同时这是**数据最小化**：错题本只存题区裁切，整卷影像留在学校侧，不进学生个人库。

### 5.3 知识点体系先落地，AI 自动打标

顺序不能颠倒：先有知识点树，再让 AI 在题目识别阶段自动打标，教师在确认题目时顺手校正（现在的确认界面已经有知识点和难度输入框，只是默认空着）。

- 知识点树按学科 + 学段建，第一版只做**物理和数学的初中段**，用课标章节体系作为骨架，不追求学术完备。
- AI 打标复用已有的识别流程，输出「知识点 id + 置信度」，低置信度不写入、交给教师。
- 老师的校正要能回流：同一道题被多个老师改成同一个知识点，说明 AI 的映射需要调整。

### 5.4 复习闭环才是「依赖」的来源

错题只是躺在那里就没有价值。三个动作：

1. **间隔重复**：简化 SM-2，间隔 1/3/7/15/30 天，每次复习只问「还会不会」，不做打字答题。
2. **考前突击**：临考前按「该学科 + 该知识点错误密度 + 距上次复习时间」排序生成一份复习清单，可打印成 A4。这是家长最买账的形态。
3. **相似题**：先用本校题库按知识点 + 难度检索真题（`question-bank` 已支持跨考试），检索不到再用 LLM 生成变式题，且必须标注「AI 生成，未经教师审核」。

### 5.5 归因摘要

- 单题归因：展示 `grading_evidence` 里未命中的评分点，零额外模型成本。
- 整场考试归因：一次 LLM 调用总结「这次主要丢在哪」，写入快照，不每次打开都重算（现有教师端班级学情分析每次重算且不缓存，学生端不能照抄这个做法，人数会放大成本）。
- 长期归因：按 `LearnerMastery` 聚合，纯统计，不用模型。

## 6. 客户端形态：建议微信小程序优先，不做 App

`plan.md` §15 原计划是 Web MVP 之后做 React Native + Expo App。对学生端这个具体场景，建议改为小程序优先：

- 分发靠老师在班级群转发，小程序不用下载安装，这是唯一能跑通的获客路径。
- **家长要看**。家长愿意打开的是微信里的东西，不是又一个 App。
- 错题本的使用形态是「每周几分钟查阅 + 考前打印」，不需要 App 级能力。
- 少维护一个客户端。`AGENTS.md` 的视觉规范本来就写了「与微信小程序端同一系统」，色板已经对齐。
- 学生 Web 端保留，用于打印和家长在电脑上查看，不单独投入。

App 继续后置，等错题本被验证有人用再说。

## 7. 合规：这是硬门槛，不是后置项

学生端一旦面向未成年人，合规就不是文档问题而是能不能上线的问题。当前仓库在这方面**基本空白**（无监护人同意、无保留期、无导出、无删除流程）。

- **未成年人个人信息**：《个人信息保护法》对不满十四周岁未成年人的个人信息要求取得监护人同意，并需单独制定处理规则。错题本长期留存成绩与手写影像，属于典型的敏感场景。
- **两条路径要先选**：
  - **B 端委托路径（推荐先走）**：学校是数据控制者，点凡阅卷是受托处理者，学生端是学校服务的延伸，同意链路由学校与家长签署。落地快、风险低。
  - **C 端直连路径**：学生或家长自行注册、数据跟人走。这才是真正的「伴随一生」，但需要完整的监护人同意、独立隐私政策与注销机制。
  - 现实做法是先 B 端跑通产品，再给学生提供「把我的错题本迁移到个人账号」的选项，迁移那一刻走 C 端同意流程。
- **双减与教育 App 备案**：2021 年《关于进一步减轻义务教育阶段学生作业负担和校外培训负担的意见》第 15 条明确，线上培训机构不得提供和传播「拍照搜题」等惰化学生思维能力的不良学习方法；教育部随后要求相关作业 App 下线整改、重新审核备案。**这直接意味着不要把参考应用的「拍题答疑」搬过来**。教师主导、不给现成答案的错题复习是政策友好的形态。面向中小学生的移动应用可能需要教育移动互联网应用程序备案，上线前须核实。
- **数据权利**：错题本必须支持导出（PDF + JSON）与删除。注意区分两类数据——学校的教学记录（成绩原件，学校留存）与学生的个人错题本（学生可删）。删除学生的错题本不应影响学校的成绩档案。

以上需要法务确认，本文档不构成法律意见。

## 8. 商业模式与成本

- 成本随学生数线性增长（存储 + 归因），收入目前来自学校（答卷额度）。现有 billing 只有「答卷份数」一个计量单位，学生端会引入第二个成本中心。
- 三种可选：算进学校套餐（按在校学生数定价）、家长增值订阅（考前复习卷 + 长期报告）、免费引流（用学生留存反向锁定学校续费）。
- 建议第一版**算进学校套餐**，不单独向家长收费：先证明留存，再谈变现。但要在 `ModelUsageEvent` 里能按学生端用途单独归集成本，否则算不清毛利。

## 9. 分阶段落地

**阶段 A：把「为什么错」给到学生**（不需要新客户端，现有 Web 学生端就能看到效果）
1. 知识点树 + AI 自动打标 + 教师确认界面回流。
2. 学生逐题详情 API：题干、标准答案、我的作答、失分原因、裁切图，带 learner 作用域的图片访问。
3. 发布即快照：`WrongQuestionEntry` 落库，裁切图独立留存。
4. 现有 `my.exams_.$examId` 接通图像与失分原因（组件 `WrongQuestionsSection` 已具备渲染能力，缺的是权限和数据）。

**阶段 B：错题本成型**
5. `LearnerProfile` + `LearnerEnrollment`，跨考试跨学年聚合，转班不断档。
6. 掌握度与知识点视图、错题本列表与筛选、导出 PDF/JSON。

**阶段 C：形成依赖**
7. 间隔重复复习 + 考前突击清单 + 相似题推荐。
8. 微信小程序端（学生 + 家长视角）、消息提醒。

**阶段 D：可携带与合规**
9. 监护人同意、隐私政策、保留期、注销与数据迁移到个人账号。
10. 成本归集与定价。

阶段 A 是唯一无争议、且立刻能看到产品效果的部分，建议先做完 A 再确认 B 的身份模型。

## 10. 明确不做

- **不做拍照搜题**。政策明令整改，且与「教师权威判分」的产品定位冲突。
- **不做通用 AI 聊天答疑作为首页**。红海，且会把产品拉成学习工具箱，丢掉自己的数据优势。
- **不做题库售卖**。版权风险。
- **不让学生自己拍照录错题**作为第一版主路径。零录入才是差异化；手工录入可以作为后期补充入口，但不能是主线。

## 11. 待决策

1. 学生端形态：微信小程序优先，还是坚持 `plan.md` 里的 React Native App？
2. 合规路径：先走学校委托，还是直接做 C 端账号？这决定 `LearnerProfile` 是否从第一天就与 org 解耦。
3. 进本规则：所有丢分题都进，还是设阈值（如得分率低于 60%）？
4. 学生能否看到标准答案？看到会不会削弱下次考试的效果，还是正是复习所需？建议可见，但只在成绩发布后。
5. 知识点树第一版覆盖哪几科哪个学段？
6. 成本归属：算进学校套餐，还是家长订阅？
