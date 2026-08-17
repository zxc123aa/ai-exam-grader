# 批卷管线第一步（版面分割）提速 — 工作报告

> 目标：降低批卷管线第一遍模型调用（版面分割/题目区域识别）的单次耗时。该步骤每次运行都要为每一页串行付出 2~3 次模型调用 + 全分辨率原图输入的成本，与缓存、冷启动无关。

---

## 一、问题分析

### 当前链路

```
execute_question_recognition (backend)
  → process_stored_files → Node 参考算法服务 /api/layout
  → analyzeLayout (参考算法/源码/server.js)
```

`analyzeLayout` 对每一页串行执行：

1. `detectRotation` — 方向判断模型调用：原图旋转成 4 张候选图（每张 900×900），模型挑一张（4 张 × 2×2 = **16 tile** 视觉输入，输出只有一个数字）
2. deskew — 本地 CPU 投影纠偏（快）
3. **版面分割主调用** — 全分辨率转正图 + 要求输出最多 40 个题目块的 JSON（输入图像 token 多 + 输出 token 长，耗时大头）
4. `refineLayoutRegions` — 本地投影精修（快）
5. `requestPrintedBoundaryAnchors` — 条件触发的第三次模型调用（边界可疑时）

三个模型调用严格串行，一页等 2~3 个往返；一场考试 N 页，批量等完才能进入下一步。

### 两个"冤枉钱"

- **`assumeUpright` 传了但没用**：后端在文档已完成预处理转正时会传 `assumeUpright`（region-candidates 路径），但 Node 端 `analyzeLayout` 一直无视它，每次仍做方向判断。
- **分割阶段不压图**：拍照批改（snap）已在调用前压到长边 1600，但版面分割这条路仍喂全分辨率原图（300 DPI A4 ≈ 20 tile）。

---

## 二、修改内容

### ① 版面主调用输入压缩（`参考算法/源码/server.js`）

- 新增 `layoutModelImage()`：长边超过 `LAYOUT_MODEL_MAX_SIDE` 才重编码，否则原样返回。
- 尺寸达标但体积超过 `LAYOUT_MODEL_SKIP_BYTES`（800KB，与后端 `downscale_image_for_model` 的 `SKIP_BYTES` 对齐）的图（如高噪 PNG）也重编码为 JPEG，避免大体积小图。
- **只有发给模型的那份被压缩**：`uprightImage` 保持全分辨率，供投影精修、锚点确认与后续 OCR 裁切使用；模型输出是 0-1000 归一化坐标，压缩不影响坐标映射与下游清晰度。

### ② 方向判断候选图 900 → 768（`参考算法/源码/server.js`）

- 候选图长边从 900 压到 `ORIENTATION_MODEL_MAX_SIDE`（默认 768）：每张从 2×2=4 tile 降到 1 tile，四张共 16 → 4 tile。
- 768 是 Gemini tile 的临界尺寸（≤768 每张 1 tile，769 起跳回 2×2）；判断文字方向不需要更高分辨率。

### ③ `assumeUpright` 跳过方向判断（Node + 后端）

- Node 端：`analyzeLayout` 收到 `page.assumeUpright === true` 时整个跳过 `detectRotation` 模型调用，rotation=0 直接进入 deskew + 版面分割；返回对象新增 `orientationSkipped` 字段用于确认。严格 `=== true`，防止字符串 `"false"` 等误触发。
- 后端（`backend/app/services/reference_algorithm.py`）：
  - `process_stored_files` 按 `document.preprocessing_status == "completed"` 给每页带 `assumeUpright`（用 `getattr` 防御，兼容无该字段的调用方）。
  - `_process_pages` 把 `assumeUpright` 透传到 `/api/layout` 请求 payload。
- region-candidates 路径（`layout_stored_file`）原本就传该标记，本次改动后 Node 端开始生效。
- 不享受跳过的路径：`process_stored_file`（单数，被 `recognition_workflow.py` 与 reference-recognition 调试接口使用）拿不到 document 对象，保持原行为。

