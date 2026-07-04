# Question Segmentation Evaluation

更新时间：2026-07-05

## 目标

评估当前 `layout_ocr_anchor_v1` 题目区域候选分割在真实试卷页上的表现。该评估只针对候选框质量，不代表 OCR 或判分能力。

## 执行命令

```bash
OCR_HTTP_URL=http://localhost:8010/ocr PYTHONPATH=backend python3 scripts/evaluate_question_segmentation.py --engine layout_ocr_anchor_v1 --ocr-http-url http://localhost:8010/ocr --output-dir materials/question-segmentation/evaluation-ocr-anchor --report docs/question-segmentation-ocr-anchor-evaluation.md
```

本地 overlay 和 JSON 生成在被 `.gitignore` 忽略的目录：

```text
materials/question-segmentation/evaluation-ocr-anchor/
```

## 结果摘要

- 样本数：`7`
- pass：`3`
- review：`3`
- fail：`1`
- engine：`layout_ocr_anchor_v1`

| 样本 | 来源 | 期望数量 | 候选数量 | 最大面积占比 | 状态 | warnings |
| --- | --- | ---: | ---: | ---: | --- | --- |
| `english_test1_left` | `materials/English/test1.jpg page 1` | 4-12 | 4 | 0.538 | review | large_candidate |
| `english_test1_right` | `materials/English/test1.jpg page 2` | 4-12 | 10 | 0.152 | pass | - |
| `english_writing` | `materials/English/writing.jpg` | 1-4 | 0 | 0.000 | fail | no_candidates, too_few_candidates |
| `physics_p1_left` | `materials/physics/1.jpg page 1` | 4-10 | 12 | 0.097 | review | too_many_candidates |
| `physics_p1_right` | `materials/physics/1.jpg page 2` | 4-10 | 8 | 0.177 | pass | - |
| `physics_p2_left` | `materials/physics/2.jpg page 3` | 3-6 | 6 | 0.349 | pass | - |
| `physics_p2_right` | `materials/physics/2.jpg page 4` | 2-5 | 11 | 0.382 | review | too_many_candidates |

## 判断

- 该报告只评价当前指定 engine 的候选框质量，不能直接代表 OCR 或判分能力。
- `layout_projection_v0` 的主要风险是把整页或大半页合并成一个候选框。
- `layout_ocr_anchor_v1` 的主要风险是题号 anchor 漏检，导致没有候选或候选数量不足。
- 写作页这类大块答题区更接近投影算法能力边界，但普通多题页面需要题号或语义约束。
- 标定页保留教师确认是必要的；不能把当前候选结果自动写入正式 `ExamRegion`。

## 失败模式

- 题号 anchor 漏检时会返回 0 个候选，写作页和大答题区尤其明显。
- 物理小题号、步骤编号或选项编号可能被误当成主题号，导致过切。
- 两栏判断仍是启发式，复杂排版需要栏边界和阅读顺序进一步约束。
- 结果依赖 OCR 服务可用性和文本框质量；低质量扫描会传导到候选框。

## 下一步方案

1. 保留 `layout_projection_v0` 作为 fallback，不再继续堆特例补丁。
2. 继续迭代 `layout_ocr_anchor_v1`：用 OCR 文本框和题号 anchor 生成题目边界候选。
3. 若 OCR anchor 仍不稳，再进入页面区域分割模型路线，标注题区 polygon/box 样本。
4. 前端继续维持“候选草稿 -> 教师确认 -> 正式题区”的闭环。

## 明细

### english_test1_left

- 文件：`materials/English/processed/test1/page_1_left.jpg`
- 尺寸：`869x1120`
- overlay：`materials/question-segmentation/evaluation-ocr-anchor/overlays/english_test1_left.jpg`
- 备注：English exam page with multiple sections; should not become one whole-page box.

| 候选 | x | y | w | h | area | confidence |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Q1 | 15 | 171 | 839 | 118 | 0.1017 | 0.9970 |
| Q2 | 15 | 199 | 839 | 90 | 0.0776 | 0.9952 |
| Q3 | 15 | 289 | 839 | 624 | 0.5379 | 0.9865 |
| Q4 | 15 | 913 | 839 | 175 | 0.1509 | 0.9923 |

### english_test1_right

- 文件：`materials/English/processed/test1/page_2_right.jpg`
- 尺寸：`870x1120`
- overlay：`materials/question-segmentation/evaluation-ocr-anchor/overlays/english_test1_right.jpg`
- 备注：English exam page with multiple sections and dense text.

| 候选 | x | y | w | h | area | confidence |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Q1 | 15 | 30 | 840 | 176 | 0.1517 | 0.8998 |
| Q2 | 15 | 206 | 840 | 124 | 0.1069 | 0.9979 |
| Q3 | 15 | 330 | 840 | 53 | 0.0457 | 0.9946 |
| Q4 | 15 | 381 | 840 | 51 | 0.0440 | 0.9787 |
| Q5 | 15 | 430 | 840 | 70 | 0.0603 | 0.9970 |
| Q6 | 15 | 500 | 840 | 101 | 0.0871 | 0.9881 |
| Q7 | 15 | 601 | 840 | 123 | 0.1060 | 0.9982 |
| Q8 | 15 | 724 | 840 | 53 | 0.0457 | 0.9810 |
| Q9 | 15 | 772 | 840 | 145 | 0.1250 | 0.9502 |
| Q10 | 15 | 917 | 840 | 141 | 0.1216 | 0.9892 |

