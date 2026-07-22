import fs from 'fs/promises';
import path from 'path';
import { execFileSync } from 'child_process';
import { randomUUID } from 'crypto';
import { createRequire } from 'module';
import { EVALUATION_DIR, loadManifest, resolveFromEvaluation, writeJson } from './lib.mjs';

const require = createRequire(import.meta.url);
const sharp = require(path.resolve(EVALUATION_DIR, '../../2_试卷分析文件/node_modules/sharp'));

function option(name, fallback) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : fallback;
}

const api = option('--api', process.env.EXAM_API || 'http://localhost:3417').replace(/\/$/, '');
const runCount = Math.max(1, Number(option('--runs', '3')) || 3);
const outputDir = path.resolve(option('--out', path.join(EVALUATION_DIR, 'runs', 'candidate')));
const manifest = await loadManifest();
const gitCommit = (() => {
  try { return execFileSync('git', ['rev-parse', 'HEAD'], { cwd: EVALUATION_DIR, encoding: 'utf8' }).trim(); }
  catch { return null; }
})();

const pages = await Promise.all(manifest.images.map(async imageRelative => {
  const imagePath = resolveFromEvaluation(imageRelative);
  const buffer = await fs.readFile(imagePath);
  const extension = path.extname(imagePath).toLowerCase();
  const mime = extension === '.png' ? 'image/png' : extension === '.webp' ? 'image/webp' : 'image/jpeg';
  return {
    id: randomUUID(),
    fileName: path.basename(imagePath),
    image: `data:${mime};base64,${buffer.toString('base64')}`
  };
}));

function imageBufferFromDataUrl(dataUrl) {
  const [, payload = ''] = String(dataUrl).split(',');
  return Buffer.from(payload, 'base64');
}

async function rotateImageBuffer(buffer, rotation = 0) {
  const normalized = Number(rotation || 0) % 360;
  if (!normalized) return buffer;
  return sharp(buffer).rotate(normalized).jpeg({ quality: 92 }).toBuffer();
}

function paddedCropBounds(region, width, height) {
  const xmin = Math.max(0, Number(region.xmin || 0) - 12);
  const ymin = Math.max(0, Number(region.ymin || 0) - 8);
  const xmax = Math.min(1000, Number(region.xmax || 1000) + 12);
  const ymax = Math.min(1000, Number(region.ymax || 1000) + 8);
  const left = Math.max(0, Math.min(width - 1, Math.round(width * xmin / 1000)));
  const top = Math.max(0, Math.min(height - 1, Math.round(height * ymin / 1000)));
  const right = Math.max(left + 1, Math.min(width, Math.round(width * xmax / 1000)));
  const bottom = Math.max(top + 1, Math.min(height, Math.round(height * ymax / 1000)));
  return {
    normalized: { xmin, ymin, xmax, ymax },
    pixels: { left, top, right, bottom }
  };
}

