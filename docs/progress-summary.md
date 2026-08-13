# 进度摘要

更新时间：2026-08-13

### 2026-08-13 CI 流水线与文档补齐

- 补上仓库此前缺失的 GitHub Actions（`.github/workflows/`）：
  - `lint-backend`：`ruff check` + `ruff format --check`，范围 `backend/app` 与 `backend/tests`。
  - `test-backend`：`postgres:18` + `redis:7-alpine` service 容器 → `alembic upgrade head` → `backend/scripts/tests-start.sh`（coverage + pytest）→ `scripts/smoke-openapi.py`，覆盖率报告作为 artifact 上传。
  - `test-frontend`：`npm ci` → `biome ci` → `tsc -p tsconfig.build.json` → `vite build`。
  - `lint-workflows`：`zizmor` 审计 workflow 自身，与 `.pre-commit-config.yaml` 中的钩子同源。
- 实测基线（Ubuntu 24.04 + Python 3.13.15 + PostgreSQL 16 + Redis 7.0，非 Docker）：后端 `338 passed, 1 skipped`、覆盖率 67%；`alembic upgrade head` 到唯一 head `c3e5f7a9b1d2`（49 个 revision，无分叉）；OpenAPI 冒烟 25 paths；前端 `tsc`、`biome ci`、`vite build` 均通过；`actionlint` 与 `zizmor` 对四个 workflow 均无告警。
- CI 暴露并修复了两处环境依赖：
  - `send_email` 现在区分 SMTP 传输层异常与投递失败。DNS 解析或连接失败以前会让找回密码接口返回 500；现在尽力投递流程只记日志，`raise_on_error=True` 的公开注册验证邮件仍向上报错。
  - 测试环境必须显式提供 `EMAILS_FROM_EMAIL`（`emails_enabled` 依赖它）和 `BILLING_ENFORCEMENT_ENABLED=false`（测试数据没有学校合同，与 `.env.example` 的本地配置一致；账单与商业化用例自己 monkeypatch 打开门禁）。
- 一次性执行 `ruff format`，对齐 47 个此前未格式化的文件，之后格式检查才能给出稳定信号。`backend/scripts` 与根 `scripts/` 不纳入 lint 门禁：运维与评测脚本按设计使用 `print`（T201）。
- mypy 与 ty 暂不纳入门禁：strict 模式下分别有 588 和 489 条告警，绝大多数是 SQLModel/SQLAlchemy 表达式（`col.in_`、`order_by`、`join` 条件）的误报，需要单独一轮类型清理，见 AEG-060。
- 文档补齐：本文件、`docs/issue-backlog.md`、`docs/decision-log.md`、`README.md`、`development.md` 已补上 2026-07-25 与 08-07 两次提交带来的商业化能力。此前文档停在 07-24，与代码相差约 28k 行。

### 2026-08-07 商业化试运行发布（commit `0884bfd`，19 个迁移）

代码时间线说明：`a61a5ff`（07-25，9 个迁移）是把下方 07-22 至 07-24 已记录的多租户与工作流工作同步进 git；`0884bfd`（08-07）在其之上加入完整商业化层。两次提交合计约 28k 行，此前均未进入进度摘要。

