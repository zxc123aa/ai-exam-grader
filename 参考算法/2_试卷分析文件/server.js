import express from "express";
import cors from "cors";
import dotenv from "dotenv";
import fs from "fs/promises";
import path from "path";
import { fileURLToPath } from "url";
import { randomUUID } from "crypto";
import sharp from "sharp";
import multer from "multer";

dotenv.config();

const app = express();
const PORT = Number(process.env.PORT || 3417);
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const JOBS_DIR = path.join(__dirname, "data", "jobs");
const BENCHMARKS_DIR = path.join(__dirname, "data", "benchmarks");
const IMPORT_BATCHES_DIR = path.join(__dirname, "data", "import-batches");
const importUpload = multer({
  storage: multer.memoryStorage(),
  limits: { files: 10, fileSize: 35 * 1024 * 1024 },
});
const MAX_CONCURRENT_OCR = Math.max(
  1,
  Math.min(8, Number(process.env.MAX_CONCURRENT_OCR || 8)),
);
const MAX_BLOCKS_PER_OCR_REQUEST = Math.max(
  1,
  Math.min(6, Number(process.env.MAX_BLOCKS_PER_OCR_REQUEST || 3)),
);
const MAX_OCR_BATCH_DATA_LENGTH = 12 * 1024 * 1024;
const MODEL_TIMEOUT_MS = Math.max(
  10000,
  Number(process.env.MODEL_TIMEOUT_MS || 180000),
);
const MODEL_LABELS = {
  "gpt-5.6-sol": "GPT-5.6 SOL",
  "gpt-5.6-terra": "GPT-5.6 Terra",
  "gpt-5.6-luna": "GPT-5.6 Luna",
  "gpt-5.5": "GPT-5.5",
  "grok-4.5": "Grok 4.5",
  "kimi-k2.7-code": "Kimi K2.7 Code",
  "kimi-k2.7-code-highspeed": "Kimi K2.7 Code Highspeed",
  "kimi-k2.6": "Kimi K2.6",
  "kimi-k2.5": "Kimi K2.5",
  "claude-opus-4-8": "Claude Opus 4.8",
  "claude-opus-4-6": "Claude Opus 4.6",
  "gemini-3.5-flash": "Gemini 3.5 Flash",
};
const providerEnvKey = (id) => id.toUpperCase().replace(/[^A-Z0-9]+/g, "_");
const configuredProviderIds = String(
  process.env.AVAILABLE_PROVIDERS || "pomoai",
)
  .split(",")
  .map((value) => value.trim())
  .filter(Boolean);
const PROVIDERS = configuredProviderIds
  .map((id) => {
    const prefix = `PROVIDER_${providerEnvKey(id)}`;
    const models = String(
      process.env[`${prefix}_MODELS`] || process.env.AVAILABLE_MODELS || "",
    )
      .split(",")
      .map((value) => value.trim())
      .filter((value) => MODEL_LABELS[value]);
    return {
      id,
      label: process.env[`${prefix}_LABEL`] || id,
      baseUrl: String(
        process.env[`${prefix}_BASE_URL`] || process.env.NEWAPI_BASE_URL || "",
      ).replace(/\/+$/, ""),
      apiKey:
        process.env[`${prefix}_API_KEY`] || process.env.NEWAPI_API_KEY || "",
      temperature: Number.isFinite(Number(process.env[`${prefix}_TEMPERATURE`]))
        ? Number(process.env[`${prefix}_TEMPERATURE`])
        : null,
      models: [...new Set(models)],
    };
  })
  .filter(
    (provider) =>
      provider.baseUrl && provider.apiKey && provider.models.length > 0,
  );
const DEFAULT_PROVIDER = PROVIDERS.some(
  (provider) => provider.id === process.env.DEFAULT_PROVIDER,
)
  ? process.env.DEFAULT_PROVIDER
  : PROVIDERS[0]?.id;
const defaultProviderConfig = PROVIDERS.find(
  (provider) => provider.id === DEFAULT_PROVIDER,
);
const requestedDefaultModel = process.env.DEFAULT_MODEL || "gemini-3.5-flash";
const DEFAULT_MODEL = defaultProviderConfig?.models.includes(
  requestedDefaultModel,
)
  ? requestedDefaultModel
  : defaultProviderConfig?.models[0];
const INPUT_USD_PER_MILLION = Number(
  process.env.MODEL_INPUT_USD_PER_MILLION || 0,
);
const OUTPUT_USD_PER_MILLION = Number(
  process.env.MODEL_OUTPUT_USD_PER_MILLION || 0,
);
const TOTAL_USD_PER_MILLION = Number(
  process.env.MODEL_TOTAL_USD_PER_MILLION || 0,
);

app.use(cors());
app.use(express.json({ limit: "120mb" }));
app.use(express.static(__dirname));

function modelUrl(provider) {
  const base = provider.baseUrl;
  return base.endsWith("/v1")
    ? `${base}/chat/completions`
    : `${base}/v1/chat/completions`;
}

export function resolveProvider(value) {
  const providerId = String(value || DEFAULT_PROVIDER).trim();
  const provider = PROVIDERS.find((item) => item.id === providerId);
  if (!provider) {
    const error = new Error(`不支持的提供者：${providerId || "空"}`);
    error.status = 400;
    throw error;
  }
  return provider;
}

export function resolveSelection(providerValue, modelValue) {
  const provider = resolveProvider(providerValue);
  const fallbackModel =
    provider.id === DEFAULT_PROVIDER && provider.models.includes(DEFAULT_MODEL)
      ? DEFAULT_MODEL
      : provider.models[0];
  const model = String(modelValue || fallbackModel).trim();
  if (!provider.models.includes(model)) {
    const error = new Error(`不支持的模型：${model || "空"}`);
    error.status = 400;
    throw error;
  }
  return { provider, model };
}

export function resolveModel(value) {
  return resolveSelection(DEFAULT_PROVIDER, value).model;
}

export function parseJson(text) {
  const withoutThinking = String(text || "").replace(
    /<think>[\s\S]*?<\/think>/gi,
    "",
  );
  const fenced = withoutThinking.match(/```(?:json)?\s*([\s\S]*?)\s*```/i);
  const raw =
    fenced?.[1] ||
    withoutThinking.slice(
      withoutThinking.indexOf("{"),
      withoutThinking.lastIndexOf("}") + 1,
    );
  if (!raw || !raw.trim()) throw new Error("模型没有返回 JSON");
  try {
    return JSON.parse(raw);
  } catch (originalError) {
    const structurallyRepaired = raw
      .replace(/[“”]/g, '"')
      .replace(/[‘’]/g, "'")
      .replace(/([{,]\s*)([A-Za-z_][A-Za-z0-9_-]*)(\s*:)/g, '$1"$2"$3')
      .replace(/}\s*{/g, "},{")
      .replace(/(\d|true|false|null)\s+(?="[A-Za-z_][A-Za-z0-9_-]*"\s*:)/g, "$1,")
      .replace(/,\s*([}\]])/g, "$1");
    let repaired = "";
    let inString = false;
    for (let index = 0; index < structurallyRepaired.length; index += 1) {
      const character = structurallyRepaired[index];
      if (character === '"') {
        let slashCount = 0;
        for (
          let previous = index - 1;
          previous >= 0 && structurallyRepaired[previous] === "\\";
          previous -= 1
        )
          slashCount += 1;
        if (slashCount % 2 === 0) inString = !inString;
        repaired += character;
        continue;
      }
      if (inString && character === "\\") {
        const next = structurallyRepaired[index + 1] || "";
        repaired += /["\\/bfnrtu]/.test(next) ? "\\" : "\\\\";
        continue;
      }
      if (inString && character === "\n") {
        repaired += "\\n";
        continue;
      }
      if (inString && character === "\r") {
        repaired += "\\r";
        continue;
      }
      if (inString && character === "\t") {
        repaired += "\\t";
        continue;
      }
      repaired += character;
    }
    try {
      return JSON.parse(repaired);
    } catch {
      throw originalError;
    }
  }
}

export function normalizeUsage(usage = {}) {
  const inputTokens =
    Number(
      usage.prompt_tokens ?? usage.input_tokens ?? usage.promptTokens ?? 0,
    ) || 0;
  const outputTokens =
    Number(
      usage.completion_tokens ??
        usage.output_tokens ??
        usage.completionTokens ??
        0,
    ) || 0;
  const totalTokens =
    Number(
      usage.total_tokens ?? usage.totalTokens ?? inputTokens + outputTokens,
    ) || inputTokens + outputTokens;
  return { inputTokens, outputTokens, totalTokens };
}

export function addUsage(...usages) {
  return usages.reduce(
    (total, usage) => {
      const current = normalizeUsage(usage);
      total.inputTokens += current.inputTokens;
      total.outputTokens += current.outputTokens;
      total.totalTokens += current.totalTokens;
      return total;
    },
    { inputTokens: 0, outputTokens: 0, totalTokens: 0 },
  );
}

export function usageCostUsd(usage) {
  const normalized = normalizeUsage(usage);
  if (TOTAL_USD_PER_MILLION)
    return Number(
      ((normalized.totalTokens / 1e6) * TOTAL_USD_PER_MILLION).toFixed(8),
    );
  if (!INPUT_USD_PER_MILLION && !OUTPUT_USD_PER_MILLION) return null;
  if (
    normalized.totalTokens &&
    !normalized.inputTokens &&
    !normalized.outputTokens
  )
    return null;
  return Number(
    (
      (normalized.inputTokens / 1e6) * INPUT_USD_PER_MILLION +
      (normalized.outputTokens / 1e6) * OUTPUT_USD_PER_MILLION
    ).toFixed(8),
  );
}

