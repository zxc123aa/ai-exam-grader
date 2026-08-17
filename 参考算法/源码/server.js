import express from 'express';
import cors from 'cors';
import dotenv from 'dotenv';
import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';
import { createHash, randomUUID } from 'crypto';
import { readFileSync } from 'fs';
import sharp from 'sharp';

dotenv.config();

const app = express();
const PORT = Number(process.env.PORT || 3417);
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const PIPELINE_VERSION = process.env.PIPELINE_VERSION || 'reference-node-gemini-v3';
const PIPELINE_SOURCE_HASH = createHash('sha256').update(readFileSync(__filename)).digest('hex');
const JOBS_DIR = path.join(__dirname, 'data', 'jobs');
const MAX_CONCURRENT_OCR = Math.max(1, Math.min(8, Number(process.env.MAX_CONCURRENT_OCR || 8)));
const MAX_BLOCKS_PER_OCR_REQUEST = Math.max(1, Math.min(6, Number(process.env.MAX_BLOCKS_PER_OCR_REQUEST || 3)));
const MAX_OCR_BATCH_DATA_LENGTH = 12 * 1024 * 1024;
const ANSWER_VERIFICATION_CONCURRENCY = Math.max(1, Math.min(4, Number(process.env.ANSWER_VERIFICATION_CONCURRENCY || 2)));
const GRADING_ELIGIBILITY_THRESHOLD = Math.max(0, Math.min(1, Number(process.env.GRADING_ELIGIBILITY_THRESHOLD || 0.8)));
const VERIFICATION_FAILURE_CONFIDENCE_CAP = Math.max(0, Math.min(1, Number(process.env.VERIFICATION_FAILURE_CONFIDENCE_CAP || 0.85)));
const EVIDENCE_TEXT_SIMILARITY_MIN = Math.max(0, Math.min(1, Number(process.env.EVIDENCE_TEXT_SIMILARITY_MIN || 0.68)));
const MODEL = process.env.OCR_MODEL || 'gemini-3.5-flash';
const LAYOUT_MODEL = process.env.LAYOUT_MODEL || MODEL;
const INPUT_USD_PER_MILLION = Number(process.env.MODEL_INPUT_USD_PER_MILLION || 0);
const OUTPUT_USD_PER_MILLION = Number(process.env.MODEL_OUTPUT_USD_PER_MILLION || 0);
const TOTAL_USD_PER_MILLION = Number(process.env.MODEL_TOTAL_USD_PER_MILLION || 0);
const LAYOUT_REFINEMENT_ENABLED = String(process.env.LAYOUT_REFINEMENT_ENABLED || 'true').toLowerCase() !== 'false';
const LAYOUT_REFINEMENT_ENGINE = 'horizontal_projection_v2';
const FIRST_QUESTION_ANCHOR_ENGINE = 'printed_question_anchor_v1';
const LAYOUT_REFINEMENT_MIN_CONFIDENCE = Math.max(0.5, Math.min(0.95, Number(process.env.LAYOUT_REFINEMENT_MIN_CONFIDENCE || 0.68)));
// 版面分割模型调用的输入压缩：长边超限才重编码，否则原样使用。
// 分割输出是归一化坐标，裁切仍走全分辨率原图，压缩不影响下游清晰度。
const LAYOUT_MODEL_MAX_SIDE = Math.max(768, Math.min(4096, Number(process.env.LAYOUT_MODEL_MAX_SIDE || 1600)));
const LAYOUT_MODEL_JPEG_QUALITY = Math.max(40, Math.min(95, Number(process.env.LAYOUT_MODEL_JPEG_QUALITY || 85)));
// 方向判断候选图压缩：900 长边占 2×2=4 tile，四张候选 16 tile；压到 768 内
// 每张只占 1 tile（共 4 tile）。判断文字方向不需要更高分辨率。
const ORIENTATION_MODEL_MAX_SIDE = Math.max(384, Math.min(1024, Number(process.env.ORIENTATION_MODEL_MAX_SIDE || 768)));
// 尺寸达标但体积仍超过该阈值的图（如高噪 PNG）也重编码，与后端 downscale_image_for_model 的 SKIP_BYTES 对齐
const LAYOUT_MODEL_SKIP_BYTES = 800 * 1024;
const OCR_CROP_PAD_X = Math.max(0, Math.min(80, Number(process.env.OCR_CROP_PAD_X || 24)));
const OCR_CROP_PAD_Y = Math.max(0, Math.min(40, Number(process.env.OCR_CROP_PAD_Y || 0)));
const DOCUMENT_AFFINE_NORMALIZATION_ENABLED = String(process.env.DOCUMENT_AFFINE_NORMALIZATION_ENABLED || 'false').toLowerCase() !== 'false';
const DOCUMENT_DESKEW_MAX_DEGREES = Math.max(0, Math.min(6, Number(process.env.DOCUMENT_DESKEW_MAX_DEGREES || 3)));
const DOCUMENT_DESKEW_STEP_DEGREES = Math.max(0.1, Math.min(1, Number(process.env.DOCUMENT_DESKEW_STEP_DEGREES || 0.5)));
const DOCUMENT_DESKEW_MIN_ABS_DEGREES = Math.max(0, Math.min(1, Number(process.env.DOCUMENT_DESKEW_MIN_ABS_DEGREES || 0.35)));
const DOCUMENT_DESKEW_MIN_SCORE_GAIN = Math.max(0, Math.min(0.5, Number(process.env.DOCUMENT_DESKEW_MIN_SCORE_GAIN || 0.035)));

app.use(cors());
app.use(express.json({ limit: '120mb' }));
app.use(express.static(__dirname));

function buildModelUrl(base) {
  const normalized = String(base || 'https://fluxnode.org').replace(/\/+$/, '');
  return normalized.endsWith('/v1') ? `${normalized}/chat/completions` : `${normalized}/v1/chat/completions`;
}

function hostLabel(base) {
  try {
    return new URL(String(base || 'https://fluxnode.org')).host;
  } catch {
    return 'invalid-provider-url';
  }
}

// 智能路由：主供应商 + 可选备用供应商（NEWAPI_FALLBACK_*）。
// 主供应商超时/断连/限流/5xx/鉴权失败时快速切换到备用，并进入冷却期，
// 冷却期内后续请求直接走备用，避免每次调用都先等主供应商超时。
const PROVIDER_REQUEST_TIMEOUT_MS = Math.max(5000, Number(process.env.MODEL_REQUEST_TIMEOUT_MS || 90000));
const PROVIDER_FAILOVER_COOLDOWN_MS = Math.max(10000, Number(process.env.PROVIDER_FAILOVER_COOLDOWN_MS || 120000));

const MODEL_PROVIDERS = [
  process.env.NEWAPI_API_KEY && {
    name: hostLabel(process.env.NEWAPI_BASE_URL),
    url: buildModelUrl(process.env.NEWAPI_BASE_URL),
    key: process.env.NEWAPI_API_KEY,
    ocrModel: MODEL,
    layoutModel: LAYOUT_MODEL
  },
  (process.env.NEWAPI_FALLBACK_API_KEY || process.env.NEWAPI_FALLBACK_BASE_URL) && {
    name: `${hostLabel(process.env.NEWAPI_FALLBACK_BASE_URL)}(备用)`,
    url: buildModelUrl(process.env.NEWAPI_FALLBACK_BASE_URL),
    key: process.env.NEWAPI_FALLBACK_API_KEY || process.env.NEWAPI_API_KEY,
    ocrModel: process.env.OCR_FALLBACK_MODEL || MODEL,
    layoutModel: process.env.LAYOUT_FALLBACK_MODEL || LAYOUT_MODEL
  }
].filter(Boolean);

const providerCircuit = new Map(); // name -> downUntil (epoch ms)

function modelUrl() {
  return buildModelUrl(process.env.NEWAPI_BASE_URL);
}

function providerLabel() {
  return hostLabel(process.env.NEWAPI_BASE_URL);
}

function pipelineMetadata({ tokenUsage = normalizeUsage(), tokenUsageRecorded = false } = {}) {
  return {
    pipeline_version: PIPELINE_VERSION,
    prompt_hash: PIPELINE_SOURCE_HASH,
    prompt_hash_scope: 'server_source_including_prompts',
    model: MODEL,
    layout_model: LAYOUT_MODEL,
    provider: providerLabel(),
    thresholds: {
      grading_eligibility: GRADING_ELIGIBILITY_THRESHOLD,
      verification_failure_confidence_cap: VERIFICATION_FAILURE_CONFIDENCE_CAP,
      evidence_text_similarity_min: EVIDENCE_TEXT_SIMILARITY_MIN,
      layout_refinement_min_confidence: LAYOUT_REFINEMENT_MIN_CONFIDENCE
    },
    layout_refinement: {
      enabled: LAYOUT_REFINEMENT_ENABLED,
      engine: LAYOUT_REFINEMENT_ENGINE,
      first_question_anchor_engine: FIRST_QUESTION_ANCHOR_ENGINE
    },
    layout_model_image: {
      max_side: LAYOUT_MODEL_MAX_SIDE,
      jpeg_quality: LAYOUT_MODEL_JPEG_QUALITY
    },
    orientation_model_image: {
      max_side: ORIENTATION_MODEL_MAX_SIDE
    },
    ocr_crop_padding: {
      x: OCR_CROP_PAD_X,
      y: OCR_CROP_PAD_Y
    },
    document_affine_normalization: {
      enabled: DOCUMENT_AFFINE_NORMALIZATION_ENABLED,
      deskew_max_degrees: DOCUMENT_DESKEW_MAX_DEGREES,
      deskew_step_degrees: DOCUMENT_DESKEW_STEP_DEGREES,
      deskew_min_abs_degrees: DOCUMENT_DESKEW_MIN_ABS_DEGREES,
      deskew_min_score_gain: DOCUMENT_DESKEW_MIN_SCORE_GAIN
    },
    git_commit: process.env.GIT_COMMIT || null,
    generated_at: new Date().toISOString(),
    token_usage: normalizeUsage(tokenUsage),
    token_usage_recorded: Boolean(tokenUsageRecorded)
  };
}

function parseJson(text) {
  const fenced = String(text || '').match(/```(?:json)?\s*([\s\S]*?)\s*```/i);
  const raw = fenced?.[1] || String(text || '').slice(String(text || '').indexOf('{'), String(text || '').lastIndexOf('}') + 1);
  if (!raw || !raw.trim()) throw new Error('模型没有返回 JSON');
  return JSON.parse(raw);
}