- **交易闭环**（`/api/v1/commerce`）：`PlanVersion`/`AddonSku` 商品版本、`CommerceOrder`/`OrderItem` 订单、`PaymentAttempt`/`PaymentWebhookEvent` 支付、`InvoiceApplication` 发票、`RefundRequest` 退款、`OutboxEvent` 事务外发。订单状态 `pending_payment → paid → fulfilled`，可至 `refunded`。幂等由四层保证：订单 `idempotency_key` 唯一、支付 `provider_transaction_id` 唯一、微信回调按 `event_id` 去重、支付与履约在 `pg_advisory_xact_lock` + `SELECT … FOR UPDATE` 内串行。一张订单最多一张发票和一笔退款（DB 唯一约束）；续费按 `ends_at = max(paid_at, 上一份 ends_at) + validity_days` 顺延；自动退款仅支持整单且额度未预留未消费，退款后恢复仍有效的上一份合同。
- **计费双轨**：面向学校的「答卷额度」（`AnswerQuotaGrant`/`Reservation`/`Allocation` + `BillableAnswerSheet`，`(org_id, exam_id, billing_identity)` 唯一保证同一份答卷只计费一次，FIFO 消耗）与平台内部的「Token 积分」成本护栏（`CreditGrant`/`Reservation`/`LedgerEntry` + `ModelUsageEvent`）。`GradingRun` 增加 `estimated/reserved/settled_microcredits`、`billing_status` 和 `awaiting_credits` 状态：创建批次时预扣答卷额度（不足 402）与积分，worker 完成后结算。`python -m app.maintenance reconcile-billing` 释放超时预占，`dispatch-outbox` 投递履约事件。
- **模型渠道控制面**（`/api/v1/platform/provider-channels`）：`ProviderChannel` + AES-GCM 加密凭证（AAD 绑定 channel_id，主密钥 `PROVIDER_CREDENTIAL_MASTER_KEY`）、`ProviderModelMapping`（canonical → upstream，含模型发现）、`ModelRoutePolicy`/`ModelRouteVersion`/`ModelRouteVersionTarget`（发布即冻结快照，可灰度回滚）、`ProviderHealthState` 熔断（连续失败置 `circuit_open_until`）、`ProviderInternalRateVersion` 上游成本、`ProviderReconciliationBatch` 对账（支持 New API 同步）、`ProviderAuditLog`。并发用 Redis ZSET 槽位分全局/学校/渠道三级并限制每分钟调用；计费门禁开启时 Redis 故障 fail-closed。私网地址需进 allowlist，公网必须 HTTPS。
- **公开模型目录**：`PlatformModelOffering` + `OrganizationModelSelection`（按 vision / reference_answer / grading 三个 scope 选型）。学校只能看到 `display_name` 与用途，看不到渠道、上游模型名和成本；offering 发布前校验渠道映射、结构化输出能力和对应用途的路由版本已发布。
- **公开注册与试用**：`PendingOrganizationSignup` + Cloudflare Turnstile + Redis 限流；邮箱验证通过后原子创建学校（code `DF-XXXXXX`）、`school_owner`、30 天试用合同、200 份答卷额度和保守用量策略（30 次/分、2 个并发任务）。缺少匹配 `PUBLIC_SIGNUP_TRIAL_RATE_VERSION` 的费率版本时返回 503 且不建租户。默认 `PUBLIC_SIGNUP_ENABLED=false`。
- **学校服务状态**：`active` / `read_only` / `frozen` / `deleting`。`read_only` 的非 GET 请求返回 423，`frozen`/`deleting` 返回 403，且只有 `active` 学校能抢到任务租约。
- **成绩发布**：`ScoreRelease`/`ScoreReleaseItem` 版本化快照，`(exam_id, version)` 唯一。发布门槛为无待复核题且每份答卷已评题数不少于已确认题数；旧版本置 `superseded`；学生端只读快照，不直接看实时批注。
- **基础设施硬化**：OSS 私有 Bucket（`STORAGE_BACKEND=oss` + `backend/scripts/migrate_storage_to_oss.py` 幂等迁移）、`/api/v1/utils/health/live|ready`（ready 校验 DB + Redis + 存储）、`OrganizationJobLease` 学校级任务租约（`(task_type, resource_id)` 唯一，TTL 5 分钟 + 60 秒心跳）、事务 outbox、新增 `platform_admin` 角色。
- **测试**：后端新增 `test_commerce`(8)、`test_billing`(9)、`test_provider_channels`(12)、`test_provider_gateway`(5)、`test_provider_security`(5)、`test_model_offerings`(5)、`test_public_signup`(4)、`test_score_releases`(2)、`test_model_concurrency`(4)、`test_new_api_billing`(2)、`test_job_control`(2)、`test_object_storage`(2)、`test_health`(1)、`test_config_production`(3)。前端新增 Playwright `platform-commerce`、`platform-org-billing`、`platform-provider-channels`、`platform-model-usage`、`platform-directory`、`sign-up`。
- **基准脚本**（离线，不进 CI）：`scripts/grading_concurrency_benchmark.py` 测不同并发配置下的批改吞吐，`scripts/grading_method_benchmark.py` 对比视觉判分路径准确性，`scripts/model_answer_benchmark.py` 让三个模型独立解 18 道物理题并交叉裁判。

### 2026-08-07 Staging 试运行环境上线