async function processViaLayoutRecognize({ api, pages }) {
  const started = performance.now();
  const layoutResponse = await fetch(`${api}/api/layout`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pages })
  });
  const layoutPayload = await layoutResponse.json().catch(() => ({}));
  if (!layoutResponse.ok) throw new Error(layoutPayload.error || `layout HTTP ${layoutResponse.status}`);

  const pageById = new Map(pages.map(page => [page.id, page]));
  const blocks = [];
  let cropMs = 0;
  for (const layout of layoutPayload.layouts || []) {
    const page = pageById.get(layout.pageId);
    if (!page || layout.error) continue;
    const originalBuffer = imageBufferFromDataUrl(page.image);
    const workingBuffer = layout.coordinateSpace === 'upright'
      ? await rotateImageBuffer(originalBuffer, layout.rotation || 0)
      : originalBuffer;
    const metadata = await sharp(workingBuffer).metadata();
    const width = metadata.width || 1;
    const height = metadata.height || 1;
    const paperKey = String(layout.studentKey || layout.studentLabel || '').trim();
    for (const [regionIndex, region] of (layout.regions || []).entries()) {
      const cropStarted = performance.now();
      const cropBounds = paddedCropBounds(region, width, height);
      const { left, top, right, bottom } = cropBounds.pixels;
      const crop = await sharp(workingBuffer)
        .extract({ left, top, width: Math.max(1, right - left), height: Math.max(1, bottom - top) })
        .jpeg({ quality: 92 })
        .toBuffer();
      cropMs += Math.round(performance.now() - cropStarted);
      const regionId = String(region.id || `block_${regionIndex + 1}`);
      blocks.push({
        ...region,
        id: `${layout.pageId}_${regionId}`,
        layoutRegionId: regionId,
        pageId: layout.pageId,
        fileName: page.fileName,
        paperKey,
        studentKey: layout.studentKey || '',
        studentLabel: layout.studentLabel || '',
        cropBounds: cropBounds.normalized,
        image: `data:image/jpeg;base64,${crop.toString('base64')}`
      });
    }
  }

  if (!blocks.length) {
    return {
      layouts: layoutPayload.layouts || [],
      blocks,
      results: [],
      timing: {
        layoutMs: layoutPayload.elapsedMs || 0,
        orientationModelMs: layoutPayload.orientationModelMs || 0,
        regionModelMs: layoutPayload.regionModelMs || 0,
        cropMs,
        ocrMs: 0,
        totalElapsedMs: Math.round(performance.now() - started)
      }
    };
  }

  const recognizeStarted = performance.now();
  const recognizeResponse = await fetch(`${api}/api/recognize`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ blocks })
  });
  const recognizePayload = await recognizeResponse.json().catch(() => ({}));
  if (!recognizeResponse.ok) throw new Error(recognizePayload.error || `recognize HTTP ${recognizeResponse.status}`);
  const ocrMs = recognizePayload.elapsedMs || Math.round(performance.now() - recognizeStarted);
  return {
    provider: recognizePayload.provider || layoutPayload.provider,
    providerLabel: recognizePayload.providerLabel || layoutPayload.providerLabel,
    model: recognizePayload.model || layoutPayload.model,
    layouts: layoutPayload.layouts || [],
    blocks: blocks.map(({ image, ...block }) => block),
    results: recognizePayload.results || [],
    verificationMode: recognizePayload.verificationMode,
    timing: {
      layoutMs: layoutPayload.elapsedMs || 0,
      orientationModelMs: layoutPayload.orientationModelMs || 0,
      regionModelMs: layoutPayload.regionModelMs || 0,
      cropMs,
      ocrMs,
      ocrModelCriticalPathMs: recognizePayload.ocrModelCriticalPathMs || null,
      answerVerificationWorkMs: recognizePayload.answerVerificationWorkMs || null,
      answerVerificationCriticalPathMs: recognizePayload.answerVerificationCriticalPathMs || null,
      totalElapsedMs: Math.round(performance.now() - started)
    },
    concurrency: recognizePayload.concurrency,
    batchCount: recognizePayload.batchCount,
    modelRequestCount: recognizePayload.modelRequestCount,
    fallbackBatchCount: recognizePayload.fallbackBatchCount,
    mergedContinuationCount: recognizePayload.mergedContinuationCount,
    tokenUsage: recognizePayload.tokenUsage || {},
    tokenUsageRecorded: recognizePayload.tokenUsageRecorded || false,
    estimatedCostUsd: recognizePayload.estimatedCostUsd || null,
    metadata: {
      provider: recognizePayload.provider || layoutPayload.provider,
      model: recognizePayload.model || layoutPayload.model,
      api_mode: 'layout_recognize',
      timing: {
        wall_elapsed_ms: Math.round(performance.now() - started)
      }
    }
  };
}

await fs.mkdir(outputDir, { recursive: true });
for (let run = 1; run <= runCount; run += 1) {
  const started = performance.now();
  let payload;
  const response = await fetch(`${api}/api/process`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pages })
  });
  payload = await response.json().catch(() => ({}));
  if (!response.ok && response.status === 404) {
    payload = await processViaLayoutRecognize({ api, pages });
  } else if (!response.ok) {
    throw new Error(payload.error || `HTTP ${response.status}`);
  }
  payload.variant = 'candidate';
  payload.run_index = run;
  payload.runner = {
    api,
    git_commit: gitCommit,
    wall_elapsed_ms: Math.round(performance.now() - started),
    source_images: manifest.images
  };
  if (payload.metadata && !payload.metadata.git_commit) payload.metadata.git_commit = gitCommit;
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  const outputPath = path.join(outputDir, `run-${String(run).padStart(2, '0')}-${stamp}.json`);
  await writeJson(outputPath, payload);
  console.log(JSON.stringify({
    run,
    file: path.relative(EVALUATION_DIR, outputPath),
    questions: (payload.results || []).map(item => item.questionNumber),
    result_count: payload.results?.length || 0,
    total_elapsed_ms: payload.timing?.totalElapsedMs,
    average_confidence: payload.results?.length
      ? payload.results.reduce((sum, item) => sum + Number(item.confidence || 0), 0) / payload.results.length
      : null
  }));
}
