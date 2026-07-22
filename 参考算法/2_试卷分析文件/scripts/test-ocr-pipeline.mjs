process.env.NODE_ENV = "test";
const {
  groupBlocksForOcr,
  mergeRecognizedResults,
  addUsage,
  resolveModel,
  resolveProvider,
  resolveSelection,
  parseJson,
  deriveReviewSignals,
  prepareRecognitionBlocks,
} = await import("../server.js");

if (
  resolveModel("gpt-5.6-sol") !== "gpt-5.6-sol" ||
  resolveModel("gpt-5.6-terra") !== "gpt-5.6-terra" ||
  resolveModel("gpt-5.6-luna") !== "gpt-5.6-luna" ||
  resolveModel("grok-4.5") !== "grok-4.5" ||
  resolveModel() !== "gemini-3.5-flash"
)
  throw new Error("模型白名单或默认模型错误");
let rejectedUnsupportedModel = false;
try {
  resolveModel("arbitrary-model");
} catch (error) {
  rejectedUnsupportedModel = error.status === 400;
}
if (!rejectedUnsupportedModel) throw new Error("未拒绝白名单外模型");
if (
  resolveProvider("fluxnode_gemini").label !== "FluxNode · Gemini" ||
  resolveSelection("fluxnode_gemini", "gemini-3.5-flash").model !==
    "gemini-3.5-flash" ||
  resolveSelection("fluxnode_grok", "grok-4.5").model !== "grok-4.5"
)
  throw new Error("提供者解析错误");
let rejectedProviderModel = false;
try {
  resolveSelection("fluxnode_gemini", "gpt-5.6-sol");
} catch (error) {
  rejectedProviderModel = error.status === 400;
}
if (!rejectedProviderModel) throw new Error("未拒绝提供者不支持的模型");
const grokJson = parseJson(
  '<think>schema {"ignored":true}</think>\n```json\n{"ok":true}\n```',
);
if (grokJson.ok !== true) throw new Error("Grok think 内容过滤失败");
const kimiSelection = resolveSelection("kimi", "kimi-k2.7-code-highspeed");
if (
  kimiSelection.provider.temperature !== 1 ||
  kimiSelection.model !== "kimi-k2.7-code-highspeed"
)
  throw new Error("Kimi 提供者模型或温度配置错误");
console.log(
  "Model selection tests passed: provider, default, allowlist and rejection",
);

const block = (
  id,
  paperKey,
  pageId,
  questionNumber,
  continuationOf = null,
) => ({
  id,
  paperKey,
  pageId,
  questionNumber,
  continuationOf,
  image: `data:image/jpeg;base64,${id}`,
});

const samePaper = [
  block("a1", "paper-a", "page-1", "1"),
  block("a2", "paper-a", "page-1", "2"),
  block("a3", "paper-a", "page-2", "3"),
  block("a4", "paper-a", "page-2", "4"),
];
const groups = groupBlocksForOcr(samePaper, { maxBlocksPerRequest: 3 });
if (groups.length !== 2 || groups[0].length !== 3 || groups[1].length !== 1) {
  throw new Error(
    `跨页同卷批次错误：${groups.map((group) => group.length).join(",")}`,
  );
}
const separated = groupBlocksForOcr(
  [
    block("a1", "paper-a", "page-1", "1"),
    block("b1", "paper-b", "page-1", "1"),
  ],
  { maxBlocksPerRequest: 3 },
);
if (separated.length !== 2) throw new Error("不同试卷不应进入同一批次");

