# Physics OCR Evaluation

更新时间：2026-07-03

## 样本

- `materials/physics/1.jpg`：横向双页手机照片，对应第 1-2 页。
- `materials/physics/2.jpg`：横向双页手机照片，对应第 3-4 页。
- 两张图均为 `1707x1280` JPG，包含透视、弯曲、中缝阴影、低对比度、物理图示、公式单位、选择题、填空题和综合题。

## 执行命令

```bash
python3 scripts/preprocess_exam_photo.py materials/physics/1.jpg --output-dir materials/physics/processed/1
python3 scripts/preprocess_exam_photo.py materials/physics/2.jpg --output-dir materials/physics/processed/2
python3 scripts/evaluate_physics_ocr.py --kimi-samples p1_right_manual,p3_q19,p4_q22 --kimi-max-tokens 1800
```

完整生成物在本地忽略目录：

```text
materials/physics/evaluation/
```

## 结果摘要

### 扫描预处理

- 初始评估时，`1.jpg` 预处理失败：只检测并矫正了左页，右页被漏掉；输出为 `single_page`。
- 修复后，`1.jpg` 可检测为双页 spread：`detected_gutter`，`gutter_ratio=0.5492`，输出 `page_1_left.jpg` 和 `page_2_right.jpg`。
- `2.jpg` 当前预处理可用：检测为双页，`detected_gutter`，拆出第 3 页和第 4 页；后续补充了内容保护边距，避免第 4 页顶部题干被裁掉，并用空白带纠偏避免右页混入左页内容。
- 结论：横向双页不能只依赖最大亮色四边形；当前已加入 relaxed spread 检测和半页 fallback 来避免漏页。
- 稳定性补充：预处理已新增软质量门禁，真实样本若存在边缘内容、低置信度中缝、模糊或 fallback 恢复，会标记为 `quality_status=review`，避免坏扫描静默进入后续 OCR/判分。

### PaddleOCR

- 全量跑了 15 个样本：4 个页级样本 + 11 个题区样本。
- 页级识别耗时约 `0.23-0.42s`，题区识别多为 `0.06-0.28s`。
- 置信度区间约 `0.827-0.987`。
- 表现好：
  - 填空题、综合计算题、普通中文题干。
  - `p3_q20` 杠杆实验题：`0.987`。
  - `p4_q22` 综合应用题：`0.984`。
  - `p2_q11_q16` 填空题：`0.981`。
- 表现弱：
  - 图示密集选择题和图片选项区域。
  - `p1_q3_q4_diagrams`：`0.827`，漏识别较多。
  - `p1_q5_q6_figures`：`0.837`，选项顺序和图文对应不稳。
  - 页级 OCR 会混排题干、图示标签、选项，不能直接用于判分。

### Kimi K2.7

- 使用 `.secrets/kimi.env` 中的 `kimi-k2.7-code`。
- 代码调用需要 `temperature=1`，并且后端应使用 `trust_env=False` 绕开当前 WSL 代理。
- `p3_q19` 实验题：约 `72.96s`，`2249 tokens`，输出比 PaddleOCR 更完整，能恢复变量格式如 `h_A`、`m_A=m_B<m_C`。
- `p4_q22` 综合应用题：约 `44.83s`，`1439 tokens`，输出明显优于 PaddleOCR，能把 `3.5×10⁻²m³`、`1.05×10³kg/m³` 等单位和上标恢复得更好。
- `p1_right_manual` 整页样本：约 `79.95s`，`2779 tokens`，但 final text 为空；说明 `kimi-k2.7-code` 不适合作为整页批量 OCR，应限制在题区级 fallback。

## 判断

- 当前主线应继续使用 PaddleOCR 作为快速 OCR baseline。
- Kimi K2.7 适合用于题区级 fallback，尤其是公式、单位、综合题和 PaddleOCR 低置信度区域。
- 不建议对整页无差别调用 Kimi：慢、贵、且可能耗完输出预算但没有 final text。
- 物理卷识别瓶颈优先级：
  1. 图示/选项题区裁剪质量。
  2. PaddleOCR 低置信度题区的 Kimi fallback。
  3. 更复杂弯曲页面的曲面展平。

## 后续建议

- 扫描预处理：继续收集更多横向双页失败样例，验证 relaxed spread 检测、内容保护边距、中缝纠偏和左右半页 fallback 的鲁棒性。
- OCR 策略：设定 PaddleOCR 低置信度阈值，建议先用 `0.90` 作为 fallback 触发线进行实验。
- Kimi 策略：只对题区图调用，默认 `max_tokens=1800`，并记录耗时、tokens 和是否返回空文本。
- 评估继续扩大到至少 3 份试卷、10 个以上题区，完成 AEG-031。