- 公网入口 `https://app.dianfandig.com`，跑在 `155.94.192.143`，与服务器上既有的 AISubAPI、独立 PostgreSQL/Redis、Nginx UI 共存但完全隔离。
- 发布使用独立 `compose.staging.yml` 和 `dianfan-staging` project，不读本地开发 override（后者会抢 80/443 并起本地 Traefik）。远端目录固定为 `/opt/dianfan-grading`，共享数据在 `shared/`，发布源码在 `releases/<release-sha>/`，`current` 指向当前发布。
- `服务器部署/deploy-staging.sh <release-sha> <stage>` 分 `config`/`infra`/`build`/`app`/`status`/`logs` 六个阶段；`generate-staging-env.sh` 为每个环境随机生成 `SECRET_KEY`、数据库口令和 `PROVIDER_CREDENTIAL_MASTER_KEY`；`sanitize-staging.sql` 清空渠道凭据并把渠道退回 draft。
- 运维安全：SSH 收敛到 `22022`，公网 `22` 已由 UFW 撤销，fail2ban `sshd` jail 已启用（起因是密码爆破挤满 `MaxStartups` 导致 SSH 假性不可用）。合作伙伴账号 `dianfan-ops` 只有普通 SSH 登录权限，不含 sudo、Docker、生产配置、数据库和上传文件访问。
- 公开注册在 staging 仍默认关闭，启用前需要配置 SMTP 与 Turnstile 站点，且 `VITE_TURNSTILE_SITE_KEY` 是构建期参数，改动后必须重跑 `build` 和 `app` 阶段。

### 2026-07-24 协作批卷 + 视觉系统切换 + 稳定性修复

- 协作批卷：教师任教档案（任教班级 TeacherClassLink + 科目标签，`/users/{id}/teaching`）；考试共享批卷（`shared_grading_enabled` + GradingAssignment 按班分配）；未分完不能发起批改（400 含缺班名）；被分配老师在答卷/批注/复核/成绩只见负责班级、跨班写 403；用户管理可编辑任教、grading 页批改分配卡（班级×老师矩阵，任教优先）、workbench 范围条「你负责：X班」、考试列表「协作」标记（迁移 f7a3b5c9d2e4）。
- 视觉系统切换为小程序同款：唯一强调蓝 #2E5BFF、暖白底 #FAFAF9、墨色三级、hairline 边、语义色收敛；logo 换 BookOpenCheck、图标块中性化、闪光图标仅留两处核心自动化。
- 复核入口统一到横批工作台（`?student=` 定位）；workbench 左侧学生选择列；未分班排最后；裁切缺失有明确空态。
- 稳定性：pypdfium2 非线程安全导致并发后全部 PDF 渲染 422——加进程级 `PDFIUM_LOCK` 串行化根治；E2E 遗留测试考生（流程测试考生）数据已清除。
- 验证：pytest 237 passed（1 个基线环境失败）、前端 tsc/biome/构建通过、双账号实测分配视角差异。

更新时间：2026-07-23（三）

### 2026-07-23（三）简洁化第二批 + 横批工作台 + 品牌定名点凡阅卷

- 品牌正式定名「点凡阅卷」（DIANFAN），产品原则写入 `AGENTS.md`：老师工具、AI 退后台、每题一个决定。
- 批卷工作台重构为「按题横批」：答题大图（缩放/平移）+ 底部固定评分栏（点分=保存+跳下一份）+ 键盘（数字/A/F/空格/←→）+ 可收起评分依据（低置信度自动展开）。
- 去 AI 符号：建议评分/学习建议/自动批改通过率/生成参考答案；置信度仅低时提示；模型/服务商/阈值/并发仅管理角色可见。
- 视觉克制：圆角 10px、阴影近乎不可见改边框区分、渐变仅留主 CTA/激活导航/logo。
- 复核队列说人话：「答案字迹不清/评分依据不足/分数接近边界」+「继续复核 N 题」主入口（workbench 支持 ?filter=needs_review）。
- 系统设置（仅平台超管）：SystemConfig 表 + `/platform/system-config` 读写判题/视觉模型与默认阈值并发，新批次生效，env 兜底。
- 识别内容/标准答案页改紧凑行列表+行内展开编辑；报告去模板化（主要失分摘要、具体化建议、错题裁切图区、雷达降为次要）。
- 步骤改名：导入模板卷→框选题目→确认题目→标准答案→批改批次→成绩；导入中心整页化；考试选择器跟随路由。
- 验证：pytest 229 passed（1 基线环境失败）、Playwright 57 passed/0 failed/7 skipped（外部依赖）、tsc/biome/构建通过。