### english_writing

- 文件：`materials/English/processed/writing_service_v3/page_1.jpg`
- 尺寸：`809x1314`
- overlay：`materials/question-segmentation/evaluation-ocr-anchor/overlays/english_writing.jpg`
- 备注：Writing page can validly produce a small number of large writing regions.

| 候选 | x | y | w | h | area | confidence |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| - | - | - | - | - | - | - |

### physics_p1_left

- 文件：`materials/physics/processed/1/page_1_left.jpg`
- 尺寸：`980x1196`
- overlay：`materials/question-segmentation/evaluation-ocr-anchor/overlays/physics_p1_left.jpg`
- 备注：Physics page 1, choice questions and diagrams.

| 候选 | x | y | w | h | area | confidence |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Q1 | 507 | 46 | 456 | 187 | 0.0728 | 0.8919 |
| Q2 | 507 | 233 | 456 | 81 | 0.0315 | 0.9549 |
| Q3 | 507 | 314 | 456 | 156 | 0.0607 | 0.9997 |
| Q4 | 507 | 470 | 456 | 79 | 0.0307 | 0.9765 |
| Q5 | 507 | 497 | 456 | 66 | 0.0257 | 0.9650 |
| Q6 | 507 | 549 | 456 | 76 | 0.0296 | 0.9959 |
| Q7 | 507 | 625 | 456 | 136 | 0.0529 | 0.9973 |
| Q8 | 17 | 723 | 456 | 150 | 0.0584 | 0.9894 |
| Q9 | 507 | 869 | 456 | 78 | 0.0303 | 0.9981 |
| Q10 | 17 | 873 | 456 | 248 | 0.0965 | 0.9922 |
| Q11 | 507 | 947 | 456 | 77 | 0.0300 | 0.9671 |
| Q12 | 507 | 1024 | 456 | 80 | 0.0311 | 0.9958 |

### physics_p1_right

- 文件：`materials/physics/processed/1/page_2_right.jpg`
- 尺寸：`812x1196`
- overlay：`materials/question-segmentation/evaluation-ocr-anchor/overlays/physics_p1_right.jpg`
- 备注：Physics page 2, choice/fill-in questions.

| 候选 | x | y | w | h | area | confidence |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Q1 | 420 | 284 | 378 | 456 | 0.1775 | 0.9734 |
| Q2 | 14 | 468 | 378 | 375 | 0.1460 | 0.9908 |
| Q3 | 14 | 843 | 378 | 99 | 0.0385 | 0.9998 |
| Q4 | 14 | 852 | 378 | 90 | 0.0350 | 0.9998 |
| Q5 | 420 | 857 | 378 | 248 | 0.0965 | 0.9521 |
| Q6 | 14 | 870 | 378 | 72 | 0.0280 | 0.9997 |
| Q7 | 14 | 942 | 378 | 76 | 0.0296 | 0.9745 |
| Q8 | 14 | 1018 | 378 | 121 | 0.0471 | 0.9931 |

### physics_p2_left

- 文件：`materials/physics/processed/2/page_1_left.jpg`
- 尺寸：`893x934`
- overlay：`materials/question-segmentation/evaluation-ocr-anchor/overlays/physics_p2_left.jpg`
- 备注：Physics page 3, questions 18-20.

| 候选 | x | y | w | h | area | confidence |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Q1 | 16 | 0 | 861 | 37 | 0.0382 | 0.9781 |
| Q2 | 16 | 32 | 861 | 322 | 0.3324 | 0.9482 |
| Q3 | 16 | 354 | 861 | 57 | 0.0588 | 0.9900 |
| Q4 | 16 | 402 | 861 | 50 | 0.0516 | 0.9920 |
| Q5 | 16 | 448 | 861 | 69 | 0.0712 | 0.9611 |
| Q6 | 16 | 517 | 861 | 338 | 0.3489 | 0.9836 |

### physics_p2_right

- 文件：`materials/physics/processed/2/page_2_right.jpg`
- 尺寸：`829x934`
- overlay：`materials/question-segmentation/evaluation-ocr-anchor/overlays/physics_p2_right.jpg`
- 备注：Physics page 4, questions 21-22.

| 候选 | x | y | w | h | area | confidence |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Q1 | 14 | 0 | 801 | 61 | 0.0631 | 0.9988 |
| Q2 | 14 | 61 | 801 | 59 | 0.0610 | 0.9428 |
| Q3 | 14 | 89 | 801 | 52 | 0.0538 | 0.9361 |
| Q4 | 14 | 104 | 801 | 85 | 0.0879 | 0.9583 |
| Q5 | 14 | 132 | 801 | 57 | 0.0590 | 0.9566 |
| Q6 | 14 | 310 | 801 | 80 | 0.0828 | 0.9925 |
| Q7 | 14 | 390 | 801 | 42 | 0.0434 | 0.9753 |
| Q8 | 14 | 414 | 801 | 42 | 0.0434 | 0.9643 |
| Q9 | 14 | 438 | 801 | 45 | 0.0466 | 0.9598 |
| Q10 | 14 | 462 | 801 | 45 | 0.0466 | 0.9781 |
| Q11 | 14 | 486 | 801 | 369 | 0.3817 | 0.9888 |
