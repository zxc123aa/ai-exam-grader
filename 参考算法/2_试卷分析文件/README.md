# 试卷分析工作台

## 启动

```powershell
npm install
Copy-Item .env.example .env
# 在 .env 中分别填写各提供者的 PROVIDER_*_API_KEY
npm start
```

打开 `http://localhost:3417`。页面先选择中转通道，再选择该通道可用的模型。当前配置 FluxNode · Gemini、FluxNode · Grok、PomoAI 和 Kimi Coding，默认为 PomoAI / Gemini 3.5 Flash。Kimi Coding 显式提供 K2.7 Code、K2.7 Code Highspeed、K2.6 和 K2.5。

## 使用

1. 拖入一组试卷图片。
2. 选择提供者和模型后点击“分析版面”。系统会比较四个旋转方向，在转正图片上显示题目块；方向、版面和后续 OCR 会锁定使用同一“提供者 + 模型”。
3. 点击“逐块识别”，系统会一次提交全部题块。服务端优先把同一考生、阅读顺序相邻的题块组成多图请求，跨照片页也允许进入同一批次，再按 `MAX_CONCURRENT_OCR` 并发调用 Gemini；模型在一个 JSON 中逐块返回，并判断 `mergeWithBlockId` 是否属于同一道跨页续题。服务端据此拼接同题并保留来源块，显著减少网络请求。批量结果缺项或格式异常时，会自动降级为单块识别，避免漏题。
4. 版面分析会读取姓名、座号或班级作为跨页配对键；没有姓名栏的续页会在“首轮姓名明确、后续页面连续无姓名”的情况下按页面顺序自动配对，并在页面卡片中标注“自动配对”。
5. 结果按考生分组并按题号排列。重复题号、缺题、低置信度、截断、无法辨认以及相邻题文本疑似串入会显示复核标记；编辑区会自动展开完整文本。
6. 在结果表中修订内容后保存任务，可导出 JSON 或 Markdown。Markdown 会按“第几份试卷”分组，每份试卷内列出全部题目、考生回答、置信度、备注和单题耗时。若姓名或座号识别有误，可在试卷分组标题旁点击“修改身份”，修改会同步到当前结果、裁块和版面信息。
7. 模型对比表会永久保存方向、版面、裁切、OCR 和总耗时，以及平均置信度、题块数、成功数、请求数和 Token。最多保留 500 条，可在页面手动清空。

识别结果还会经过统一复核门禁：默认 `REVIEW_CONFIDENCE_THRESHOLD=0.8`。低于阈值、题干为空、出现“无法辨认/截断/缺失”等证据风险、模型报告多视图答案冲突，都会写入 `reviewRequired=true` 和 `reviewReasons[]`，并在结果区标记。跨页合并只作为信息提示，不会单独阻止结果。置信度只是门禁信号之一，不能替代文字准确率验收。

`AVAILABLE_PROVIDERS` 是提供者白名单；每家通过 `PROVIDER_<ID>_LABEL/BASE_URL/API_KEY/MODELS` 配置，特殊模型可用 `PROVIDER_<ID>_TEMPERATURE` 覆盖温度。`DEFAULT_PROVIDER` 和 `DEFAULT_MODEL` 控制默认组合。

模型响应中的 `usage` 会按任务累计输入、输出和总 token，并写入 JSON/Markdown 与对比记录。若供应商只返回 `total_tokens`，可配置 `MODEL_TOTAL_USD_PER_MILLION`。

命令行样卷处理完成后，会同时在 `data/exports/<任务ID>.md` 保存 Markdown 文件：

```powershell
$env:EXAM_API = 'http://localhost:3417'
node scripts/process-sample.mjs
```

本地回归测试（不上传图片）：

```powershell
npm run test:ocr
```

## 安全

`.env` 只放服务端，不要提交到代码仓库或复制到浏览器端。对比记录仅保存指标和文件摘要，不保存图片或识别正文。
