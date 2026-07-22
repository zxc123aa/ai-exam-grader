import fs from 'fs/promises';
import path from 'path';
import sharp from 'sharp';

const api = 'http://localhost:3417';
const inputDir = 'C:/Users/fu/Documents/临时/改卷子识别';
const jobsDir = new URL('../data/jobs/', import.meta.url);
const names = (await fs.readdir(jobsDir)).filter(name => name.endsWith('.json')).sort().reverse();
if (!names.length) throw new Error('No saved job found');
const job = JSON.parse(await fs.readFile(new URL(names[0], jobsDir), 'utf8'));
const failedIndexes = job.results.map((item, index) => item.error ? index : -1).filter(index => index >= 0);
if (!failedIndexes.length) {
  console.log('No failed blocks');
  process.exit(0);
}

const post = async (route, body) => {
  const response = await fetch(`${api}${route}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `${route} failed`);
  return data;
};

let retryMs = 0;
for (const resultIndex of failedIndexes) {
  const failed = job.results[resultIndex];
  const block = job.blocks.find(item => item.id === failed.blockId && item.pageId === failed.pageId);
  const page = job.pages.find(item => item.id === failed.pageId);
  const layout = job.layouts.find(item => item.pageId === failed.pageId);
  const source = await fs.readFile(path.join(inputDir, page.fileName));
  const meta = await sharp(source).metadata();
  const left = Math.max(0, Math.floor(meta.width * block.xmin / 1000));
  const top = Math.max(0, Math.floor(meta.height * block.ymin / 1000));
  const width = Math.max(20, Math.min(meta.width - left, Math.floor(meta.width * (block.xmax - block.xmin) / 1000)));
  const height = Math.max(20, Math.min(meta.height - top, Math.floor(meta.height * (block.ymax - block.ymin) / 1000)));
  const crop = await sharp(source).extract({ left, top, width, height }).rotate(layout.rotation).jpeg({ quality: 94 }).toBuffer();
  const data = await post('/api/recognize', { blocks: [{ ...block, image: `data:image/jpeg;base64,${crop.toString('base64')}` }] });
  job.results[resultIndex] = data.results[0];
  retryMs += data.elapsedMs || 0;
  console.log(`Retried ${block.id}: ${data.results[0].error ? 'failed' : 'ok'}`);
}
job.timing.ocrMs += retryMs;
job.timing.totalElapsedMs += retryMs;
await post('/api/jobs', job);
console.log(JSON.stringify({ jobId: job.id, retryMs, errors: job.results.filter(item => item.error).length }, null, 2));
