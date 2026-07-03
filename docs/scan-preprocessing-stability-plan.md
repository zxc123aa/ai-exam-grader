# 扫描预处理稳定性阶段计划

## 背景

当前手机照片预处理已经能完成 JPG/PNG 输入、纸面检测、透视矫正、增强、双页拆分和 PDF 生成，但真实物理卷样本暴露出两个关键事实：

- 能生成 PDF 不代表裁切质量可靠。
- 启发式修复可以覆盖单个样本，但缺少质量门禁会让半成品继续进入 OCR 和判分。

因此扫描预处理需要单独进入稳定性阶段，目标是先保证“不静默产出坏结果”，再继续提高自动裁切能力。

## 阶段目标

1. 保守裁切：宁可多留背景，也不裁掉题干、答题区和页脚。
2. 可观测：每次预处理都输出结构化质量状态、warnings 和 debug 产物。
3. 可复核：风险结果进入 `review`，后续由教师复核或人工调整承接。
4. 可回归：真实失败样例沉淀为脚本验收和单测/回归样本。
5. 可演进：后续可以平滑替换为更强的版面检测、分割或移动端采集方案。

## 当前已完成

- `materials/physics/1.jpg` 左页单独检测、右页漏检问题：已通过 relaxed spread 检测和半页 fallback 修复。
- `materials/physics/2.jpg` 顶部题干被裁掉问题：已通过内容保护边距修复。
- `materials/physics/2.jpg` 中缝偏左问题：已通过空白带纠偏修复。
- 已新增可插拔扫描引擎配置：`SCAN_ENGINE=opencv_v1|scan_http`，默认仍为 `opencv_v1`。
- 已新增可插拔扫描服务边界：复用现有 `ocr-service` Paddle GPU 容器，新增 `POST /preprocess`，避免重复构建 Paddle 镜像。
- 已实机验证 `ocr-service /preprocess` 可调用 Paddle DocPreprocessor；该能力是单图文档方向/几何矫正，不是双页拆分器。`materials/physics/2.jpg` 返回 1 个预处理图，双页拆分仍需 OpenCV baseline 或后续页面 polygon 分割模型。
- 预处理结果已新增软质量门禁：
  - `quality_status=pass|review`
  - `quality_warnings[]`
  - API metadata: `registration_homography.quality`
  - API notes: `scan_quality=...`
  - 调试脚本输出质量状态和 warning。

## 质量门禁 V1

当前为软门禁，不阻断 PDF 生成。触发 `warning` 时，结果标记为 `review`。

已覆盖信号：

- `low_sharpness`：原始照片清晰度过低。
- `low_gutter_confidence`：双页中缝置信度低或使用中心 fallback。
- `split_half_page_fallback`：初始双页检测不完整，改用左右半页恢复。
- `partial_spread_recovered`：初始横向检测疑似只覆盖局部，已用 fallback 恢复。
- `page_aspect_outlier`：拆出的页面宽高比异常。
- `content_near_*_edge`：页面边缘附近存在深色内容，疑似裁切过紧或混入背景/邻页。

## 后续实施顺序

### P0：门禁闭环

- 前端显示 `scan_quality` 和 warnings。
- `review` 状态结果仍可保存，但在进入 OCR/判分前提示人工确认。
- 本地 debug 包保存：原图、mask、检测框、warped spread、增强 spread、拆页、warnings JSON。
- `scan_http` 通过 fake HTTP 回归测试锁定接口，真实模型服务以 Docker profile 单独验证。

### P1：真实样本回归集

- 建立 `materials/*` 非提交样本清单和结果摘要。
- 至少覆盖：
  - 横向双页正常样本。
  - 单页样本。
  - 暗顶部/阴影样本。
  - 右页偏暗样本。
  - 弯曲/褶皱样本。
  - 拍摄角度较大的样本。
- 每个样本记录：期望页数、允许背景、不能裁掉的题号区域、质量状态。

### P2：算法结构调整

- 优先尝试“先粗分左右页，再分别检测/矫正单页”，减少整张双页一次透视带来的误差。
- 保留当前 spread 检测作为 fallback，而不是唯一主路径。
- 将中缝检测从单一竖向投影升级为多信号评分：空白带、暗线、左右页宽度、文本密度突变。
- 增加旋转估计和页边保护策略，进一步降低裁字概率。
- 若 Paddle 文档预处理仍不能稳定处理双页，进入页面 polygon 分割模型路线：标注 `single_page`、`left_page`、`right_page`、`gutter`。
- Paddle DocPreprocessor 只作为单页矫正模块使用；横向双页必须先做页面检测/拆页，再对每页分别调用文档预处理。

### P3：人工调整入口

- 教师复核页提供扫描预处理检查视图。
- 支持拖动四角、调整中缝、重新生成拆页 PDF。
- 保存人工调整参数，作为后续自动算法训练/规则优化样本。

## 验收标准

- 真实样本中不能再静默产出明显裁题、漏页、混页结果。
- 风险结果必须带 `review` 和明确 warning。
- 自动结果不确定时优先保留背景，避免裁掉正文。
- `review` 结果进入 OCR/判分前必须可被教师看见。
- 新增失败样例必须能沉淀到回归记录或测试。

## 启动方式

默认仍使用 OpenCV v1：

```bash
SCAN_ENGINE=opencv_v1
```

启用独立扫描服务：

```bash
docker compose --profile ocr-gpu up --build ocr-service
SCAN_ENGINE=scan_http
SCAN_HTTP_URL=http://ocr-service:8010/preprocess
```

本地直接访问：

```bash
curl http://localhost:8010/health
```
