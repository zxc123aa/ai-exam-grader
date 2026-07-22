# 单份物理完卷 1–22 题评测

该目录是隔离评测区，不得被生产服务读取。生产算法不得包含本卷的题号、题干、答案、公式或固定旋转角度特例。

## 评测原则

- `gold.prelabel.json` 由历史输出生成，默认全部为 `needs_human_confirmation`，不是金标。
- 只有教师对照原图逐题确认后，才能把 `confirmed` 改为 `true`、`confirmation_status` 改为 `confirmed`。
- 旧版和新版同图同模型至少各3次。每题新版中位分不得低于旧版；新版不得新增严重错误；至少一道旧失败题必须严格改善。
- 文字准确性是主指标：报告单独输出每题 `text_accuracy`、题干文字准确率和学生答案文字准确率。`text_accuracy` 按金标题干与答案长度加权计算，不能被综合分掩盖。
- 平均置信度会写入报告，但它不是准确率，也不参与发布门禁。
- 旋转、镜像图只做鲁棒性测试，不能当独立金标样本。

## 命令

```bash
cd 参考算法/源码
npm run eval:test
npm run eval:prelabel
npm run eval:leakage
npm run eval:run-current
npm run eval:report
```

`eval:report` 在金标未人工确认、旧版不足3次或新版退化时会以退出码2拒绝发布，同时仍生成 `reports/latest/report.json` 和 `report.md`。