更新时间：2026-07-23（二）

### 2026-07-23（二）多租户角色体系：平台 × 学校

- 角色模型 6 档：平台侧 `platform_superuser`（超管）/`platform_support`（运营，跨校只读）；学校侧 `school_owner`（总管理员，校内全部+学校设置）/`school_admin`（管理员，管老师学生+全校只读）/`teacher`/`student`（迁移 a7b8c9d0e1f2，userrole 枚举只加不删）。
- Organization 表（name/code/status/exam_sharing_enabled/contact_name）；存量数据回填「默认学校」；User/Exam/ClassGroup 加 org_id（迁移 c4d6e8f0a2b4，班级名改为 (org,name) 唯一）。
- 数据隔离（services/org_scope.py）：platform 看全部；school_owner/admin 看本校；teacher 看自己的+（学校开启共享时）同校只读；写操作限本人考试（school_owner 可写本校）；不可见统一 404。
- 端点：`/platform/orgs` 学校 CRUD+首个总管理员（超管）/详情（运营可读）；`/org/settings` 学校设置（teacher 可读、school_owner 可写互见开关）；`/users/signup` 关闭（管理员创建制）；用户管理按角色分级创建、列表学校隔离。
- 前端：平台控制台（学校列表/详情/新建向导/添加总管理员）；学校设置页（教师间互见开关）；侧栏按 6 角色渲染；登录/注册入口清理；考试信息表单必填校验；班级改学校内共享；全局 403 误踢登录修复（仅凭证失效才登出）。
- 验证：pytest 222 passed（3 个基线环境失败）；前端 tsc/biome/构建通过；双学校真实隔离验证（示范二中 owner 只见本校）；测试学校「示范二中」demo2.owner@example.com 已建。

更新时间：2026-07-23

### 2026-07-23 规范化整改：考试信息 / 角色体系 / 班级学生实体 / 学生端

- 角色体系：`User.role`（superuser/admin/teacher/student，迁移 c8e2f4a6b105 回填）；admin+ 管用户（不能设超管）、teacher 管自己的考试班级、student 仅访问 `/students/me/*`；开放注册默认 student；业务路由对学生 403。
- 班级学生实体（迁移 e7b3c5d9f204）：`ClassGroup`/`Student`/`ExamClassLink`/`StudentSubmission.student_id`；演示数据回填 001班/002班 各 4 人；导入答卷自动归位（不存在则自动创建）；学生可绑定 role=student 登录账号。
- 考试信息：`exam_date`、`description`、班级多对多关联（迁移 f1a2b3c4d5e6）；新建/编辑考试完整表单（名称/科目/年级/班级/时间/备注）；考试列表显示班级 Tag、考试时间、进度（替代失效的 status）。
- 学生端：`/my/exams` 成绩卡片列表 + `/my/exams/$id` A4 个人报告（只读、可打印）；未绑定档案显示引导空态；登录按角色分流、路由守卫、侧栏按角色渲染。
- 前端新增页：班级学生管理（班级 CRUD + 名单 + 批量添加 + 绑定账号）；用户管理角色化（角色列 + 角色下拉）。
- 命名修正：步骤「导入」→「导入卷面」、「批量批改」→「批改批次」；toast 标题中文化；导入中心从弹窗改为整页（弹窗保留给步骤条入口，共用 ImportCenterTabs）；考试管理提至主导航第二位；「进入」按钮按进度跳转（完成→批卷工作台）。
- 裁切图端点回退：批注无持久化裁切时按模板区域实时裁切（修复批卷工作台裁切图 404）。
- 验证：后端 pytest 189 passed（3 个基线环境失败）；前端 tsc/biome/生产构建通过；学生账号（刘雨欣）真实登录验证学生端数据与隔离。

更新时间：2026-07-22

### 2026-07-22 前端 UI 全面重构（对齐「智批 AI」原型）

