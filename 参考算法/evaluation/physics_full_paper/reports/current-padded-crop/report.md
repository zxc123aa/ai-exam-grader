# 物理完卷 1–22 题 A/B 评测

- 发布门：**拒绝**
- 人工确认金标：0/22
- 旧版/新版运行数：2/1
- 新版中位总耗时：28376 ms
- 新版中位平均置信度：0.9（不是准确率）

## 门禁失败原因

- gold_not_fully_human_confirmed
- baseline_runs_2_below_3
- candidate_runs_1_below_3
- candidate_severe_errors:6
- question_1_regressed:-0.1599
- question_1_text_regressed:-0.527
- question_3_regressed:-0.0202
- question_3_text_regressed:-0.0801
- question_4_regressed:-0.0807
- question_4_text_regressed:-0.0222
- question_5_regressed:-0.1044
- question_5_text_regressed:-0.2128
- question_6_regressed:-0.0074
- question_6_text_regressed:-0.1284
- question_7_text_regressed:-0.0119
- question_8_regressed:-0.0295
- question_8_text_regressed:-0.0175
- question_9_regressed:-0.8349
- question_9_text_regressed:-0.0539
- question_10_regressed:-0.2315
- question_10_text_regressed:-0.0823
- question_11_regressed:-0.3426
- question_11_text_regressed:-0.341
- question_12_regressed:-0.0828
- question_12_text_regressed:-0.0281
- question_13_text_regressed:-0.283
- question_14_regressed:-0.7683
- question_14_text_regressed:-0.1781
- question_15_regressed:-0.1907
- question_15_text_regressed:-0.0729
- question_16_regressed:-0.475
- question_16_text_regressed:-0.5
- question_17_regressed:-0.5878
- question_17_text_regressed:-0.3111
- question_18_regressed:-0.3586
- question_18_text_regressed:-0.1613
- question_19_regressed:-0.0173
- question_19_text_regressed:-0.0639
- question_20_regressed:-0.3597
- question_20_text_regressed:-0.0094
- question_21_regressed:-0.0563
- question_21_text_regressed:-0.0465
- question_22_regressed:-0.1492
- question_22_text_regressed:-0.1031

## 逐题对比

| 题号 | 旧版文字准确率 | 新版文字准确率 | 文字差值 | 题干准确率 新/旧 | 答案准确率 新/旧 | 综合分差值 | 新版严重错误运行数 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.9865 | 0.4595 | -0.527 | 0.4521 / 0.9863 | 1 / 1 | -0.1599 | 0 |
| 2 | 0.9909 | 0.9909 | 0 | 0.9908 / 0.9909 | 1 / 1 | 0.025 | 0 |
| 3 | 0.9968 | 0.9167 | -0.0801 | 0.9161 / 0.9968 | 1 / 1 | -0.0202 | 0 |
| 4 | 0.9778 | 0.9556 | -0.0222 | 0.9545 / 0.9772 | 1 / 1 | -0.0807 | 0 |
| 5 | 0.7873 | 0.5745 | -0.2128 | 0.5652 / 0.7826 | 1 / 1 | -0.1044 | 0 |
| 6 | 0.8629 | 0.7345 | -0.1284 | 0.7321 / 0.8616 | 1 / 1 | -0.0074 | 0 |
| 7 | 1 | 0.9881 | -0.0119 | 0.988 / 1 | 1 / 1 | -0.003 | 0 |
| 8 | 0.9941 | 0.9766 | -0.0175 | 0.9765 / 0.9941 | 1 / 1 | -0.0295 | 0 |
| 9 | 0.9526 | 0.8987 | -0.0539 | 0.9045 / 0.9523 | 0 / 1 | -0.8349 | 1 |
| 10 | 0.9177 | 0.8354 | -0.0823 | 0.9514 / 0.9722 | 0 / 0.525 | -0.2315 | 0 |
| 11 | 0.9887 | 0.6477 | -0.341 | 0.6173 / 0.9876 | 1 / 1 | -0.3426 | 0 |
| 12 | 0.9382 | 0.9101 | -0.0281 | 0.9 / 0.9313 | 1 / 1 | -0.0828 | 0 |
| 13 | 0.566 | 0.283 | -0.283 | 0.24 / 0.55 | 1 / 0.8334 | 0.1225 | 0 |
| 14 | 1 | 0.8219 | -0.1781 | 0.8769 / 1 | 0.375 / 1 | -0.7683 | 1 |
| 15 | 1 | 0.9271 | -0.0729 | 0.9231 / 1 | 1 / 1 | -0.1907 | 0 |
| 16 | 0.5 | 0 | -0.5 | 0 / 0.5 | 0 / 0.5 | -0.475 | 1 |
| 17 | 0.6444 | 0.3333 | -0.3111 | 0.3488 / 0.6512 | 0 / 0.5 | -0.5878 | 1 |
| 18 | 0.8602 | 0.6989 | -0.1613 | 0.9271 / 1 | 0.4556 / 0.7111 | -0.3586 | 1 |
| 19 | 0.9802 | 0.9163 | -0.0639 | 0.9091 / 0.9785 | 1 / 1 | -0.0173 | 0 |
| 20 | 0.8099 | 0.8005 | -0.0094 | 0.8912 / 0.872 | 0.5 / 0.6047 | -0.3597 | 1 |
| 21 | 0.9913 | 0.9448 | -0.0465 | 0.9941 / 1 | 0.8966 / 0.9828 | -0.0563 | 0 |
| 22 | 0.9382 | 0.8351 | -0.1031 | 0.9713 / 0.9857 | 0.7243 / 0.8996 | -0.1492 | 0 |

失败队列：1、3、4、5、6、7、8、9、10、11、12、13、14、15、16、17、18、19、20、21、22
