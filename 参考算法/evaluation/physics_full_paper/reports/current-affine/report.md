# 物理完卷 1–22 题 A/B 评测

- 发布门：**拒绝**
- 人工确认金标：0/22
- 旧版/新版运行数：2/1
- 新版中位总耗时：32174 ms
- 新版中位平均置信度：0.9（不是准确率）

## 门禁失败原因

- gold_not_fully_human_confirmed
- baseline_runs_2_below_3
- candidate_runs_1_below_3
- candidate_severe_errors:5
- question_1_regressed:-0.07
- question_1_text_regressed:-0.2433
- question_3_regressed:-0.0476
- question_3_text_regressed:-0.1891
- question_4_regressed:-0.0807
- question_4_text_regressed:-0.0222
- question_5_regressed:-0.8044
- question_5_text_regressed:-0.2341
- question_6_regressed:-0.1618
- question_6_text_regressed:-0.1461
- question_7_regressed:-0.8801
- question_7_text_regressed:-0.131
- question_8_regressed:-0.0265
- question_8_text_regressed:-0.0058
- question_9_regressed:-0.4416
- question_9_text_regressed:-0.0665
- question_10_regressed:-0.5952
- question_10_text_regressed:-0.0884
- question_11_regressed:-0.3426
- question_11_text_regressed:-0.341
- question_12_regressed:-0.0828
- question_12_text_regressed:-0.0281
- question_13_regressed:-0.5375
- question_13_text_regressed:-0.3773
- question_14_regressed:-0.9469
- question_14_text_regressed:-0.3836
- question_15_regressed:-0.461
- question_15_text_regressed:-0.0937
- question_16_regressed:-0.4336
- question_16_text_regressed:-0.1429
- question_17_regressed:-0.1831
- question_17_text_regressed:-0.2444
- question_18_regressed:-0.0965
- question_18_text_regressed:-0.3279
- question_19_regressed:-0.0102
- question_19_text_regressed:-0.0375
- question_21_regressed:-0.1578
- question_21_text_regressed:-0.0843
- question_22_regressed:-0.1443
- question_22_text_regressed:-0.0903

## 逐题对比

| 题号 | 旧版文字准确率 | 新版文字准确率 | 文字差值 | 题干准确率 新/旧 | 答案准确率 新/旧 | 综合分差值 | 新版严重错误运行数 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.9865 | 0.7432 | -0.2433 | 0.7397 / 0.9863 | 1 / 1 | -0.07 | 0 |
| 2 | 0.9909 | 1 | 0.0091 | 1 / 0.9909 | 1 / 1 | 0.0273 | 0 |
| 3 | 0.9968 | 0.8077 | -0.1891 | 0.8065 / 0.9968 | 1 / 1 | -0.0476 | 0 |
| 4 | 0.9778 | 0.9556 | -0.0222 | 0.9545 / 0.9772 | 1 / 1 | -0.0807 | 0 |
| 5 | 0.7873 | 0.5532 | -0.2341 | 0.5652 / 0.7826 | 0 / 1 | -0.8044 | 1 |
| 6 | 0.8629 | 0.7168 | -0.1461 | 0.7143 / 0.8616 | 1 / 1 | -0.1618 | 0 |
| 7 | 1 | 0.869 | -0.131 | 0.8795 / 1 | 0 / 1 | -0.8801 | 1 |
| 8 | 0.9941 | 0.9883 | -0.0058 | 0.9882 / 0.9941 | 1 / 1 | -0.0265 | 0 |
| 9 | 0.9526 | 0.8861 | -0.0665 | 0.8917 / 0.9523 | 0 / 1 | -0.4416 | 0 |
| 10 | 0.9177 | 0.8293 | -0.0884 | 0.9444 / 0.9722 | 0 / 0.525 | -0.5952 | 1 |
| 11 | 0.9887 | 0.6477 | -0.341 | 0.6173 / 0.9876 | 1 / 1 | -0.3426 | 0 |
| 12 | 0.9382 | 0.9101 | -0.0281 | 0.9 / 0.9313 | 1 / 1 | -0.0828 | 0 |
| 13 | 0.566 | 0.1887 | -0.3773 | 0.2 / 0.55 | 0 / 0.8334 | -0.5375 | 0 |
| 14 | 1 | 0.6164 | -0.3836 | 0.6923 / 1 | 0 / 1 | -0.9469 | 1 |
| 15 | 1 | 0.9063 | -0.0937 | 0.956 / 1 | 0 / 1 | -0.461 | 0 |
| 16 | 0.5 | 0.3571 | -0.1429 | 0.3111 / 0.5 | 0.5455 / 0.5 | -0.4336 | 1 |
| 17 | 0.6444 | 0.4 | -0.2444 | 0.4186 / 0.6512 | 0 / 0.5 | -0.1831 | 0 |
| 18 | 0.8602 | 0.5323 | -0.3279 | 1 / 1 | 0.0333 / 0.7111 | -0.0965 | 0 |
| 19 | 0.9802 | 0.9427 | -0.0375 | 0.9378 / 0.9785 | 1 / 1 | -0.0102 | 0 |
| 20 | 0.8099 | 0.8248 | 0.0149 | 0.8316 / 0.872 | 0.8023 / 0.6047 | 0.0888 | 0 |
| 21 | 0.9913 | 0.907 | -0.0843 | 1 / 1 | 0.8161 / 0.9828 | -0.1578 | 0 |
| 22 | 0.9382 | 0.8479 | -0.0903 | 0.9713 / 0.9857 | 0.7477 / 0.8996 | -0.1443 | 0 |

失败队列：1、3、4、5、6、7、8、9、10、11、12、13、14、15、16、17、18、19、21、22