### 环境变量（均可选，Node 服务）

| 变量 | 默认 | 范围 | 说明 |
|---|---|---|---|
| `LAYOUT_MODEL_MAX_SIDE` | 1600 | 768–4096 | 版面主调用输入长边上限 |
| `LAYOUT_MODEL_JPEG_QUALITY` | 85 | 40–95 | 版面主调用 JPEG 质量 |
| `ORIENTATION_MODEL_MAX_SIDE` | 768 | 384–1024 | 方向判断候选图长边上限 |

管线元数据（`pipelineMetadata`）新增 `layout_model_image` 与 `orientation_model_image` 两个字段，部署后可确认配置生效。

---

## 三、验证情况

- 后端 `py_compile` 通过。
- 用 mock 单测验证了后端三种情况：`preprocessing_status == "completed"` → `assumeUpright=True`；其他状态 → `False`；字段缺失（legacy 调用方）→ `False` 不崩；以及 `_process_pages` 的 payload 透传。
- 完整 pytest 未跑成：本机 PG 测试数据目录已不存在（2026-08-13 搭的本地环境被清理，与本次改动无关）。`test_reference_algorithm.py` 本身是纯单测（断言 usage 与部分字段，不比对 payload 全量），等价行为已用 mock 覆盖。
- Node 端本机无 node 运行时，未做语法检查；改动均为函数级插入，已通读复核。

---

## 四、预期效果（估计值）

- 版面主调用（`regionModelElapsedMs`）：输入 20 → 6 tile + 上传体积约降一个数量级，**预计省 20~30%**（输出 token 未动，仍是该调用的主要耗时）。
- 第一步整体（含方向判断、deskew）：**预计快 10~20%**；已预处理转正的文档额外省掉整次方向判断调用。
- 对比参考：拍照批改此前"压到长边 1600"配合输出收敛实测 128s → 16s（commit 241f46a），其中大头来自输出 token 收敛，本次只动输入侧，幅度更保守。

---

## 五、部署后验证建议

1. 拿一张已预处理转正卷跑 region-candidates：响应里应看到 `orientationSkipped: true`；拿未预处理卷确认 `false` 且方向判断正常。
2. 拿一张 300 DPI 典型卷 A/B：改动前后各跑一次 `/api/layout`，对比 `orientationElapsedMs` / `regionModelElapsedMs` 与分割框是否一致（重点看小字号试卷）。边界漂移时可把 `LAYOUT_MODEL_MAX_SIDE` 调到 2000（典型 A4 竖版仍落 6 tile 内）或 `ORIENTATION_MODEL_MAX_SIDE` 调回 900。
3. 注意：跳过方向判断后，该页 layout 的 `elapsedMs` 不再包含方向判断时间，跨版本对比耗时需注意口径。

---

## 六、已知预存在问题（本次未修）

后端 timing 读的是 `layout_payload.get("orientationModelMs", 0)` 顶层字段，但 Node `/api/layout` 响应顶层没有该字段（只有每个 layout 对象里的 `orientationElapsedMs`），所以后端记录的 `orientationModelMs` 一直是 0。可选修复：Node 响应加顶层汇总字段，或后端改读 layouts 数组。

---

## 七、改动文件清单

| 文件 | 改动 |
|---|---|
| `参考算法/源码/server.js` | 新增 `LAYOUT_MODEL_MAX_SIDE` / `LAYOUT_MODEL_JPEG_QUALITY` / `ORIENTATION_MODEL_MAX_SIDE` / `LAYOUT_MODEL_SKIP_BYTES` 配置；新增 `layoutModelImage()`；`detectRotation` 候选图尺寸可调；`analyzeLayout` 支持 `assumeUpright` 跳过并返回 `orientationSkipped`；`pipelineMetadata` 增加两个 image 配置块 |
| `backend/app/services/reference_algorithm.py` | `process_stored_files` 按预处理状态传 `assumeUpright`；`_process_pages` 透传该字段 |

