# 物理完卷 1–22 题 A/B 评测

- 发布门：**拒绝**
- 人工确认金标：0/22
- 旧版/新版运行数：2/1
- 新版中位总耗时：67683 ms
- 新版中位平均置信度：无数据（不是准确率）

## 门禁失败原因

- gold_not_fully_human_confirmed
- baseline_runs_2_below_3
- candidate_runs_1_below_3
- candidate_missing_questions:runs/current-check/run-01-2026-07-16T03-12-56-836Z.json
- candidate_severe_errors:22
- question_1_regressed:-0.9883
- question_1_text_regressed:-0.9865
- question_2_regressed:-0.9727
- question_2_text_regressed:-0.9909
- question_3_regressed:-0.9992
- question_3_text_regressed:-0.9968
- question_4_regressed:-0.9193
- question_4_text_regressed:-0.9778
- question_5_regressed:-0.8457
- question_5_text_regressed:-0.7873
- question_6_regressed:-0.9404
- question_6_text_regressed:-0.8629
- question_7_regressed:-1
- question_7_text_regressed:-1
- question_8_regressed:-0.9736
- question_8_text_regressed:-0.9941
- question_9_regressed:-0.9616
- question_9_text_regressed:-0.9526
- question_10_regressed:-0.7393
- question_10_text_regressed:-0.9177
- question_11_regressed:-0.9969
- question_11_text_regressed:-0.9887
- question_12_regressed:-0.9078
- question_12_text_regressed:-0.9382
- question_13_regressed:-0.6875
- question_13_text_regressed:-0.566
- question_14_regressed:-1
- question_14_text_regressed:-1
- question_15_regressed:-1
- question_15_text_regressed:-1
- question_16_regressed:-0.475
- question_16_text_regressed:-0.5
- question_17_regressed:-0.5878
- question_17_text_regressed:-0.6444
- question_18_regressed:-0.6595
- question_18_text_regressed:-0.8602
- question_19_regressed:-0.9946
- question_19_text_regressed:-0.9802
- question_20_regressed:-0.6325
- question_20_text_regressed:-0.8099
- question_21_regressed:-0.9883
- question_21_text_regressed:-0.9913
- question_22_regressed:-0.8858
- question_22_text_regressed:-0.9382
- no_strict_improvement_on_previous_failure

## 逐题对比

| 题号 | 旧版文字准确率 | 新版文字准确率 | 文字差值 | 题干准确率 新/旧 | 答案准确率 新/旧 | 综合分差值 | 新版严重错误运行数 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.9865 | 0 | -0.9865 | 0 / 0.9863 | 0 / 1 | -0.9883 | 1 |
| 2 | 0.9909 | 0 | -0.9909 | 0 / 0.9909 | 0 / 1 | -0.9727 | 1 |
| 3 | 0.9968 | 0 | -0.9968 | 0 / 0.9968 | 0 / 1 | -0.9992 | 1 |
| 4 | 0.9778 | 0 | -0.9778 | 0 / 0.9772 | 0 / 1 | -0.9193 | 1 |
| 5 | 0.7873 | 0 | -0.7873 | 0 / 0.7826 | 0 / 1 | -0.8457 | 1 |
| 6 | 0.8629 | 0 | -0.8629 | 0 / 0.8616 | 0 / 1 | -0.9404 | 1 |
| 7 | 1 | 0 | -1 | 0 / 1 | 0 / 1 | -1 | 1 |
| 8 | 0.9941 | 0 | -0.9941 | 0 / 0.9941 | 0 / 1 | -0.9736 | 1 |
| 9 | 0.9526 | 0 | -0.9526 | 0 / 0.9523 | 0 / 1 | -0.9616 | 1 |
| 10 | 0.9177 | 0 | -0.9177 | 0 / 0.9722 | 0 / 0.525 | -0.7393 | 1 |
| 11 | 0.9887 | 0 | -0.9887 | 0 / 0.9876 | 0 / 1 | -0.9969 | 1 |
| 12 | 0.9382 | 0 | -0.9382 | 0 / 0.9313 | 0 / 1 | -0.9078 | 1 |
| 13 | 0.566 | 0 | -0.566 | 0 / 0.55 | 0 / 0.8334 | -0.6875 | 1 |
| 14 | 1 | 0 | -1 | 0 / 1 | 0 / 1 | -1 | 1 |
| 15 | 1 | 0 | -1 | 0 / 1 | 0 / 1 | -1 | 1 |
| 16 | 0.5 | 0 | -0.5 | 0 / 0.5 | 0 / 0.5 | -0.475 | 1 |
| 17 | 0.6444 | 0 | -0.6444 | 0 / 0.6512 | 0 / 0.5 | -0.5878 | 1 |
| 18 | 0.8602 | 0 | -0.8602 | 0 / 1 | 0 / 0.7111 | -0.6595 | 1 |
| 19 | 0.9802 | 0 | -0.9802 | 0 / 0.9785 | 0 / 1 | -0.9946 | 1 |
| 20 | 0.8099 | 0 | -0.8099 | 0 / 0.872 | 0 / 0.6047 | -0.6325 | 1 |
| 21 | 0.9913 | 0 | -0.9913 | 0 / 1 | 0 / 0.9828 | -0.9883 | 1 |
| 22 | 0.9382 | 0 | -0.9382 | 0 / 0.9857 | 0 / 0.8996 | -0.8858 | 1 |

失败队列：1、2、3、4、5、6、7、8、9、10、11、12、13、14、15、16、17、18、19、20、21、22
