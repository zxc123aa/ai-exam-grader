# 试卷分析工作台

## 启动

```powershell
npm install
Copy-Item .env.example .env
# 在 .env 中填写 NEWAPI_API_KEY
npm start
```

打开 `http://localhost:3417`。当前默认模型为 `gemini-3.5-flash`，接口地址为 `https://fluxnode.org/v1/chat/completions`。

## 使用

1. 拖入一组试卷图片。
2. 点击“分析版面”。系统会比较四个旋转方向，在转正图片上显示题目块；红框必须覆盖完整题干、选项和作答。
3. 点击“逐块识别”，系统会一次提交全部题块。服务端优先把同一考生、阅读顺序相邻的题块组成多图请求，跨照片页也允许进入同一批次，再按 `MAX_CONCURRENT_OCR` 并发调用 Gemini；模型在一个 JSON 中逐块返回，并判断 `mergeWithBlockId` 是否属于同一道跨页续题。服务端据此拼接同题并保留来源块，显著减少网络请求。批量结果缺项或格式异常时，会自动降级为单块识别，避免漏题。
4. 版面分析会读取姓名、座号或班级作为跨页配对键；没有姓名栏的续页会在“首轮姓名明确、后续页面连续无姓名”的情况下按页面顺序自动配对，并在页面卡片中标注“自动配对”。
5. 结果按考生分组并按题号排列。重复题号、缺题、低置信度、截断、无法辨认以及相邻题文本疑似串入会显示复核标记；编辑区会自动展开完整文本。
6. 在结果表中修订内容后保存任务，可导出 JSON 或 Markdown。Markdown 会按“第几份试卷”分组，每份试卷内列出全部题目、考生回答、置信度、备注和单题耗时。若姓名或座号识别有误，可在试卷分组标题旁点击“修改身份”，修改会同步到当前结果、裁块和版面信息。

`MAX_CONCURRENT_OCR` 默认值为 `8`，服务端会将其限制在 1–8 路。`MAX_BLOCKS_PER_OCR_REQUEST` 默认值为 `3`，限制在 1–6 块；健康状态和任务耗时会记录并发数、批次数、实际模型请求数和降级批次数。如果上游出现 429 或超时，应先将并发调低到 4，再视结果调整每请求块数。

模型响应中的 `usage` 会按任务累计输入、输出和总 token，并写入 JSON/Markdown。若供应商分别返回输入和输出 token，在 `.env` 配置 `MODEL_INPUT_USD_PER_MILLION` 和 `MODEL_OUTPUT_USD_PER_MILLION`；若像当前 fluxnode 接口一样只返回 `total_tokens`，配置 `MODEL_TOTAL_USD_PER_MILLION`。不配置单价时仍记录 token，但费用显示为“未配置单价”。

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

`.env` 只放服务端，不要提交到代码仓库或复制到浏览器端。模型响应仅用于当前任务和本地 `data/jobs` 结果文件。