- 设计令牌重写（`frontend/src/index.css`）：靛紫主色 #6366F1、18px 大圆角、shadow-card、深浅双主题；移除「试卷红笔」视觉（PaperRule/RedSeal/Noto Serif）。
- App Shell：浅色侧栏（工作台/导入试卷/批卷工作台/改卷报告/班级分析/重新组卷 + 管理区）+ 顶栏（页面标题、考试选择器、全局搜索占位、通知、头像）；产品名统一为「智批 AI」。
- 组件库：`components/Common/`（StatCard/Tag/Chip/ConfBadge/ProgressBar/PageHead/EmptyState/AvatarGradient）+ `components/charts/`（recharts 封装：Line/Donut/Bar/HBar/Radar + 手写 Heatmap）。
- 新页面：工作台重设计（统计卡/批卷任务/趋势/快捷操作）；批卷工作台三栏页（学生列表+题目裁切对照+AI 评分卡，改分/采纳 AI/评语，续页合并）；改卷报告（A4 版式 + 打印导出 PDF）；班级分析（分布/分数段/各题得分率/AI 学情报告）；重新组卷（知识点勾选+难度+题型数量+薄弱点优先）。
- 后端：`ExamQuestion`/`QuestionRecognitionItem` 加 `knowledge_point`、`difficulty`（迁移 e5f7a9c1d304）；`StandardAnswer.exam_region_id` 放宽可空；新增 `GET /exams/question-bank`、`POST /exams/compose`、`POST /exams/{id}/analysis-report`（LLM 四段学情报告，不缓存）；区域接口返回题目关联（question_key/role）。
- 验证：后端 pytest 164 passed（3 个基线环境失败）；前端 tsc/biome/生产构建通过；各页面 Playwright 深浅色截图核对。

更新时间：2026-07-18

### 2026-07-18 识别复核门禁与稳定性复核

- 对同一张 v14 双页物理卷（1–17 题）连续运行 3 次，题块召回均为 `17/17`；印刷题干字符准确率中位数 `97.54%`、最差 `97.10%`；学生答案字符准确率中位数 `96.72%`；答案关键点准确率中位数 `100%`、最差 `96%`；平均置信度中位数 `93.71%`；总耗时中位数 `28.1s`、最慢 `30.4s`。
- 参考算法 Node 服务新增通用 `deriveReviewSignals()` 复核门禁，不依赖题号或固定坐标：低置信度、空题干、无法辨认/截断/缺失、答案证据分歧进入 `reviewRequired`；跨页合并作为信息提示。
- 结果页和模型基准记录显示门禁复核数量；`npm run test:ocr` 通过，前端生产构建通过；当前前后端/Node 服务健康检查均返回 200。
- 后端 pytest 本轮未执行破坏性测试：当前开发库不是专用 test 数据库，测试安全门主动拒绝，未绕过该保护。
- 针对 `2_试卷分析文件/material/样本2` 完成矩形校正专项验证：`0_0`–`0_2` 正确识别为双页展开，`0_3`–`0_4` 正确识别为单页；修复了竖页误二分、180°旋转后页序倒置、旧 opposite-axis fallback 重复页和页缝过度重叠问题。输出见 `outputs/sample2-rectangle-rectifier-v5/` 与 `outputs/sample2-rectangle-rectifier-v6/`。

## 当前阶段

2026-08-13：**商业化试运行**。教师批卷主流程（导入 → 框选 → 确认题目 → 标准答案 → 批改 → 复核 → 成绩发布）已端到端打通；多租户角色体系、SaaS 计费与答卷额度、模型渠道控制面、公开模型目录、订单与支付闭环已落地；staging 环境 `https://app.dianfandig.com` 已对外可访问；CI 已就位。

当前阶段的主要工作不再是补业务功能，而是：真实规模验证（数百份量级的识别准确率与成本）、把仍在 In Progress 的算法项（题目自动分割、扫描质量门禁确认闭环）收口、以及把商业化闭环缺的最后一段（学校端自助购课界面、outbox 真实投递）补齐。

- 题目—答案工作流规范与验收入口：`docs/question-answer-workflow-spec.md`。
- 生产运行手册（含商业运营闭环、OSS 迁移、备份恢复、告警与故障处置）：`docs/production-operations.md`。
- staging 部署与服务器边界：`服务器部署/新服务器登录说明.md`、`服务器部署/AGENTS.md`。

### 2026-07-14 题目—答案—批改闭环