function parseLooseJson(text) {
  try {
    return parseJson(text);
  } catch (originalError) {
    const fenced = String(text || '').match(/```(?:json)?\s*([\s\S]*?)\s*```/i);
    const source = fenced?.[1] || String(text || '').slice(String(text || '').indexOf('{'), String(text || '').lastIndexOf('}') + 1);
    const structurallyRepaired = source
      .replace(/[“”]/g, '"')
      .replace(/[‘’]/g, "'")
      .replace(/([{,]\s*)([A-Za-z_][A-Za-z0-9_-]*)(\s*:)/g, '$1"$2"$3')
      .replace(/}\s*{/g, '},{')
      .replace(/(\d|true|false|null)\s+(?="[A-Za-z_][A-Za-z0-9_-]*"\s*:)/g, '$1,')
      .replace(/,\s*([}\]])/g, '$1');
    let repaired = '';
    let inString = false;
    for (let index = 0; index < structurallyRepaired.length; index += 1) {
      const character = structurallyRepaired[index];
      if (character === '"') {
        let slashCount = 0;
        for (let previous = index - 1; previous >= 0 && structurallyRepaired[previous] === '\\'; previous -= 1) slashCount += 1;
        if (slashCount % 2 === 0) inString = !inString;
        repaired += character;
        continue;
      }
      if (inString && character === '\\') {
        const next = structurallyRepaired[index + 1] || '';
        repaired += /["\\/bfnrtu]/.test(next) ? '\\' : '\\\\';
        continue;
      }
      if (inString && character === '\n') { repaired += '\\n'; continue; }
      if (inString && character === '\r') { repaired += '\\r'; continue; }
      if (inString && character === '\t') { repaired += '\\t'; continue; }
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
  const inputTokens = Number(usage.prompt_tokens ?? usage.input_tokens ?? usage.promptTokens ?? 0) || 0;
  const outputTokens = Number(usage.completion_tokens ?? usage.output_tokens ?? usage.completionTokens ?? 0) || 0;
  const totalTokens = Number(usage.total_tokens ?? usage.totalTokens ?? inputTokens + outputTokens) || inputTokens + outputTokens;
  return { inputTokens, outputTokens, totalTokens };
}

export function addUsage(...usages) {
  return usages.reduce((total, usage) => {
    const current = normalizeUsage(usage);
    total.inputTokens += current.inputTokens;
    total.outputTokens += current.outputTokens;
    total.totalTokens += current.totalTokens;
    return total;
  }, { inputTokens: 0, outputTokens: 0, totalTokens: 0 });
}

export function usageCostUsd(usage) {
  const normalized = normalizeUsage(usage);
  if (TOTAL_USD_PER_MILLION) return Number(((normalized.totalTokens / 1e6) * TOTAL_USD_PER_MILLION).toFixed(8));
  if (!INPUT_USD_PER_MILLION && !OUTPUT_USD_PER_MILLION) return null;
  if (normalized.totalTokens && !normalized.inputTokens && !normalized.outputTokens) return null;
  return Number(((normalized.inputTokens / 1e6) * INPUT_USD_PER_MILLION + (normalized.outputTokens / 1e6) * OUTPUT_USD_PER_MILLION).toFixed(8));
}

async function callModelOnProvider(provider, { model, messages, temperature = 0.1 }) {
  const routedModel = model === LAYOUT_MODEL ? provider.layoutModel : provider.ocrModel;
  const started = performance.now();
  const response = await fetch(provider.url, {
    method: 'POST',
    signal: AbortSignal.timeout(PROVIDER_REQUEST_TIMEOUT_MS),
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${provider.key}` },
    body: JSON.stringify({ model: routedModel, temperature, messages })
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.error?.message || `模型请求失败（HTTP ${response.status}）`);
    error.status = response.status;
    throw error;
  }
  return { data, elapsedMs: Math.round(performance.now() - started), usage: normalizeUsage(data.usage), usageAvailable: Boolean(data.usage), provider: provider.name };
}

function isFailoverWorthyError(error) {
  return isTransientModelError(error) || [401, 402, 403, 404].includes(Number(error?.status));
}

async function callModel(options) {
  if (!MODEL_PROVIDERS.length) throw new Error('服务端未配置 NEWAPI_API_KEY，请填写 .env');
  const now = Date.now();
  const cooling = (provider) => (providerCircuit.get(provider.name) || 0) > now;
  // 全部供应商都在冷却期时，忽略冷却重试一轮（半开探测），而不是直接失败。
  const candidates = MODEL_PROVIDERS.filter((provider) => !cooling(provider));
  const route = candidates.length > 0 ? candidates : MODEL_PROVIDERS;
  let lastError;
  for (const provider of route) {
    try {
      const result = await callModelOnProvider(provider, options);
      providerCircuit.delete(provider.name);
      return result;
    } catch (error) {
      lastError = error;
      if (!isFailoverWorthyError(error)) throw error;
      providerCircuit.set(provider.name, Date.now() + PROVIDER_FAILOVER_COOLDOWN_MS);
      const hasNext = route.indexOf(provider) < route.length - 1;
      console.warn(
        hasNext
          ? `[router] 供应商 ${provider.name} 调用失败（${error.message}），切换下一供应商，冷却 ${PROVIDER_FAILOVER_COOLDOWN_MS / 1000}s`
          : `[router] 供应商 ${provider.name} 调用失败（${error.message}），已无可用备用供应商`
      );
    }
  }
  throw lastError;
}

export function isTransientModelError(error) {
  const message = String(error?.message || '');
  return error?.name === 'TimeoutError'
    || error?.name === 'AbortError'
    || error?.name === 'TypeError'
    || /fetch failed|econnreset|econnrefused|socket|network|tls|connect/i.test(message)
    || error?.status === 429
    || Number(error?.status) >= 500;
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
      await new Promise(resolve => setTimeout(resolve, 700 + Math.round(Math.random() * 500)));
    }
  }
  throw lastError;
}

async function callOcrJson(options, { loose = false } = {}) {
  let usage = normalizeUsage();
  let usageAvailable = false;
  let elapsedMs = 0;
  let attempts = 0;
  let lastError;
  for (let structuredAttempt = 1; structuredAttempt <= 2; structuredAttempt += 1) {
    const messages = structuredAttempt === 1
      ? options.messages
      : [...options.messages, { role: 'user', content: '严格只返回合法 JSON。所有属性名和字符串必须使用双引号，字符串内部换行必须转义，不要 Markdown，不要注释。' }];
    const result = await callOcrModel({ ...options, messages });
    usage = addUsage(usage, result.usage);
    usageAvailable ||= result.usageAvailable;
    elapsedMs += Number(result.elapsedMs || 0);
    attempts += Number(result.attempts || 1);
    try {
      const content = result.data.choices?.[0]?.message?.content || '';
      const parsed = loose ? parseLooseJson(content) : parseJson(content);
      return { ...result, parsed, usage, usageAvailable, elapsedMs, attempts };
    } catch (error) {
      lastError = error;
    }
  }
  throw new Error(`模型连续返回无效 JSON：${lastError?.message || '未知解析错误'}`);
}

function cleanRegion(region, index) {
  const number = (value, fallback = 0) => Number.isFinite(Number(value)) ? Math.max(0, Math.min(1000, Math.round(Number(value)))) : fallback;
  const ymin = number(region?.ymin);
  const xmin = number(region?.xmin);
  const ymax = Math.max(ymin + 20, number(region?.ymax, 1000));
  const xmax = Math.max(xmin + 20, number(region?.xmax, 1000));
  return {
    id: region?.id || `block_${index + 1}`,
    questionNumber: String(region?.questionNumber || '').trim(),
    label: String(region?.label || `第 ${index + 1} 块`),
    kind: ['question', 'answer', 'question_answer', 'continuation'].includes(region?.kind) ? region.kind : 'question_answer',
    readingOrder: Number(region?.readingOrder || index + 1),
    continuationOf: region?.continuationOf ? String(region.continuationOf) : null,
    ymin, xmin, ymax: Math.min(1000, ymax), xmax: Math.min(1000, xmax)
  };
}

function paddedCropBounds(region, width, height) {
  const xmin = clamp(Number(region.xmin || 0) - OCR_CROP_PAD_X, 0, 1000);
  const ymin = clamp(Number(region.ymin || 0) - OCR_CROP_PAD_Y, 0, 1000);
  const xmax = clamp(Number(region.xmax || 1000) + OCR_CROP_PAD_X, 0, 1000);
  const ymax = clamp(Number(region.ymax || 1000) + OCR_CROP_PAD_Y, 0, 1000);
  const left = Math.max(0, Math.floor(xmin / 1000 * width));
  const top = Math.max(0, Math.floor(ymin / 1000 * height));
  const right = Math.min(width, Math.ceil(xmax / 1000 * width));
  const bottom = Math.min(height, Math.ceil(ymax / 1000 * height));
  return {
    normalized: { xmin, ymin, xmax, ymax },
    pixels: { left, top, right, bottom }
  };
}

function clamp(value, minimum, maximum) {
  return Math.max(minimum, Math.min(maximum, value));
}

function median(values) {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

function quantile(values, ratio) {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.max(0, Math.round((sorted.length - 1) * ratio)))];
}

function groupRegionIndexesByColumn(regions) {
  const indexed = regions.map((region, index) => ({
    index,
    center: (Number(region.xmin || 0) + Number(region.xmax || 1000)) / 2
  })).sort((a, b) => a.center - b.center);
  if (indexed.length < 2) return [indexed.map(item => item.index)];
  let largestGap = 0;
  let splitIndex = -1;
  for (let index = 1; index < indexed.length; index += 1) {
    const gap = indexed[index].center - indexed[index - 1].center;
    if (gap > largestGap) {
      largestGap = gap;
      splitIndex = index;
    }
  }
  if (largestGap < 150 || splitIndex <= 0 || splitIndex >= indexed.length) {
    return [indexed.map(item => item.index)];
  }
  return [indexed.slice(0, splitIndex), indexed.slice(splitIndex)].map(group => group.map(item => item.index));
}

function otsuThreshold(data, width, bounds) {
  const histogram = new Uint32Array(256);
  let total = 0;
  for (let y = bounds.top; y < bounds.bottom; y += 2) {
    const rowOffset = y * width;
    for (let x = bounds.left; x < bounds.right; x += 2) {
      histogram[data[rowOffset + x]] += 1;
      total += 1;
    }
  }
  if (!total) return 145;
  let totalWeighted = 0;
  for (let value = 0; value < 256; value += 1) totalWeighted += value * histogram[value];
  let backgroundWeight = 0;
  let backgroundWeighted = 0;
  let bestVariance = -1;
  let bestThreshold = 145;
  for (let value = 0; value < 256; value += 1) {
    backgroundWeight += histogram[value];
    if (!backgroundWeight) continue;
    const foregroundWeight = total - backgroundWeight;
    if (!foregroundWeight) break;
    backgroundWeighted += value * histogram[value];
    const backgroundMean = backgroundWeighted / backgroundWeight;
    const foregroundMean = (totalWeighted - backgroundWeighted) / foregroundWeight;
    const variance = backgroundWeight * foregroundWeight * (backgroundMean - foregroundMean) ** 2;
    if (variance > bestVariance) {
      bestVariance = variance;
      bestThreshold = value;
    }
  }
  return clamp(bestThreshold, 80, 185);
}

function buildHorizontalInkProjection(data, width, height, left, right, threshold) {
  const projection = new Float64Array(height);
  const safeLeft = clamp(Math.round(left), 0, width - 1);
  const safeRight = clamp(Math.round(right), safeLeft + 1, width);
  const span = Math.max(1, safeRight - safeLeft);
  for (let y = 0; y < height; y += 1) {
    const rowOffset = y * width;
    let ink = 0;
    for (let x = safeLeft; x < safeRight; x += 1) {
      if (data[rowOffset + x] <= threshold) ink += 1;
    }
    projection[y] = ink / span;
  }
  return projection;
}

function buildLocalContrastProjection(data, background, width, height, left, right, top, bottom) {
  const safeLeft = clamp(Math.round(left), 0, width - 1);
  const safeRight = clamp(Math.round(right), safeLeft + 1, width);
  const safeTop = clamp(Math.round(top), 0, height - 1);
  const safeBottom = clamp(Math.round(bottom), safeTop + 1, height);
  const span = Math.max(1, safeRight - safeLeft);
  const projection = [];
  for (let y = safeTop; y < safeBottom; y += 1) {
    const rowOffset = y * width;
    let ink = 0;
    for (let x = safeLeft; x < safeRight; x += 1) {
      // Local background subtraction rejects the dark desk, paper shadows and
      // uneven lighting while retaining narrow printed strokes.
      if (background[rowOffset + x] - data[rowOffset + x] >= 10) ink += 1;
    }
    projection.push(ink / span);
  }
  return { projection, top: safeTop };
}

function findPrintedRowBands(data, background, width, height, region, stripRatio) {
  const regionLeft = Math.round(region.xmin / 1000 * width);
  const regionRight = Math.round(region.xmax / 1000 * width);
  const regionTop = Math.round(region.ymin / 1000 * height);
  const regionBottom = Math.round(region.ymax / 1000 * height);
  const xInset = Math.max(2, Math.round(width * 0.002));
  const left = clamp(regionLeft + xInset, 0, width - 1);
  const right = clamp(
    regionLeft + Math.round((regionRight - regionLeft) * stripRatio),
    left + 1,
    width
  );
  const top = clamp(regionTop - Math.round(height * 0.005), 0, height - 1);
  const bottom = clamp(
    Math.min(
      regionBottom,
      regionTop + Math.round(height * 0.16),
      regionTop + Math.round((regionBottom - regionTop) * 0.48)
    ),
    top + 1,
    height
  );
  const local = buildLocalContrastProjection(data, background, width, height, left, right, top, bottom);
  const smoothed = local.projection.map((value, index, values) => {
    const previous = values[index - 1] ?? value;
    const next = values[index + 1] ?? value;
    return (previous + value + next) / 3;
  });
  const activeThreshold = 0.012;
  const maximumGap = Math.max(1, Math.round(height * 0.0015));
  const minimumBandHeight = Math.max(2, Math.round(height * 0.0018));
  const rawBands = [];
  let start = -1;
  let lastActive = -1;
  for (let index = 0; index <= smoothed.length; index += 1) {
    const active = index < smoothed.length && smoothed[index] >= activeThreshold;
    if (active) {
      if (start < 0) start = index;
      lastActive = index;
      continue;
    }
    if (start >= 0 && (index === smoothed.length || index - lastActive > maximumGap)) {
      if (lastActive - start + 1 >= minimumBandHeight) rawBands.push({ start, end: lastActive });
      start = -1;
      lastActive = -1;
    }
  }
  return rawBands.map(band => {
    const startY = local.top + band.start;
    const endY = local.top + band.end;
    const minimumColumnInk = Math.max(2, Math.round((endY - startY + 1) * 0.1));
    let leadingInkX = right;
    for (let x = left; x < right; x += 1) {
      let columnInk = 0;
      for (let y = startY; y <= endY; y += 1) {
        if (background[y * width + x] - data[y * width + x] >= 10) columnInk += 1;
      }
      if (columnInk >= minimumColumnInk) {
        leadingInkX = x;
        break;
      }
    }
    return {
      startY,
      endY,
      start: Math.round(startY / height * 1000),
      end: Math.round(endY / height * 1000),
      leadingInkX: Math.round(leadingInkX / width * 1000),
      maximumInk: Number(Math.max(...smoothed.slice(band.start, band.end + 1)).toFixed(4))
    };
  });
}

function findFirstQuestionTopAnchor(data, background, width, height, region) {
  const stripRatios = [0.15, 0.2, 0.25];
  const detections = [];
  for (const stripRatio of stripRatios) {
    const bands = findPrintedRowBands(data, background, width, height, region, stripRatio);
    if (bands.length < 2) continue;
    const heading = bands[0];
    let questionIndex = -1;
    for (let index = 1; index < Math.min(bands.length, 4); index += 1) {
      const leadingDelta = bands[index].leadingInkX - heading.leadingInkX;
      const intermediateBands = bands.slice(1, index);
      const intermediateIndented = intermediateBands.every(band => band.leadingInkX - heading.leadingInkX >= 8);
      if (Math.abs(leadingDelta) <= 7 && (index === 1 || intermediateIndented)) {
        questionIndex = index;
        break;
      }
    }
    if (questionIndex < 1) continue;
    const question = bands[questionIndex];
    const precedingBands = bands.slice(0, questionIndex);
    const headingHeight = heading.end - heading.start + 1;
    const precedingHeights = precedingBands.map(band => band.end - band.start + 1);
    const gaps = bands.slice(1, questionIndex + 1).map((band, index) => band.start - bands[index].end);
    const rawGap = heading.start - region.ymin;
    const candidateShift = question.start - region.ymin;
    const maximumShift = Math.min(105, Math.round((region.ymax - region.ymin) * 0.36));
    const structureSafe = rawGap >= 10
      && candidateShift >= 22
      && candidateShift <= maximumShift
      && headingHeight <= 20
      && precedingHeights.every(bandHeight => bandHeight <= 20)
      && gaps.every(gap => gap >= 2 && gap <= 24);
    if (!structureSafe) continue;
    detections.push({
      stripRatio,
      candidateY: question.start,
      questionIndex,
      rawGap,
      candidateShift,
      gaps,
      headingHeight,
      leadingDelta: question.leadingInkX - heading.leadingInkX,
      candidateInk: question.maximumInk,
      bands: bands.slice(0, questionIndex + 1)
    });
  }
  if (detections.length < 2) return null;
  const candidateValues = detections.map(item => item.candidateY);
  const candidateMedian = median(candidateValues);
  const candidateSpread = Math.max(...candidateValues) - Math.min(...candidateValues);
  const rawGapMedian = median(detections.map(item => item.rawGap));
  const gapMedian = median(detections.flatMap(item => item.gaps));
  const consistencyScore = 1 - clamp(candidateSpread / 8, 0, 1);
  const coverageScore = detections.length / stripRatios.length;
  const rawGapScore = clamp(rawGapMedian / 20, 0, 1);
  const separationScore = clamp(gapMedian / 5, 0, 1);
  const alignmentScore = 1 - clamp(median(detections.map(item => Math.abs(item.leadingDelta))) / 8, 0, 1);
  const inkScore = clamp(median(detections.map(item => item.candidateInk)) / 0.12, 0, 1);
  const confidence = clamp(
    consistencyScore * 0.27
      + coverageScore * 0.2
      + rawGapScore * 0.16
      + separationScore * 0.12
      + alignmentScore * 0.13
      + inkScore * 0.12,
    0,
    1
  );
  const margin = Math.max(3, Math.round(height * 0.003 / height * 1000));
  const normalizedY = clamp(Math.round(candidateMedian - margin), 0, 1000);
  const applied = candidateSpread <= 8
    && confidence >= LAYOUT_REFINEMENT_MIN_CONFIDENCE
    && normalizedY >= region.ymin + 20
    && normalizedY <= region.ymax - 20;
  return {
    source: FIRST_QUESTION_ANCHOR_ENGINE,
    y: normalizedY,
    rawY: region.ymin,
    candidateY: Math.round(candidateMedian),
    stripAgreement: detections.length,
    candidateSpread,
    questionLineIndex: Math.round(median(detections.map(item => item.questionIndex))),
    confidence: Number(confidence.toFixed(4)),
    applied
  };
}

function averageProjection(projection, center, radius) {
  const start = clamp(Math.round(center - radius), 0, projection.length - 1);
  const end = clamp(Math.round(center + radius), start, projection.length - 1);
  let total = 0;
  for (let y = start; y <= end; y += 1) total += projection[y];
  return total / Math.max(1, end - start + 1);
}

function findHorizontalBoundary(projection, imageHeight, previous, next) {
  const previousTop = Math.round(previous.ymin / 1000 * imageHeight);
  const previousBottom = Math.round(previous.ymax / 1000 * imageHeight);
  const nextTop = Math.round(next.ymin / 1000 * imageHeight);
  const nextBottom = Math.round(next.ymax / 1000 * imageHeight);
  const expected = Math.round((previousBottom + nextTop) / 2);
  const roughDisagreement = Math.abs(previousBottom - nextTop);
  const searchRadius = Math.round(clamp(
    Math.max(imageHeight * 0.022, roughDisagreement / 2 + imageHeight * 0.01),
    14,
    imageHeight * 0.05
  ));
  const minimumRegionHeight = Math.max(12, Math.round(imageHeight * 0.018));
  const searchStart = clamp(expected - searchRadius, previousTop + minimumRegionHeight, nextBottom - minimumRegionHeight);
  const searchEnd = clamp(expected + searchRadius, searchStart, nextBottom - minimumRegionHeight);
  if (searchEnd - searchStart < 4) return null;
  const bandRadius = Math.max(2, Math.round(imageHeight * 0.0025));
  const samples = [];
  for (let y = searchStart; y <= searchEnd; y += 1) {
    const inkRatio = averageProjection(projection, y, bandRadius);
    const distanceRatio = Math.abs(y - expected) / Math.max(1, searchRadius);
    samples.push({ y, inkRatio, distanceRatio, score: inkRatio + distanceRatio * 0.035 });
  }
  const best = samples.reduce((current, sample) => sample.score < current.score ? sample : current, samples[0]);
  const referenceInk = Math.max(0.002, quantile(samples.map(sample => sample.inkRatio), 0.75));
  const blankScore = 1 - clamp(best.inkRatio / referenceInk, 0, 1);
  const distanceScore = 1 - clamp(best.distanceRatio, 0, 1);
  const isValley = best.inkRatio <= 0.025 || best.inkRatio <= referenceInk * 0.72;
  const confidence = clamp((blankScore * 0.68 + distanceScore * 0.32) * (isValley ? 1 : 0.55), 0, 1);
  return {
    y: best.y,
    normalizedY: clamp(Math.round(best.y / imageHeight * 1000), 0, 1000),
    expectedY: expected,
    inkRatio: Number(best.inkRatio.toFixed(4)),
    referenceInk: Number(referenceInk.toFixed(4)),
    confidence: Number(confidence.toFixed(4)),
    applied: isValley && confidence >= LAYOUT_REFINEMENT_MIN_CONFIDENCE
  };
}

function finalizeRegionRefinement(regions) {
  return regions.map(region => {
    const boundaries = [region.refinement.topBoundary, region.refinement.bottomBoundary].filter(Boolean);
    const appliedBoundaries = boundaries.filter(boundary => boundary.applied);
    const confidenceBoundaries = appliedBoundaries.length ? appliedBoundaries : boundaries;
    const confidence = confidenceBoundaries.length
      ? confidenceBoundaries.reduce((sum, boundary) => sum + Number(boundary.confidence || 0), 0) / confidenceBoundaries.length
      : 0;
    return {
      ...region,
      refinement: {
        ...region.refinement,
        applied: appliedBoundaries.length > 0,
        appliedBoundaryCount: appliedBoundaries.length,
        confidence: Number(confidence.toFixed(4))
      }
    };
  });
}

export async function refineLayoutRegions(uprightImage, inputRegions) {
  const regions = inputRegions.map(region => ({
    ...region,
    refinement: {
      engine: LAYOUT_REFINEMENT_ENGINE,
      rawBounds: {
        ymin: region.ymin,
        xmin: region.xmin,
        ymax: region.ymax,
        xmax: region.xmax
      },
      topBoundary: null,
      bottomBoundary: null
    }
  }));
  const source = imageBufferFromDataUrl(uprightImage);
  const { data, info } = await sharp(source).greyscale().raw().toBuffer({ resolveWithObject: true });
  const width = info.width || 1;
  const height = info.height || 1;
  const blurSigma = clamp(Math.min(width, height) * 0.006, 4, 10);
  const { data: localBackground } = await sharp(source).greyscale().blur(blurSigma).raw().toBuffer({ resolveWithObject: true });
  const columnGroups = groupRegionIndexesByColumn(regions);
  for (const groupIndexes of columnGroups) {
    if (!groupIndexes.length) continue;
    const orderedIndexes = [...groupIndexes].sort((leftIndex, rightIndex) => {
      const left = regions[leftIndex];
      const right = regions[rightIndex];
      return Number(left.ymin || 0) - Number(right.ymin || 0) || Number(left.readingOrder || 0) - Number(right.readingOrder || 0);
    });
    const xInset = Math.max(3, Math.round(width * 0.006));
    const left = clamp(Math.round(median(orderedIndexes.map(index => regions[index].xmin)) / 1000 * width) + xInset, 0, width - 1);
    const right = clamp(Math.round(median(orderedIndexes.map(index => regions[index].xmax)) / 1000 * width) - xInset, left + 1, width);
    const top = clamp(Math.round(Math.min(...orderedIndexes.map(index => regions[index].ymin)) / 1000 * height) - 20, 0, height - 1);
    const bottom = clamp(Math.round(Math.max(...orderedIndexes.map(index => regions[index].ymax)) / 1000 * height) + 20, top + 1, height);
    const threshold = otsuThreshold(data, width, { left, right, top, bottom });
    const projection = buildHorizontalInkProjection(data, width, height, left, right, threshold);
    const firstRegion = regions[orderedIndexes[0]];
    const topAnchor = findFirstQuestionTopAnchor(data, localBackground, width, height, firstRegion);
    if (topAnchor) {
      firstRegion.refinement.topBoundary = topAnchor;
      if (topAnchor.applied) firstRegion.ymin = topAnchor.y;
    }
    for (let index = 1; index < orderedIndexes.length; index += 1) {
      const previous = regions[orderedIndexes[index - 1]];
      const next = regions[orderedIndexes[index]];
      const boundary = findHorizontalBoundary(projection, height, previous, next);
      if (!boundary) continue;
      const detail = {
        source: LAYOUT_REFINEMENT_ENGINE,
        y: boundary.normalizedY,
        expectedY: Math.round(boundary.expectedY / height * 1000),
        inkRatio: boundary.inkRatio,
        referenceInk: boundary.referenceInk,
        confidence: boundary.confidence,
        applied: boundary.applied
      };
      previous.refinement.bottomBoundary = detail;
      next.refinement.topBoundary = detail;
      if (!boundary.applied) continue;
      if (boundary.normalizedY <= previous.ymin + 20 || boundary.normalizedY >= next.ymax - 20) continue;
      previous.ymax = boundary.normalizedY;
      next.ymin = boundary.normalizedY;
    }
  }
  return finalizeRegionRefinement(regions);
}

function collectUpwardBoundaryRisks(regions) {
  const risks = [];
  const columnGroups = groupRegionIndexesByColumn(regions);
  for (const groupIndexes of columnGroups) {
    const orderedIndexes = [...groupIndexes].sort((leftIndex, rightIndex) => {
      const left = regions[leftIndex];
      const right = regions[rightIndex];
      return Number(left.refinement?.rawBounds?.ymin ?? left.ymin) - Number(right.refinement?.rawBounds?.ymin ?? right.ymin)
        || Number(left.readingOrder || 0) - Number(right.readingOrder || 0);
    });
    for (let index = 1; index < orderedIndexes.length; index += 1) {
      const previousIndex = orderedIndexes[index - 1];
      const nextIndex = orderedIndexes[index];
      const previous = regions[previousIndex];
      const next = regions[nextIndex];
      const boundary = previous.refinement?.bottomBoundary;
      if (!boundary || boundary.source !== LAYOUT_REFINEMENT_ENGINE) continue;
      const previousRawBottom = Number(previous.refinement?.rawBounds?.ymax ?? previous.ymax);
      const nextRawTop = Number(next.refinement?.rawBounds?.ymin ?? next.ymin);
      const rawBoundary = Math.round((previousRawBottom + nextRawTop) / 2);
      if (Number(boundary.y) >= rawBoundary - 2) continue;
      risks.push({
        pairId: `${previous.id || previousIndex}->${next.id || nextIndex}`,
        previousIndex,
        nextIndex,
        previousQuestionNumber: String(previous.questionNumber || ''),
        nextQuestionNumber: String(next.questionNumber || ''),
        nextRawTop,
        nextRawHeight: Math.max(1, Number(next.refinement?.rawBounds?.ymax ?? next.ymax) - nextRawTop),
        rawBoundary,
        projectedBoundary: Number(boundary.y),
        xmin: Math.min(Number(previous.xmin || 0), Number(next.xmin || 0)),
        xmax: Math.max(Number(previous.xmax || 1000), Number(next.xmax || 1000))
      });
    }
  }
  return risks;
}

async function requestPrintedBoundaryAnchors(uprightImage, risks) {
  if (!risks.length) return { anchors: [], elapsedMs: 0, usage: normalizeUsage(), usageAvailable: false };
  const source = imageBufferFromDataUrl(uprightImage);
  const metadata = await sharp(source).metadata();
  const width = metadata.width || 1;
  const height = metadata.height || 1;
  const content = [{
    type: 'text',
    text: `你是中文试卷题号锚点定位器。下面每张裁图只对应一对相邻题目的交界。你的唯一任务是定位“下一题”的印刷题号及其首行顶部，绝不能把上一题的手写“解：(3)”或手写公式当成下一题。\n坐标 anchorTop 使用各自裁图从上到下归一化 0-1000。只有清晰看见指定的下一题印刷题号（例如 22.、22．）时 visible=true；不确定时 visible=false。只返回 JSON：{"anchors":[{"pairId":"...","nextQuestionNumber":"...","visible":true,"anchorTop":0,"confidence":0到1,"reason":""}]}`
  }];
  const crops = [];
  for (const risk of risks) {
    const x0 = clamp(Math.round((risk.xmin - 12) / 1000 * width), 0, width - 1);
    const x1 = clamp(Math.round((risk.xmax + 12) / 1000 * width), x0 + 1, width);
    const y0Normalized = clamp(risk.rawBoundary - 90, 0, 999);
    const y1Normalized = clamp(risk.rawBoundary + 90, y0Normalized + 1, 1000);
    const y0 = clamp(Math.round(y0Normalized / 1000 * height), 0, height - 1);
    const y1 = clamp(Math.round(y1Normalized / 1000 * height), y0 + 1, height);
    const buffer = await sharp(source)
      .extract({ left: x0, top: y0, width: x1 - x0, height: y1 - y0 })
      .resize({ width: 1200, withoutEnlargement: false })
      .jpeg({ quality: 90 })
      .toBuffer();
    crops.push({ ...risk, y0Normalized, y1Normalized });
    content.push(
      { type: 'text', text: `pairId=${risk.pairId}；上一题=${risk.previousQuestionNumber || '未知'}；必须寻找的下一题印刷题号=${risk.nextQuestionNumber || '未知'}。` },
      { type: 'image_url', image_url: { url: `data:image/jpeg;base64,${buffer.toString('base64')}` } }
    );
  }
  const result = await callOcrModel({ model: LAYOUT_MODEL, messages: [{ role: 'user', content }], temperature: 0.05 });
  const parsed = parseJson(result.data.choices?.[0]?.message?.content || '');
  const returned = Array.isArray(parsed.anchors) ? parsed.anchors : [];
  const anchors = crops.map(crop => {
    const candidate = returned.find(item => String(item?.pairId || '') === crop.pairId);
    const cropAnchor = Number(candidate?.anchorTop);
    const visible = candidate?.visible === true && Number.isFinite(cropAnchor) && cropAnchor >= 0 && cropAnchor <= 1000;
    const anchorY = visible
      ? Math.round(crop.y0Normalized + cropAnchor / 1000 * (crop.y1Normalized - crop.y0Normalized))
      : null;
    return {
      pairId: crop.pairId,
      nextQuestionNumber: String(candidate?.nextQuestionNumber || ''),
      visible,
      anchorY,
      confidence: clamp(Number(candidate?.confidence || 0), 0, 1),
      reason: String(candidate?.reason || '')
    };
  });
  return { anchors, elapsedMs: result.elapsedMs, usage: result.usage, usageAvailable: result.usageAvailable };
}

export function applyPrintedBoundaryAnchors(inputRegions, risks, anchors) {
  const regions = inputRegions.map(region => ({ ...region, refinement: { ...region.refinement } }));
  for (const risk of risks) {
    const previous = regions[risk.previousIndex];
    const next = regions[risk.nextIndex];
    const anchor = anchors.find(item => item.pairId === risk.pairId);
    const nextMatches = !risk.nextQuestionNumber
      || String(anchor?.nextQuestionNumber || '') === risk.nextQuestionNumber;
    const anchorSafe = anchor?.visible === true
      && nextMatches
      && Number(anchor.confidence || 0) >= 0.72
      && Number(anchor.anchorY) >= risk.rawBoundary - 8
      && Number(anchor.anchorY) <= risk.rawBoundary + 70
      && Number(anchor.anchorY) >= risk.projectedBoundary + 6;
    let boundaryY = risk.rawBoundary;
    let detail;
    if (anchorSafe) {
      const nextRawHeight = Math.max(
        40,
        Number(next.refinement?.rawBounds?.ymax ?? next.ymax) - Number(next.refinement?.rawBounds?.ymin ?? next.ymin)
      );
      // Vision anchor coordinates have several pixels of spatial uncertainty.
      // Keep a proportional margin above the detected printed line so the next
      // question number and its first row are never touched.
      const safetyMargin = clamp(Math.round(nextRawHeight * 0.025), 8, 14);
      boundaryY = clamp(Math.round(Number(anchor.anchorY) - safetyMargin), risk.rawBoundary - 8, risk.rawBoundary + 68);
      const maxDownwardShiftFromRawTop = clamp(Math.round(Number(risk.nextRawHeight || nextRawHeight) * 0.2), 12, 24);
      const cappedBoundaryY = Math.min(boundaryY, Number(risk.nextRawTop || boundaryY) + maxDownwardShiftFromRawTop);
      const boundaryWasCapped = cappedBoundaryY !== boundaryY;
      boundaryY = cappedBoundaryY;
      detail = {
        source: 'gemini_printed_question_anchor_v1',
        y: boundaryY,
        rawY: risk.rawBoundary,
        projectedY: risk.projectedBoundary,
        anchorY: Number(anchor.anchorY),
        safetyMargin,
        maxDownwardShiftFromRawTop,
        boundaryWasCapped,
        confidence: Number(Number(anchor.confidence).toFixed(4)),
        applied: true
      };
    } else {
      detail = {
        source: LAYOUT_REFINEMENT_ENGINE,
        y: boundaryY,
        rawY: risk.rawBoundary,
        projectedY: risk.projectedBoundary,
        confidence: Number(Number(anchor?.confidence || 0).toFixed(4)),
        applied: false,
        rejectedReason: 'upward_projection_requires_printed_question_anchor'
      };
    }
    if (boundaryY <= previous.ymin + 20 || boundaryY >= next.ymax - 20) continue;
    previous.ymax = boundaryY;
    next.ymin = boundaryY;
    previous.refinement = { ...previous.refinement, bottomBoundary: detail };
    next.refinement = { ...next.refinement, topBoundary: detail };
  }
  return finalizeRegionRefinement(regions);
}

function cleanPaperKey(value) {
  return String(value || '')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 80);
}

function imageBufferFromDataUrl(dataUrl) {
  const match = String(dataUrl || '').match(/^data:([^;]+);base64,(.+)$/s);
  if (!match) throw new Error('图片数据格式无效');
  return Buffer.from(match[2], 'base64');
}

async function rotateDataUrl(dataUrl, rotation) {
  if (!rotation) return dataUrl;
  const buffer = await sharp(imageBufferFromDataUrl(dataUrl))
    .rotate(rotation)
    .jpeg({ quality: 92 })
    .toBuffer();
  return `data:image/jpeg;base64,${buffer.toString('base64')}`;
}

function scoreDeskewProjection(data, width, height) {
  const marginX = Math.round(width * 0.08);
  const marginY = Math.round(height * 0.06);
  const bounds = {
    left: marginX,
    right: Math.max(marginX + 1, width - marginX),
    top: marginY,
    bottom: Math.max(marginY + 1, height - marginY)
  };
  const threshold = otsuThreshold(data, width, bounds);
  const projection = new Float64Array(bounds.bottom - bounds.top);
  const span = Math.max(1, bounds.right - bounds.left);
  for (let y = bounds.top; y < bounds.bottom; y += 1) {
    const rowOffset = y * width;
    let ink = 0;
    for (let x = bounds.left; x < bounds.right; x += 2) {
      if (data[rowOffset + x] <= threshold) ink += 2;
    }
    projection[y - bounds.top] = ink / span;
  }
  const mean = projection.reduce((sum, value) => sum + value, 0) / Math.max(1, projection.length);
  let variance = 0;
  for (const value of projection) variance += (value - mean) ** 2;
  return variance / Math.max(1, projection.length);
}

async function deskewScoreForAngle(buffer, angle) {
  const pipeline = sharp(buffer);
  if (angle) pipeline.rotate(angle, { background: '#ffffff' });
  const { data, info } = await pipeline
    .resize({ width: 900, height: 900, fit: 'inside', withoutEnlargement: true })
    .greyscale()
    .raw()
    .toBuffer({ resolveWithObject: true });
  return scoreDeskewProjection(data, info.width || 1, info.height || 1);
}

function deskewCandidateAngles() {
  const angles = [];
  const steps = Math.round(DOCUMENT_DESKEW_MAX_DEGREES / DOCUMENT_DESKEW_STEP_DEGREES);
  for (let index = -steps; index <= steps; index += 1) {
    const angle = Number((index * DOCUMENT_DESKEW_STEP_DEGREES).toFixed(3));
    if (Math.abs(angle) <= DOCUMENT_DESKEW_MAX_DEGREES + 1e-6) angles.push(angle);
  }
  return [...new Set(angles)];
}

async function estimateDeskewAngle(buffer) {
  const angles = deskewCandidateAngles();
  const scored = [];
  for (const angle of angles) scored.push({ angle, score: await deskewScoreForAngle(buffer, angle) });
  scored.sort((left, right) => right.score - left.score);
  const best = scored[0] || { angle: 0, score: 0 };
  const zero = scored.find(item => item.angle === 0) || { angle: 0, score: best.score };
  const scoreGain = zero.score > 0 ? (best.score - zero.score) / zero.score : 0;
  const applied = Math.abs(best.angle) >= DOCUMENT_DESKEW_MIN_ABS_DEGREES
    && scoreGain >= DOCUMENT_DESKEW_MIN_SCORE_GAIN;
  return {
    angle: applied ? best.angle : 0,
    detectedAngle: best.angle,
    applied,
    scoreGain: Number(scoreGain.toFixed(4)),
    score: Number(best.score.toFixed(8)),
    zeroScore: Number(zero.score.toFixed(8)),
    candidates: scored.slice(0, 5).map(item => ({ angle: item.angle, score: Number(item.score.toFixed(8)) }))
  };
}

async function normalizeDocumentImage(dataUrl) {
  const started = performance.now();
  if (!DOCUMENT_AFFINE_NORMALIZATION_ENABLED) {
    return {
      image: dataUrl,
      elapsedMs: 0,
      metadata: { enabled: false, applied: false, angle: 0, reason: 'disabled' }
    };
  }
  const source = imageBufferFromDataUrl(dataUrl);
  const deskew = await estimateDeskewAngle(source);
  if (!deskew.applied) {
    return {
      image: dataUrl,
      elapsedMs: Math.round(performance.now() - started),
      metadata: { enabled: true, applied: false, ...deskew }
    };
  }
  const buffer = await sharp(source)
    .rotate(deskew.angle, { background: '#ffffff' })
    .jpeg({ quality: 92 })
    .toBuffer();
  return {
    image: `data:image/jpeg;base64,${buffer.toString('base64')}`,
    elapsedMs: Math.round(performance.now() - started),
    metadata: { enabled: true, ...deskew, transform: 'affine_rotate_deskew' }
  };
}

async function detectRotation(page) {
  const source = imageBufferFromDataUrl(page.image);
  const requestIsolationId = `${String(page.id || 'page')}:${createHash('sha256').update(source).digest('hex').slice(0, 16)}`;
  const rotations = [0, 90, 180, 270];
  const candidates = await Promise.all(rotations.map(async rotation => {
    const buffer = await sharp(source)
      .rotate(rotation)
      .resize({ width: ORIENTATION_MODEL_MAX_SIDE, height: ORIENTATION_MODEL_MAX_SIDE, fit: 'inside', withoutEnlargement: true })
      .jpeg({ quality: 82 })
      .toBuffer();
    return { rotation, image: `data:image/jpeg;base64,${buffer.toString('base64')}` };
  }));
  const content = [{ type: 'text', text: `请求隔离标识：${requestIsolationId}\n下面依次给出同一张中文试卷实际旋转后的四个候选图。请选择文字可以正常从左到右、从上到下阅读且不倒置的候选图。标签就是程序实际采用的顺时针旋转角度，不需要换算。只返回 JSON：{"rotation":0|90|180|270}` }];
  candidates.forEach(candidate => content.push({ type: 'text', text: `候选 ${candidate.rotation}°` }, { type: 'image_url', image_url: { url: candidate.image } }));
  const result = await callModel({ model: LAYOUT_MODEL, messages: [{ role: 'user', content }] });
  const parsed = parseJson(result.data.choices?.[0]?.message?.content || '');
  const rotation = [0, 90, 180, 270].includes(Number(parsed.rotation)) ? Number(parsed.rotation) : 0;
  return { rotation, elapsedMs: result.elapsedMs, usage: result.usage, usageAvailable: result.usageAvailable };
}

function inferMissingPaperKeys(layouts) {
  const explicitKeys = [...new Set(layouts.map(layout => cleanPaperKey(layout.studentKey || layout.studentLabel)).filter(Boolean))];
  if (explicitKeys.length < 2) return layouts;
  const firstMissing = layouts.findIndex(layout => !cleanPaperKey(layout.studentKey || layout.studentLabel));
  if (firstMissing < explicitKeys.length || firstMissing < 0) return layouts;
  if (!layouts.slice(firstMissing).every(layout => !cleanPaperKey(layout.studentKey || layout.studentLabel))) return layouts;
  return layouts.map((layout, index) => {
    if (cleanPaperKey(layout.studentKey || layout.studentLabel)) return layout;
    const key = explicitKeys[index % explicitKeys.length];
    return { ...layout, studentKey: key, studentLabel: `${key}（自动配对）`, paperKeySource: 'inferred-order' };
  });
}

// 版面分割模型输入压缩：只压缩发给模型的那份，uprightImage 保持全分辨率
// 供 refineLayoutRegions 投影分析、锚点确认与后续 OCR 裁切使用。
async function layoutModelImage(uprightImage) {
  const source = imageBufferFromDataUrl(uprightImage);
  const metadata = await sharp(source).metadata();
  const longestSide = Math.max(metadata.width || 0, metadata.height || 0);
  if (longestSide <= LAYOUT_MODEL_MAX_SIDE && source.length <= LAYOUT_MODEL_SKIP_BYTES) {
    return uprightImage;
  }
  let pipeline = sharp(source);
  if (longestSide > LAYOUT_MODEL_MAX_SIDE) {
    pipeline = pipeline.resize({ width: LAYOUT_MODEL_MAX_SIDE, height: LAYOUT_MODEL_MAX_SIDE, fit: 'inside', withoutEnlargement: true });
  }
  const buffer = await pipeline.jpeg({ quality: LAYOUT_MODEL_JPEG_QUALITY }).toBuffer();
  return `data:image/jpeg;base64,${buffer.toString('base64')}`;
}

async function analyzeLayout(page) {
  // 调用方声明图片已转正（assumeUpright）时跳过方向判断模型调用，
  // 直接按 rotation=0 继续。后端只在预处理管线确认转正后才传该标记。
  // 严格 === true：防止字符串 "false" 等非布尔值误触发跳过。
  const orientation = page.assumeUpright === true
    ? { rotation: 0, elapsedMs: 0, usage: normalizeUsage(), usageAvailable: false, skipped: 'assumeUpright' }
    : await detectRotation(page);
  const rotatedImage = await rotateDataUrl(page.image, orientation.rotation);
  const affineNormalization = await normalizeDocumentImage(rotatedImage);
  const uprightImage = affineNormalization.image;
  const requestIsolationId = `${String(page.id || 'page')}:${createHash('sha256').update(imageBufferFromDataUrl(page.image)).digest('hex').slice(0, 16)}`;
  const prompt = `请求隔离标识：${requestIsolationId}
你是考试试卷版面分析器。输入图片已经转正，可能同时拍到左右两页或一张跨页展开的中文试卷。请只返回 JSON，不要 Markdown。
任务：按印刷题号找出每一个需要 OCR 的完整题目块。一个块必须从题号和题干开始，包含该题全部选项、插图、填空及考生手写答案，结束于下一道印刷题号之前。严禁把同一道题的题干、选项或作答拆成多个块，也不要把试卷标题、姓名栏、密封线单独当题目块。大题说明行（如“一、单项选择题：本题共8小题，每小题3分，共24分”及多选题计分规则）必须并入其后第一题的块内，不得丢弃、不得切掉。questionNumber 必须读取图片中真实印刷题号，不能根据块次序猜测。
若照片边界确实截断一道题，保留可见部分并在 kind 使用 continuation、continuationOf 写同一真实题号。左右两页分别按从上到下阅读，整张图按正常页序排列。每个矩形左右应覆盖所在纸页的完整文字列，并在不包含相邻题目的前提下保留约 2% 边缘。
同时读取姓名、座号、班级，用 studentLabel 返回可读标识，用 studentKey 返回稳定短键（优先“姓名+座号”，看不清或不存在时为空）。不要把不同考生页面配在一起。
坐标基于当前已转正图片，归一化到 0-1000，字段顺序为 ymin,xmin,ymax,xmax。
JSON格式：{"pageLabel":"...","studentLabel":"姓名/座号/班级的可读组合","studentKey":"跨页配对键或空字符串","paperPart":"前半/后半/第几页等","pageNumber":null,"regions":[{"id":"p1_q1","questionNumber":"1","label":"第1题","kind":"question_answer|continuation","readingOrder":1,"continuationOf":null,"ymin":0,"xmin":0,"ymax":1000,"xmax":500}]}。最多返回40个块，按阅读顺序排列。`;
  const modelImage = await layoutModelImage(uprightImage);
  const result = await callModel({ model: LAYOUT_MODEL, messages: [{ role: 'user', content: [{ type: 'text', text: prompt }, { type: 'image_url', image_url: { url: modelImage } }] }] });
  const parsed = parseJson(result.data.choices?.[0]?.message?.content || '');
  const rawRegions = Array.isArray(parsed.regions) ? parsed.regions.map(cleanRegion) : [];
  if (!rawRegions.length) rawRegions.push(cleanRegion({ label: '整页兜底', kind: 'question_answer', ymin: 0, xmin: 0, ymax: 1000, xmax: 1000 }, 0));
  const refinementStarted = performance.now();
  let regions = rawRegions;
  let refinementError = null;
  let refinementAnchorElapsedMs = 0;
  let refinementUsage = normalizeUsage();
  let refinementUsageAvailable = false;
  if (LAYOUT_REFINEMENT_ENABLED && rawRegions.length > 1) {
    try {
      regions = await refineLayoutRegions(uprightImage, rawRegions);
      const upwardRisks = collectUpwardBoundaryRisks(regions);
      if (upwardRisks.length) {
        try {
          const anchorResult = await requestPrintedBoundaryAnchors(uprightImage, upwardRisks);
          refinementAnchorElapsedMs = anchorResult.elapsedMs;
          refinementUsage = anchorResult.usage;
          refinementUsageAvailable = anchorResult.usageAvailable;
          regions = applyPrintedBoundaryAnchors(regions, upwardRisks, anchorResult.anchors);
        } catch (error) {
          regions = applyPrintedBoundaryAnchors(regions, upwardRisks, []);
          refinementError = `印刷题号锚点确认失败，已恢复 Gemini 粗边界：${String(error?.message || error)}`;
        }
      }
    } catch (error) { refinementError = String(error?.message || error); }
  }
  const refinementElapsedMs = Math.round(performance.now() - refinementStarted);
  return {
    pageId: page.id,
    fileName: page.fileName,
    rotation: orientation.rotation,
    orientationSkipped: Boolean(orientation.skipped),
    coordinateSpace: 'upright',
    uprightImage,
    pageLabel: parsed.pageLabel || page.fileName,
    studentLabel: cleanPaperKey(parsed.studentLabel),
    studentKey: cleanPaperKey(parsed.studentKey),
    paperPart: cleanPaperKey(parsed.paperPart),
    pageNumber: Number.isFinite(Number(parsed.pageNumber)) ? Number(parsed.pageNumber) : null,
    regions,
    refinementEngine: LAYOUT_REFINEMENT_ENABLED ? LAYOUT_REFINEMENT_ENGINE : null,
    affineNormalization: affineNormalization.metadata,
    affineNormalizationElapsedMs: affineNormalization.elapsedMs,
    refinementElapsedMs,
    refinementAnchorElapsedMs,
    refinementError,
    elapsedMs: orientation.elapsedMs + affineNormalization.elapsedMs + result.elapsedMs + refinementElapsedMs,
    orientationElapsedMs: orientation.elapsedMs,
    preprocessingElapsedMs: affineNormalization.elapsedMs,
    regionModelElapsedMs: result.elapsedMs,
    regionElapsedMs: result.elapsedMs + refinementElapsedMs,
    usage: addUsage(orientation.usage, result.usage, refinementUsage),
    usageAvailable: Boolean(orientation.usageAvailable || result.usageAvailable || refinementUsageAvailable)
  };
}

function normalizePrintedMaxScore(value) {
  if (value === null || value === undefined || value === '') return null;
  const score = Number(value);
  return Number.isFinite(score) && score > 0 ? score : null;
}

function makeOcrResult(block, parsed, elapsedMs, requestMeta = {}) {
  return normalizeOcrResultForGrading({
    blockId: block.id,
    pageId: block.pageId,
    sourceLabel: block.label,
    questionNumber: String(parsed.questionNumber || block.questionNumber || '').trim(),
    question: String(parsed.question || '').trim(),
    printedMaxScore: normalizePrintedMaxScore(parsed.printedMaxScore),
    sectionScoreRule: String(parsed.sectionScoreRule || '').trim(),
    studentAnswer: String(parsed.studentAnswer || '').trim(),
    printedQuestionMarks: Array.isArray(parsed.printedQuestionMarks)
      ? parsed.printedQuestionMarks.map(mark => ({
          text: String(mark?.text || '').trim(),
          type: String(mark?.type || mark?.markType || 'printed_text_mark').trim()
        })).filter(mark => mark.text)
      : [],
    answerType: String(parsed.answerType || '未知'),
    confidence: Math.max(0, Math.min(1, Number(parsed.confidence ?? 0))),
    notes: String(parsed.notes || '').trim(),
    continuationOf: block.continuationOf || null,
    mergeWithBlockId: requestMeta.mergeWithBlockId || null,
    paperKey: cleanPaperKey(block.paperKey || block.studentKey || block.studentLabel),
    elapsedMs,
    ocrBatchSize: requestMeta.batchSize || 1,
    ocrAttempts: requestMeta.attempts || 1
  });
}

function stripLeadingSectionHeader(question) {
  const source = String(question || '').trim();
  const questionStart = source.search(/\n\s*\d+\s*[.．、]/);
  if (
    questionStart > 0 &&
    /^[一二三四五六七八九十]+[、.．]/.test(source.slice(0, questionStart).trim())
  ) {
    return source.slice(questionStart).trim();
  }
  return source;
}

function isChoiceAnswerType(answerType, question) {
  return /选择/.test(String(answerType || '')) || /A[.．、].*B[.．、].*C[.．、].*D[.．、]/s.test(String(question || ''));
}

function extractFinalChoiceAnswer(answer) {
  const source = String(answer || '').normalize('NFKC').trim();
  const direct = source.match(/^(?:答案|选|选择|作答|答)?\s*[:：]?\s*([A-D])(?:\b|[，,；;\s。.)）]|$)/i);
  if (direct) return direct[1].toUpperCase();
  const standalone = [...source.matchAll(/(?:^|[^A-Za-z])([A-D])(?:[^A-Za-z]|$)/gi)]
    .map(match => match[1].toUpperCase());
  return standalone.length === 1 ? standalone[0] : '';
}

function isLikelyScratchLine(line) {
  const source = String(line || '').trim();
  if (!source) return false;
  if (/[=]/.test(source) && source.length >= 6) return true;
  if (/(?:W有|W总|Gh|Fs|P=|Fv|m=|ρ|kg\/m|N×|m\/s)/i.test(source)) return true;
  const numericCount = (source.match(/\d/g) || []).length;
  return numericCount >= 5 && /[×*/+=]/.test(source);
}

function removeTrailingFillBlankScratch(answer) {
  const lines = String(answer || '').split(/\r?\n/).map(line => line.trim()).filter(Boolean);
  if (lines.length <= 1) return { answer: String(answer || '').trim(), scratch: [] };
  const kept = [];
  const scratch = [];
  for (const line of lines) {
    if (kept.length > 0 && isLikelyScratchLine(line)) scratch.push(line);
    else kept.push(line);
  }
  return {
    answer: kept.join('\n').trim(),
    scratch
  };
}

function normalizeOcrResultForGrading(result) {
  let question = stripLeadingSectionHeader(result.question);
  let studentAnswer = String(result.studentAnswer || '').trim();
  const notes = [String(result.notes || '').trim()].filter(Boolean);

  if (question !== String(result.question || '').trim()) {
    notes.push('已从题干中移除章节标题，避免把“二、填空题”等栏目说明计入本题题干');
  }

  if (isChoiceAnswerType(result.answerType, question)) {
    const choice = extractFinalChoiceAnswer(studentAnswer);
    if (choice && choice !== studentAnswer.trim()) {
      notes.push(`已将选择题草稿/公式从 studentAnswer 分离，保留最终选项 ${choice}`);
      studentAnswer = choice;
    }
  } else if (/填空/.test(String(result.answerType || ''))) {
    const cleaned = removeTrailingFillBlankScratch(studentAnswer);
    if (cleaned.scratch.length) {
      notes.push(`已将填空题旁侧计算草稿移入 notes：${cleaned.scratch.join('；')}`);
      studentAnswer = cleaned.answer;
    }
  }

  return {
    ...result,
    question,
    studentAnswer,
    notes: notes.join('；')
  };
}

function normalizedTranscription(value) {
  return String(value || '')
    .normalize('NFKC')
    .replace(/[×＊*]/g, 'x')
    .replace(/\^([+-]?\d+)/g, '$1')
    .replace(/[\s，。；：、,.]/g, '')
    .toLowerCase();
}

function numericTokens(value) {
  return String(value || '')
    .normalize('NFKC')
    .match(/[+-]?\d+(?:\.\d+)?(?:×10\^?[+-]?\d+)?/g) || [];
}

function stripAnswerLineLabel(value) {
  return String(value || '')
    .trim()
    .replace(/^[（(]?\d+[）).、:：]?\s*/, '')
    .replace(/^(?:答案|作答|答)\s*[:：]\s*/, '')
    .trim();
}

function isExplicitQuestionChoice(candidate, question) {
  if (/^[a-d]$/i.test(candidate)) return true;
  const source = String(question || '').normalize('NFKC');
  const choiceSegments = source.match(/(?:选填|选择|填写|填入|选|填)[^；。\n]{0,64}/g) || [];
  for (const segment of choiceSegments) {
    const quotedCandidates = [...segment.matchAll(/[“"'‘]([^”"'’]{1,24})[”"'’]/g)]
      .map(match => normalizedTranscription(match[1]));
    if (quotedCandidates.includes(normalizedTranscription(candidate))) return true;
  }
  return false;
}

function isLikelyPrintedQuestionMark(line, question) {
  const candidate = stripAnswerLineLabel(line);
  if (!candidate || /[［\[]划去[:：]/.test(candidate)) return false;
  if (/[=+-×÷/\d]/.test(candidate)) return false;
  const hanCount = (candidate.match(/[\p{Script=Han}]/gu) || []).length;
  if (hanCount < 2 || candidate.length > 24) return false;
  if (isExplicitQuestionChoice(candidate, question)) return false;
  const normalizedCandidate = normalizedTranscription(candidate);
  const normalizedQuestion = normalizedTranscription(question);
  return normalizedCandidate.length >= 2 && normalizedQuestion.includes(normalizedCandidate);
}

export function separatePrintedQuestionMarks(result) {
  const question = String(result.question || '').trim();
  const answer = String(result.studentAnswer || '').trim();
  if (!question || !answer) return result;
  const keptLines = [];
  const printedQuestionMarks = [];
  for (const rawLine of answer.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line) continue;
    if (isLikelyPrintedQuestionMark(line, question)) {
      printedQuestionMarks.push({
        text: line,
        type: 'printed_text_mark',
        reason: 'matches_printed_question_without_answer_slot'
      });
    } else {
      keptLines.push(line);
    }
  }
  if (!printedQuestionMarks.length) return result;
  const combinedMarks = [...(Array.isArray(result.printedQuestionMarks) ? result.printedQuestionMarks : []), ...printedQuestionMarks]
    .filter((item, index, values) => item?.text && values.findIndex(other => other.text === item.text && other.type === item.type) === index);
  const separated = printedQuestionMarks.map(item => item.text).join('、');
  return {
    ...result,
    studentAnswer: keptLines.join('\n'),
    printedQuestionMarks: combinedMarks,
    notes: [String(result.notes || '').trim(), `已从考生答案中分离印刷题干圈画/划线：${separated}`]
      .filter(Boolean)
      .join('；'),
    answerVerification: {
      ...(result.answerVerification || {}),
      printedQuestionMarks: combinedMarks
    }
  };
}

function questionSubsections(question) {
  const source = String(question || '').trim();
  const matches = [...source.matchAll(/[（(](\d+)[）)]/g)];
  if (!matches.length) return [{ subquestion: null, text: source }];
  return matches.map((match, index) => ({
    subquestion: match[1],
    text: source.slice(match.index, matches[index + 1]?.index ?? source.length).trim()
  }));
}

function blankCount(value) {
  return (String(value || '').match(/_{2,}|＿{2,}|\.{4,}|…{2,}/g) || []).length;
}

export function deriveQuestionAnswerSlots(question) {
  return questionSubsections(question).flatMap(section => {
    const count = Math.max(1, blankCount(section.text));
    return Array.from({ length: count }, (_, index) => ({
      slotId: `${section.subquestion ? `q${section.subquestion}` : 'main'}_s${index + 1}`,
      subquestion: section.subquestion,
      slotIndex: index + 1,
      expectedKind: count > 1 || blankCount(section.text) ? 'blank' : 'response',
      questionExcerpt: section.text.slice(0, 320)
    }));
  });
}

function answerGroupsBySubquestion(answer) {
  const groups = new Map();
  const unassigned = [];
  let current = null;
  const splitDraftEvidence = value => {
    const text = String(value || '').trim();
    const marker = text.match(/(?:手写)?(?:草稿|计算过程|计算草稿|过程)|右侧(?:及下方)?有|下方有|右上角|右侧及下方/i);
    if (!marker || marker.index == null) return { answerPart: text, draftPart: '' };
    const answerPart = text.slice(0, marker.index).trim();
    const draftPart = text.slice(marker.index).trim();
    return { answerPart, draftPart };
  };
  for (const rawLine of String(answer || '').split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line) continue;
    const marker = line.match(/^(?:(?:解|答)\s*[:：]\s*)?[（(](\d+)[）)]\s*(.*)$/);
    if (marker) {
      current = marker[1];
      if (!groups.has(current)) groups.set(current, []);
      if (marker[2].trim()) {
        const { answerPart, draftPart } = splitDraftEvidence(marker[2]);
        if (answerPart) groups.get(current).push(answerPart);
        if (draftPart) unassigned.push(`(${current}) ${draftPart}`);
      }
      continue;
    }
    const { answerPart, draftPart } = splitDraftEvidence(line);
    if (answerPart && current) groups.get(current).push(answerPart);
    else if (answerPart) unassigned.push(answerPart);
    if (draftPart) unassigned.push(current ? `(${current}) ${draftPart}` : draftPart);
  }
  return { groups, unassigned };
}

function splitBlankAnswers(text, expectedCount) {
  if (expectedCount <= 1) return [String(text || '').trim()];
  const parts = String(text || '')
    .split(/[;；,，、]/)
    .map(item => item.trim())
    .filter(Boolean);
  if (parts.length === expectedCount) return parts;
  const whitespaceParts = String(text || '').trim().split(/\s+/).filter(Boolean);
  return whitespaceParts.length === expectedCount
    ? whitespaceParts
    : [String(text || '').trim()];
}

export function structureStudentAnswerEvidence(result) {
  const slots = deriveQuestionAnswerSlots(result.question);
  const answer = String(result.studentAnswer || '').trim();
  const { groups, unassigned: leadingUnassigned } = answerGroupsBySubquestion(answer);
  const answerEntries = [];
  const hasExplicitGroups = groups.size > 0;
  const unassignedEvidence = hasExplicitGroups ? [...leadingUnassigned] : [];
  const evidenceBounds = Array.isArray(result.answerVerification?.regions)
    ? result.answerVerification.regions
    : [];
  if (hasExplicitGroups) {
    for (const [subquestion, sectionSlots] of Map.groupBy(slots, slot => slot.subquestion || 'main')) {
      const lines = groups.get(subquestion) || [];
      const combined = lines.join('\n').trim();
      const pieces = splitBlankAnswers(combined, sectionSlots.length);
      sectionSlots.forEach((slot, index) => {
        const text = pieces.length === sectionSlots.length ? pieces[index] : (index === 0 ? combined : '');
        answerEntries.push({
          ...slot,
          text,
          status: text ? 'assigned' : 'missing',
          confidence: Number(result.confidence || 0),
          evidenceBounds,
          coordinatePrecision: evidenceBounds.length ? 'answer_region_union' : 'none'
        });
      });
    }
    for (const [subquestion, lines] of groups) {
      if (!slots.some(slot => slot.subquestion === subquestion)) {
        unassignedEvidence.push(`(${subquestion}) ${lines.join('\n')}`.trim());
      }
    }
  } else {
    const lines = answer.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
    slots.forEach((slot, index) => {
      const text = index < slots.length ? (lines[index] || '') : '';
      answerEntries.push({
        ...slot,
        text,
        status: text ? 'assigned' : 'missing',
        confidence: Number(result.confidence || 0),
        evidenceBounds,
        coordinatePrecision: evidenceBounds.length ? 'answer_region_union' : 'none'
      });
    });
    if (lines.length > slots.length) unassignedEvidence.push(...lines.slice(slots.length));
  }

  const gradingAnswer = answerEntries
    .filter(entry => entry.status === 'assigned' && entry.text)
    .map(entry => `${entry.subquestion ? `(${entry.subquestion}) ` : ''}${entry.text}`)
    .join('\n')
    .trim();
  const verificationStatus = String(result.answerVerification?.status || 'not_available');
  const hasUnresolvedText = /\[无法辨认\]|\[看不清\]|［无法辨认］|［看不清］/.test(answer);
  const gradingEligible = Number(result.confidence || 0) >= GRADING_ELIGIBILITY_THRESHOLD &&
    !hasUnresolvedText &&
    answerEntries.every(entry => entry.status === 'assigned') &&
    !['evidence_disagreement', 'failed', 'not_run_fast_recognition'].includes(verificationStatus);
  return {
    ...result,
    answerEntries,
    unassignedEvidence,
    gradingAnswer,
    gradingEligible,
    answerStructure: {
      version: 'answer_slots_v1',
      slotCount: slots.length,
      assignedCount: answerEntries.filter(entry => entry.status === 'assigned').length,
      missingCount: answerEntries.filter(entry => entry.status === 'missing').length,
      unassignedCount: unassignedEvidence.length,
      gradingEligible,
      verificationStatus,
      coordinatePrecision: evidenceBounds.length ? 'answer_region_union' : 'none'
    }
  };
}

function finalizeStudentAnswer(result) {
  return structureStudentAnswerEvidence(separatePrintedQuestionMarks(result));
}

function combinedPrintedQuestionMarks(...values) {
  const marks = values.flatMap(value => Array.isArray(value) ? value : []);
  return marks
    .map(mark => ({
      text: String(mark?.text || '').trim(),
      type: String(mark?.type || mark?.markType || 'printed_text_mark').trim()
    }))
    .filter((mark, index, all) => mark.text && all.findIndex(other => other.text === mark.text && other.type === mark.type) === index);
}

export function reconcileStudentAnswer(result, verification = {}) {
  const initialAnswer = String(result.studentAnswer || '').trim();
  const initialConfidence = Math.max(0, Math.min(1, Number(result.confidence ?? 0)));
  const verifiedAnswer = String(verification.studentAnswer || '').trim();
  const candidateAnswer = String(verification.candidateStudentAnswer || '').trim();
  const verificationNotes = String(verification.notes || '').trim();
  const diagnosticNotes = String(result.notes || '').trim();
  const notes = [];
  if (verification.error) {
    notes.push(`考生作答独立核验失败：${verification.error}`);
    if (initialAnswer) notes.push('已保留首轮并发 OCR 原文；核验服务故障不视为内容冲突，仅轻微下调置信度');
    if (diagnosticNotes) notes.push(diagnosticNotes);
    return finalizeStudentAnswer({
      ...result,
      studentAnswer: initialAnswer,
      printedQuestionMarks: combinedPrintedQuestionMarks(result.printedQuestionMarks, verification.printedQuestionMarks),
      confidence: initialAnswer
        ? Math.min(initialConfidence || VERIFICATION_FAILURE_CONFIDENCE_CAP, VERIFICATION_FAILURE_CONFIDENCE_CAP)
        : 0,
      notes: notes.filter(Boolean).join('；'),
      answerVerification: {
        status: 'failed',
        blockedInitialTranscription: false,
        fallbackToInitialTranscription: Boolean(initialAnswer)
      }
    });
  }
  const verifierConfidence = Math.max(0, Math.min(1, Number(verification.confidence ?? 0)));
  if (verification.consensus !== true) {
    const reviewAnswer = verification.preferInitialOnDisagreement
      ? initialAnswer
      : (candidateAnswer || initialAnswer);
    notes.push(verification.strategy === 'light'
      ? '轻量答案复核与首轮 OCR 不一致，已保留首轮 OCR 原文并禁止自动批改'
      : '手写证据宽视图与聚焦视图不一致，已保留首轮并发 OCR 原文并降为低置信度候选');
    if (diagnosticNotes) notes.push(diagnosticNotes);
    if (!initialAnswer && candidateAnswer) notes.push('首轮未返回作答，暂采用扩边复核候选');
    if (verificationNotes) notes.push(verificationNotes);
    return finalizeStudentAnswer({
      ...result,
      studentAnswer: reviewAnswer,
      printedQuestionMarks: combinedPrintedQuestionMarks(result.printedQuestionMarks, verification.printedQuestionMarks),
      confidence: reviewAnswer
        ? Math.min(initialConfidence || verifierConfidence || 0.6, 0.6)
        : 0,
      notes: notes.filter(Boolean).join('；'),
      answerVerification: {
        status: 'evidence_disagreement',
        strategy: verification.strategy || 'evidence',
        confidence: verifierConfidence,
        blockedInitialTranscription: false,
        fallbackToInitialTranscription: Boolean(verification.preferInitialOnDisagreement || (!candidateAnswer && initialAnswer)),
        candidateStudentAnswer: candidateAnswer,
        regions: Array.isArray(verification.regions) ? verification.regions : [],
        cropBounds: verification.cropBounds || null
      }
    });
  }
  notes.push(verification.strategy === 'light'
    ? '考生正式答案经首轮 OCR 与轻量独立复核一致'
    : '考生作答采用手写证据宽视图与聚焦视图一致的逐字转写；完整题块转写仅用于诊断，不参与批改');
  if (verificationNotes) notes.push(verificationNotes);
  return finalizeStudentAnswer({
    ...result,
    studentAnswer: verifiedAnswer,
    printedQuestionMarks: combinedPrintedQuestionMarks(result.printedQuestionMarks, verification.printedQuestionMarks),
    confidence: Math.min(verifierConfidence || 1, 0.9),
    notes: notes.filter(Boolean).join('；'),
    answerVerification: {
      status: verification.status || (verification.strategy === 'light' ? 'light_consensus' : 'evidence_consensus'),
      strategy: verification.strategy || 'evidence',
      confidence: verifierConfidence,
      regions: Array.isArray(verification.regions) ? verification.regions : [],
      cropBounds: verification.cropBounds || null
    }
  });
}

async function locateStudentAnswerRegions(block) {
  const prompt = `你是试卷手写区域定位器，只定位考生亲笔写下、画出或填入的内容，不做文字识别，不解题。
请用 0-1000 归一化坐标返回所有考生作答区域。矩形要尽量紧贴手写笔迹，排除印刷题干、印刷公式、题号和图片；同一行连续手写内容可用一个矩形。填空处、草稿、计算过程、作图痕迹和被划掉的答案都要保留。最多 16 个区域。
只返回 JSON：{"regions":[{"ymin":0,"xmin":0,"ymax":1000,"xmax":1000}],"confidence":0到1,"notes":"定位风险"}。没有任何手写作答时 regions 返回空数组。候选题号 ${block.questionNumber || '未知'} 只用于定位。`;
  const modelResult = await callOcrModel({
    model: MODEL,
    temperature: 0,
    messages: [{ role: 'user', content: [
      { type: 'text', text: prompt },
      { type: 'image_url', image_url: { url: block.image } }
    ] }]
  });
  const raw = String(modelResult.data.choices?.[0]?.message?.content || '');
  const regionObjects = [...raw.matchAll(/\{[^{}]*?\bymin\b[^{}]*?\}/gs)]
    .map(match => match[0]);
  const readCoordinate = (object, name) => {
    const match = object.match(new RegExp(`["']?${name}["']?\\s*:\\s*(-?\\d+(?:\\.\\d+)?)`, 'i'));
    return match ? Number(match[1]) : null;
  };
  const regions = regionObjects
    .map(object => ({
      ymin: readCoordinate(object, 'ymin'),
      xmin: readCoordinate(object, 'xmin'),
      ymax: readCoordinate(object, 'ymax'),
      xmax: readCoordinate(object, 'xmax')
    }))
    .filter(region => Object.values(region).every(value => Number.isFinite(value)))
    .slice(0, 16)
    .map((region, index) => cleanRegion(region, index));
  const confidenceMatch = raw.match(/["']?confidence["']?\s*:\s*(0(?:\.\d+)?|1(?:\.0+)?)/i);
  const notesMatch = raw.match(/["']?notes["']?\s*:\s*["']([^"'\r\n]*)/i);
  return {
    regions,
    confidence: Math.max(0, Math.min(1, Number(confidenceMatch?.[1] ?? 0))),
    notes: String(notesMatch?.[1] || '').trim(),
    elapsedMs: modelResult.elapsedMs,
    attempts: modelResult.attempts,
    usage: modelResult.usage,
    usageAvailable: modelResult.usageAvailable
  };
}

function horizontalOverlapRatio(left, right) {
  const overlap = Math.max(0, Math.min(left.xmax, right.xmax) - Math.max(left.xmin, right.xmin));
  return overlap / Math.max(1, Math.min(left.xmax - left.xmin, right.xmax - right.xmin));
}

export function buildExpandedHandwritingClusters(regions, profile = 'wide') {
  const profileConfig = profile === 'focused'
    ? { horizontalRatio: 0.08, minHorizontal: 42, verticalRatio: 0.06, minVertical: 20, maxVertical: 30, edgeContext: 340 }
    : { horizontalRatio: 0.12, minHorizontal: 55, verticalRatio: 0.08, minVertical: 24, maxVertical: 40, edgeContext: 380 };
  const remaining = regions
    .map(region => ({ ...region }))
    .sort((left, right) => left.ymin - right.ymin);
  const clusters = [];
  while (remaining.length) {
    const members = [remaining.shift()];
    let changed = true;
    while (changed) {
      changed = false;
      for (let index = remaining.length - 1; index >= 0; index -= 1) {
        const candidate = remaining[index];
        const connected = members.some(member => {
          const verticalGap = Math.max(0, Math.max(member.ymin, candidate.ymin) - Math.min(member.ymax, candidate.ymax));
          return verticalGap <= 70 && horizontalOverlapRatio(member, candidate) >= 0.16;
        });
        if (connected) {
          members.push(candidate);
          remaining.splice(index, 1);
          changed = true;
        }
      }
    }
    const bounds = members.reduce((total, region) => ({
      xmin: Math.min(total.xmin, region.xmin),
      ymin: Math.min(total.ymin, region.ymin),
      xmax: Math.max(total.xmax, region.xmax),
      ymax: Math.max(total.ymax, region.ymax)
    }), { xmin: 1000, ymin: 1000, xmax: 0, ymax: 0 });
    const width = bounds.xmax - bounds.xmin;
    const height = bounds.ymax - bounds.ymin;
    // The locator returns tight handwriting boxes. Add context around the box,
    // and, near an image edge, grow inward so the last formula is not cut off.
    const horizontalPadding = Math.max(
      profileConfig.minHorizontal,
      Math.min(150, Math.round(width * profileConfig.horizontalRatio))
    );
    const verticalPadding = Math.max(
      profileConfig.minVertical,
      Math.min(profileConfig.maxVertical, Math.round(height * profileConfig.verticalRatio))
    );
    const expanded = {
      xmin: Math.max(0, bounds.xmin - horizontalPadding),
      xmax: Math.min(1000, bounds.xmax + horizontalPadding),
      ymin: Math.max(0, bounds.ymin - verticalPadding),
      ymax: Math.min(1000, bounds.ymax + verticalPadding)
    };
    if (bounds.ymax >= 930 && height < profileConfig.edgeContext) {
      expanded.ymin = Math.min(
        expanded.ymin,
        Math.max(0, bounds.ymax - Math.max(profileConfig.edgeContext, height + verticalPadding * 2))
      );
      expanded.ymax = 1000;
    }
    clusters.push({ members, bounds, expanded, area: width * height });
  }
  const largestArea = Math.max(...clusters.map(cluster => cluster.area), 1);
  return clusters
    .filter(cluster => cluster.area >= Math.max(1200, largestArea * 0.12))
    .sort((left, right) => left.expanded.ymin - right.expanded.ymin)
    .slice(0, 4);
}

function pageEvidenceBounds(block, localBounds) {
  if (!block._pageImage) return localBounds;
  const blockXmin = Number(block.xmin || 0);
  const blockYmin = Number(block.ymin || 0);
  const blockWidth = Math.max(1, Number(block.xmax || 1000) - blockXmin);
  const blockHeight = Math.max(1, Number(block.ymax || 1000) - blockYmin);
  const touchesBottom = localBounds.ymax >= 930;
  const nextRegionYmin = Number(block._nextRegionYmin);
  const downwardContext = touchesBottom ? 24 : 12;
  const rawYmax = blockYmin + localBounds.ymax / 1000 * blockHeight + downwardContext;
  const cappedYmax = Number.isFinite(nextRegionYmin)
    ? Math.min(rawYmax, nextRegionYmin + downwardContext)
    : rawYmax;
  return {
    xmin: Math.max(0, blockXmin + localBounds.xmin / 1000 * blockWidth),
    ymin: Math.max(0, blockYmin + localBounds.ymin / 1000 * blockHeight),
    xmax: Math.min(1000, blockXmin + localBounds.xmax / 1000 * blockWidth),
    // The original upright page is intentionally used here. A question crop may
    // end exactly on the final handwritten baseline, so small downward context
    // is needed to retain descenders and the final number.
    ymax: Math.min(1000, cappedYmax)
  };
}

async function cropStudentAnswerRegions(block, regions, profile = 'wide', answerType = '') {
  const usePageEvidence = Boolean(block._pageImage);
  const source = imageBufferFromDataUrl(usePageEvidence ? block._pageImage : block.image);
  const metadata = await sharp(source).metadata();
  const width = metadata.width || 1;
  const height = metadata.height || 1;
  const clusters = buildExpandedHandwritingClusters(regions, profile);
  const calculationAnswer = /计算|calculation/i.test(String(answerType || ''));
  const selectedClusters = calculationAnswer && clusters.length > 1
    ? [clusters.reduce((bottommost, cluster) => (
      cluster.bounds.ymax > bottommost.bounds.ymax ? cluster : bottommost
    ))]
    : clusters;
  return Promise.all(selectedClusters.map(async (cluster, index) => {
    const band = pageEvidenceBounds(block, cluster.expanded);
    const left = Math.max(0, Math.floor(band.xmin / 1000 * width));
    const top = Math.max(0, Math.floor(band.ymin / 1000 * height));
    const right = Math.min(width, Math.ceil(band.xmax / 1000 * width));
    const bottom = Math.min(height, Math.ceil(band.ymax / 1000 * height));
    const cropWidth = Math.max(1, right - left);
    const cropHeight = Math.max(1, bottom - top);
    const buffer = await sharp(source)
      .extract({ left, top, width: cropWidth, height: cropHeight })
      .resize({ width: Math.min(1800, Math.max(900, cropWidth * 3)), withoutEnlargement: false, kernel: 'lanczos3' })
      .grayscale()
      .normalize()
      .sharpen()
      .png()
      .toBuffer();
    return {
      index,
      bounds: band,
      sourceBounds: cluster.bounds,
      image: `data:image/png;base64,${buffer.toString('base64')}`
    };
  }));
}

function evidenceSignature(value) {
  const text = String(value || '').trim();
  return {
    text,
    normalized: normalizedTranscription(text),
    numbers: numericTokens(text).map(token => token.toLowerCase().replace(/^\+/, ''))
  };
}

function isTokenMultisetSubset(subset, superset) {
  const remaining = new Map();
  for (const token of superset) remaining.set(token, (remaining.get(token) || 0) + 1);
  for (const token of subset) {
    const count = remaining.get(token) || 0;
    if (!count) return false;
    remaining.set(token, count - 1);
  }
  return true;
}

function bigramDiceSimilarity(left, right) {
  if (left === right) return 1;
  if (!left || !right) return 0;
  if (left.length === 1 || right.length === 1) return left === right ? 1 : 0;
  const counts = new Map();
  for (let index = 0; index < left.length - 1; index += 1) {
    const gram = left.slice(index, index + 2);
    counts.set(gram, (counts.get(gram) || 0) + 1);
  }
  let overlap = 0;
  for (let index = 0; index < right.length - 1; index += 1) {
    const gram = right.slice(index, index + 2);
    const count = counts.get(gram) || 0;
    if (!count) continue;
    overlap += 1;
    counts.set(gram, count - 1);
  }
  return (2 * overlap) / ((left.length - 1) + (right.length - 1));
}

export function evidenceViewsAgree(wideText, focusedText) {
  const wide = evidenceSignature(wideText);
  const focused = evidenceSignature(focusedText);
  if (!wide.text && !focused.text) return true;
  if (!wide.text || !focused.text) return false;

  // 宽视图常会比聚焦视图多带到草稿数字或边缘文字。数字证据只要一方为另一方的多重子集即可兼容；
  // 双方都有但无法相互包含的数字证据，仍然必须判定为冲突。
  if (wide.numbers.length || focused.numbers.length) {
    if (!wide.numbers.length || !focused.numbers.length) return false;
    const numbersCompatible = isTokenMultisetSubset(wide.numbers, focused.numbers) ||
      isTokenMultisetSubset(focused.numbers, wide.numbers);
    if (!numbersCompatible) return false;
  }

  if (wide.normalized === focused.normalized) return true;
  const shortest = wide.normalized.length <= focused.normalized.length ? wide.normalized : focused.normalized;
  const longest = shortest === wide.normalized ? focused.normalized : wide.normalized;
  if (shortest.length >= 3 && longest.includes(shortest)) return true;

  // 允许换行、标点、少量单位/边缘文字差异，但不会越过上面的数字冲突门。
  return bigramDiceSimilarity(wide.normalized, focused.normalized) >= EVIDENCE_TEXT_SIMILARITY_MIN;
}

function conciseEvidenceRiskNotes(...values) {
  const riskPattern = /无法辨认|看不清|不清|裁切|截断|切边|划去|涂改|模糊|边缘/i;
  const notes = [];
  for (const value of values) {
    const fragments = String(value || '')
      .split(/[；。\n]/)
      .map(fragment => fragment.trim())
      .filter(fragment => fragment && riskPattern.test(fragment));
    notes.push(...fragments);
  }
  return [...new Set(notes)].join('；').slice(0, 600);
}

function isDiagramAnswerQuestion(question, answerType = '') {
  const source = `${question || ''}\n${answerType || ''}`;
  return /作图|画出|画在|连线|示意图|受力图|滑轮组|组装|绕线|图甲|图乙/.test(source);
}

function isHeavyEvidenceQuestion(question, answerType = '') {
  const type = String(answerType || '');
  return /计算题|实验题|作图题|解答题/.test(type) || isDiagramAnswerQuestion(question, type);
}

function extractChoiceAnswer(value) {
  const source = String(value || '').trim();
  const standalone = source.match(/(?:^|[\s（(：:])([A-D])(?:$|[\s）).,，。；;])/i);
  if (standalone) return standalone[1].toUpperCase();
  return /^[A-D]$/i.test(source) ? source.toUpperCase() : '';
}

function normalizedSimpleFillPart(value) {
  return normalizedTranscription(value)
    .replace(/(?:pa|kg|km|cm|mm|m|n|j|w|s)$/i, '');
}

function simpleFillParts(value, expectedCount) {
  let parts = String(value || '')
    .split(/[\r\n;；,，、]+/)
    .map(item => item.trim())
    .filter(Boolean);
  if (parts.length === 1 && expectedCount > 1) {
    const whitespaceParts = parts[0].split(/\s+/).map(item => item.trim()).filter(Boolean);
    if (whitespaceParts.length >= expectedCount) parts = whitespaceParts.slice(0, expectedCount);
  }
  return parts.map(normalizedSimpleFillPart).filter(Boolean);
}

function simpleAnswersAgree(initialAnswer, verifiedAnswer, answerType = '', question = '') {
  if (/选择题/.test(String(answerType || ''))) {
    const initialChoice = extractChoiceAnswer(initialAnswer);
    const verifiedChoice = extractChoiceAnswer(verifiedAnswer);
    return Boolean(initialChoice && verifiedChoice && initialChoice === verifiedChoice);
  }
  const expectedCount = deriveQuestionAnswerSlots(question).length;
  const verifiedParts = simpleFillParts(verifiedAnswer, expectedCount);
  if (verifiedParts.length < expectedCount) return false;
  const normalizedInitial = normalizedTranscription(initialAnswer);
  return verifiedParts.every(part => normalizedInitial.includes(part));
}

async function verifySimpleStudentAnswer(block, initialResult) {
  const answerType = String(initialResult.answerType || '');
  const choiceMode = /选择题/.test(answerType);
  const prompt = choiceMode
    ? `你是选择题最终答案复核员。只读取考生在题干括号、答题位置或明确最终答案位置填写的一个 A/B/C/D。
选项文字旁的对勾、叉号、圈画、排除标记和草稿计算都不是最终答案，禁止把它们当答案。
看不清时返回“[无法辨认]”。不要解题。只返回 JSON：{"studentAnswer":"A/B/C/D或[无法辨认]","confidence":0到1,"notes":"辨认风险"}。`
    : `你是填空题正式答案复核员。只按顺序转写考生填写在印刷横线、括号或明确空格中的最终答案。
忽略空格外的草稿、计算过程、圈画、下一题文字以及被明确划掉的旧答案。不要解题或纠错。
多个空用换行分隔；看不清写“[无法辨认]”。只返回 JSON：{"studentAnswer":"正式填空答案","confidence":0到1,"notes":"辨认风险"}。`;
  const modelResult = await callOcrJson({
    model: MODEL,
    temperature: 0,
    messages: [{ role: 'user', content: [
      { type: 'text', text: `${prompt}\n候选题号：${block.questionNumber || '未知'}\n题干摘要：${String(initialResult.question || '').slice(0, 600)}` },
      { type: 'image_url', image_url: { url: block.image } }
    ] }]
  }, { loose: true });
  const parsed = modelResult.parsed;
  const studentAnswer = String(parsed.studentAnswer || '').trim();
  const confidence = Math.max(0, Math.min(1, Number(parsed.confidence ?? 0)));
  const initialStructured = structureStudentAnswerEvidence(separatePrintedQuestionMarks({
    ...initialResult,
    answerVerification: { status: 'light_pending' }
  }));
  const initialAnswer = String(initialStructured.gradingAnswer || initialResult.studentAnswer || '').trim();
  const consensus = confidence >= 0.8 && simpleAnswersAgree(
    initialAnswer,
    studentAnswer,
    answerType,
    initialResult.question
  );
  return {
    studentAnswer: consensus ? studentAnswer : '',
    candidateStudentAnswer: studentAnswer,
    confidence: consensus ? confidence : 0,
    notes: String(parsed.notes || '').trim(),
    elapsedMs: modelResult.elapsedMs,
    attempts: modelResult.attempts,
    usage: modelResult.usage,
    usageAvailable: modelResult.usageAvailable,
    regions: [],
    consensus,
    strategy: 'light',
    status: consensus ? 'light_consensus' : 'light_disagreement',
    preferInitialOnDisagreement: true
  };
}

async function transcribeHandwritingEvidence({ crops, profileLabel }) {
  const prompt = `你是“考生手写原文逐字转写员”，不是解题者。输入图是从手写定位框向四周扩展的 ${profileLabel} 证据块；你不知道原题，也不能根据常识推断答案。
1. 只转写考生实际写下的内容。考生可能算错、公式错误、单位错误，必须原样保留，绝对禁止解题、验算、纠错或补全。
2. 逐字核对数字、运算符、指数、单位和最终结果。即使卷面公式或结果明显错误，也必须原样保留，不得换成你认为正确的公式或数值。
3. 数字和符号必须按笔迹转写，尤其注意 1/6/0、5/S、2/Z、p/P/D、×/+ 的混淆；如果不能确认，写［无法辨认］，不要用题目条件或物理公式反推。
4. 看不清的单个字符写［无法辨认］；不要猜测。被划掉内容用［划去：原文］表示。
5. 裁图中可能残留少量印刷文字，不能转写印刷题干。考生只是圈出、划线或涂抹印刷词句时，不得把被标记的印刷词句当成新写答案；将可辨认的被标记印刷词句放入 printedQuestionMarks。相邻证据块的重叠内容只转写一次。
只返回合法 JSON：{"studentAnswer":"逐字原文","printedQuestionMarks":[{"text":"被圈/划线的印刷词句","type":"circle|underline|crossout|other"}],"confidence":0到1,"notes":"辨认风险"}。`;
  const reports = [];
  for (const crop of crops) {
    const modelResult = await callOcrJson({
      model: MODEL,
      temperature: 0,
      messages: [{ role: 'user', content: [
        { type: 'text', text: `${prompt}\n这是唯一的手写证据块，不要参考任何其他图片。` },
        { type: 'image_url', image_url: { url: crop.image } }
      ] }]
    }, { loose: true });
    const parsed = modelResult.parsed;
    reports.push({
      crop,
      studentAnswer: String(parsed.studentAnswer || '').trim(),
      printedQuestionMarks: Array.isArray(parsed.printedQuestionMarks)
        ? parsed.printedQuestionMarks
        : [],
      confidence: Math.max(0, Math.min(1, Number(parsed.confidence ?? 0))),
      notes: String(parsed.notes || '').trim(),
      elapsedMs: modelResult.elapsedMs,
      attempts: modelResult.attempts,
      usage: modelResult.usage,
      usageAvailable: modelResult.usageAvailable
    });
  }
  return {
    studentAnswer: reports.map(report => report.studentAnswer).filter(Boolean).join('\n'),
    printedQuestionMarks: combinedPrintedQuestionMarks(...reports.map(report => report.printedQuestionMarks)),
    confidence: reports.length
      ? Math.min(...reports.map(report => report.confidence || 0))
      : 0,
    notes: reports.map(report => report.notes).filter(Boolean).join('；'),
    elapsedMs: reports.reduce((sum, report) => sum + Number(report.elapsedMs || 0), 0),
    attempts: reports.reduce((sum, report) => sum + Number(report.attempts || 0), 0),
    usage: addUsage(...reports.map(report => report.usage)),
    usageAvailable: reports.some(report => report.usageAvailable),
    cropBounds: reports.map(report => report.crop.bounds)
  };
}

async function transcribeDiagramEvidence(block, question) {
  const prompt = `你是中文物理试卷“作图题/图形作答”证据识别员。输入是一整块题目图片，里面可能有印刷图形和考生后画的线、箭头、字母、绕线。
只描述考生新增的图形作答，不要复述印刷题干，不要解题，不要按常识补画。
重点检查：
1. 力的示意图：是否有考生画出的箭头、方向、作用点、字母标注，例如 G、F。
2. 滑轮组/电路/连线/作图：是否有考生画出的连线或绕线，描述连接关系和大致方向。
3. 如果题目含（1）（2）等小问，按小问输出；看不清写“[无法辨认]”。
只返回合法 JSON：{"studentAnswer":"作图答案结构化描述","confidence":0到1,"notes":"图形作答辨认风险"}。`;
  const modelResult = await callOcrJson({
    model: MODEL,
    temperature: 0,
    messages: [{ role: 'user', content: [
      { type: 'text', text: `${prompt}\n候选题号：${block.questionNumber || '未知'}\n已识别题干摘要：${String(question || '').slice(0, 600)}` },
      { type: 'image_url', image_url: { url: block.image } }
    ] }]
  }, { loose: true });
  const parsed = modelResult.parsed;
  return {
    studentAnswer: String(parsed.studentAnswer || '').trim(),
    confidence: Math.max(0, Math.min(1, Number(parsed.confidence ?? 0))),
    notes: String(parsed.notes || '').trim(),
    elapsedMs: modelResult.elapsedMs,
    attempts: modelResult.attempts,
    usage: modelResult.usage,
    usageAvailable: modelResult.usageAvailable
  };
}

async function transcribeBottomEdgeCalculationEvidence(block, regions) {
  const calculationRegions = (regions || [])
    .filter(region => Object.values(region).every(value => Number.isFinite(Number(value))))
    .sort((left, right) => Number(left.ymin) - Number(right.ymin));
  const bottomY = Math.max(0, ...calculationRegions.map(region => Number(region.ymax || 0)));
  if (bottomY < 900) return null;
  const bottomRegions = calculationRegions.filter(region => Number(region.ymax || 0) >= bottomY - 125);
  if (!bottomRegions.length) return null;
  const bounds = bottomRegions.reduce((total, region) => ({
    xmin: Math.min(total.xmin, Number(region.xmin)),
    ymin: Math.min(total.ymin, Number(region.ymin)),
    xmax: Math.max(total.xmax, Number(region.xmax)),
    ymax: Math.max(total.ymax, Number(region.ymax))
  }), { xmin: 1000, ymin: 1000, xmax: 0, ymax: 0 });
  const bottomCrop = await cropStudentAnswerRegions(block, [{
    xmin: Math.max(0, bounds.xmin - 35),
    ymin: Math.max(0, bounds.ymin - 35),
    xmax: Math.min(1000, bounds.xmax + 80),
    ymax: Math.min(1000, bounds.ymax + 15)
  }], 'wide', '');
  if (!bottomCrop.length) return null;
  return transcribeHandwritingEvidence({
    crops: bottomCrop.slice(0, 1),
    profileLabel: '计算题底部最终行'
  });
}

async function verifyStudentAnswer(block, answerType = '', question = '') {
  const locator = await locateStudentAnswerRegions(block);
  if (!locator.regions.length) {
    return {
      studentAnswer: '',
      confidence: locator.confidence,
      notes: [locator.notes, '未定位到考生手写区域'].filter(Boolean).join('；'),
      elapsedMs: locator.elapsedMs,
      attempts: locator.attempts,
      usage: locator.usage,
      usageAvailable: locator.usageAvailable,
      regions: []
    };
  }
  const diagramQuestion = isDiagramAnswerQuestion(question, answerType);
  const [wide, focused, diagramCheck] = await Promise.all([
    transcribeHandwritingEvidence({
      crops: await cropStudentAnswerRegions(block, locator.regions, 'wide', answerType),
      profileLabel: '宽上下文'
    }),
    transcribeHandwritingEvidence({
      crops: await cropStudentAnswerRegions(block, locator.regions, 'focused', answerType),
      profileLabel: '聚焦'
    }),
    diagramQuestion ? transcribeDiagramEvidence(block, question) : null
  ]);
  const hasEvidenceText = Boolean(String(wide.studentAnswer || '').trim() || String(focused.studentAnswer || '').trim());
  const handwritingConsensus = hasEvidenceText && evidenceViewsAgree(wide.studentAnswer, focused.studentAnswer);
  const diagramConsensus = diagramQuestion && String(diagramCheck?.studentAnswer || '').trim() && Number(diagramCheck?.confidence || 0) >= 0.75;
  const consensus = diagramQuestion ? Boolean(diagramConsensus) : handwritingConsensus;
  const calculationAnswer = /计算|calculation/i.test(String(answerType || ''));
  const bottomCheck = calculationAnswer && !consensus
    ? await transcribeBottomEdgeCalculationEvidence(block, locator.regions)
    : null;
  const consensusStudentAnswer = diagramQuestion && diagramConsensus
    ? [wide.studentAnswer, diagramCheck.studentAnswer].map(value => String(value || '').trim()).filter(Boolean).join('\n')
    : wide.studentAnswer;
  const candidateStudentAnswer = [wide.studentAnswer, diagramCheck?.studentAnswer, bottomCheck?.studentAnswer]
    .map(value => String(value || '').trim())
    .filter((value, index, all) => value && all.indexOf(value) === index)
    .join('\n');
  return {
    studentAnswer: consensus ? consensusStudentAnswer : '',
    candidateStudentAnswer,
    printedQuestionMarks: combinedPrintedQuestionMarks(wide.printedQuestionMarks, focused.printedQuestionMarks),
    confidence: consensus
      ? Math.min(locator.confidence || 1, wide.confidence || 1, focused.confidence || 1, diagramCheck?.confidence || 1)
      : 0,
    notes: [
      conciseEvidenceRiskNotes(locator.notes, wide.notes, focused.notes, diagramCheck?.notes),
      diagramCheck?.studentAnswer ? `作图结构复核：${diagramCheck.studentAnswer}` : '',
      bottomCheck?.studentAnswer ? `计算题底部最终行复核：${bottomCheck.studentAnswer}` : ''
    ].filter(Boolean).join('；'),
    elapsedMs: Number(locator.elapsedMs || 0) + Number(wide.elapsedMs || 0) + Number(focused.elapsedMs || 0) + Number(diagramCheck?.elapsedMs || 0) + Number(bottomCheck?.elapsedMs || 0),
    attempts: Number(locator.attempts || 0) + Number(wide.attempts || 0) + Number(focused.attempts || 0) + Number(diagramCheck?.attempts || 0) + Number(bottomCheck?.attempts || 0),
    usage: addUsage(locator.usage, wide.usage, focused.usage, diagramCheck?.usage, bottomCheck?.usage),
    usageAvailable: Boolean(locator.usageAvailable || wide.usageAvailable || focused.usageAvailable || diagramCheck?.usageAvailable || bottomCheck?.usageAvailable),
    regions: locator.regions,
    cropBounds: { wide: wide.cropBounds, focused: focused.cropBounds },
    consensus
  };
}

async function verifyStudentAnswerByMode(block, initialResult, verificationMode = 'evidence') {
  if (verificationMode === 'selective' && !isHeavyEvidenceQuestion(initialResult.question, initialResult.answerType)) {
    return verifySimpleStudentAnswer(block, initialResult);
  }
  const verification = await verifyStudentAnswer(block, initialResult.answerType, initialResult.question);
  return {
    ...verification,
    strategy: 'evidence',
    status: verification.consensus ? 'evidence_consensus' : 'evidence_disagreement'
  };
}

async function safelyVerifyStudentAnswer(block, initialResult, verificationMode = 'evidence') {
  try {
    return await verifyStudentAnswerByMode(block, initialResult, verificationMode);
  } catch (error) {
    return { error: error.message, attempts: 1, usage: normalizeUsage(), usageAvailable: false };
  }
}

export function finalizeFastRecognition(baseResult) {
  const structured = structureStudentAnswerEvidence(separatePrintedQuestionMarks(baseResult));
  return {
    ...structured,
    gradingEligible: false,
    answerVerification: {
      status: 'not_run_fast_recognition',
      requiredBeforeGrading: true,
      reason: '首次快速识别不执行手写证据双视图核验'
    },
    answerVerificationElapsedMs: 0
  };
}

async function recognizeBlock(block, options = {}) {
  const prompt = `你是中文考试阅卷 OCR。请识别图片中的一块试卷，区分印刷题目和考生手写内容。不要补写图片中不存在的内容；看不清的位置写“[无法辨认]”。只返回 JSON：
{"questionNumber":"题号","question":"完整题干和选项（含公式尽量用纯文本）","printedMaxScore":"题号后印刷的本题满分数字，如（10分）填10；裁块中看不到则填null","sectionScoreRule":"本题所属大题印刷的赋分说明原文（如“本题共8小题，每小题3分，共24分”“全部选对得4分，选对但不全得2分，有选错得0分”）；裁块中看不到则填空字符串","studentAnswer":"考生回答原文；没有则为空","printedQuestionMarks":[{"text":"被圈/划线的印刷词句","type":"circle|underline|crossout|other"}],"answerType":"选择题|填空题|计算题|实验题|未知","confidence":0到1,"notes":"图示、跨页或辨认风险"}
题号优先读取图片中的印刷题号，候选题号仅供校验。题干必须逐字完整转录，不得概括或省略；题号后印刷的分值标记（如“（10分）”）必须原样保留在题干中题号之后；图、表、示意图不得省略，用简短文字描述其内容（如“图示：电场线分布图，左板带正电”）插入题干对应位置。printedMaxScore 与 sectionScoreRule 只能抄录裁块中真实可见的印刷文字，看不到就留空，禁止推测。必须保留手写计算过程，但计算草稿、旁注公式、划叉痕迹应写入 notes，不要混入题干，也不要混入选择题/填空题的 studentAnswer。
studentAnswer 只写可用于批改的最终作答：选择题只写最终选项字母；填空题只写填在空格上的词、数值或短语；实验题/计算题才保留必要解题过程。考生圈出或划线的印刷题干属于题干标记，不能把被圈的印刷词句复制到 studentAnswer；考生实际填写的选项字母、选填词和答题区文字仍必须保留。逐项检查题干、A/B/C/D 等选项和作答是否完整；只要裁块截断文字、缺少可见选项或存在“[无法辨认]”，confidence 不得高于 0.6，并在 notes 明确说明。候选题号：${block.questionNumber || '未知'}。`;
  const result = await callOcrModel({ model: MODEL, messages: [{ role: 'user', content: [{ type: 'text', text: prompt }, { type: 'image_url', image_url: { url: block.image } }] }] });
  const parsed = parseJson(result.data.choices?.[0]?.message?.content || '');
  const baseResult = makeOcrResult(block, parsed, result.elapsedMs, { attempts: result.attempts });
  if (options.verificationMode === 'fast') {
    return {
      ...finalizeFastRecognition(baseResult),
      ocrAttempts: Number(result.attempts || 1),
      usage: result.usage,
      usageAvailable: result.usageAvailable
    };
  }
  const verification = await safelyVerifyStudentAnswer(block, baseResult, options.verificationMode);
  const reconciled = reconcileStudentAnswer(baseResult, verification);
  return {
    ...reconciled,
    answerVerificationElapsedMs: Number(verification.elapsedMs || 0),
    ocrAttempts: Number(result.attempts || 1) + Number(verification.attempts || 0),
    usage: addUsage(result.usage, verification.usage),
    usageAvailable: Boolean(result.usageAvailable || verification.usageAvailable)
  };
}

export function groupBlocksForOcr(blocks, options = {}) {
  const maxBlocksPerRequest = Math.max(1, Number(options.maxBlocksPerRequest || MAX_BLOCKS_PER_OCR_REQUEST));
  const maxDataLength = Math.max(1, Number(options.maxDataLength || MAX_OCR_BATCH_DATA_LENGTH));
  const groups = [];
  let current = [];
  let currentDataLength = 0;
  const flush = () => {
    if (current.length) groups.push(current);
    current = [];
    currentDataLength = 0;
  };
  blocks.forEach((block, inputIndex) => {
    const entry = { block, inputIndex, ocrKey: `${inputIndex}:${block.id || 'block'}` };
    const dataLength = String(block.image || '').length;
    let previous = current.at(-1)?.block;
    const continuationMatchesPrevious = previous && block.continuationOf &&
      cleanPaperKey(previous.paperKey || previous.studentKey || previous.studentLabel) === cleanPaperKey(block.paperKey || block.studentKey || block.studentLabel) &&
      String(block.continuationOf) === String(previous.questionNumber || previous.id);
    if (continuationMatchesPrevious && current.length >= maxBlocksPerRequest) {
      const parent = current.pop();
      currentDataLength -= String(parent.block.image || '').length;
      flush();
      current.push(parent);
      currentDataLength = String(parent.block.image || '').length;
      previous = parent.block;
    }
    // Adjacent blocks from the same paper may cross a photographed page boundary.
    // The vision model decides whether they are separate questions or one continuation.
    const sameContext = previous &&
      cleanPaperKey(previous.paperKey || previous.studentKey || previous.studentLabel) === cleanPaperKey(block.paperKey || block.studentKey || block.studentLabel);
    if (current.length && (!sameContext || current.length >= maxBlocksPerRequest || currentDataLength + dataLength > maxDataLength)) flush();
    current.push(entry);
    currentDataLength += dataLength;
  });
  flush();
  return groups;
}

async function recognizeBlockGroup(entries, options = {}) {
  const schema = '{"results":[{"blockId":"必须原样返回给定BLOCK_ID","mergeWithBlockId":"若与本批更早图片属于同一道题则填其BLOCK_ID，否则为空字符串","questionNumber":"题号","question":"完整题干和选项","printedMaxScore":"题号后印刷的本题满分数字，如（10分）填10；看不到则填null","sectionScoreRule":"本题所属大题印刷的赋分说明原文；看不到则填空字符串","studentAnswer":"考生回答原文","printedQuestionMarks":[{"text":"被圈/划线的印刷词句","type":"circle|underline|crossout|other"}],"answerType":"选择题|填空题|计算题|实验题|未知","confidence":0到1,"notes":"图示、跨页、边界或辨认风险"}]}';
  const prompt = `你是中文考试阅卷 OCR。下面会给出 ${entries.length} 张题目裁块，每张图前都有唯一 BLOCK_ID。请在一次回复中完成所有图片的识别，严格返回 ${schema}，不要 Markdown。\n规则：\n1. results 必须与图片一一对应，数量必须为 ${entries.length}，BLOCK_ID 必须原样返回，不得漏项、重复或改写。\n2. 相邻图片可能是不同题，也可能是同一道题的分页或跨栏续块。请根据题号、语义承接、句子边界和版面边缘自行判断；若当前图片明确续接本批更早图片，在 mergeWithBlockId 填较早图片的 BLOCK_ID。不能仅因题号相似就合并，不确定时保持分开并在 notes 提示复核。\n3. 每张图片仍必须单独返回一项。不同题目的文字绝不能互相合并；系统会依据 mergeWithBlockId 或 CONTINUATION_OF 在后处理阶段拼接同题。\n4. 以“候选题号”对应的题目为识别目标。裁块边缘即使露出上一题、下一题或章节标题，也不要放进当前 question 或 studentAnswer；在 notes 写明已排除相邻内容。\n5. 区分印刷题目和考生手写内容，不要补写图中不存在的内容；看不清写“[无法辨认]”。考生只是圈出、划线或涂抹印刷词句时，被标记的印刷词句不得进入 studentAnswer；但实际填入空格的选填词、选项字母和答题区中新写的文字必须保留。必须保留目标题的完整题干、A/B/C/D 等全部可见选项和图示说明。题干必须逐字完整转录，不得概括或省略；题号后印刷的分值标记（如“（10分）”）必须原样保留在题干中题号之后；图、表、示意图不得省略，用简短文字描述其内容（如“图示：电场线分布图”）插入题干对应位置。\n6. studentAnswer 只写可用于批改的最终作答：选择题只写最终选项字母；填空题只写填在空格上的词、数值或短语；实验题/计算题才保留必要解题过程。旁边草稿公式、验算过程、划叉、圈画印刷文字，写入 notes 或 printedQuestionMarks，不得混入 studentAnswer。\n7. 目标题被裁块截断、缺少可见选项或出现无法辨认时，confidence 不得高于 0.6，并在 notes 说明。题号优先读取图片中的印刷题号，候选题号只用于校验。\n8. 逐字抄录赋分信息：题号后印刷分值填入 printedMaxScore（纯数字，如“（10分）”填 10，看不到填 null）；本题所属大题的印刷赋分说明（如“本题共8小题，每小题3分，共24分”、多选题“全部选对得4分，选对但不全得2分，有选错得0分”）原文填入 sectionScoreRule，看不到填空字符串。只能抄录真实可见的印刷文字，禁止推测或编造。`;
  const content = [{ type: 'text', text: prompt }];
  entries.forEach(({ block, ocrKey }, index) => {
    content.push({
      type: 'text',
      text: `图片 ${index + 1} / ${entries.length}\nBLOCK_ID: ${ocrKey}\n候选题号: ${block.questionNumber || '未知'}\nCONTINUATION_OF: ${block.continuationOf || '无'}`
    });
    content.push({ type: 'image_url', image_url: { url: block.image } });
  });
  const modelResult = await callOcrModel({ model: MODEL, messages: [{ role: 'user', content }] });
  const parsed = parseJson(modelResult.data.choices?.[0]?.message?.content || '');
  if (!Array.isArray(parsed.results)) throw new Error('批量 OCR 未返回 results 数组');
  const byId = new Map(parsed.results.map(item => [String(item.blockId || ''), item]));
  const entryById = new Map(entries.map(entry => [entry.ocrKey, entry]));
  const missing = entries.filter(entry => !byId.has(entry.ocrKey));
  if (missing.length || byId.size !== entries.length) throw new Error(`批量 OCR 结果映射不完整（缺少 ${missing.length} 项）`);
  const verifications = options.verificationMode !== 'fast'
    ? await mapWithConcurrency(
      entries,
      async entry => {
        const parsedItem = byId.get(entry.ocrKey);
        const initialResult = makeOcrResult(entry.block, parsedItem, modelResult.elapsedMs, {
          batchSize: entries.length,
          attempts: modelResult.attempts
        });
        return safelyVerifyStudentAnswer(entry.block, initialResult, options.verificationMode);
      },
      ANSWER_VERIFICATION_CONCURRENCY
    )
    : entries.map(() => null);
  return {
    results: entries.map((entry, index) => {
      const parsedItem = byId.get(entry.ocrKey);
      const targetKey = String(parsedItem.mergeWithBlockId || '');
      const targetEntry = entryById.get(targetKey);
      const targetIndex = targetEntry ? entries.indexOf(targetEntry) : -1;
      const samePaper = targetEntry && cleanPaperKey(targetEntry.block.paperKey) === cleanPaperKey(entry.block.paperKey);
      const mergeWithBlockId = targetIndex >= 0 && targetIndex < index && samePaper ? targetEntry.block.id : null;
      const baseResult = makeOcrResult(entry.block, parsedItem, modelResult.elapsedMs, {
        batchSize: entries.length,
        attempts: modelResult.attempts,
        mergeWithBlockId
      });
      if (options.verificationMode === 'fast') {
        return { inputIndex: entry.inputIndex, result: finalizeFastRecognition(baseResult) };
      }
      const verification = verifications[index] || { error: '未返回核验结果' };
      return {
        inputIndex: entry.inputIndex,
        result: {
          ...reconcileStudentAnswer(baseResult, verification),
          answerVerificationElapsedMs: Number(verification.elapsedMs || 0)
        }
      };
    }),
    requestCount: Number(modelResult.attempts || 1) + verifications.reduce((sum, item) => sum + Number(item?.attempts || 0), 0),
    fallback: false,
    usage: addUsage(modelResult.usage, ...verifications.map(item => item?.usage)),
    usageAvailable: Boolean(modelResult.usageAvailable || verifications.some(item => item?.usageAvailable))
  };
}

async function recognizeGroupWithFallback(entries, options = {}) {
  try {
    return await recognizeBlockGroup(entries, options);
  } catch (batchError) {
    const results = [];
    let requestCount = 1;
    let usage = normalizeUsage();
    let usageAvailable = false;
    for (const entry of entries) {
      try {
        const result = await recognizeBlock(entry.block, options);
        requestCount += result.ocrAttempts || 1;
        usage = addUsage(usage, result.usage);
        usageAvailable ||= result.usageAvailable;
        results.push({ inputIndex: entry.inputIndex, result: { ...result, batchFallback: true } });
      } catch (error) {
        requestCount += 1;
        results.push({ inputIndex: entry.inputIndex, result: {
          id: entry.block.id,
          blockId: entry.block.id,
          pageId: entry.block.pageId,
          sourceLabel: entry.block.label,
          questionNumber: String(entry.block.questionNumber || ''),
          question: '',
          studentAnswer: '',
          confidence: 0,
          gradingEligible: false,
          answerVerification: {
            status: 'failed',
            requiredBeforeGrading: true,
            reason: '模型网络请求失败'
          },
          paperKey: cleanPaperKey(entry.block.paperKey || entry.block.studentKey || entry.block.studentLabel),
          error: error.message,
          batchError: batchError.message,
          elapsedMs: 0,
          batchFallback: true
        } });
      }
    }
    return { results, requestCount, fallback: true, fallbackReason: batchError.message, usage, usageAvailable };
  }
}

export function mergeRecognizedResults(results) {
  const merged = [];
  const byKey = new Map();
  for (const item of results) {
    if (item.error) { merged.push(item); continue; }
    const paper = cleanPaperKey(item.paperKey) || '未分组试卷';
    const reference = item.mergeWithBlockId || item.continuationOf;
    const parent = reference
      ? byKey.get(`${paper}::${reference}`) || byKey.get(`${paper}::q:${reference}`)
      : null;
    if (parent) {
      parent.question = [parent.question, item.question].filter(Boolean).join('\n');
      parent.studentAnswer = [parent.studentAnswer, item.studentAnswer].filter(Boolean).join('\n');
      parent.notes = [parent.notes, item.notes].filter(Boolean).join('；');
      if (parent.printedMaxScore == null && item.printedMaxScore != null) parent.printedMaxScore = item.printedMaxScore;
      parent.sectionScoreRule = [parent.sectionScoreRule, item.sectionScoreRule].filter(Boolean).join('；');
      parent.sourceLabel = [parent.sourceLabel, item.sourceLabel].filter(Boolean).join(' + ');
      parent.sourceBlockIds.push(item.blockId);
      parent.confidence = Math.min(Number(parent.confidence || 0), Number(item.confidence || 0));
      parent.elapsedMs = Math.max(Number(parent.elapsedMs || 0), Number(item.elapsedMs || 0));
      parent.mergedBlockCount = parent.sourceBlockIds.length;
      continue;
    }
    const copy = { ...item, paperKey: paper, sourceBlockIds: [item.blockId], mergedBlockCount: 1 };
    merged.push(copy);
    const aliases = [`${paper}::${copy.blockId}`, `${paper}::${copy.id || ''}`];
    if (copy.questionNumber) aliases.push(`${paper}::${copy.questionNumber}`, `${paper}::q:${copy.questionNumber}`);
    aliases.forEach(alias => byKey.set(alias, copy));
  }
  return merged.map(item => item.error ? item : structureStudentAnswerEvidence(item));
}

async function mapWithConcurrency(items, worker, limit) {
  const out = new Array(items.length);
  let next = 0;
  async function run() {
    while (true) {
      const index = next++;
      if (index >= items.length) return;
      try { out[index] = await worker(items[index], index); }
      catch (error) { out[index] = { id: items[index].id, blockId: items[index].id, pageId: items[index].pageId || items[index].id, fileName: items[index].fileName, sourceLabel: items[index].label, error: error.message, elapsedMs: 0 }; }
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
  await fs.writeFile(target, serialized, 'utf8');
}

app.get('/api/health', (_req, res) => res.json({
  ok: true,
  pipeline: pipelineMetadata(),
  model: MODEL,
  layoutModel: LAYOUT_MODEL,
  ocrConcurrency: MAX_CONCURRENT_OCR,
  ocrBlocksPerRequest: MAX_BLOCKS_PER_OCR_REQUEST,
  answerEvidencePolicy: {
    gradingEligibilityThreshold: GRADING_ELIGIBILITY_THRESHOLD,
    verificationFailureConfidenceCap: VERIFICATION_FAILURE_CONFIDENCE_CAP,
    evidenceTextSimilarityMin: EVIDENCE_TEXT_SIMILARITY_MIN
  },
  layoutRefinement: {
    enabled: LAYOUT_REFINEMENT_ENABLED,
    engine: LAYOUT_REFINEMENT_ENGINE,
    minimumConfidence: LAYOUT_REFINEMENT_MIN_CONFIDENCE
  },
  pricing: {
    inputUsdPerMillion: INPUT_USD_PER_MILLION || null,
    outputUsdPerMillion: OUTPUT_USD_PER_MILLION || null,
    totalUsdPerMillion: TOTAL_USD_PER_MILLION || null,
    configured: Boolean(INPUT_USD_PER_MILLION || OUTPUT_USD_PER_MILLION || TOTAL_USD_PER_MILLION)
  },
  hasKey: Boolean(process.env.NEWAPI_API_KEY),
  providers: MODEL_PROVIDERS.map(provider => ({
    name: provider.name,
    ocrModel: provider.ocrModel,
    layoutModel: provider.layoutModel,
    coolingDown: (providerCircuit.get(provider.name) || 0) > Date.now()
  }))
}));

app.post('/api/layout', async (req, res) => {
  const pages = Array.isArray(req.body?.pages) ? req.body.pages : [];
  if (!pages.length) return res.status(400).json({ error: '请至少提供一张图片' });
  const started = performance.now();
  try {
    let layouts = await mapWithConcurrency(pages, async page => {
      try { return await analyzeLayout(page); }
      catch (firstError) {
        try { return await analyzeLayout(page); }
        catch (secondError) { throw new Error(`重试后仍失败：${secondError.message || firstError.message}`); }
      }
    }, 2);
    layouts = inferMissingPaperKeys(layouts);
    const tokenUsage = addUsage(...layouts.map(layout => layout.usage));
    const tokenUsageRecorded = layouts.some(layout => layout.usageAvailable);
    res.json({ layouts, elapsedMs: Math.round(performance.now() - started), tokenUsage, tokenUsageRecorded, estimatedCostUsd: usageCostUsd(tokenUsage) });
  } catch (error) { res.status(500).json({ error: error.message }); }
});

app.post('/api/recognize', async (req, res) => {
  const blocks = Array.isArray(req.body?.blocks) ? req.body.blocks : [];
  if (!blocks.length) return res.status(400).json({ error: '没有可识别的题目块' });
  const requestedVerificationMode = String(req.body?.verificationMode || 'fast');
  const verificationMode = ['evidence', 'selective'].includes(requestedVerificationMode)
    ? requestedVerificationMode
    : 'fast';
  const started = performance.now();
  const groups = groupBlocksForOcr(blocks);
  const reports = await mapWithConcurrency(groups, group => recognizeGroupWithFallback(group, { verificationMode }), MAX_CONCURRENT_OCR);
  const ordered = reports.flatMap(report => report.results || []).sort((a, b) => a.inputIndex - b.inputIndex);
  const rawResults = ordered.map(item => item.result);
  const results = mergeRecognizedResults(rawResults);
  const answerVerificationWorkMs = rawResults.reduce((sum, item) => sum + Number(item.answerVerificationElapsedMs || 0), 0);
  const answerVerificationCriticalPathMs = Math.max(0, ...rawResults.map(item => Number(item.answerVerificationElapsedMs || 0)));
  const ocrModelCriticalPathMs = Math.max(0, ...rawResults.map(item => Number(item.elapsedMs || 0)));
  const fallbackBatchCount = reports.filter(report => report.fallback).length;
  const modelRequestCount = reports.reduce((sum, report) => sum + Number(report.requestCount || 0), 0);
  const tokenUsage = addUsage(...reports.map(report => report.usage));
  const tokenUsageRecorded = reports.some(report => report.usageAvailable);
  res.json({
    results,
    verificationMode,
    elapsedMs: Math.round(performance.now() - started),
    ocrModelCriticalPathMs,
    answerVerificationWorkMs,
    answerVerificationCriticalPathMs,
    concurrency: MAX_CONCURRENT_OCR,
    blocksPerRequest: MAX_BLOCKS_PER_OCR_REQUEST,
    completedCount: results.length,
    rawResultCount: rawResults.length,
    mergedContinuationCount: rawResults.length - results.length,
    batchCount: groups.length,
    modelRequestCount,
    fallbackBatchCount,
    tokenUsage,
    tokenUsageRecorded,
    estimatedCostUsd: usageCostUsd(tokenUsage),
    savedRequestCount: Math.max(0, blocks.length - groups.length)
  });
});

// Internal API for the web application. The recognition path stays in this
// Node process so sharp, rotation, batching, fallback and timing remain the
// same as the reference workbench.
app.post('/api/process', async (req, res) => {
  const pages = Array.isArray(req.body?.pages) ? req.body.pages : [];
  if (!pages.length) return res.status(400).json({ error: '请至少提供一张图片' });
  const requestedVerificationMode = String(req.body?.verificationMode || 'fast');
  const verificationMode = ['evidence', 'selective'].includes(requestedVerificationMode)
    ? requestedVerificationMode
    : 'fast';
  const started = performance.now();
  try {
    const layouts = await mapWithConcurrency(pages, async page => analyzeLayout(page), 2);
    const blocks = [];
    let cropMs = 0;
    for (const layout of layouts) {
      const page = pages.find(item => item.id === layout.pageId);
      if (!page || layout.error) continue;
      const uprightImage = layout.uprightImage || await rotateDataUrl(page.image, layout.rotation || 0);
      const source = imageBufferFromDataUrl(uprightImage);
      const metadata = await sharp(source).metadata();
      const width = metadata.width || 1;
      const height = metadata.height || 1;
      for (const [regionIndex, region] of (layout.regions || []).entries()) {
        const cropStarted = performance.now();
        const cropBounds = paddedCropBounds(region, width, height);
        const { left, top, right, bottom } = cropBounds.pixels;
        const buffer = await sharp(source).extract({ left, top, width: Math.max(1, right - left), height: Math.max(1, bottom - top) }).jpeg({ quality: 92 }).toBuffer();
        cropMs += Math.round(performance.now() - cropStarted);
        blocks.push({
          ...region,
          id: `${layout.pageId}_${region.id}`,
          pageId: layout.pageId,
          fileName: page.fileName,
          paperKey: layout.studentKey || layout.studentLabel || '',
          cropBounds: cropBounds.normalized,
          image: `data:image/jpeg;base64,${buffer.toString('base64')}`,
          _pageImage: uprightImage,
          _nextRegionYmin: Number((layout.regions || [])[regionIndex + 1]?.ymin ?? 1000)
        });
      }
    }
    const ocrStarted = performance.now();
    const groups = groupBlocksForOcr(blocks);
    const reports = await mapWithConcurrency(groups, group => recognizeGroupWithFallback(group, { verificationMode }), MAX_CONCURRENT_OCR);
    const ordered = reports.flatMap(report => report.results || []).sort((a, b) => a.inputIndex - b.inputIndex);
    const rawResults = ordered.map(item => item.result);
    const results = mergeRecognizedResults(rawResults);
    const ocrMs = Math.round(performance.now() - ocrStarted);
    const answerVerificationWorkMs = rawResults.reduce((sum, item) => sum + Number(item.answerVerificationElapsedMs || 0), 0);
    const answerVerificationCriticalPathMs = Math.max(0, ...rawResults.map(item => Number(item.answerVerificationElapsedMs || 0)));
    const ocrModelCriticalPathMs = Math.max(0, ...rawResults.map(item => Number(item.elapsedMs || 0)));
    const layoutModelMs = layouts.reduce((sum, item) => sum + Number(item.regionModelElapsedMs ?? item.regionElapsedMs ?? 0), 0);
    const refinementMs = layouts.reduce((sum, item) => sum + Number(item.refinementElapsedMs || 0), 0);
    const layoutMs = layoutModelMs + refinementMs;
    const orientationMs = layouts.reduce((sum, item) => sum + Number(item.orientationElapsedMs || 0), 0);
    const preprocessingMs = layouts.reduce((sum, item) => sum + Number(item.preprocessingElapsedMs || item.affineNormalizationElapsedMs || 0), 0);
    const tokenUsage = addUsage(...layouts.map(layout => layout.usage), ...reports.map(report => report.usage));
    const tokenUsageRecorded = layouts.some(layout => layout.usageAvailable) || reports.some(report => report.usageAvailable);
    res.json({ layouts, results, blocks: blocks.map(({ image, _pageImage, _nextRegionYmin, ...block }) => block), verificationMode, timing: { orientationMs, preprocessingMs, layoutMs, layoutModelMs, refinementMs, cropMs, ocrMs, ocrModelCriticalPathMs, answerVerificationWorkMs, answerVerificationCriticalPathMs, totalElapsedMs: Math.round(performance.now() - started) }, concurrency: MAX_CONCURRENT_OCR, batchCount: groups.length, modelRequestCount: reports.reduce((sum, report) => sum + Number(report.requestCount || 0), 0), fallbackBatchCount: reports.filter(report => report.fallback).length, mergedContinuationCount: rawResults.length - results.length, tokenUsage, tokenUsageRecorded, estimatedCostUsd: usageCostUsd(tokenUsage), metadata: pipelineMetadata({ tokenUsage, tokenUsageRecorded }) });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

app.post('/api/jobs', async (req, res) => {
  try {
    const job = { ...req.body, id: req.body?.id || randomUUID(), createdAt: new Date().toISOString() };
    delete job.images;
    await writeJob(job);
    res.json({ id: job.id, createdAt: job.createdAt });
  } catch (error) {
    res.status(500).json({ error: `任务保存失败：${error.message}` });
  }
});

app.get('/api/jobs', async (_req, res) => {
  await fs.mkdir(JOBS_DIR, { recursive: true });
  const names = (await fs.readdir(JOBS_DIR)).filter(name => name.endsWith('.json'));
  const jobs = (await Promise.all(names.map(async name => {
    try { return JSON.parse(await fs.readFile(path.join(JOBS_DIR, name), 'utf8')); }
    catch { return null; }
  }))).filter(Boolean);
  jobs.sort((a, b) => String(b.createdAt || '').localeCompare(String(a.createdAt || '')));
  res.json(jobs.slice(0, 30).map(job => ({
    id: job.id,
    title: job.title,
    createdAt: job.createdAt,
    resultCount: job.results?.length || 0,
    paperCount: new Set((job.results || []).map(item => item.paperKey || '未分组')).size,
    totalElapsedMs: job.timing?.totalElapsedMs || 0
  })));
});

app.get('/api/jobs/:id', async (req, res) => {
  try { res.json(JSON.parse(await fs.readFile(path.join(JOBS_DIR, `${req.params.id}.json`), 'utf8'))); }
  catch { res.status(404).json({ error: '任务不存在' }); }
});

app.get('/api/jobs/:id/export', async (req, res) => {
  try {
    const job = JSON.parse(await fs.readFile(path.join(JOBS_DIR, `${req.params.id}.json`), 'utf8'));
    if (req.query.format === 'json') { res.type('application/json').send(JSON.stringify(job, null, 2)); return; }
    const groups = new Map();
    for (const item of job.results || []) {
      const key = item.paperKey || '未分组试卷';
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(item);
    }
    const tokenUsage = addUsage(job.timing?.layoutTokenUsage, job.timing?.tokenUsage);
    const estimatedCostUsd = usageCostUsd(tokenUsage);
    const tokenUsageRecorded = Boolean(job.timing?.layoutTokenUsageRecorded || job.timing?.tokenUsageRecorded);
    const lines = [
      `# ${job.title || '试卷识别结果'}`,
      '',
      `生成时间：${job.createdAt}`,
      `总耗时：${job.timing?.totalElapsedMs || 0} ms`,
      `OCR 配置：${job.timing?.ocrConcurrency || '—'} 路并发，每请求最多 ${job.timing?.ocrBatchSize || '—'} 块`,
      `OCR 调度：${job.timing?.ocrBatchCount || '—'} 批，实际模型请求 ${job.timing?.modelRequestCount || '—'} 次，降级批次 ${job.timing?.fallbackBatchCount || 0} 次`,
      `同题续块：${job.timing?.mergedContinuationCount || 0} 组由模型判断后拼接`,
      `Token 用量：${tokenUsageRecorded ? `输入 ${tokenUsage.inputTokens}，输出 ${tokenUsage.outputTokens}，合计 ${tokenUsage.totalTokens}` : '模型未返回 usage，无法统计'}`,
      `估算费用：${!tokenUsageRecorded ? '无法估算（缺少 token）' : estimatedCostUsd === null ? '未配置单价' : `$${estimatedCostUsd.toFixed(8)}`}`,
      `试卷数：${groups.size}`,
      ''
    ];
    let paperIndex = 0;
    for (const [paperKey, items] of groups) {
      paperIndex += 1;
      const pages = (job.layouts || []).filter(layout => (layout.studentKey || layout.studentLabel || '未分组试卷') === paperKey).map(layout => layout.fileName).filter(Boolean);
      const reviewItems = items.filter(item => {
        const text = `${item.question || ''} ${item.studentAnswer || ''} ${item.notes || ''}`.replace(/无截断|无缺失|不影响文字辨认|没有截断/g, '');
        return Number(item.confidence || 0) < 0.65 || /无法辨认|截断|缺失|不完整|残缺|裁切|裁剪|看不清/.test(text);
      });
      lines.push(`## 第${paperIndex}份试卷：${paperKey}`, '', pages.length ? `页面：${pages.join('、')}` : '', reviewItems.length ? `复核提示：第${reviewItems.map(item => item.questionNumber || '?').join('、')}题` : '复核提示：无自动标记', '');
      items.forEach((item, index) => lines.push(`### 第${item.questionNumber || index + 1}题`, '', `**题目**：${item.question || '（未识别）'}`, '', `**考生回答**：${item.studentAnswer || '（空）'}`, '', `识别置信度：${Math.round((item.confidence || 0) * 100)}%　耗时：${item.elapsedMs || 0} ms`, item.notes ? `备注：${item.notes}` : '', ''));
    }
    res.type('text/markdown').send(lines.join('\n'));
  } catch { res.status(404).json({ error: '任务不存在' }); }
});

app.get('*', (_req, res) => res.sendFile(path.join(__dirname, 'index.html')));
if (process.env.NODE_ENV !== 'test') app.listen(PORT, () => console.log(`Exam analysis workbench: http://localhost:${PORT}`));