const merged = mergeRecognizedResults([
  {
    blockId: "a1",
    paperKey: "paper-a",
    questionNumber: "7",
    question: "题干上半段",
    studentAnswer: "A",
    notes: "",
    sourceLabel: "上半页",
    confidence: 0.9,
    elapsedMs: 120,
  },
  {
    blockId: "a2",
    paperKey: "paper-a",
    questionNumber: "7",
    mergeWithBlockId: "a1",
    question: "题干下半段",
    studentAnswer: "补充",
    notes: "",
    sourceLabel: "下半页",
    confidence: 0.8,
    elapsedMs: 140,
  },
  {
    blockId: "b1",
    paperKey: "paper-a",
    questionNumber: "8",
    question: "另一题",
    studentAnswer: "B",
    notes: "",
    sourceLabel: "同页",
    confidence: 0.9,
    elapsedMs: 130,
  },
]);
if (
  merged.length !== 2 ||
  merged[0].mergedBlockCount !== 2 ||
  !merged[0].question.includes("题干下半段") ||
  merged[0].elapsedMs !== 140
) {
  throw new Error("模型判断续题后的服务端拼接错误");
}
console.log(
  "OCR pipeline tests passed: cross-page batching, paper isolation, model-directed merge",
);
const mergedChoiceContinuation = mergeRecognizedResults([
  {
    blockId: "q3-a",
    paperKey: "paper-a",
    questionNumber: "3",
    question: "3. 下列说法正确的是\nA. 选项A\nB. 选项B",
    studentAnswer: "B",
    notes: "题目被截断，缺失选项C和D",
    sourceLabel: "第3题",
    confidence: 0.9,
    elapsedMs: 100,
  },
  {
    blockId: "q3-b",
    paperKey: "paper-a",
    questionNumber: "3",
    kind: "continuation",
    continuationOf: "q3-a",
    question: "C. 选项C\nD. 选项D",
    studentAnswer: "",
    notes: "本块为续题",
    sourceLabel: "第3题续",
    confidence: 0.85,
    elapsedMs: 110,
  },
]);
if (
  !mergedChoiceContinuation[0].question.includes("C. 选项C") ||
  /缺失选项C和D|题目被截断/.test(mergedChoiceContinuation[0].notes)
)
  throw new Error("跨页选项补齐后未清理过期缺失提示");
console.log(
  "Merged-note reconciliation tests passed: stale missing-choice notes removed after continuation",
);
const repairedNumbering = prepareRecognitionBlocks([
  block("q12", "paper-a", "page-5", "12"),
  {
    ...block("q13", "paper-a", "page-5", "", "13"),
    kind: "continuation",
  },
  block("q14", "paper-a", "page-5", "14"),
  {
    ...block("q1", "paper-a", "page-6", "1"),
    kind: "question_answer",
  },
  {
    ...block("q2", "paper-a", "page-6", "2"),
    kind: "question_answer",
  },
  block("q16", "paper-a", "page-7", "16"),
]);
if (
  repairedNumbering.map((item) => item.questionNumber).join(",") !==
    "12,13,14,15,15,16" ||
  repairedNumbering[3].continuationOf !== "q14" ||
  repairedNumbering[4].continuationOf !== "q14" ||
  repairedNumbering[1].continuationOf !== null
)
  throw new Error("题号序列修复或显式续题归属错误");
console.log(
  "Question numbering tests passed: missing anchor, backward reset and duplicate block isolation",
);
const safeReview = deriveReviewSignals({
  question: "完整题干",
  studentAnswer: "A",
  confidence: 0.95,
});
if (safeReview.reviewRequired || safeReview.reviewReasons.length !== 0)
  throw new Error("高质量题块不应进入复核门禁");
const unsafeReview = deriveReviewSignals({
  question: "题干[无法辨认]",
  studentAnswer: "100N",
  confidence: 0.72,
  answerVerification: { status: "evidence_disagreement" },
});
if (
  !unsafeReview.reviewRequired ||
  !unsafeReview.reviewReasons.some(
    (reason) => reason.code === "incomplete_evidence",
  ) ||
  !unsafeReview.reviewReasons.some(
    (reason) => reason.code === "evidence_disagreement",
  ) ||
  !unsafeReview.reviewReasons.some(
    (reason) => reason.code === "low_confidence",
  )
)
  throw new Error("低质量或证据冲突题块未进入统一复核门禁");
console.log(
  "Review gate tests passed: missing evidence, disagreement and confidence threshold",
);
const usage = addUsage(
  { prompt_tokens: 1200, completion_tokens: 300, total_tokens: 1500 },
  { input_tokens: 500, output_tokens: 100 },
);
if (
  usage.inputTokens !== 1700 ||
  usage.outputTokens !== 400 ||
  usage.totalTokens !== 2100
)
  throw new Error("token usage aggregation failed");
console.log("Token usage tests passed: OpenAI and generic usage field aliases");
