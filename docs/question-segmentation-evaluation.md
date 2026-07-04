# Question Segmentation Evaluation

更新时间：2026-07-05

## 目标

评估当前 `layout_projection_v0` 题目区域候选分割在真实试卷页上的表现。该评估只针对候选框质量，不代表 OCR 或判分能力。

## 执行命令

```bash
PYTHONPATH=backend python3 scripts/evaluate_question_segmentation.py
```

本地 overlay 和 JSON 生成在被 `.gitignore` 忽略的目录：

```text
materials/question-segmentation/evaluation/
```

## 结果摘要

- 样本数：`7`
- pass：`0`
- review：`1`
- fail：`6`
- engine：`layout_projection_v0`

| 样本 | 来源 | 期望数量 | 候选数量 | 最大面积占比 | 状态 | warnings |
| --- | --- | ---: | ---: | ---: | --- | --- |
| `english_test1_left` | `materials/English/test1.jpg page 1` | 4-12 | 1 | 0.873 | fail | too_few_candidates, large_candidate, dominant_whole_page_candidate |
| `english_test1_right` | `materials/English/test1.jpg page 2` | 4-12 | 1 | 0.909 | fail | too_few_candidates, large_candidate, dominant_whole_page_candidate |
| `english_writing` | `materials/English/writing.jpg` | 1-4 | 2 | 0.569 | review | large_candidate |
| `physics_p1_left` | `materials/physics/1.jpg page 1` | 4-10 | 1 | 0.855 | fail | too_few_candidates, large_candidate, dominant_whole_page_candidate |
| `physics_p1_right` | `materials/physics/1.jpg page 2` | 4-10 | 1 | 0.846 | fail | too_few_candidates, large_candidate, dominant_whole_page_candidate |
| `physics_p2_left` | `materials/physics/2.jpg page 3` | 3-6 | 1 | 0.782 | fail | too_few_candidates, large_candidate, dominant_whole_page_candidate |
| `physics_p2_right` | `materials/physics/2.jpg page 4` | 2-5 | 1 | 0.928 | fail | too_few_candidates, large_candidate, dominant_whole_page_candidate |

## 判断

- 该报告只评价当前指定 engine 的候选框质量，不能直接代表 OCR 或判分能力。
- `layout_projection_v0` 的主要风险是把整页或大半页合并成一个候选框。
- `layout_ocr_anchor_v1` 的主要风险是题号 anchor 漏检，导致没有候选或候选数量不足。
- 写作页这类大块答题区更接近投影算法能力边界，但普通多题页面需要题号或语义约束。
- 标定页保留教师确认是必要的；不能把当前候选结果自动写入正式 `ExamRegion`。

## 失败模式

- 版面投影和横向膨胀会把密集题干、图示、答题线连接成一个大连通块。
- 没有 OCR layout、题号 anchor 或栏/题间分隔线建模，因此无法稳定判断题目边界。
- 物理图示和英语长段落会进一步放大合并问题。

## 下一步方案

1. 保留 `layout_projection_v0` 作为 fallback，不再继续堆特例补丁。
2. 继续迭代 `layout_ocr_anchor_v1`：用 OCR 文本框和题号 anchor 生成题目边界候选。
3. 若 OCR anchor 仍不稳，再进入页面区域分割模型路线，标注题区 polygon/box 样本。
4. 前端继续维持“候选草稿 -> 教师确认 -> 正式题区”的闭环。

## 明细

### english_test1_left

- 文件：`materials/English/processed/test1/page_1_left.jpg`
- 尺寸：`869x1120`
- overlay：`materials/question-segmentation/evaluation/overlays/english_test1_left.jpg`
- 备注：English exam page with multiple sections; should not become one whole-page box.

| 候选 | x | y | w | h | area | confidence |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Q1 | 24 | 42 | 841 | 1010 | 0.8727 | 1.0000 |

### english_test1_right

- 文件：`materials/English/processed/test1/page_2_right.jpg`
- 尺寸：`870x1120`
- overlay：`materials/question-segmentation/evaluation/overlays/english_test1_right.jpg`
- 备注：English exam page with multiple sections and dense text.

| 候选 | x | y | w | h | area | confidence |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Q1 | 73 | 2 | 797 | 1111 | 0.9087 | 1.0000 |

### english_writing

- 文件：`materials/English/processed/writing_service_v3/page_1.jpg`
- 尺寸：`809x1314`
- overlay：`materials/question-segmentation/evaluation/overlays/english_writing.jpg`
- 备注：Writing page can validly produce a small number of large writing regions.

| 候选 | x | y | w | h | area | confidence |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Q1 | 2 | 0 | 785 | 214 | 0.1580 | 0.9669 |
| Q2 | 8 | 213 | 801 | 755 | 0.5689 | 0.9674 |

### physics_p1_left

- 文件：`materials/physics/processed/1/page_1_left.jpg`
- 尺寸：`980x1196`
- overlay：`materials/question-segmentation/evaluation/overlays/physics_p1_left.jpg`
- 备注：Physics page 1, choice questions and diagrams.

| 候选 | x | y | w | h | area | confidence |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Q1 | 0 | 0 | 838 | 1196 | 0.8551 | 1.0000 |

### physics_p1_right

- 文件：`materials/physics/processed/1/page_2_right.jpg`
- 尺寸：`812x1196`
- overlay：`materials/question-segmentation/evaluation/overlays/physics_p1_right.jpg`
- 备注：Physics page 2, choice/fill-in questions.

| 候选 | x | y | w | h | area | confidence |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Q1 | 0 | 0 | 742 | 1107 | 0.8458 | 1.0000 |

### physics_p2_left

- 文件：`materials/physics/processed/2/page_1_left.jpg`
- 尺寸：`893x934`
- overlay：`materials/question-segmentation/evaluation/overlays/physics_p2_left.jpg`
- 备注：Physics page 3, questions 18-20.

| 候选 | x | y | w | h | area | confidence |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Q1 | 79 | 0 | 760 | 858 | 0.7818 | 1.0000 |

### physics_p2_right

- 文件：`materials/physics/processed/2/page_2_right.jpg`
- 尺寸：`829x934`
- overlay：`materials/question-segmentation/evaluation/overlays/physics_p2_right.jpg`
- 备注：Physics page 4, questions 21-22.

| 候选 | x | y | w | h | area | confidence |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Q1 | 60 | 0 | 769 | 934 | 0.9276 | 1.0000 |
