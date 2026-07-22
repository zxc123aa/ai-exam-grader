import fs from 'fs/promises';
import path from 'path';
import sharp from 'sharp';
import { fileURLToPath } from 'url';

const api = process.env.EXAM_API || 'http://localhost:3418';
const inputDir = 'C:/Users/fu/Documents/临时/改卷子识别';
const jobsDir = new URL('../data/jobs/', import.meta.url);
const exportsDir = new URL('../data/exports/', import.meta.url);

const names = (await fs.readdir(jobsDir)).filter(name => name.endsWith('.json'));
if (!names.length) throw new Error('没有可更新的任务');
const jobs = await Promise.all(names.map(async name => ({ name, job: JSON.parse(await fs.readFile(new URL(name, jobsDir), 'utf8')) })));
jobs.sort((a, b) => String(b.job.createdAt || '').localeCompare(String(a.job.createdAt || '')));
const job = jobs[0].job;

const post = async (route, body) => {
  const response = await fetch(`${api}${route}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `${route} failed`);
  return data;
};

const pages = await Promise.all((job.pages || []).map(async page => {
  const buffer = await fs.readFile(path.join(inputDir, page.fileName));
  await sharp(buffer).metadata();
  return { id: page.id, fileName: page.fileName, image: `data:image/jpeg;base64,${buffer.toString('base64')}` };
}));
const layoutData = await post('/api/layout', { pages });
const layouts = layoutData.layouts || [];
const byPage = new Map(layouts.map(layout => [layout.pageId, layout]));
for (const result of job.results || []) {
  const layout = byPage.get(result.pageId);
  result.paperKey = layout?.studentKey || layout?.studentLabel || '未分组试卷';
}
job.layouts = layouts;
job.timing = { ...(job.timing || {}), regroupLayoutMs: layoutData.elapsedMs || 0 };
await fs.mkdir(exportsDir, { recursive: true });
await fs.writeFile(new URL(`${job.id}.json`, jobsDir), JSON.stringify(job, null, 2), 'utf8');

const groups = new Map();
for (const item of job.results || []) {
  const key = item.paperKey || '未分组试卷';
  if (!groups.has(key)) groups.set(key, []);
  groups.get(key).push(item);
}
const lines = [`# ${job.title || '试卷识别结果'}`, '', `生成时间：${job.createdAt}`, `总耗时：${job.timing?.totalElapsedMs || 0} ms`, `重新分卷耗时：${job.timing.regroupLayoutMs} ms`, `试卷数：${groups.size}`, ''];
let paperIndex = 0;
for (const [key, items] of groups) {
  paperIndex += 1;
  const pageNames = layouts.filter(layout => (layout.studentKey || layout.studentLabel || '未分组试卷') === key).map(layout => layout.fileName).filter(Boolean);
  lines.push(`## 第${paperIndex}份试卷：${key}`, '', pageNames.length ? `页面：${pageNames.join('、')}` : '', '');
  for (const [index, item] of items.entries()) {
    lines.push(`### 第${item.questionNumber || index + 1}题`, '', `**题目**：${item.question || '（未识别）'}`, '', `**考生回答**：${item.studentAnswer || '（空）'}`, '', `识别置信度：${Math.round((item.confidence || 0) * 100)}%　耗时：${item.elapsedMs || 0} ms`, item.notes ? `备注：${item.notes}` : '', '');
  }
}
const output = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'data', 'exports', `${job.id}.md`);
await fs.writeFile(output, lines.join('\n'), 'utf8');
console.log(JSON.stringify({ jobId: job.id, papers: [...groups].map(([key, items]) => ({ key, count: items.length })), markdown: output, regroupLayoutMs: layoutData.elapsedMs }, null, 2));
