import fs from 'fs/promises';
import path from 'path';
import sharp from 'sharp';
import { randomUUID } from 'crypto';

const api = process.env.EXAM_API || 'http://localhost:3417';
const inputDir = process.env.INPUT_DIR || 'C:/Users/fu/Documents/临时/改卷子识别';
const files = (await fs.readdir(inputDir)).filter(name => /\.(jpe?g|png|webp)$/i.test(name)).sort();
const pages = await Promise.all(files.map(async fileName => {
  const buffer = await fs.readFile(path.join(inputDir, fileName));
  const meta = await sharp(buffer).metadata();
  return { id: randomUUID(), fileName, buffer, width: meta.width, height: meta.height, image: `data:image/jpeg;base64,${buffer.toString('base64')}` };
}));

const post = async (route, body) => {
  const response = await fetch(`${api}${route}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `${route} failed`);
  return data;
};

console.log(`Layout: ${pages.length} pages`);
const layoutStarted = performance.now();
const layoutData = await post('/api/layout', { pages: pages.map(({ id, fileName, image }) => ({ id, fileName, image })) });
const layouts = layoutData.layouts;
const failedLayouts = layouts.filter(layout => !Array.isArray(layout.regions));
if (failedLayouts.length) console.warn(`Layout failures: ${failedLayouts.map(item => item.fileName).join(', ')}`);
const blocks = [];
for (const layout of layouts.filter(item => Array.isArray(item.regions))) {
  const page = pages.find(item => item.id === layout.pageId);
  const upright = layout.coordinateSpace === 'upright';
  const workingBuffer = upright ? await sharp(page.buffer).rotate(layout.rotation).toBuffer() : page.buffer;
  const workingMeta = await sharp(workingBuffer).metadata();
  for (const region of layout.regions) {
    const xmin = Math.max(0, region.xmin - (upright ? 12 : 0));
    const ymin = Math.max(0, region.ymin - (upright ? 8 : 0));
    const xmax = Math.min(1000, region.xmax + (upright ? 12 : 0));
    const ymax = Math.min(1000, region.ymax + (upright ? 8 : 0));
    const left = Math.max(0, Math.floor(workingMeta.width * xmin / 1000));
    const top = Math.max(0, Math.floor(workingMeta.height * ymin / 1000));
    const width = Math.max(20, Math.min(workingMeta.width - left, Math.ceil(workingMeta.width * xmax / 1000) - left));
    const height = Math.max(20, Math.min(workingMeta.height - top, Math.ceil(workingMeta.height * ymax / 1000) - top));
    const pipeline = sharp(workingBuffer).extract({ left, top, width, height });
    const crop = await (upright ? pipeline : pipeline.rotate(layout.rotation)).jpeg({ quality: 92 }).toBuffer();
    blocks.push({
      ...region,
      id: `${page.id}::${region.id}`,
      layoutRegionId: region.id,
      layoutCandidateQuestionNumber: region.questionNumber || '',
      pageId: page.id,
      paperKey: layout.studentKey || layout.studentLabel || '未分组试卷',
      image: `data:image/jpeg;base64,${crop.toString('base64')}`
    });
  }
}
console.log(`Cropped: ${blocks.length} blocks in ${Math.round(performance.now() - layoutStarted)} ms`);
const cropMs = Math.max(0, Math.round(performance.now() - layoutStarted) - layoutData.elapsedMs);
const recognizeStarted = performance.now();
console.log(`OCR: submitting all ${blocks.length} blocks to the server scheduler`);
const batchData = await post('/api/recognize', { blocks });
const results = batchData.results || [];
const ocrMs = batchData.elapsedMs || Math.round(performance.now() - recognizeStarted);
console.log(`OCR: ${batchData.batchCount} batches, ${batchData.modelRequestCount} model requests, ${batchData.fallbackBatchCount} fallbacks`);
console.log(`Tokens: layout ${JSON.stringify(layoutData.tokenUsage || {})}, OCR ${JSON.stringify(batchData.tokenUsage || {})}`);
const job = await post('/api/jobs', {
  title: `样卷识别 ${new Date().toLocaleString('zh-CN')}`,
  pages: pages.map(({ id, fileName, width, height }) => ({ id, fileName, width, height })),
  layouts,
  blocks: blocks.map(({ image, ...block }) => block),
  results,
  timing: {
    layoutMs: layoutData.elapsedMs,
    layoutTokenUsage: layoutData.tokenUsage,
    layoutTokenUsageRecorded: layoutData.tokenUsageRecorded,
    cropMs,
    ocrMs,
    totalElapsedMs: Math.round(performance.now() - layoutStarted),
    blockCount: blocks.length,
    paperCount: new Set(results.map(item => item.paperKey || '未分组试卷')).size,
    ocrBatchCount: batchData.batchCount,
    modelRequestCount: batchData.modelRequestCount,
    fallbackBatchCount: batchData.fallbackBatchCount,
    mergedContinuationCount: batchData.mergedContinuationCount,
    tokenUsage: batchData.tokenUsage,
    tokenUsageRecorded: batchData.tokenUsageRecorded,
    estimatedCostUsd: batchData.estimatedCostUsd,
    ocrConcurrency: batchData.concurrency,
    ocrBatchSize: batchData.blocksPerRequest
  }
});
const exportResponse = await fetch(`${api}/api/jobs/${job.id}/export?format=markdown`);
if (exportResponse.ok) {
  await fs.mkdir(new URL('../data/exports/', import.meta.url), { recursive: true });
  await fs.writeFile(new URL(`../data/exports/${job.id}.md`, import.meta.url), await exportResponse.text(), 'utf8');
}
console.log(JSON.stringify({
  jobId: job.id,
  pages: pages.length,
  blocks: blocks.length,
  results: results.length,
  layoutMs: layoutData.elapsedMs,
  ocrMs,
  totalMs: Math.round(performance.now() - layoutStarted),
  concurrency: batchData.concurrency,
  blocksPerRequest: batchData.blocksPerRequest,
  batchCount: batchData.batchCount,
  modelRequestCount: batchData.modelRequestCount,
  fallbackBatchCount: batchData.fallbackBatchCount,
  mergedContinuationCount: batchData.mergedContinuationCount,
  tokenUsage: batchData.tokenUsage,
  tokenUsageRecorded: batchData.tokenUsageRecorded,
  estimatedCostUsd: batchData.estimatedCostUsd
}, null, 2));
