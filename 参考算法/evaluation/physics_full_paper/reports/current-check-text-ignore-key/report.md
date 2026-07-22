# 物理完卷 1–22 题 A/B 评测

- 发布门：**拒绝**
- 人工确认金标：0/22
- 旧版/新版运行数：2/1
- 新版中位总耗时：67683 ms
- 新版中位平均置信度：0.95（不是准确率）

## 门禁失败原因

- gold_not_fully_human_confirmed
- baseline_runs_2_below_3
- candidate_runs_1_below_3
- candidate_severe_errors:5
- question_1_regressed:-0.0152
- question_1_text_regressed:-0.027
- question_2_regressed:-0.0296
- question_2_text_regressed:-0.0182
- question_3_regressed:-0.1879
- question_3_text_regressed:-0.1506
- question_4_regressed:-0.0807
- question_4_text_regressed:-0.0222
- question_5_text_regressed:-0.2128
- question_6_regressed:-0.1618
- question_6_text_regressed:-0.1461
- question_7_regressed:-0.159
- question_7_text_regressed:-0.0357
- question_8_regressed:-0.028
- question_8_text_regressed:-0.0116
- question_9_regressed:-0.44
- question_9_text_regressed:-0.0602
- question_10_regressed:-0.5959
- question_10_text_regressed:-0.1067
- question_11_regressed:-0.3552
- question_11_text_regressed:-0.0569
- question_12_regressed:-0.2755
- question_12_text_regressed:-0.073
- question_13_regressed:-0.0475
- question_13_text_regressed:-0.3585
- question_14_regressed:-0.7031
- question_14_text_regressed:-0.137
- question_15_regressed:-0.8907
- question_15_text_regressed:-0.125
- question_16_regressed:-0.475
- question_16_text_regressed:-0.5
- question_17_regressed:-0.5878
- question_17_text_regressed:-0.5111
- question_18_regressed:-0.0495
- question_18_text_regressed:-0.2473
- question_19_regressed:-0.0102
- question_19_text_regressed:-0.0375
- question_20_text_regressed:-0.0067
- question_21_regressed:-0.0196
- question_21_text_regressed:-0.0291
- question_22_regressed:-0.1443
- question_22_text_regressed:-0.0903

## 逐题对比

| 题号 | 旧版文字准确率 | 新版文字准确率 | 文字差值 | 题干准确率 新/旧 | 答案准确率 新/旧 | 综合分差值 | 新版严重错误运行数 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.9865 | 0.9595 | -0.027 | 0.9589 / 0.9863 | 1 / 1 | -0.0152 | 0 |
| 2 | 0.9909 | 0.9727 | -0.0182 | 0.9725 / 0.9909 | 1 / 1 | -0.0296 | 0 |
| 3 | 0.9968 | 0.8462 | -0.1506 | 0.8452 / 0.9968 | 1 / 1 | -0.1879 | 0 |
| 4 | 0.9778 | 0.9556 | -0.0222 | 0.9545 / 0.9772 | 1 / 1 | -0.0807 | 0 |
| 5 | 0.7873 | 0.5745 | -0.2128 | 0.5652 / 0.7826 | 1 / 1 | 0.0456 | 0 |
| 6 | 0.8629 | 0.7168 | -0.1461 | 0.7143 / 0.8616 | 1 / 1 | -0.1618 | 0 |
| 7 | 1 | 0.9643 | -0.0357 | 0.9639 / 1 | 1 / 1 | -0.159 | 0 |
| 8 | 0.9941 | 0.9825 | -0.0116 | 0.9824 / 0.9941 | 1 / 1 | -0.028 | 0 |
| 9 | 0.9526 | 0.8924 | -0.0602 | 0.8981 / 0.9523 | 0 / 1 | -0.44 | 0 |
| 10 | 0.9177 | 0.811 | -0.1067 | 0.9236 / 0.9722 | 0 / 0.525 | -0.5959 | 1 |
| 11 | 0.9887 | 0.9318 | -0.0569 | 0.9383 / 0.9876 | 0.8571 / 1 | -0.3552 | 0 |
| 12 | 0.9382 | 0.8652 | -0.073 | 0.8625 / 0.9313 | 0.8889 / 1 | -0.2755 | 0 |
| 13 | 0.566 | 0.2075 | -0.3585 | 0.16 / 0.55 | 1 / 0.8334 | -0.0475 | 0 |
| 14 | 1 | 0.863 | -0.137 | 0.9077 / 1 | 0.5 / 1 | -0.7031 | 1 |
| 15 | 1 | 0.875 | -0.125 | 0.9231 / 1 | 0 / 1 | -0.8907 | 1 |
| 16 | 0.5 | 0 | -0.5 | 0 / 0.5 | 0 / 0.5 | -0.475 | 1 |
| 17 | 0.6444 | 0.1333 | -0.5111 | 0.1395 / 0.6512 | 0 / 0.5 | -0.5878 | 1 |
| 18 | 0.8602 | 0.6129 | -0.2473 | 1 / 1 | 0.2 / 0.7111 | -0.0495 | 0 |
| 19 | 0.9802 | 0.9427 | -0.0375 | 0.9378 / 0.9785 | 1 / 1 | -0.0102 | 0 |
| 20 | 0.8099 | 0.8032 | -0.0067 | 0.8316 / 0.872 | 0.7093 / 0.6047 | 0.0703 | 0 |
| 21 | 0.9913 | 0.9622 | -0.0291 | 0.9765 / 1 | 0.9483 / 0.9828 | -0.0196 | 0 |
| 22 | 0.9382 | 0.8479 | -0.0903 | 0.9713 / 0.9857 | 0.7477 / 0.8996 | -0.1443 | 0 |

失败队列：1、2、3、4、5、6、7、8、9、10、11、12、13、14、15、16、17、18、19、20、21、22