async function callModel({
  provider: providerValue,
  model,
  messages,
  temperature = 0.1,
}) {
  const initialSelection = resolveSelection(providerValue, model);
  const candidates = [
    initialSelection.provider,
    ...PROVIDERS.filter(
      (provider) =>
        provider.id !== initialSelection.provider.id &&
        provider.models.includes(initialSelection.model),
    ),
  ];
  const started = performance.now();
  const attempts = [];
  let lastError;
  for (const [index, provider] of candidates.entries()) {
    const attemptStarted = performance.now();
    try {
      const response = await fetch(modelUrl(provider), {
        method: "POST",
        signal: AbortSignal.timeout(MODEL_TIMEOUT_MS),
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${provider.apiKey}`,
        },
        body: JSON.stringify({
          model: initialSelection.model,
          temperature: provider.temperature ?? temperature,
          messages,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        const error = new Error(
          data.error?.message || `模型请求失败（HTTP ${response.status}）`,
        );
        error.status = response.status;
        throw error;
      }
      attempts.push({
        provider: provider.id,
        ok: true,
        elapsedMs: Math.round(performance.now() - attemptStarted),
      });
      return {
        data,
        elapsedMs: Math.round(performance.now() - started),
        usage: normalizeUsage(data.usage),
        usageAvailable: Boolean(data.usage),
        provider: provider.id,
        providerLabel: provider.label,
        requestedProvider: initialSelection.provider.id,
        providerFailoverCount: index,
        providerAttempts: attempts,
      };
    } catch (error) {
      lastError = error;
      attempts.push({
        provider: provider.id,
        ok: false,
        status: Number(error?.status) || null,
        error: String(error?.message || error),
        elapsedMs: Math.round(performance.now() - attemptStarted),
      });
      if (!isTransientModelError(error) || index === candidates.length - 1) {
        error.providerAttempts = attempts;
        throw error;
      }
    }
  }
  throw lastError;
}

function isTransientModelError(error) {
  return (
    error?.name === "TimeoutError" ||
    error?.name === "AbortError" ||
    error?.name === "TypeError" ||
    error?.code === "ECONNRESET" ||
    error?.code === "ECONNREFUSED" ||
    error?.code === "ENOTFOUND" ||
    error?.status === 429 ||
    error?.status === 408 ||
    Number(error?.status) >= 500
  );
}

async function callOcrModel(options) {
  let lastError;
  for (let attempt = 1; attempt <= 2; attempt += 1) {
    try {
      const result = await callModel(options);
      return { ...result, attempts: attempt };
    } catch (error) {
      lastError = error;
      if (attempt === 2 || !isTransientModelError(error)) throw error;
      await new Promise((resolve) =>
        setTimeout(resolve, 700 + Math.round(Math.random() * 500)),
      );
    }
  }
  throw lastError;
}

function cleanRegion(region, index) {
  const number = (value, fallback = 0) =>
    Number.isFinite(Number(value))
      ? Math.max(0, Math.min(1000, Math.round(Number(value))))
      : fallback;
  const ymin = number(region?.ymin);
  const xmin = number(region?.xmin);
  const ymax = Math.max(ymin + 20, number(region?.ymax, 1000));
  const xmax = Math.max(xmin + 20, number(region?.xmax, 1000));
  return {
    id: region?.id || `block_${index + 1}`,
    questionNumber: String(region?.questionNumber || "").trim(),
    layoutCandidateQuestionNumber: String(
      region?.layoutCandidateQuestionNumber || region?.questionNumber || "",
    ).trim(),
    label: String(region?.label || `第 ${index + 1} 块`),
    kind: ["question", "answer", "question_answer", "continuation"].includes(
      region?.kind,
    )
      ? region.kind
      : "question_answer",
    readingOrder: Number(region?.readingOrder || index + 1),
    continuationOf: region?.continuationOf
      ? String(region.continuationOf)
      : null,
    ymin,
    xmin,
    ymax: Math.min(1000, ymax),
    xmax: Math.min(1000, xmax),
  };
}

function filterEdgeSliverRegions(regions) {
  return regions.filter((region) => {
    const width = Number(region.xmax || 0) - Number(region.xmin || 0);
    const height = Number(region.ymax || 0) - Number(region.ymin || 0);
    const touchesSide =
      Number(region.xmin || 0) <= 25 || Number(region.xmax || 0) >= 975;
    const isSliver = width <= 80 || width * Math.max(1, height) <= 9000;
    const isContinuation =
      region.kind === "continuation" || Boolean(region.continuationOf);
    return !(touchesSide && isSliver && isContinuation);
  });
}

function parseQuestionNumber(value) {
  const text = String(value ?? "").trim();
  const match = text.match(/^(?:Q|第)?\s*(\d{1,3})\s*(?:题)?[.、．]?$/i);
  return match ? Number(match[1]) : null;
}

function isSuspiciousFullPageRegion(regions) {
  if (!Array.isArray(regions) || regions.length !== 1) return false;
  const region = regions[0];
  const width = Number(region.xmax || 0) - Number(region.xmin || 0);
  const height = Number(region.ymax || 0) - Number(region.ymin || 0);
  return width * height >= 600000;
}

/**
 * Layout models occasionally lose one printed number or restart numbering on a
 * narrow/cropped continuation image. Resolve only those cases that are
 * strongly constrained by surrounding anchors; never invent a number from the
 * block index alone.
 */
export function resolveQuestionNumbering(blocks) {
  const ordered = Array.isArray(blocks) ? blocks : [];
  const numericCandidates = ordered.map((block) =>
    parseQuestionNumber(
      block.layoutCandidateQuestionNumber || block.questionNumber,
    ),
  );
  const nextAnchor = (index, minimum) => {
    for (let cursor = index + 1; cursor < numericCandidates.length; cursor += 1) {
      const value = numericCandidates[cursor];
      if (value !== null && value >= minimum) return value;
    }
    return null;
  };
  let previousNumber = null;
  let previousMainBlock = null;
  const latestByQuestion = new Map();

  ordered.forEach((block, index) => {
    const original = parseQuestionNumber(
      block.layoutCandidateQuestionNumber || block.questionNumber,
    );
    const upcoming = nextAnchor(index, (previousNumber ?? 0) + 1);
    let resolved = original;
    let inferred = false;
    let forcedContinuation = false;

    if (resolved === null) {
      if (
        previousNumber !== null &&
        upcoming !== null &&
        upcoming > previousNumber &&
        upcoming <= previousNumber + 3
      ) {
        resolved = previousNumber + 1;
        inferred = true;
      }
    } else if (previousNumber !== null && resolved < previousNumber) {
      // A backwards jump immediately before the next sequential anchor is
      // usually a cropped continuation whose printed number was misread.
      if (
        upcoming !== null &&
        upcoming > previousNumber &&
        upcoming <= previousNumber + 3
      ) {
        resolved =
          upcoming === previousNumber + 1
            ? previousNumber
            : previousNumber + 1;
        inferred = true;
        forcedContinuation = true;
      }
    }

    if (resolved !== null) {
      block.modelQuestionNumber = block.modelQuestionNumber || null;
      block.layoutCandidateQuestionNumber =
        block.layoutCandidateQuestionNumber || (original === null ? "" : String(original));
      block.questionNumber = String(resolved);
      if (inferred) {
        block.questionNumberResolution = forcedContinuation
          ? "sequence_conflict_continuation"
          : "missing_sequence_anchor";
        block.questionNumberResolutionEvidence = {
          previous: previousNumber,
          candidate: original,
          next: upcoming,
        };
      }
    }

    const explicitContinuation =
      block.kind === "continuation" || Boolean(block.continuationOf);
    if (block.continuationOf) {
      const reference = String(block.continuationOf);
      const knownParent =
        latestByQuestion.get(reference) || latestByQuestion.get(String(resolved));
      if (knownParent && knownParent !== block.id) {
        block.continuationOf = knownParent;
      } else if (!knownParent && !forcedContinuation) {
        // A model sometimes echoes the current number (e.g. "continuationOf":
        // "13") for the first block of a question. It is not a valid parent.
        block.continuationOf = null;
        if (inferred || resolved !== previousNumber)
          block.kind = "question_answer";
      }
    }
    if (
      previousMainBlock &&
      (forcedContinuation ||
        (explicitContinuation &&
          resolved !== null &&
          previousNumber !== null &&
          resolved === previousNumber))
    ) {
      block.kind = "continuation";
      block.continuationOf =
        latestByQuestion.get(String(resolved)) || previousMainBlock.id;
    }

    if (resolved !== null) {
      if (!block.continuationOf) {
        previousMainBlock = block;
        previousNumber = resolved;
        latestByQuestion.set(String(resolved), block.id);
      } else if (previousNumber === null) {
        previousNumber = resolved;
      }
    }
  });
  return ordered;
}

export function prepareRecognitionBlocks(inputBlocks) {
  const blocks = (Array.isArray(inputBlocks) ? inputBlocks : []).map((item) => ({
    ...item,
    layoutCandidateQuestionNumber:
      item.layoutCandidateQuestionNumber || item.questionNumber || "",
  }));
  const seenIds = new Set();
  blocks.forEach((block, index) => {
    const originalId = String(block.id || `block_${index + 1}`);
    if (seenIds.has(originalId)) {
      const pagePart = String(block.pageId || `page_${index + 1}`).replace(
        /[^a-zA-Z0-9_.:-]+/g,
        "_",
      );
      block.layoutRegionId = block.layoutRegionId || originalId;
      block.id = `${pagePart}::${originalId}`;
    } else {
      block.id = originalId;
    }
    seenIds.add(block.id);
  });
  return resolveQuestionNumbering(blocks);
}

function cleanPaperKey(value) {
  return String(value || "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 80);
}

function imageBufferFromDataUrl(dataUrl) {
  const match = String(dataUrl || "").match(/^data:([^;]+);base64,(.+)$/s);
  if (!match) throw new Error("图片数据格式无效");
  return Buffer.from(match[2], "base64");
}

async function rotateDataUrl(dataUrl, rotation) {
  if (!rotation) return dataUrl;
  const buffer = await sharp(imageBufferFromDataUrl(dataUrl))
    .rotate(rotation)
    .jpeg({ quality: 92 })
    .toBuffer();
  return `data:image/jpeg;base64,${buffer.toString("base64")}`;
}

async function detectRotation(page, provider, model) {
  if (page.assumeUpright) {
    return {
      rotation: 0,
      elapsedMs: 0,
      usage: normalizeUsage(),
      usageAvailable: false,
      provider,
      providerLabel: resolveProvider(provider).label,
      providerFailoverCount: 0,
      providerAttempts: [],
    };
  }
  const source = imageBufferFromDataUrl(page.image);
  const rotations = [0, 90, 180, 270];
  const candidates = await Promise.all(
    rotations.map(async (rotation) => {
      const buffer = await sharp(source)
        .rotate(rotation)
        .resize({
          width: 900,
          height: 900,
          fit: "inside",
          withoutEnlargement: true,
        })
        .jpeg({ quality: 82 })
        .toBuffer();
      return {
        rotation,
        image: `data:image/jpeg;base64,${buffer.toString("base64")}`,
      };
    }),
  );
  const content = [
    {
      type: "text",
      text: '下面依次给出同一张中文试卷实际旋转后的四个候选图。请选择文字可以正常从左到右、从上到下阅读且不倒置的候选图。标签就是程序实际采用的顺时针旋转角度，不需要换算。只返回 JSON：{"rotation":0|90|180|270}',
    },
  ];
  candidates.forEach((candidate) =>
    content.push(
      { type: "text", text: `候选 ${candidate.rotation}°` },
      { type: "image_url", image_url: { url: candidate.image } },
    ),
  );
  const result = await callModel({
    provider,
    model,
    messages: [{ role: "user", content }],
  });
  const parsed = parseJson(result.data.choices?.[0]?.message?.content || "");
  const rotation = [0, 90, 180, 270].includes(Number(parsed.rotation))
    ? Number(parsed.rotation)
    : 0;
  return {
    rotation,
    elapsedMs: result.elapsedMs,
    usage: result.usage,
    usageAvailable: result.usageAvailable,
    provider: result.provider,
    providerLabel: result.providerLabel,
    providerFailoverCount: result.providerFailoverCount || 0,
    providerAttempts: result.providerAttempts || [],
  };
}

function inferMissingPaperKeys(layouts) {
  const explicitKeys = [
    ...new Set(
      layouts
        .map((layout) =>
          cleanPaperKey(layout.studentKey || layout.studentLabel),
        )
        .filter(Boolean),
    ),
  ];
  if (explicitKeys.length < 2) return layouts;
  const firstMissing = layouts.findIndex(
    (layout) => !cleanPaperKey(layout.studentKey || layout.studentLabel),
  );
  if (firstMissing < explicitKeys.length || firstMissing < 0) return layouts;
  if (
    !layouts
      .slice(firstMissing)
      .every(
        (layout) => !cleanPaperKey(layout.studentKey || layout.studentLabel),
      )
  )
    return layouts;
  return layouts.map((layout, index) => {
    if (cleanPaperKey(layout.studentKey || layout.studentLabel)) return layout;
    const key = explicitKeys[index % explicitKeys.length];
    return {
      ...layout,
      studentKey: key,
      studentLabel: `${key}（自动配对）`,
      paperKeySource: "inferred-order",
    };
  });
}

async function analyzeLayout(page, provider, model) {
  const orientation = await detectRotation(page, provider, model);
  const uprightImage = await rotateDataUrl(page.image, orientation.rotation);
  const prompt = `你是考试试卷版面分析器。输入图片已经转正，可能同时拍到左右两页或一张跨页展开的中文试卷。请只返回 JSON，不要 Markdown。
任务：按印刷大题题号找出每一个需要 OCR 的完整题目块。一个块必须从题号和题干开始，包含该题全部选项、插图、填空、小问及考生手写答案，结束于下一道印刷大题题号之前。严禁把同一道题的题干、选项、小问或作答拆成多个块，也不要把试卷标题、姓名栏、密封线单独当题目块。questionNumber 必须读取图片中真实印刷大题题号，不能根据块次序猜测。注意不同大题（选择题、填空题、计算题等）会各自从 1 重新编号：题号相同但属于不同大题的是不同的题，分块时以“大题标题+题号”一起判断边界，不要因为题号相同就把它们当成同一道题。填空题、判断题这类小题经常一题只有一行、编号紧密相连（如“1.…2.…3.…”），也必须每个编号单独成块，严禁因为题短就把相邻小题合并成一块；拿不准时宁多勿缺。
特别注意：①、②、③、(1)、(2)、(3) 这类是小问编号，不是大题题号，不能作为独立 region 的 questionNumber；它们必须并入最近的上级印刷大题，例如“15.”后面的①②③都属于第15题。
若照片边界确实截断一道题，保留可见部分并在 kind 使用 continuation、continuationOf 写同一真实题号。左右两页分别按从上到下阅读，整张图按正常页序排列。每个矩形左右应覆盖所在纸页的完整文字列，并在不包含相邻题目的前提下保留约 2% 边缘。
同时读取姓名、座号、班级，用 studentLabel 返回可读标识，用 studentKey 返回稳定短键（优先“姓名+座号”，看不清或不存在时为空）。不要把不同考生页面配在一起。
坐标基于当前已转正图片，归一化到 0-1000，字段顺序为 ymin,xmin,ymax,xmax。
JSON格式：{"pageLabel":"...","studentLabel":"姓名/座号/班级的可读组合","studentKey":"跨页配对键或空字符串","paperPart":"前半/后半/第几页等","pageNumber":null,"regions":[{"id":"region_1","questionNumber":"实际印刷题号","label":"实际印刷题号对应的题目","kind":"question_answer|continuation","readingOrder":1,"continuationOf":null,"ymin":0,"xmin":0,"ymax":1000,"xmax":500}]}。示例中没有默认题号，严禁把每页第一个块固定写成1。最多返回40个块，按阅读顺序排列。`;
  let result = await callModel({
    provider,
    model,
    messages: [
      {
        role: "user",
        content: [
          { type: "text", text: prompt },
          { type: "image_url", image_url: { url: uprightImage } },
        ],
      },
    ],
  });
  let parsed = parseJson(result.data.choices?.[0]?.message?.content || "");
  let regions = Array.isArray(parsed.regions)
    ? filterEdgeSliverRegions(parsed.regions.map(cleanRegion))
    : [];
  let regionElapsedMs = result.elapsedMs;
  let regionUsage = result.usage;
  let regionUsageAvailable = result.usageAvailable;
  if (isSuspiciousFullPageRegion(regions)) {
    const retryResult = await callModel({
      provider,
      model,
      messages: [
        {
          role: "user",
          content: [
            {
              type: "text",
              text: `${prompt}\n\n上一次分割可能把整页错当成一道题。请重新逐个查找图中真实印刷大题号；如果同时出现“1.”“2.”“3.”，必须返回三个独立 region，不得返回覆盖整页的单个 region。`,
            },
            { type: "image_url", image_url: { url: uprightImage } },
          ],
        },
      ],
    });
    const retryParsed = parseJson(
      retryResult.data.choices?.[0]?.message?.content || "",
    );
    const retryRegions = Array.isArray(retryParsed.regions)
      ? filterEdgeSliverRegions(retryParsed.regions.map(cleanRegion))
      : [];
    regionElapsedMs += retryResult.elapsedMs;
    regionUsage = addUsage(regionUsage, retryResult.usage);
    regionUsageAvailable = Boolean(
      regionUsageAvailable || retryResult.usageAvailable,
    );
    if (retryRegions.length > regions.length) {
      result = retryResult;
      parsed = retryParsed;
      regions = retryRegions;
    }
  }
  if (!regions.length)
    regions.push(
      cleanRegion(
        {
          label: "整页兜底",
          kind: "question_answer",
          ymin: 0,
          xmin: 0,
          ymax: 1000,
          xmax: 1000,
        },
        0,
      ),
    );
  const layoutReviewRequired = isSuspiciousFullPageRegion(regions);
  return {
    pageId: page.id,
    provider: result.provider || provider,
    providerLabel: result.providerLabel,
    requestedProvider: provider,
    providerFailoverCount:
      Number(orientation.providerFailoverCount || 0) +
      Number(result.providerFailoverCount || 0),
    providerAttempts: [
      ...(orientation.providerAttempts || []),
      ...(result.providerAttempts || []),
    ],
    model,
    fileName: page.fileName,
    rotation: orientation.rotation,
    coordinateSpace: "upright",
    pageLabel: parsed.pageLabel || page.fileName,
    studentLabel: cleanPaperKey(parsed.studentLabel),
    studentKey: cleanPaperKey(parsed.studentKey),
    paperPart: cleanPaperKey(parsed.paperPart),
    pageNumber: Number.isFinite(Number(parsed.pageNumber))
      ? Number(parsed.pageNumber)
      : null,
    regions,
    layoutReviewRequired,
    layoutReviewReason: layoutReviewRequired
      ? "suspicious_full_page_region"
      : null,
    elapsedMs: orientation.elapsedMs + regionElapsedMs,
    orientationElapsedMs: orientation.elapsedMs,
    regionElapsedMs,
    usage: addUsage(orientation.usage, regionUsage),
    usageAvailable: Boolean(
      orientation.usageAvailable || regionUsageAvailable,
    ),
  };
}

export function deriveReviewSignals(result, options = {}) {
  const threshold = Number.isFinite(Number(options.threshold))
    ? Number(options.threshold)
    : Number(process.env.REVIEW_CONFIDENCE_THRESHOLD || 0.8);
  const question = String(result?.question || "");
  const answer = String(result?.studentAnswer || "");
  const notes = String(result?.notes || "");
  const combined = `${question}\n${answer}\n${notes}`;
  const reasons = [];
  const add = (code, message, severity = "warning") => {
    if (!reasons.some((reason) => reason.code === code))
      reasons.push({ code, message, severity });
  };
  if (result?.error) add("recognition_error", "题块识别失败", "critical");
  if (!question.trim()) add("missing_question", "未提取到题干", "critical");
  if (
    /无法辨认|看不清|截断|缺失|不完整|残缺|裁切|裁剪/.test(combined)
  )
    add("incomplete_evidence", "题干或答案存在缺失、截断或无法辨认提示");
  if (
    result?.answerVerification?.status === "evidence_disagreement" ||
    result?.answerVerification?.status === "failed"
  )
    add("evidence_disagreement", "多视图答案证据不一致", "critical");
  if (result?.layoutReviewRequired)
    add(
      "suspicious_full_page_region",
      "自动重分割后仍是整页单题块，需要人工检查版面",
      "critical",
    );
  if (
    answer.trim() &&
    /^(?:[-—_=；;，,\s]|无|没有|未作答)+$/.test(answer.trim())
  )
    add("empty_or_placeholder_answer", "答案为空或仅包含占位符");
  const confidence = Number(result?.confidence);
  if (Number.isFinite(confidence) && confidence < threshold)
    add(
      "low_confidence",
      `模型置信度 ${(confidence * 100).toFixed(0)}% 低于复核阈值 ${(threshold * 100).toFixed(0)}%`,
    );
  if (Number(result?.mergedBlockCount || 1) > 1)
    add("merged_blocks", "题目由多个题块合并，需确认跨页边界", "info");
  const critical = reasons.some((reason) => reason.severity === "critical");
  const reviewRequired = reasons.some(
    (reason) => reason.severity !== "info",
  );
  return {
    reviewRequired,
    reviewReasons: reasons,
    reviewSeverity: critical
      ? "critical"
      : reviewRequired
        ? "warning"
        : reasons.length
          ? "info"
          : "none",
  };
}

function makeOcrResult(block, parsed, elapsedMs, requestMeta = {}) {
  const modelQuestionNumber = parseQuestionNumber(parsed.questionNumber);
  const layoutQuestionNumber = parseQuestionNumber(
    block.layoutCandidateQuestionNumber || block.questionNumber,
  );
  const result = {
    blockId: block.id,
    pageId: block.pageId,
    sourceLabel: block.label,
    kind: block.kind || "question_answer",
    questionNumber:
      modelQuestionNumber !== null
        ? String(modelQuestionNumber)
        : layoutQuestionNumber !== null
          ? String(layoutQuestionNumber)
          : "",
    layoutCandidateQuestionNumber: String(
      block.layoutCandidateQuestionNumber || "",
    ).trim(),
    modelQuestionNumber: String(parsed.questionNumber || "").trim(),
    question: String(parsed.question || "").trim(),
    studentAnswer: String(parsed.studentAnswer || "").trim(),
    answerType: String(parsed.answerType || "未知"),
    confidence: Math.max(0, Math.min(1, Number(parsed.confidence ?? 0))),
    notes: String(parsed.notes || "").trim(),
    continuationOf: block.continuationOf || null,
    mergeWithBlockId: requestMeta.mergeWithBlockId || null,
    layoutReviewRequired: Boolean(block.layoutReviewRequired),
    paperKey: cleanPaperKey(
      block.paperKey || block.studentKey || block.studentLabel,
    ),
    elapsedMs,
    ocrBatchSize: requestMeta.batchSize || 1,
    ocrAttempts: requestMeta.attempts || 1,
    provider: requestMeta.provider || block.provider,
    providerLabel: requestMeta.providerLabel || "",
    requestedProvider: block.provider,
    providerFailoverCount: requestMeta.providerFailoverCount || 0,
  };
  return { ...result, ...deriveReviewSignals(result) };
}

async function recognizeBlock(block, provider, model) {
  const prompt = `你是中文考试阅卷 OCR。请识别图片中的一块试卷，区分印刷题目和考生手写内容。不要补写图片中不存在的内容；看不清的位置写“[无法辨认]”。只返回 JSON：
{"questionNumber":"题号","question":"完整题干和选项（含公式尽量用纯文本）","studentAnswer":"考生回答原文；没有则为空","answerType":"选择题|填空题|计算题|实验题|未知","confidence":0到1,"notes":"图示、跨页或辨认风险"}
题号优先读取图片中的印刷题号，候选题号仅供校验。必须保留手写计算过程，不把它混入题干。逐项检查题干、A/B/C/D 等选项和作答是否完整；只要裁块截断文字、缺少可见选项或存在“[无法辨认]”，confidence 不得高于 0.6，并在 notes 明确说明。候选题号：${block.questionNumber || "未知"}。`;
  const result = await callOcrModel({
    provider,
    model,
    messages: [
      {
        role: "user",
        content: [
          { type: "text", text: prompt },
          { type: "image_url", image_url: { url: block.image } },
        ],
      },
    ],
  });
  const parsed = parseJson(result.data.choices?.[0]?.message?.content || "");
  return {
    ...makeOcrResult(block, parsed, result.elapsedMs, {
      attempts: result.attempts,
      provider: result.provider,
      providerLabel: result.providerLabel,
      providerFailoverCount: result.providerFailoverCount,
    }),
    usage: result.usage,
    usageAvailable: result.usageAvailable,
  };
}

export function groupBlocksForOcr(blocks, options = {}) {
  const maxBlocksPerRequest = Math.max(
    1,
    Number(options.maxBlocksPerRequest || MAX_BLOCKS_PER_OCR_REQUEST),
  );
  const maxDataLength = Math.max(
    1,
    Number(options.maxDataLength || MAX_OCR_BATCH_DATA_LENGTH),
  );
  const groups = [];
  let current = [];
  let currentDataLength = 0;
  const flush = () => {
    if (current.length) groups.push(current);
    current = [];
    currentDataLength = 0;
  };
  blocks.forEach((block, inputIndex) => {
    const entry = {
      block,
      inputIndex,
      ocrKey: `${inputIndex}:${block.id || "block"}`,
    };
    const dataLength = String(block.image || "").length;
    let previous = current.at(-1)?.block;
    const continuationMatchesPrevious =
      previous &&
      block.continuationOf &&
      cleanPaperKey(
        previous.paperKey || previous.studentKey || previous.studentLabel,
      ) ===
        cleanPaperKey(
          block.paperKey || block.studentKey || block.studentLabel,
        ) &&
      String(block.continuationOf) ===
        String(previous.questionNumber || previous.id);
    if (continuationMatchesPrevious && current.length >= maxBlocksPerRequest) {
      const parent = current.pop();
      currentDataLength -= String(parent.block.image || "").length;
      flush();
      current.push(parent);
      currentDataLength = String(parent.block.image || "").length;
      previous = parent.block;
    }
    // Adjacent blocks from the same paper may cross a photographed page boundary.
    // The vision model decides whether they are separate questions or one continuation.
    const sameContext =
      previous &&
      cleanPaperKey(
        previous.paperKey || previous.studentKey || previous.studentLabel,
      ) ===
        cleanPaperKey(block.paperKey || block.studentKey || block.studentLabel);
    if (
      current.length &&
      (!sameContext ||
        current.length >= maxBlocksPerRequest ||
        currentDataLength + dataLength > maxDataLength)
    )
      flush();
    current.push(entry);
    currentDataLength += dataLength;
  });
  flush();
  return groups;
}

async function recognizeBlockGroup(entries, provider, model) {
  const schema =
    '{"results":[{"blockId":"必须原样返回给定BLOCK_ID","mergeWithBlockId":"若与本批更早图片属于同一道题则填其BLOCK_ID，否则为空字符串","questionNumber":"题号","question":"完整题干和选项","studentAnswer":"考生回答原文","answerType":"选择题|填空题|计算题|实验题|未知","confidence":0到1,"notes":"图示、跨页、边界或辨认风险"}]}';
  const prompt = `你是中文考试阅卷 OCR。下面会给出 ${entries.length} 张题目裁块，每张图前都有唯一 BLOCK_ID。请在一次回复中完成所有图片的识别，严格返回 ${schema}，不要 Markdown。\n规则：\n1. results 必须与图片一一对应，数量必须为 ${entries.length}，BLOCK_ID 必须原样返回，不得漏项、重复或改写。\n2. 相邻图片可能是不同题，也可能是同一道题的分页或跨栏续块。请根据题号、语义承接、句子边界和版面边缘自行判断；若当前图片明确续接本批更早图片，在 mergeWithBlockId 填较早图片的 BLOCK_ID。不能仅因题号相似就合并，不确定时保持分开并在 notes 提示复核。特别注意：试卷的不同大题（如“一、选择题”“二、填空题”“三、计算题”）通常各自从 1 重新编号，判断两块是否同题前先看它们属于哪道大题；所属大题不同的两个相同题号是两道不同的题，绝不能合并或互填 mergeWithBlockId。拿不准合不合理时，宁可不合并。\n3. 每张图片仍必须单独返回一项。不同题目的文字绝不能互相合并；系统会依据 mergeWithBlockId 或 CONTINUATION_OF 在后处理阶段拼接同题。\n4. 以“候选题号”对应的题目为识别目标。裁块边缘即使露出上一题或下一题的文字，也不要放进当前 question 或 studentAnswer；在 notes 写明已排除相邻题内容。\n5. 区分印刷题目和考生手写内容，不要补写图中不存在的内容；看不清写“[无法辨认]”。必须保留目标题的完整题干、A/B/C/D 等全部可见选项、图示说明和手写计算过程。\n6. 目标题被裁块截断、缺少可见选项或出现无法辨认时，confidence 不得高于 0.6，并在 notes 说明。题号优先读取图片中的印刷题号，候选题号只用于校验。`;
  const content = [{ type: "text", text: prompt }];
  entries.forEach(({ block, ocrKey }, index) => {
    content.push({
      type: "text",
      text: `图片 ${index + 1} / ${entries.length}\nBLOCK_ID: ${ocrKey}\n候选题号: ${block.questionNumber || "未知"}\nCONTINUATION_OF: ${block.continuationOf || "无"}`,
    });
    content.push({ type: "image_url", image_url: { url: block.image } });
  });
  const modelResult = await callOcrModel({
    provider,
    model,
    messages: [{ role: "user", content }],
  });
  const parsed = parseJson(
    modelResult.data.choices?.[0]?.message?.content || "",
  );
  if (!Array.isArray(parsed.results))
    throw new Error("批量 OCR 未返回 results 数组");
  const byId = new Map(
    parsed.results.map((item) => [String(item.blockId || ""), item]),
  );
  const entryById = new Map(entries.map((entry) => [entry.ocrKey, entry]));
  const missing = entries.filter((entry) => !byId.has(entry.ocrKey));
  if (missing.length || byId.size !== entries.length)
    throw new Error(`批量 OCR 结果映射不完整（缺少 ${missing.length} 项）`);
  return {
    results: entries.map((entry, index) => {
      const parsedItem = byId.get(entry.ocrKey);
      const targetKey = String(parsedItem.mergeWithBlockId || "");
      const targetEntry = entryById.get(targetKey);
      const targetIndex = targetEntry ? entries.indexOf(targetEntry) : -1;
      const samePaper =
        targetEntry &&
        cleanPaperKey(targetEntry.block.paperKey) ===
          cleanPaperKey(entry.block.paperKey);
      const mergeWithBlockId =
        targetIndex >= 0 && targetIndex < index && samePaper
          ? targetEntry.block.id
          : null;
      return {
        inputIndex: entry.inputIndex,
        result: makeOcrResult(entry.block, parsedItem, modelResult.elapsedMs, {
          batchSize: entries.length,
          attempts: modelResult.attempts,
          mergeWithBlockId,
          provider: modelResult.provider,
          providerLabel: modelResult.providerLabel,
          providerFailoverCount: modelResult.providerFailoverCount,
        }),
      };
    }),
    requestCount: modelResult.attempts,
    fallback: false,
    usage: modelResult.usage,
    usageAvailable: modelResult.usageAvailable,
  };
}

async function recognizeGroupWithFallback(entries, provider, model) {
  try {
    return await recognizeBlockGroup(entries, provider, model);
  } catch (batchError) {
    const results = [];
    let requestCount = 1;
    let usage = normalizeUsage();
    let usageAvailable = false;
    for (const entry of entries) {
      try {
        const result = await recognizeBlock(entry.block, provider, model);
        requestCount += result.ocrAttempts || 1;
        usage = addUsage(usage, result.usage);
        usageAvailable ||= result.usageAvailable;
        results.push({
          inputIndex: entry.inputIndex,
          result: { ...result, batchFallback: true },
        });
      } catch (error) {
        requestCount += 1;
        results.push({
          inputIndex: entry.inputIndex,
          result: {
            id: entry.block.id,
            blockId: entry.block.id,
            pageId: entry.block.pageId,
            sourceLabel: entry.block.label,
            paperKey: cleanPaperKey(
              entry.block.paperKey ||
                entry.block.studentKey ||
                entry.block.studentLabel,
            ),
            error: error.message,
            batchError: batchError.message,
            elapsedMs: 0,
            batchFallback: true,
          },
        });
      }
    }
    return {
      results,
      requestCount,
      fallback: true,
      fallbackReason: batchError.message,
      usage,
      usageAvailable,
    };
  }
}

export function mergeRecognizedResults(results) {
  const merged = [];
  const byKey = new Map();
  const byBlockId = new Map();
  const latestByQuestion = new Map();
  for (const item of results) {
    if (item.error) {
      merged.push(item);
      continue;
    }
    const paper = cleanPaperKey(item.paperKey) || "未分组试卷";
    const reference = item.mergeWithBlockId || item.continuationOf;
    const explicitBlockReference =
      Boolean(item.mergeWithBlockId) || String(reference || "").includes("::");
    const parent = reference
      ? byKey.get(`${paper}::${reference}`) ||
        (explicitBlockReference ? byBlockId.get(String(reference)) : null) ||
        (item.continuationOf && item.kind === "continuation"
          ? latestByQuestion.get(`${paper}::${item.questionNumber}`)
          : null)
      : null;
    if (parent) {
      parent.question = [parent.question, item.question]
        .filter(Boolean)
        .join("\n");
      parent.studentAnswer = [parent.studentAnswer, item.studentAnswer]
        .filter(Boolean)
        .join("\n");
      parent.notes = [parent.notes, item.notes].filter(Boolean).join("；");
      parent.sourceLabel = [parent.sourceLabel, item.sourceLabel]
        .filter(Boolean)
        .join(" + ");
      parent.sourceBlockIds.push(item.blockId);
      parent.confidence = Math.min(
        Number(parent.confidence || 0),
        Number(item.confidence || 0),
      );
      parent.elapsedMs = Math.max(
        Number(parent.elapsedMs || 0),
        Number(item.elapsedMs || 0),
      );
      parent.mergedBlockCount = parent.sourceBlockIds.length;
      reconcileMergedNotes(parent);
      Object.assign(parent, deriveReviewSignals(parent));
      continue;
    }
    const copy = {
      ...item,
      paperKey: paper,
      sourceBlockIds: [item.blockId],
      mergedBlockCount: 1,
    };
    merged.push(copy);
    const aliases = [`${paper}::${copy.blockId}`, `${paper}::${copy.id || ""}`];
    aliases.forEach((alias) => byKey.set(alias, copy));
    if (copy.blockId) byBlockId.set(String(copy.blockId), copy);
    if (copy.questionNumber)
      latestByQuestion.set(`${paper}::${copy.questionNumber}`, copy);
  }
  return merged;
}

function hasChoiceLabel(text, label) {
  return new RegExp(`(?:^|\\n|\\s)${label}[.．、:]`).test(String(text || ""));
}

function reconcileMergedNotes(result) {
  if (Number(result?.mergedBlockCount || 1) <= 1) return result;
  const question = String(result.question || "");
  let notes = String(result.notes || "");
  if (!notes) return result;

  if (hasChoiceLabel(question, "C") && hasChoiceLabel(question, "D")) {
    notes = notes.replace(
      /题目被截断[，,、；;\s]*缺(?:失|少)选项\s*C\s*(?:和|、|\/)?\s*D/g,
      "续块已补充选项C/D",
    );
    notes = notes.replace(
      /缺(?:失|少)选项\s*C\s*(?:和|、|\/)?\s*D/g,
      "续块已补充选项C/D",
    );
  }

  result.notes = Array.from(
    new Set(
      notes
        .split(/[；;]/)
        .map((item) => item.trim())
        .filter(Boolean),
    ),
  ).join("；");
  return result;
}

async function mapWithConcurrency(items, worker, limit) {
  const out = new Array(items.length);
  let next = 0;
  async function run() {
    while (true) {
      const index = next++;
      if (index >= items.length) return;
      try {
        out[index] = await worker(items[index], index);
      } catch (error) {
        out[index] = {
          id: items[index].id,
          blockId: items[index].id,
          pageId: items[index].pageId || items[index].id,
          fileName: items[index].fileName,
          sourceLabel: items[index].label,
          error: error.message,
          elapsedMs: 0,
        };
      }
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, run));
  return out;
}

async function writeJob(job) {
  await fs.mkdir(JOBS_DIR, { recursive: true });
  const serialized = JSON.stringify(job, null, 2);
  JSON.parse(serialized);
  const target = path.join(JOBS_DIR, `${job.id}.json`);
  await fs.writeFile(target, serialized, "utf8");
}

function cleanMetricObject(value, keys) {
  return Object.fromEntries(
    keys.map((key) => [key, Math.max(0, Number(value?.[key] || 0))]),
  );
}

function cleanBenchmarkPayload(value = {}) {
  const selection = resolveSelection(value.provider, value.model);
  return {
    provider: selection.provider.id,
    providerLabel: selection.provider.label,
    model: selection.model,
    inputSignature: String(value.inputSignature || "").slice(0, 128),
    inputLabel: String(value.inputLabel || "").slice(0, 300),
    pageCount: Math.max(0, Number(value.pageCount || 0)),
    status: ["layout_complete", "completed", "failed"].includes(value.status)
      ? value.status
      : "failed",
    timings: cleanMetricObject(value.timings, [
      "orientationModelMs",
      "regionModelMs",
      "layoutWallMs",
      "cropMs",
      "ocrWallMs",
      "totalWallMs",
    ]),
    counts: cleanMetricObject(value.counts, [
      "blocks",
      "results",
      "failed",
      "batches",
      "requests",
      "fallbacks",
      "mergedContinuations",
    ]),
    layoutTokenUsage: normalizeUsage(value.layoutTokenUsage),
    ocrTokenUsage: normalizeUsage(value.ocrTokenUsage),
    averageConfidence: Math.max(
      0,
      Math.min(1, Number(value.averageConfidence || 0)),
    ),
    error: String(value.error || "").slice(0, 1000),
  };
}

async function writeBenchmark(benchmark) {
  await fs.mkdir(BENCHMARKS_DIR, { recursive: true });
  await fs.writeFile(
    path.join(BENCHMARKS_DIR, `${benchmark.id}.json`),
    JSON.stringify(benchmark, null, 2),
    "utf8",
  );
}

async function readBenchmarks() {
  await fs.mkdir(BENCHMARKS_DIR, { recursive: true });
  const names = (await fs.readdir(BENCHMARKS_DIR)).filter((name) =>
    name.endsWith(".json"),
  );
  const records = (
    await Promise.all(
      names.map(async (name) => {
        try {
          return JSON.parse(
            await fs.readFile(path.join(BENCHMARKS_DIR, name), "utf8"),
          );
        } catch {
          return null;
        }
      }),
    )
  ).filter(Boolean);
  return records.sort((a, b) =>
    String(b.createdAt || "").localeCompare(String(a.createdAt || "")),
  );
}

async function pruneBenchmarks(limit = 500) {
  const records = await readBenchmarks();
  await Promise.all(
    records
      .slice(limit)
      .map((record) =>
        fs.rm(path.join(BENCHMARKS_DIR, `${record.id}.json`), { force: true }),
      ),
  );
}

function safeSegment(value, fallback = "item") {
  const segment = String(value || "")
    .trim()
    .replace(/[\\/:*?"<>|\u0000-\u001f]/g, "_")
    .replace(/\s+/g, " ")
    .slice(0, 120);
  return segment || fallback;
}

function importBatchPath(batchId) {
  return path.join(IMPORT_BATCHES_DIR, safeSegment(batchId));
}

async function writeImportManifest(manifest) {
  const root = importBatchPath(manifest.id);
  await fs.mkdir(root, { recursive: true });
  const target = path.join(root, "manifest.json");
  const temp = `${target}.tmp-${process.pid}`;
  await fs.writeFile(temp, JSON.stringify(manifest, null, 2), "utf8");
  await fs.rename(temp, target);
}

async function readImportManifest(batchId) {
  return JSON.parse(
    await fs.readFile(
      path.join(importBatchPath(batchId), "manifest.json"),
      "utf8",
    ),
  );
}

const importManifestLocks = new Map();
async function mutateImportManifest(batchId, updater) {
  const previous = importManifestLocks.get(batchId) || Promise.resolve();
  const operation = previous
    .catch(() => {})
    .then(async () => {
      const manifest = await readImportManifest(batchId);
      const result = await updater(manifest);
      manifest.updatedAt = new Date().toISOString();
      await writeImportManifest(manifest);
      return result === undefined ? manifest : result;
    });
  importManifestLocks.set(batchId, operation);
  try {
    return await operation;
  } finally {
    if (importManifestLocks.get(batchId) === operation)
      importManifestLocks.delete(batchId);
  }
}

function refreshImportBatchStatus(manifest) {
  const submissions = manifest.subjects.flatMap(
    (subject) => subject.submissions,
  );
  if (!submissions.length) {
    manifest.status = "draft";
    return;
  }
  if (submissions.some((submission) => submission.status === "failed")) {
    manifest.status = submissions.every((submission) =>
      ["completed", "failed"].includes(submission.status),
    )
      ? "completed_with_errors"
      : "processing";
    return;
  }
  manifest.status = submissions.every(
    (submission) => submission.status === "completed",
  )
    ? "completed"
    : "processing";
}

async function updateImportSubmission(
  batchId,
  subjectId,
  submissionId,
  update,
) {
  return mutateImportManifest(batchId, (manifest) => {
    const subject = manifest.subjects.find((item) => item.id === subjectId);
    const submission = subject?.submissions.find(
      (item) => item.id === submissionId,
    );
    if (!submission) return null;
    update(submission, subject, manifest);
    refreshImportBatchStatus(manifest);
    return { manifest, subject, submission };
  });
}

function parsePageOrder(value, fallbackCount) {
  try {
    const parsed = JSON.parse(String(value || "[]"));
    if (Array.isArray(parsed) && parsed.length === fallbackCount) return parsed;
  } catch {}
  return Array.from({ length: fallbackCount }, (_, index) => index);
}

function importFileDataUrl(file) {
  const type = file.mimetype || "image/jpeg";
  return `data:${type};base64,${file.buffer.toString("base64")}`;
}

const importQueue = [];
const importQueueKeys = new Set();
let activeImportTasks = 0;
function enqueueImportProcessing(batchId, subjectId, submissionId) {
  const key = `${batchId}:${subjectId}:${submissionId}`;
  if (importQueueKeys.has(key)) return false;
  importQueueKeys.add(key);
  importQueue.push({ batchId, subjectId, submissionId, key });
  pumpImportQueue();
  return true;
}
function pumpImportQueue() {
  while (activeImportTasks < 2 && importQueue.length) {
    const task = importQueue.shift();
    activeImportTasks += 1;
    processImportedSubmission(task)
      .catch((error) => console.error("Import processing failed", error))
      .finally(() => {
        importQueueKeys.delete(task.key);
        activeImportTasks -= 1;
        pumpImportQueue();
      });
  }
}
async function cropImportedRegion(buffer, layout, region) {
  const working = await sharp(buffer)
    .rotate(layout.rotation || 0)
    .toBuffer();
  const meta = await sharp(working).metadata();
  const xmin = Math.max(0, Number(region.xmin || 0) - 12),
    ymin = Math.max(0, Number(region.ymin || 0) - 8),
    xmax = Math.min(1000, Number(region.xmax || 1000) + 12),
    ymax = Math.min(1000, Number(region.ymax || 1000) + 8);
  const left = Math.max(0, Math.floor((meta.width * xmin) / 1000)),
    top = Math.max(0, Math.floor((meta.height * ymin) / 1000));
  const width = Math.max(
      1,
      Math.min(meta.width - left, Math.ceil((meta.width * xmax) / 1000) - left),
    ),
    height = Math.max(
      1,
      Math.min(meta.height - top, Math.ceil((meta.height * ymax) / 1000) - top),
    );
  return sharp(working)
    .extract({ left, top, width, height })
    .jpeg({ quality: 92 })
    .toBuffer();
}
async function processImportedSubmission({ batchId, subjectId, submissionId }) {
  let context = await updateImportSubmission(
    batchId,
    subjectId,
    submissionId,
    (submission) => {
      submission.status = "processing_layout";
      submission.error = "";
      submission.startedAt = new Date().toISOString();
    },
  );
  if (!context) return;
  let manifest = context.manifest;
  let subject = manifest.subjects.find((item) => item.id === subjectId);
  let submission = subject?.submissions.find(
    (item) => item.id === submissionId,
  );
  if (!subject || !submission) return;
  try {
    const orderedFiles = submission.files;
    const pages = await Promise.all(
      orderedFiles.map(async (file, index) => {
        const buffer = await fs.readFile(
          path.join(importBatchPath(batchId), file.storageKey),
        );
        return {
          id: `${submission.id}-page-${index + 1}`,
          fileName: file.originalName,
          buffer,
          image: `data:${file.contentType};base64,${buffer.toString("base64")}`,
        };
      }),
    );
    const layouts = await mapWithConcurrency(
      pages,
      (page) => analyzeLayout(page, subject.provider, subject.model),
      2,
    );
    const failedLayout = layouts.find((layout) => layout.error);
    if (failedLayout) throw new Error(failedLayout.error);
    await updateImportSubmission(batchId, subjectId, submissionId, (item) => {
      item.status = "processing_ocr";
      item.layoutCount = layouts.reduce(
        (sum, layout) => sum + (layout.regions?.length || 0),
        0,
      );
    });
    const blocks = [];
    for (const layout of layouts) {
      const page = pages.find((item) => item.id === layout.pageId);
      for (const region of layout.regions || []) {
        const crop = await cropImportedRegion(page.buffer, layout, region);
        blocks.push({
          ...region,
          id: `${page.id}::${region.id}`,
          layoutRegionId: region.id,
          provider: subject.provider,
          model: subject.model,
          pageId: page.id,
          paperKey: submission.studentIdentifier || submission.studentName,
          image: `data:image/jpeg;base64,${crop.toString("base64")}`,
        });
      }
    }
    prepareRecognitionBlocks(blocks);
    const groups = groupBlocksForOcr(blocks);
    const reports = await mapWithConcurrency(
      groups,
      (entries) =>
        recognizeGroupWithFallback(entries, subject.provider, subject.model),
      MAX_CONCURRENT_OCR,
    );
    const rawResults = reports
      .flatMap((report) => report.results || [])
      .sort((a, b) => a.inputIndex - b.inputIndex)
      .map((item) => item.result);
    const results = mergeRecognizedResults(rawResults);
    const confidenceValues = results
      .filter((item) => !item.error && Number.isFinite(Number(item.confidence)))
      .map((item) => Number(item.confidence));
    const resultPath = path.join(
      importBatchPath(batchId),
      "subjects",
      subjectId,
      "submissions",
      submissionId,
      "results.json",
    );
    await fs.writeFile(
      resultPath,
      JSON.stringify({ layouts, results }, null, 2),
      "utf8",
    );
    const labels = layouts
      .map((layout) => String(layout.studentLabel || ""))
      .filter(Boolean);
    const identityMismatch =
      labels.length > 0 &&
      !labels.some((label) =>
        label
          .replace(/\s+/g, "")
          .includes(submission.studentName.replace(/\s+/g, "")),
      );
    await updateImportSubmission(batchId, subjectId, submissionId, (item) => {
      item.status = "completed";
      item.resultCount = results.length;
      item.failedCount = results.filter((result) => result.error).length;
      item.averageConfidence = confidenceValues.length
        ? confidenceValues.reduce((sum, value) => sum + value, 0) /
          confidenceValues.length
        : 0;
      item.identityCheck = identityMismatch
        ? "mismatch"
        : labels.length
          ? "matched"
          : "unknown";
      if (
        identityMismatch &&
        !item.warnings.some((warning) =>
          warning.startsWith("图片姓名与目录姓名不一致"),
        )
      )
        item.warnings.push(`图片姓名与目录姓名不一致：${labels.join("、")}`);
      item.resultStorageKey = path.relative(
        importBatchPath(batchId),
        resultPath,
      );
      item.completedAt = new Date().toISOString();
    });
  } catch (error) {
    await updateImportSubmission(batchId, subjectId, submissionId, (item) => {
      item.status = "failed";
      item.error = error.message;
      item.failedAt = new Date().toISOString();
    });
  }
}

app.post("/api/page-order", async (req, res) => {
  const images = Array.isArray(req.body?.images) ? req.body.images : [];
  if (images.length < 2)
    return res.status(400).json({ error: "至少需要两张图片才能判断页序" });
  try {
    const selection = resolveSelection(req.body?.provider, req.body?.model);
    const content = [
      {
        type: "text",
        text: `你是试卷页序判断器。下面是同一名学生的 ${images.length} 张试卷照片。根据页码、题号连续性、题目承接和版面结构判断从第一页到最后一页的顺序。只返回 JSON：{"orderedImageIds":["原ID"],"pageLabels":["第1页"],"confidence":0到1,"warnings":""}`,
      },
    ];
    images.forEach((image) =>
      content.push(
        {
          type: "text",
          text: `IMAGE_ID: ${image.id}\n文件名: ${image.fileName}`,
        },
        { type: "image_url", image_url: { url: image.dataUrl } },
      ),
    );
    const result = await callModel({
      provider: selection.provider.id,
      model: selection.model,
      messages: [{ role: "user", content }],
    });
    const parsed = parseJson(result.data.choices?.[0]?.message?.content || "");
    const ids = new Set(images.map((image) => String(image.id)));
    const ordered = Array.isArray(parsed.orderedImageIds)
      ? parsed.orderedImageIds.map(String).filter((id) => ids.has(id))
      : [];
    if (ordered.length !== images.length)
      throw new Error("模型返回的页序不完整");
    res.json({
      provider: selection.provider.id,
      providerLabel: selection.provider.label,
      model: selection.model,
      orderedImageIds: ordered,
      pageLabels: parsed.pageLabels || [],
      confidence: Math.max(0, Math.min(1, Number(parsed.confidence || 0))),
      warnings: String(parsed.warnings || ""),
      elapsedMs: result.elapsedMs,
    });
  } catch (error) {
    res.status(error.status || 500).json({ error: error.message });
  }
});

app.post("/api/import-batches", async (req, res) => {
  try {
    const selection = resolveSelection(
      req.body?.defaultProvider,
      req.body?.defaultModel,
    );
    const subjects = Array.isArray(req.body?.subjects) ? req.body.subjects : [];
    if (!subjects.length)
      return res.status(400).json({ error: "至少需要一个科目" });
    const manifest = {
      id: randomUUID(),
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      status: "draft",
      title: String(req.body?.title || "未命名批次").slice(0, 255),
      academicYear: String(req.body?.academicYear || "").slice(0, 40),
      grade: String(req.body?.grade || "").slice(0, 80),
      className: String(req.body?.className || "").slice(0, 120),
      examName: String(req.body?.examName || "").slice(0, 160),
      defaultProvider: selection.provider.id,
      defaultModel: selection.model,
      subjects: subjects.map((subject) => {
        const chosen = resolveSelection(
          subject.provider || selection.provider.id,
          subject.model || selection.model,
        );
        return {
          id: randomUUID(),
          name: safeSegment(subject.name, "未命名科目"),
          provider: chosen.provider.id,
          model: chosen.model,
          templateFiles: [],
          answerFiles: [],
          submissions: [],
        };
      }),
    };
    await writeImportManifest(manifest);
    res.json(manifest);
  } catch (error) {
    res
      .status(error.status || 500)
      .json({ error: `批次创建失败：${error.message}` });
  }
});

app.get("/api/import-batches/:batchId", async (req, res) => {
  try {
    res.json(await readImportManifest(req.params.batchId));
  } catch {
    res.status(404).json({ error: "导入批次不存在" });
  }
});

app.post(
  "/api/import-batches/:batchId/subjects/:subjectId/assets",
  importUpload.fields([
    { name: "template", maxCount: 10 },
    { name: "answerKey", maxCount: 10 },
  ]),
  async (req, res) => {
    try {
      const subject = await mutateImportManifest(
        req.params.batchId,
        async (manifest) => {
          const current = manifest.subjects.find(
            (item) => item.id === req.params.subjectId,
          );
          if (!current) {
            const error = new Error("科目不存在");
            error.status = 404;
            throw error;
          }
          const root = path.join(
            importBatchPath(manifest.id),
            "subjects",
            current.id,
          );
          await fs.mkdir(root, { recursive: true });
          for (const [field, targetName] of [
            ["template", "template"],
            ["answerKey", "answer-key"],
          ]) {
            const files = req.files?.[field] || [];
            if (!files.length) continue;
            const targetDir = path.join(root, targetName);
            await fs.mkdir(targetDir, { recursive: true });
            current[`${field === "answerKey" ? "answer" : field}Files`] = [];
            for (const file of files) {
              const name = `${randomUUID()}-${safeSegment(file.originalname, "page")}`;
              await fs.writeFile(path.join(targetDir, name), file.buffer);
              current[`${field === "answerKey" ? "answer" : field}Files`].push({
                name: file.originalname,
                storageKey: path.relative(
                  importBatchPath(manifest.id),
                  path.join(targetDir, name),
                ),
              });
            }
          }
          return current;
        },
      );
      res.json(subject);
    } catch (error) {
      res
        .status(error.status || 500)
        .json({ error: `科目素材上传失败：${error.message}` });
    }
  },
);

app.post(
  "/api/import-batches/:batchId/subjects/:subjectId/submissions",
  importUpload.array("pages", 10),
  async (req, res) => {
    try {
      const files = req.files || [];
      if (!files.length)
        return res.status(400).json({ error: "至少需要一张学生试卷图片" });
      const studentName = String(req.body?.studentName || "").trim();
      const studentIdentifier = String(
        req.body?.studentIdentifier || "",
      ).trim();
      if (!studentName)
        return res.status(400).json({ error: "学生姓名不能为空" });
      const submission = {
        id: randomUUID(),
        studentName,
        studentIdentifier,
        pageCount: files.length,
        pageOrder: parsePageOrder(req.body?.pageOrder, files.length),
        status: "uploaded",
        warnings:
          files.length < 2 || files.length > 3 ? ["页数不在2-3页范围内"] : [],
        createdAt: new Date().toISOString(),
        files: [],
      };
      const stored = await mutateImportManifest(
        req.params.batchId,
        async (manifest) => {
          const subject = manifest.subjects.find(
            (item) => item.id === req.params.subjectId,
          );
          if (!subject) {
            const error = new Error("科目不存在");
            error.status = 404;
            throw error;
          }
          if (!subject.templateFiles.length || !subject.answerFiles.length) {
            const error = new Error("请先上传该科目的空白卷和答案卷");
            error.status = 400;
            throw error;
          }
          const duplicate = subject.submissions.find((item) =>
            studentIdentifier
              ? item.studentIdentifier === studentIdentifier
              : item.studentName === studentName,
          );
          if (duplicate) {
            const error = new Error("该科目已存在同一学生提交");
            error.status = 409;
            error.existingSubmissionId = duplicate.id;
            throw error;
          }
          const targetDir = path.join(
            importBatchPath(manifest.id),
            "subjects",
            subject.id,
            "submissions",
            submission.id,
          );
          await fs.mkdir(targetDir, { recursive: true });
          for (let index = 0; index < files.length; index += 1) {
            const file = files[index];
            const name = `${String(index + 1).padStart(2, "0")}-${safeSegment(file.originalname, "page")}`;
            await fs.writeFile(path.join(targetDir, name), file.buffer);
            submission.files.push({
              id: submission.pageOrder[index] || index,
              originalName: file.originalname,
              storageKey: path.relative(
                importBatchPath(manifest.id),
                path.join(targetDir, name),
              ),
              contentType: file.mimetype || "image/jpeg",
              size: file.size,
            });
          }
          submission.status = "queued";
          subject.submissions.push(submission);
          refreshImportBatchStatus(manifest);
          return { batchId: manifest.id, subjectId: subject.id };
        },
      );
      enqueueImportProcessing(stored.batchId, stored.subjectId, submission.id);
      res.status(201).json({ ...stored, submission });
    } catch (error) {
      res.status(error.status || 500).json({
        error: `学生试卷上传失败：${error.message}`,
        existingSubmissionId: error.existingSubmissionId,
      });
    }
  },
);

app.post(
  "/api/import-batches/:batchId/submissions/:submissionId/retry",
  async (req, res) => {
    try {
      let subjectId = "";
      const updated = await mutateImportManifest(
        req.params.batchId,
        (manifest) => {
          const subject = manifest.subjects.find((item) =>
            item.submissions.some(
              (submission) => submission.id === req.params.submissionId,
            ),
          );
          const submission = subject?.submissions.find(
            (item) => item.id === req.params.submissionId,
          );
          if (!subject || !submission) {
            const error = new Error("学生提交不存在");
            error.status = 404;
            throw error;
          }
          if (!["failed", "uploaded"].includes(submission.status)) {
            const error = new Error("该提交当前不可重试");
            error.status = 409;
            throw error;
          }
          subjectId = subject.id;
          submission.status = "queued";
          submission.error = "";
          submission.retryCount = Number(submission.retryCount || 0) + 1;
          refreshImportBatchStatus(manifest);
          return submission;
        },
      );
      enqueueImportProcessing(
        req.params.batchId,
        subjectId,
        req.params.submissionId,
      );
      res.json(updated);
    } catch (error) {
      res.status(error.status || 500).json({ error: error.message });
    }
  },
);

app.get("/api/health", (_req, res) => {
  const operational = PROVIDERS.length > 0;
  res.status(operational ? 200 : 503).json({
    ok: true,
    provider: DEFAULT_PROVIDER,
    defaultProvider: DEFAULT_PROVIDER,
    model: DEFAULT_MODEL,
    defaultModel: DEFAULT_MODEL,
    availableProviders: PROVIDERS.map((provider) => ({
      id: provider.id,
      label: provider.label,
      models: provider.models.map((id) => ({ id, label: MODEL_LABELS[id] })),
      configured: Boolean(provider.apiKey && provider.baseUrl),
    })),
    modelTimeoutMs: MODEL_TIMEOUT_MS,
    ocrConcurrency: MAX_CONCURRENT_OCR,
    ocrBlocksPerRequest: MAX_BLOCKS_PER_OCR_REQUEST,
    pricing: {
      inputUsdPerMillion: INPUT_USD_PER_MILLION || null,
      outputUsdPerMillion: OUTPUT_USD_PER_MILLION || null,
      totalUsdPerMillion: TOTAL_USD_PER_MILLION || null,
      configured: Boolean(
        INPUT_USD_PER_MILLION ||
        OUTPUT_USD_PER_MILLION ||
        TOTAL_USD_PER_MILLION,
      ),
    },
    hasKey: operational,
  });
});

app.post("/api/layout", async (req, res) => {
  const pages = Array.isArray(req.body?.pages) ? req.body.pages : [];
  if (!pages.length)
    return res.status(400).json({ error: "请至少提供一张图片" });
  const started = performance.now();
  try {
    const selection = resolveSelection(req.body?.provider, req.body?.model);
    const provider = selection.provider.id;
    const model = selection.model;
    let layouts = await mapWithConcurrency(
      pages,
      async (page) => {
        try {
          return await analyzeLayout(page, provider, model);
        } catch (firstError) {
          try {
            return await analyzeLayout(page, provider, model);
          } catch (secondError) {
            throw new Error(
              `重试后仍失败：${secondError.message || firstError.message}`,
            );
          }
        }
      },
      2,
    );
    layouts = inferMissingPaperKeys(layouts);
    const tokenUsage = addUsage(...layouts.map((layout) => layout.usage));
    const tokenUsageRecorded = layouts.some((layout) => layout.usageAvailable);
    const orientationModelMs = layouts.reduce(
      (sum, layout) => sum + Number(layout.orientationElapsedMs || 0),
      0,
    );
    const regionModelMs = layouts.reduce(
      (sum, layout) => sum + Number(layout.regionElapsedMs || 0),
      0,
    );
    const actualProviders = [
      ...new Set(layouts.map((layout) => layout.provider).filter(Boolean)),
    ];
    const providerFailoverCount = layouts.reduce(
      (sum, layout) => sum + Number(layout.providerFailoverCount || 0),
      0,
    );
    res.json({
      provider: actualProviders.length === 1 ? actualProviders[0] : provider,
      providerLabel:
        actualProviders.length === 1
          ? PROVIDERS.find((item) => item.id === actualProviders[0])?.label ||
            selection.provider.label
          : selection.provider.label,
      requestedProvider: provider,
      actualProviders,
      providerFailoverCount,
      model,
      layouts,
      elapsedMs: Math.round(performance.now() - started),
      orientationModelMs,
      regionModelMs,
      tokenUsage,
      tokenUsageRecorded,
      estimatedCostUsd: usageCostUsd(tokenUsage),
    });
  } catch (error) {
    res.status(error.status || 500).json({ error: error.message });
  }
});

app.post("/api/recognize", async (req, res) => {
  const blocks = prepareRecognitionBlocks(req.body?.blocks);
  if (!blocks.length)
    return res.status(400).json({ error: "没有可识别的题目块" });
  const started = performance.now();
  try {
    const selection = resolveSelection(req.body?.provider, req.body?.model);
    const provider = selection.provider.id;
    const model = selection.model;
    if (
      blocks.some(
        (block) =>
          (block.provider && block.provider !== provider) ||
          (block.model && block.model !== model),
      )
    )
      return res
        .status(400)
        .json({ error: "版面分析与 OCR 必须使用同一提供者和模型" });
    const groups = groupBlocksForOcr(blocks);
    const reports = await mapWithConcurrency(
      groups,
      (entries) => recognizeGroupWithFallback(entries, provider, model),
      MAX_CONCURRENT_OCR,
    );
    const ordered = reports
      .flatMap((report) => report.results || [])
      .sort((a, b) => a.inputIndex - b.inputIndex);
    const rawResults = ordered.map((item) => item.result);
    const results = mergeRecognizedResults(rawResults);
    const fallbackBatchCount = reports.filter(
      (report) => report.fallback,
    ).length;
    const modelRequestCount = reports.reduce(
      (sum, report) => sum + Number(report.requestCount || 0),
      0,
    );
    const tokenUsage = addUsage(...reports.map((report) => report.usage));
    const tokenUsageRecorded = reports.some((report) => report.usageAvailable);
    const actualProviders = [
      ...new Set(rawResults.map((item) => item.provider).filter(Boolean)),
    ];
    const providerFailoverCount = rawResults.reduce(
      (sum, item) => sum + Number(item.providerFailoverCount || 0),
      0,
    );
    res.json({
      provider: actualProviders.length === 1 ? actualProviders[0] : provider,
      providerLabel:
        actualProviders.length === 1
          ? PROVIDERS.find((item) => item.id === actualProviders[0])?.label ||
            selection.provider.label
          : selection.provider.label,
      requestedProvider: provider,
      actualProviders,
      providerFailoverCount,
      model,
      results,
      elapsedMs: Math.round(performance.now() - started),
      concurrency: MAX_CONCURRENT_OCR,
      blocksPerRequest: MAX_BLOCKS_PER_OCR_REQUEST,
      completedCount: results.length,
      rawResultCount: rawResults.length,
      reviewCount: results.filter((item) => item.reviewRequired).length,
      mergedContinuationCount: rawResults.length - results.length,
      batchCount: groups.length,
      modelRequestCount,
      fallbackBatchCount,
      tokenUsage,
      tokenUsageRecorded,
      estimatedCostUsd: usageCostUsd(tokenUsage),
      savedRequestCount: Math.max(0, blocks.length - groups.length),
    });
  } catch (error) {
    res.status(error.status || 500).json({ error: error.message });
  }
});

app.get("/api/benchmarks", async (_req, res) => {
  try {
    res.json((await readBenchmarks()).slice(0, 500));
  } catch (error) {
    res.status(500).json({ error: `对比记录读取失败：${error.message}` });
  }
});

app.post("/api/benchmarks", async (req, res) => {
  try {
    const now = new Date().toISOString();
    const benchmark = {
      ...cleanBenchmarkPayload(req.body),
      id: randomUUID(),
      createdAt: now,
      updatedAt: now,
    };
    await writeBenchmark(benchmark);
    await pruneBenchmarks();
    res.json(benchmark);
  } catch (error) {
    res
      .status(error.status || 500)
      .json({ error: `对比记录保存失败：${error.message}` });
  }
});

app.put("/api/benchmarks/:id", async (req, res) => {
  try {
    const target = path.join(BENCHMARKS_DIR, `${req.params.id}.json`);
    const existing = JSON.parse(await fs.readFile(target, "utf8"));
    const benchmark = {
      ...existing,
      ...cleanBenchmarkPayload({ ...existing, ...req.body }),
      id: existing.id,
      createdAt: existing.createdAt,
      updatedAt: new Date().toISOString(),
    };
    await writeBenchmark(benchmark);
    res.json(benchmark);
  } catch (error) {
    if (error.code === "ENOENT")
      return res.status(404).json({ error: "对比记录不存在" });
    res
      .status(error.status || 500)
      .json({ error: `对比记录更新失败：${error.message}` });
  }
});

app.delete("/api/benchmarks", async (_req, res) => {
  try {
    await fs.rm(BENCHMARKS_DIR, { recursive: true, force: true });
    await fs.mkdir(BENCHMARKS_DIR, { recursive: true });
    res.json({ ok: true });
  } catch (error) {
    res.status(500).json({ error: `对比记录清空失败：${error.message}` });
  }
});

app.post("/api/jobs", async (req, res) => {
  try {
    const job = {
      ...req.body,
      id: req.body?.id || randomUUID(),
      createdAt: new Date().toISOString(),
    };
    delete job.images;
    await writeJob(job);
    res.json({ id: job.id, createdAt: job.createdAt });
  } catch (error) {
    res.status(500).json({ error: `任务保存失败：${error.message}` });
  }
});

app.get("/api/jobs", async (_req, res) => {
  await fs.mkdir(JOBS_DIR, { recursive: true });
  const names = (await fs.readdir(JOBS_DIR)).filter((name) =>
    name.endsWith(".json"),
  );
  const jobs = (
    await Promise.all(
      names.map(async (name) => {
        try {
          return JSON.parse(
            await fs.readFile(path.join(JOBS_DIR, name), "utf8"),
          );
        } catch {
          return null;
        }
      }),
    )
  ).filter(Boolean);
  jobs.sort((a, b) =>
    String(b.createdAt || "").localeCompare(String(a.createdAt || "")),
  );
  res.json(
    jobs.slice(0, 30).map((job) => ({
      id: job.id,
      title: job.title,
      createdAt: job.createdAt,
      resultCount: job.results?.length || 0,
      paperCount: new Set(
        (job.results || []).map((item) => item.paperKey || "未分组"),
      ).size,
      totalElapsedMs: job.timing?.totalElapsedMs || 0,
      provider: job.timing?.provider || job.provider || DEFAULT_PROVIDER,
      model: job.timing?.model || job.model || DEFAULT_MODEL,
    })),
  );
});

app.get("/api/jobs/:id", async (req, res) => {
  try {
    res.json(
      JSON.parse(
        await fs.readFile(path.join(JOBS_DIR, `${req.params.id}.json`), "utf8"),
      ),
    );
  } catch {
    res.status(404).json({ error: "任务不存在" });
  }
});

app.get("/api/jobs/:id/export", async (req, res) => {
  try {
    const job = JSON.parse(
      await fs.readFile(path.join(JOBS_DIR, `${req.params.id}.json`), "utf8"),
    );
    if (req.query.format === "json") {
      res.type("application/json").send(JSON.stringify(job, null, 2));
      return;
    }
    const groups = new Map();
    for (const item of job.results || []) {
      const key = item.paperKey || "未分组试卷";
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(item);
    }
    const tokenUsage = addUsage(
      job.timing?.layoutTokenUsage,
      job.timing?.tokenUsage,
    );
    const estimatedCostUsd = usageCostUsd(tokenUsage);
    const tokenUsageRecorded = Boolean(
      job.timing?.layoutTokenUsageRecorded || job.timing?.tokenUsageRecorded,
    );
    const lines = [
      `# ${job.title || "试卷识别结果"}`,
      "",
      `生成时间：${job.createdAt}`,
      `提供者：${job.timing?.providerLabel || job.timing?.provider || job.provider || DEFAULT_PROVIDER}`,
      `使用模型：${job.timing?.model || job.model || DEFAULT_MODEL}`,
      `总耗时：${job.timing?.totalElapsedMs || 0} ms`,
      `分阶段耗时：方向 ${job.timing?.orientationModelMs || 0} ms，版面 ${job.timing?.regionModelMs || 0} ms，裁切 ${job.timing?.cropMs || 0} ms，OCR ${job.timing?.ocrMs || 0} ms`,
      `OCR 配置：${job.timing?.ocrConcurrency || "—"} 路并发，每请求最多 ${job.timing?.ocrBatchSize || "—"} 块`,
      `OCR 调度：${job.timing?.ocrBatchCount || "—"} 批，实际模型请求 ${job.timing?.modelRequestCount || "—"} 次，降级批次 ${job.timing?.fallbackBatchCount || 0} 次`,
      `同题续块：${job.timing?.mergedContinuationCount || 0} 组由模型判断后拼接`,
      `Token 用量：${tokenUsageRecorded ? `输入 ${tokenUsage.inputTokens}，输出 ${tokenUsage.outputTokens}，合计 ${tokenUsage.totalTokens}` : "模型未返回 usage，无法统计"}`,
      `估算费用：${!tokenUsageRecorded ? "无法估算（缺少 token）" : estimatedCostUsd === null ? "未配置单价" : `$${estimatedCostUsd.toFixed(8)}`}`,
      `试卷数：${groups.size}`,
      "",
    ];
    let paperIndex = 0;
    for (const [paperKey, items] of groups) {
      paperIndex += 1;
      const pages = (job.layouts || [])
        .filter(
          (layout) =>
            (layout.studentKey || layout.studentLabel || "未分组试卷") ===
            paperKey,
        )
        .map((layout) => layout.fileName)
        .filter(Boolean);
      const reviewItems = items.filter((item) => {
        const text =
          `${item.question || ""} ${item.studentAnswer || ""} ${item.notes || ""}`.replace(
            /无截断|无缺失|不影响文字辨认|没有截断/g,
            "",
          );
        return (
          Number(item.confidence || 0) < 0.65 ||
          /无法辨认|截断|缺失|不完整|残缺|裁切|裁剪|看不清/.test(text)
        );
      });
      lines.push(
        `## 第${paperIndex}份试卷：${paperKey}`,
        "",
        pages.length ? `页面：${pages.join("、")}` : "",
        reviewItems.length
          ? `复核提示：第${reviewItems.map((item) => item.questionNumber || "?").join("、")}题`
          : "复核提示：无自动标记",
        "",
      );
      items.forEach((item, index) =>
        lines.push(
          `### 第${item.questionNumber || index + 1}题`,
          "",
          `**题目**：${item.question || "（未识别）"}`,
          "",
          `**考生回答**：${item.studentAnswer || "（空）"}`,
          "",
          `识别置信度：${Math.round((item.confidence || 0) * 100)}%　耗时：${item.elapsedMs || 0} ms`,
          item.notes ? `备注：${item.notes}` : "",
          "",
        ),
      );
    }
    res.type("text/markdown").send(lines.join("\n"));
  } catch {
    res.status(404).json({ error: "任务不存在" });
  }
});

app.get("*", (_req, res) => res.sendFile(path.join(__dirname, "index.html")));
if (process.env.NODE_ENV !== "test")
  app.listen(PORT, () =>
    console.log(`Exam analysis workbench: http://localhost:${PORT}`),
  );