- 新增 `ExamQuestion`、多区域关联、识别运行/项目、答案准备运行/项目和 `StandardAnswerRevision`。
- Alembic `c7d9e1f3a526` 已在当前数据库升级；旧版题区/答案回填、downgrade、re-upgrade 均在临时库通过。
- `/exams/$examId/questions` 已支持多文件 Node 参考识别、考生卷面作答、真实置信度、人工修订/排除和正式确认。
- `/exams/$examId/answers` 已支持 `pomoai / gpt-5.6-sol` 解题、答案文件上传、匹配冲突处理、评分准则确认、修订历史与发布锁定。
- 新卷子首次建库流程已明确：题目源页面优先使用空白卷；没有空白卷时可上传一份代表学生卷提取印刷题目，考生作答只作为旁证展示，不进入正式题干；标准答案只在题目确认后生成或导入，发布后作为不可变版本复用。
- 批改批次创建时锁定题目对应的已发布 revision；多区域题目只生成一个 `GradingItem`，多个区域一起提供给视觉模型。
- 本次后端全量测试：临时 PostgreSQL `118 passed`；本次改动 Ruff 全通过。
- 前端 Biome 与生产构建通过；Playwright `question-answer-workflow-live.spec.ts`：`2 passed (9.0s)`。
- 真实两文件物理卷草稿批次 `12896cfa-ebc3-41bd-8836-aeab9b6778b5` 已完成：22 题、总耗时 70.25 秒、平均置信度 94.77%，未自动确认。
- 当前服务健康：前端 `5173`、后端 `8000`、Node 参考服务 `3417` 均返回成功。

周期 1 到周期 4 前置能力衔接：Web 上传、PDF/图片分页预览、手工题区标定、学生答卷上传、答卷预览、模板题区叠加、单题裁剪接口、配准状态记录、人工确认流程、教师复核页、结构化批注、学生答卷处理任务管线、真实题区裁剪产物、OCR 初稿字段/服务接口、手机照片预处理后端入口、PaddleOCR GPU 独立服务、题目区域候选分割接口、标定页候选草稿导入、标准答案模型/API 和标准答案工作台已实现。下一阶段主线是“学生答案识别 -> 评分草稿 -> 教师复核”，优先把标准答案接入 Worker 和复核页。真实自动配准 homography、AI 判分增强和批注 PDF 导出仍待后续周期接入。

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
- 已新增 StandardAnswer 数据模型、Alembic migration 和考试下标准答案 CRUD API；标准答案第一版只能绑定 `region_type=question` 的 `ExamRegion`，同一题区最多一条。
- 标准答案 API 已覆盖创建、读取、更新、删除、重复题区冲突、非 question 题区拒绝和跨用户权限边界；OpenAPI smoke 已包含 `/api/v1/exams/{exam_id}/answers`。
- 前端 OpenAPI client 已同步生成 `StandardAnswer*` 类型和 `ExamsService.*StandardAnswer*` 方法。
- 已新增 `/exams/$examId/answers` 标准答案工作台，考试列表新增 Answers 入口；教师可按题区录入参考答案、满分、rubric、评分点和 `draft|ready` 状态。
- 标准答案工作台已显示题区覆盖状态：ready、draft、missing；无 question 题区时提示回到 Marking。
- 标准答案工作台 E2E 已通过：`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/snap/bin/chromium ../node_modules/.bin/playwright test exams.spec.ts -g "Can prepare a standard answer" --project chromium`，2 passed。
- 已新增批注评分草稿字段：`suggested_score`、`suggested_comment`、`grading_confidence`、`grading_reasons`、`grading_status`、`answer_key_updated_at`。
- Worker 已接入 ready 标准答案：OCR 成功且置信度达标时写入建议分和 reasons；无 ready 标准答案时写 `skipped_missing_answer`；OCR 不可用或低置信度时写 `needs_review`。
- 标准答案更新后，同题区已有 `succeeded/needs_review` 评分草稿会标记为 `stale`，不覆盖教师最终 `score/comment/status`。
- 教师复核页已显示标准答案、rubric、OCR draft、评分草稿状态、建议分、建议评语和置信度；Apply suggestion 只填入最终表单，仍需教师保存批注。
- 手机文档扫描已升级为 `hybrid_v2`：OpenCV 页面候选与独立 Homography、Gemini 3.5 Flash 歧义边界回退及一次几何反馈重试、逐页 Paddle DocPreprocessor 方向/曲面展开、比例与清晰度安全门控。
- 模板卷、答案卷和学生答卷图片上传统一支持 `preprocess=auto|force|none`；默认保留原图，校正 PDF 作为工作文件，并保存页面四边形、Homography、质量分、警告、分割策略和分阶段耗时。
- 前端试卷页面与学生答卷列表已显示扫描通过/需复核、质量百分比、页面策略、原图保留状态、总耗时和中文质量提示。
- 真实 `参考算法/2_试卷分析文件/material/2.jpg` 已验证输出两页；Gemini 页面 polygon 实际跑通。逐页 UVDoc 虽正常返回，但清晰度从 Homography 的约 532/700 降到约 286/340，现已由质量门控拒绝并保留更清晰的 Homography 结果。
- Alembic 已升级到 `e2f4a6c8b013`；后端全量测试 `125 passed`，扫描服务专项测试 `12 passed`，前端生产构建通过。
- 真实 API 上传 `material/2.jpg` 已生成两页 `2-scanned.pdf`，原图 ID、91% 质量分、去重后的风险类型及 OpenCV/Gemini/UVDoc/总耗时均已持久化。页面四边形采用 OpenCV 外沿与 Gemini 中缝融合，安全边从约 4.5% 收紧到约 0.4%。
- 新增 `scan-preprocessing-live.spec.ts`，系统 Chromium 下验证“需要复核 · 91%”“视觉双页边界”“已保留原图”“扫描耗时”和中文警告均在试卷页面弹窗可见，1 passed；截图保存于 `outputs/scan-validation/scan-metadata-dialog.png`。
- 2026-07-15 完成真实物理双页答卷全流程验收：原始 GUI 按“上传 -> 版面分析 -> 8 路题块 OCR”识别出 18-22 共 5 题，全部保留考生作答；原始 GUI 实测总耗时 54.4 秒，截图为 `outputs/reference-gui-full-flow.png`。
- 已发布 GPT-5.6 SOL 标准答案 revision 1，卷面分值由题面标题锁定为 18题4分、19题6分、20题10分、21题10分、22题12分，共 42 分。
- 主网站 GUI 已完成“Gemini 识别预览 -> 教师确认 -> GPT-5.6 SOL 批改 -> 分层复核队列”，识别批次 `ce89cbd7-e69b-4949-8878-0787b2df2a7d` 与批改批次 `c023aa2b-bb53-4dae-8f5e-619f35bfc125` 均为 completed，5/5 题、0 失败，建议总分 29/42，平均置信度 66%，4 个低置信度题进入复核。
- 本轮真实流程修复了四类集成缺陷：识别预览创建访问不存在字段导致 500；已确认 OCR 覆盖分支引用未定义变量；前端题块轮询停在 0/N 且刷新后丢失识别批次；参考算法证据不一致时清空首轮 OCR。现在保留首轮结果并降置信度，作图题可追加整块视觉描述，低置信度统一进入复核。
- 批改批次已记录分阶段耗时：方向 12.709 秒、版面 20.169 秒、裁切 0.132 秒、OCR 149.767 秒、GPT 判题墙钟 38.182 秒、端到端 206.526 秒；主网站截图为 `outputs/main-grading-full-flow.png`。
- Playwright 真实 GUI 验收通过：`reference-source-gui-live.spec.ts` 1 passed（1.1m），`main-grading-full-flow-live.spec.ts` 1 passed（3.7m）；测试不硬编码题号、题数或旋转角度。
- 2026-07-15 修复 OCR 置信度校准失真：宽/聚焦证据改为比较完整规范化转写，允许一方多带草稿数字，但 `100N`/`600N` 类数字冲突仍进入复核；核验服务网络失败不再强制压到 60%。
- 修复后真实 Gemini 复跑识别批次 `10b325e3-77ca-4ccc-ad05-22853edeba0c`：5/5 成功、0 失败，置信度为 90%/90%/60%/90%/90%，平均 84%；第 20 题因卷面涂改造成双视图真实分歧，保留 60% 复核。方向 10.979 秒、版面 22.806 秒、裁切 0.133 秒、OCR 49.087 秒、总计 75.097 秒。
- 2026-07-16 将“题干圈画”从学生答案中拆分为独立 `printed_question_marks`：第 19 题的“阻力对”会保留为可审计题干标记，但不再进入 `studentAnswer` 或后续判分。选填词“同一”、选项字母 `C`、计算式和显式划改仍保留。
- 主站识别预览已显示“题干标记（不参与判分）”。Node OCR/版面回归通过，Ruff、Python compileall、RecognitionItemPublic schema 校验和前端生产构建通过；pytest 因当前连接开发库而被专用测试库安全门阻止，未绕过保护。
- 已新增 `answer_slots_v1`：自动识别印刷小问和填空数，将答案映射为 `answer_entries`，把题干批注/草稿放入 `unassigned_evidence`，生成仅含已归属内容的 `gradingAnswer`。第 19 题可映射为“(1)同一、(2)匀速直线运动、(3)C”；第 20 题可拆成 5 个填空槽；第 22 题题干旁的 `1`/`P=W/t` 可进入未归属证据而不直接判分。
- 主站预览已显示逐小问/逐空结构和“未归属证据（不直接判分）”。Node 回归、Ruff/compileall、判分隔离门直接校验及前端生产构建通过，前后端与 Node 服务已加载新字段。
- `answer_slots_v1` 真实复跑批次 `fe1824ac-c0ea-42ee-8f22-c5b9e64c5e63`：5/5 成功，总耗时 92.627 秒。第 19 题的 `student_answer` 已清理为“同一/匀速直线运动/C”。真实数据同时暴露三个反例：第 20 题用空格而非逗号分隔多空答案；第 21/22 题首行以“解:(1)”开头；无小问标签的顺序答案曾被重复放入未归属证据。三个反例已固化为回归测试并修复。
- 同一批次第 21 题再次出现首轮 OCR 语义纠错为 `100N`，但系统已标记为 60% 和双视图分歧。新增 `grading_eligible`：低于 0.8、双视图分歧、核验失败、存在缺失槽或无法辨认时明确标记为“不可直接自动判分”；主站同时展示扩边复核候选。
- 后端已实际执行 `grading_eligible` 安全门：不合格识别不再调用 GPT/规则判分，不写建议分，保留原成绩并进入人工复核，审计来源为 `auto_blocked`。旧批次未包含该字段时保持兼容；新批次字段存在但为空时不得回退到未分层全文。

## 进行中

- 2026-07-21 物理样本 2 的当前实现、验证、数据库批次和剩余工作已固化到 `docs/progress-2026-07-21-physics-sample2.md`；原始卷面和关键产物归档于 `data/archives/physics-sample2-2026-07-21/`。

- 在复核页核验作图题与低置信度涂改题；当前第 18 题图形描述仍不足以自动锁定最终分数。
- 完善识别预览中的逐题编辑/重试入口，使教师能在确认前修订个别图形题或边缘裁切题。

## 下一步

1. 扩大真实规模验证：数百份量级的批改，观察识别准确率、耗时和模型成本，并核对答卷额度与积分账本。
2. 补齐商业化闭环最后一段：学校端自助购课界面（下单/微信支付 API 已就绪，前端只有平台侧工作台）、outbox 真实投递（当前只写日志）。
3. 把题目自动分割从 `3 pass / 3 review / 1 fail` 提升到无 fail（AEG-035），并完成扫描质量门禁的教师确认闭环（AEG-032）。
4. 复核效率优化：批量通过、按题型筛选、键盘快捷键；成绩与批注导出（Excel/PDF）。
5. 在复核页确认物理样本剩余作图题与低置信度涂改题，并为作图题输出结构化视觉证据。
6. 让 Playwright 的非 live 用例进入 CI（AEG-061），以及 mypy/ty 类型债清理（AEG-060）。

## 风险与阻塞

- staging 是单机单实例，与 `docs/production-operations.md` 要求的「Web/API 至少 2 个实例、worker 至少 2 个实例、RDS 与 Redis 高可用」不一致；正式商用前必须补齐，或明确 staging 仅作试运行。
- staging 仍使用容器内 PostgreSQL 与本地上传目录，尚未切到 RDS 与私有 OSS；`backend/scripts/migrate_storage_to_oss.py` 已就绪但未执行。
- 商业化闭环有两处未闭合：学校端没有自助下单界面（API 与 SDK 已具备），`OutboxEvent` 的 dispatcher 只记录日志并标记完成，没有真正对接邮件或财务系统。
- 微信支付退款目前只推进数据库状态机，未见调用微信退款接口；上线收款前必须确认真实退款链路与对账口径。
- mypy 588 条、ty 489 条告警，绝大多数是 SQLModel 表达式误报，但也因此掩盖了真实类型问题；类型门禁暂不可用。
- Playwright 的 live 用例依赖真实模型 Key 与本机 Chromium（`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/snap/bin/chromium`），无法进 CI；CI 目前只覆盖后端 pytest 与前端构建。
- `.env` 已从仓库移除并改为 `.env.example`（commit `0884bfd`），但历史提交中仍存在过旧的 `.env`；轮换密钥前不要假设历史凭据已失效。
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
