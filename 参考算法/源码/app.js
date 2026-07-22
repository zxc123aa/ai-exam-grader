const $ = (selector) => document.querySelector(selector);
const state = { pages: [], layouts: [], blocks: [], results: [], jobId: null, timing: {}, ocrConcurrency: 0, ocrBatchSize: 1 };
const fileInput = $('#file-input');

function paperKey(layout) { return String(layout?.studentKey || layout?.studentLabel || '未分组试卷').trim() || '未分组试卷'; }

function toast(message) { const node = $('#toast'); node.textContent = message; node.classList.add('show'); setTimeout(() => node.classList.remove('show'), 2600); }
function setPhase(text) { $('#phase').textContent = text; }
function setBusy(button, busy, text) { button.disabled = busy; if (busy) button.dataset.old = button.textContent; button.querySelector('span').textContent = busy ? text : (button === $('#analyze') ? '分析版面' : '逐块识别'); }
function formatMs(value) { if (!Number.isFinite(value)) return '—'; return value > 999 ? `${(value / 1000).toFixed(1)} s` : `${value} ms`; }
function readImage(file) { return new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => { const img = new Image(); img.onload = () => resolve({ id: crypto.randomUUID(), fileName: file.name, image: reader.result, width: img.naturalWidth, height: img.naturalHeight, element: img }); img.onerror = reject; img.src = reader.result; }; reader.onerror = reject; reader.readAsDataURL(file); }); }

function loadImage(src) { return new Promise((resolve, reject) => { const image = new Image(); image.onload = () => resolve(image); image.onerror = reject; image.src = src; }); }

async function prepareWorkingPage(page, layout) {
  page.layout = layout;
  if (layout.coordinateSpace !== 'upright' || !layout.rotation) {
    page.workingImage = page.image;
    page.workingWidth = page.width;
    page.workingHeight = page.height;
    page.workingElement = page.element || await loadImage(page.image);
    return;
  }
  const swapSides = [90, 270].includes(layout.rotation);
  const canvas = document.createElement('canvas');
  canvas.width = swapSides ? page.height : page.width;
  canvas.height = swapSides ? page.width : page.height;
  const context = canvas.getContext('2d');
  context.translate(canvas.width / 2, canvas.height / 2);
  context.rotate(layout.rotation * Math.PI / 180);
  context.drawImage(page.element, -page.width / 2, -page.height / 2);
  page.workingImage = canvas.toDataURL('image/jpeg', .92);
  page.workingWidth = canvas.width;
  page.workingHeight = canvas.height;
  page.workingElement = await loadImage(page.workingImage);
}

function renderFiles() { const target = $('#file-list'); target.innerHTML = state.pages.length ? state.pages.map((page, index) => `<div class="file-item"><span class="num">${String(index + 1).padStart(2, '0')}</span><span class="name">${page.fileName}</span></div>`).join('') : '<div class="empty-note">还没有图片。建议一次放入同一份试卷的所有页。</div>'; $('#analyze').disabled = !state.pages.length; }
async function acceptFiles(files) { const images = [...files].filter(file => file.type.startsWith('image/')); if (!images.length) return; state.pages = await Promise.all(images.map(readImage)); state.layouts = []; state.results = []; state.jobId = null; renderFiles(); renderLayout(); renderResults(); $('#recognize').disabled = true; $('#save').disabled = true; $('#export-json').disabled = true; $('#export-md').disabled = true; setPhase(`${state.pages.length} 张图片待分析`); toast(`已载入 ${state.pages.length} 张图片`); }

function cropRegion(page, region) { return new Promise(resolve => {
  if (page.layout?.coordinateSpace === 'upright') {
    const xmin = Math.max(0, region.xmin - 12);
    const ymin = Math.max(0, region.ymin - 8);
    const xmax = Math.min(1000, region.xmax + 12);
    const ymax = Math.min(1000, region.ymax + 8);
    const sx = page.workingWidth * xmin / 1000;
    const sy = page.workingHeight * ymin / 1000;
    const sw = page.workingWidth * (xmax - xmin) / 1000;
    const sh = page.workingHeight * (ymax - ymin) / 1000;
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(sw));
    canvas.height = Math.max(1, Math.round(sh));
    canvas.getContext('2d').drawImage(page.workingElement, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height);
    resolve(canvas.toDataURL('image/jpeg', .92));
    return;
  }
  const sx = page.width * region.xmin / 1000;
  const sy = page.height * region.ymin / 1000;
  const sw = page.width * (region.xmax - region.xmin) / 1000;
  const sh = page.height * (region.ymax - region.ymin) / 1000;
  const angle = (page.layout?.rotation || 0) * Math.PI / 180;
  const canvas = document.createElement('canvas');
  const rotated = [90, 270].includes(page.layout?.rotation) ? [sh, sw] : [sw, sh];
  canvas.width = Math.max(1, Math.round(rotated[0]));
  canvas.height = Math.max(1, Math.round(rotated[1]));
  const context = canvas.getContext('2d');
  context.translate(canvas.width / 2, canvas.height / 2);
  context.rotate(angle);
  context.drawImage(page.element, sx, sy, sw, sh, -sw / 2, -sh / 2, sw, sh);
  resolve(canvas.toDataURL('image/jpeg', .92));
}); }

function renderLayout() { const grid = $('#layout-grid'); if (!state.layouts.length) { grid.innerHTML = '<div class="blank-state"><span>◎</span><b>先放入试卷图片</b><small>版面分析后，这里会显示每张原图与题目块。</small></div>'; $('#layout-summary').textContent = state.pages.length ? '尚未分析' : '等待图片'; return; } const valid = state.layouts.filter(item => Array.isArray(item.regions)); const paperCount = new Set(valid.map(paperKey)).size; $('#layout-summary').textContent = `${valid.reduce((n, item) => n + item.regions.length, 0)} 个题目块 · ${paperCount} 份试卷 · ${valid.length}/${state.layouts.length} 张成功`; grid.innerHTML = state.layouts.map(layout => { const page = state.pages.find(item => item.id === layout.pageId); if (layout.error) return `<article class="page-card"><div class="page-card-head"><b>${escapeHtml(layout.fileName || page?.fileName || '未知图片')}</b><span>FAILED</span></div><div class="blank-state compact"><span>!</span><b>版面分析失败</b><small>${escapeHtml(layout.error)}</small></div></article>`; const boxes = layout.regions.map(region => { const left = region.xmin / 10, top = region.ymin / 10, width = (region.xmax - region.xmin) / 10, height = (region.ymax - region.ymin) / 10; return `<div class="region-box" style="left:${left}%;top:${top}%;width:${width}%;height:${height}%"><span>${escapeHtml(region.questionNumber || region.label)}</span></div>`; }).join(''); const chips = layout.regions.map(region => `<span class="region-chip ${region.continuationOf ? 'cont' : ''}">${escapeHtml(region.questionNumber || '未编号')}${region.continuationOf ? ' ↳续' : ''}</span>`).join(''); const image = page.workingImage || page.image; const width = page.workingWidth || page.width; const height = page.workingHeight || page.height; const rotationLabel = layout.rotation ? `已校正 ${layout.rotation}°` : '方向正常'; return `<article class="page-card"><div class="page-card-head"><b>${escapeHtml(layout.pageLabel || page.fileName)}</b><span>${escapeHtml(paperKey(layout))} · ${rotationLabel} · ${formatMs(layout.elapsedMs)}</span></div><div class="page-image-wrap" style="aspect-ratio:${width}/${height}"><img src="${image}" alt="${escapeHtml(page.fileName)}" /><div class="boxes-overlay">${boxes}</div></div><div class="region-list">${chips}</div></article>`; }).join(''); }

async function analyze() { const button = $('#analyze'); setBusy(button, true, '分析中…'); setPhase('正在判断方向并分析完整题目块'); const started = performance.now(); try { const response = await fetch('/api/layout', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pages: state.pages.map(({ id, fileName, image }) => ({ id, fileName, image })) }) }); const data = await response.json(); if (!response.ok) throw new Error(data.error); state.layouts = data.layouts || []; state.timing.layoutMs = data.elapsedMs || Math.round(performance.now() - started); state.timing.layoutTokenUsage = data.tokenUsage || null; state.timing.layoutTokenUsageRecorded = Boolean(data.tokenUsageRecorded); state.timing.layoutEstimatedCostUsd = data.estimatedCostUsd ?? null; setPhase('正在生成转正版面预览'); await Promise.all(state.layouts.map(async layout => { const page = state.pages.find(item => item.id === layout.pageId); if (page && !layout.error) await prepareWorkingPage(page, layout); })); renderLayout(); $('#recognize').disabled = !state.layouts.some(layout => Array.isArray(layout.regions)); setPhase(`版面完成 · ${formatMs(state.timing.layoutMs)}${data.tokenUsage?.totalTokens ? ` · ${data.tokenUsage.totalTokens} tokens` : ''}`); toast(`版面分析完成，共 ${state.layouts.reduce((n, layout) => n + (layout.regions?.length || 0), 0)} 个块`); } catch (error) { toast(error.message); setPhase('分析失败'); } finally { setBusy(button, false); } }

async function recognize() { const button = $('#recognize'); setBusy(button, true, '识别中…'); setPhase('正在裁切并准备多图并发识别'); const started = performance.now(); try { const blocks = []; for (const layout of state.layouts.filter(item => Array.isArray(item.regions))) { const page = state.pages.find(item => item.id === layout.pageId); if (!page.workingElement) await prepareWorkingPage(page, layout); for (const region of layout.regions) blocks.push({ ...region, pageId: page.id, paperKey: paperKey(layout), studentKey: layout.studentKey || '', studentLabel: layout.studentLabel || '', image: await cropRegion(page, region) }); } state.blocks = blocks; setPhase(`正在识别 ${blocks.length} 个题块 · ${state.ocrConcurrency || '—'} 路并发 · 每请求最多 ${state.ocrBatchSize} 块`); const response = await fetch('/api/recognize', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ blocks }) }); const data = await response.json(); if (!response.ok) throw new Error(data.error); state.ocrConcurrency = Number(data.concurrency || state.ocrConcurrency || 0); state.ocrBatchSize = Number(data.blocksPerRequest || state.ocrBatchSize || 1); const rawResults = data.results || []; state.results = mergeContinuation(rawResults); state.timing.ocrMs = data.elapsedMs || Math.round(performance.now() - started); state.timing.totalElapsedMs = state.timing.layoutMs + state.timing.ocrMs; state.timing.blockCount = blocks.length; state.timing.paperCount = new Set(state.results.map(item => item.paperKey || '未分组试卷')).size; state.timing.ocrBatchCount = Number(data.batchCount || 0); state.timing.modelRequestCount = Number(data.modelRequestCount || 0); state.timing.fallbackBatchCount = Number(data.fallbackBatchCount || 0); state.timing.mergedContinuationCount = Number(data.mergedContinuationCount || 0); state.timing.tokenUsage = data.tokenUsage || null; state.timing.tokenUsageRecorded = Boolean(data.tokenUsageRecorded); state.timing.estimatedCostUsd = data.estimatedCostUsd ?? null; state.timing.ocrConcurrency = state.ocrConcurrency; state.timing.ocrBatchSize = state.ocrBatchSize; renderResults(); $('#save').disabled = false; $('#export-json').disabled = true; $('#export-md').disabled = true; const fallbackNote = state.timing.fallbackBatchCount ? ` · ${state.timing.fallbackBatchCount} 批降级` : ''; const mergeNote = state.timing.mergedContinuationCount ? ` · ${state.timing.mergedContinuationCount} 组续题拼接` : ''; const tokenNote = state.timing.tokenUsage?.totalTokens ? ` · ${state.timing.tokenUsage.totalTokens} tokens` : ''; setPhase(`识别完成 · ${formatMs(state.timing.ocrMs)} · ${state.ocrConcurrency} 路 · ${state.timing.modelRequestCount} 次模型请求${fallbackNote}${mergeNote}${tokenNote}`); $('#total-time').textContent = formatMs(state.timing.totalElapsedMs); toast(`识别完成，${state.timing.paperCount} 份试卷，共 ${state.results.length} 道题`); } catch (error) { toast(error.message); setPhase('识别失败'); } finally { setBusy(button, false); } }

function mergeContinuation(results) { const merged = []; const byKey = new Map(); for (const item of results) { if (item.error) { merged.push(item); continue; } const paper = item.paperKey || '未分组试卷'; let parent = null; const reference = item.mergeWithBlockId || item.continuationOf; if (reference) { parent = byKey.get(`${paper}::${reference}`) || byKey.get(`${paper}::q:${reference}`); } if (parent) { parent.question = [parent.question, item.question].filter(Boolean).join('\n'); parent.studentAnswer = [parent.studentAnswer, item.studentAnswer].filter(Boolean).join('\n'); parent.notes = [parent.notes, item.notes].filter(Boolean).join('；'); parent.sourceLabel = `${parent.sourceLabel} + ${item.sourceLabel}`; parent.elapsedMs = Math.max(parent.elapsedMs || 0, item.elapsedMs || 0); parent.confidence = Math.min(parent.confidence || 0, item.confidence || 0); } else { const copy = { ...item, paperKey: paper }; merged.push(copy); const aliases = [`${paper}::${copy.blockId}`, `${paper}::${copy.id || ''}`]; if (copy.questionNumber) aliases.push(`${paper}::${copy.questionNumber}`, `${paper}::q:${copy.questionNumber}`); aliases.forEach(alias => byKey.set(alias, copy)); } } return merged; }

function normalizedQuestionText(value) { return String(value || '').replace(/\[截断\]|\[无法辨认\]/g, '').replace(/[\s\d，。！？、；：,.!?;:()[\]{}"“”‘’（）【】_]+/g, ''); }
function hasQuestionOverlap(left, right) { const a = normalizedQuestionText(left); const b = normalizedQuestionText(right); if (a.length < 10 || b.length < 10) return false; const tail = a.slice(-Math.min(28, a.length)); for (let size = Math.min(28, tail.length); size >= 10; size -= 1) if (b.includes(tail.slice(-size))) return true; return false; }

function auditResults(results) {
  const issues = new Map();
  const byPaper = new Map();
  results.forEach((item, index) => {
    const flags = [];
    if (item.error) flags.push('识别失败');
    if (item.confidence < .65) flags.push('低置信度');
    const riskText = `${item.question || ''} ${item.studentAnswer || ''} ${item.notes || ''}`
      .replace(/轻微(?:裁剪|裁切)[^。；\n]*(?:不影响文字辨认|不影响)[^。；\n]*/g, '')
      .replace(/无截断|无缺失|不影响文字辨认|没有截断/g, '');
    if (/无法辨认|截断|缺失|不完整|残缺|裁切|裁剪|看不清/.test(riskText)) flags.push('内容不完整');
    issues.set(index, flags);
    const key = item.paperKey || '未分组试卷';
    if (!byPaper.has(key)) byPaper.set(key, []);
    byPaper.get(key).push({ item, index });
  });
  const paperSummaries = [];
  for (const [paper, entries] of byPaper) {
    const numbered = entries.map(entry => String(entry.item.questionNumber || '').match(/^\d+$/)?.[0]).filter(Boolean).map(Number);
    const seen = new Set();
    const duplicate = new Set();
    numbered.forEach(number => { if (seen.has(number)) duplicate.add(number); seen.add(number); });
    duplicate.forEach(number => entries.filter(entry => Number(entry.item.questionNumber) === number).forEach(entry => { const flags = issues.get(entry.index) || []; if (!flags.includes('题号重复')) flags.push('题号重复'); }));
    const min = numbered.length > 2 ? Math.min(...numbered) : 0;
    const max = numbered.length > 2 ? Math.max(...numbered) : 0;
    const missing = max - min > 1 ? Array.from({ length: max - min + 1 }, (_, offset) => min + offset).filter(number => !seen.has(number)) : [];
    entries.forEach((entry, index) => {
      const next = entries[index + 1];
      if (next && hasQuestionOverlap(entry.item.question, next.item.question)) {
        const flags = issues.get(entry.index) || [];
        if (!flags.includes('疑似串入相邻题')) flags.push('疑似串入相邻题');
        const nextFlags = issues.get(next.index) || [];
        if (!nextFlags.includes('疑似相邻题重复')) nextFlags.push('疑似相邻题重复');
      }
    });
    paperSummaries.push({ paper, duplicate: [...duplicate], missing, flagged: entries.filter(entry => (issues.get(entry.index) || []).length).length });
  }
  return { issues, paperSummaries };
}

function autoSizeTextarea(node) { node.style.height = 'auto'; node.style.height = `${Math.max(66, node.scrollHeight)}px`; }

function renderResults() { const target = $('#results'); if (!state.results.length) { target.innerHTML = '<div class="blank-state compact"><span>⌁</span><b>识别结果会出现在这里</b><small>每道题可直接修改，之后再保存。</small></div>'; $('#results-summary').textContent = ''; return; } const audit = auditResults(state.results); const totalFlags = [...audit.issues.values()].filter(flags => flags.length).length; const hasNumberingIssues = audit.paperSummaries.some(summary => summary.duplicate.length || summary.missing.length); $('#results-summary').textContent = totalFlags ? `复核提示：${totalFlags} 题 · ${hasNumberingIssues ? '含重复或缺题，' : '题号连续，'}低置信度或不完整内容已标记` : '结构检查通过 · 仍请核对手写内容'; const paperOrder = new Map(); state.results.forEach(item => { const key = item.paperKey || '未分组试卷'; if (!paperOrder.has(key)) paperOrder.set(key, paperOrder.size); }); const displayEntries = state.results.map((item, index) => ({ item, index })).sort((left, right) => { const leftPaper = left.item.paperKey || '未分组试卷'; const rightPaper = right.item.paperKey || '未分组试卷'; const paperDifference = paperOrder.get(leftPaper) - paperOrder.get(rightPaper); if (paperDifference) return paperDifference; const leftNumber = Number(left.item.questionNumber); const rightNumber = Number(right.item.questionNumber); if (Number.isFinite(leftNumber) && Number.isFinite(rightNumber) && leftNumber !== rightNumber) return leftNumber - rightNumber; return left.index - right.index; }); let previousPaper = ''; const html = []; displayEntries.forEach(({ item, index }) => { const currentPaper = item.paperKey || '未分组试卷'; const flags = audit.issues.get(index) || []; if (currentPaper !== previousPaper) { const paper = audit.paperSummaries.find(summary => summary.paper === currentPaper); const paperNote = paper && (paper.duplicate.length || paper.missing.length) ? ` · ${paper.duplicate.length ? `重复${paper.duplicate.join('、')}` : ''}${paper.missing.length ? ` 缺${paper.missing.join('、')}` : ''}` : ''; html.push(`<div class="paper-divider"><span>试卷</span><strong>${escapeHtml(currentPaper)}</strong><button class="rename-paper" type="button" data-paper="${escapeHtml(currentPaper)}">修改身份</button><small>${escapeHtml(paperNote)}</small></div>`); previousPaper = currentPaper; } const flagHtml = flags.length ? `<div class="result-flags">${flags.map(flag => `<span>${escapeHtml(flag)}</span>`).join('')}</div>` : ''; html.push(item.error ? `<div class="result-row flagged" data-index="${index}"><div class="result-num">${String(index + 1).padStart(2, '0')}</div><div class="result-error">${escapeHtml(item.error)} <button class="retry-block" data-retry="${index}">重试此块</button></div></div>` : `<div class="result-row ${flags.length ? 'flagged' : ''}" data-index="${index}"><div class="result-num"><label>题号</label><input data-field="questionNumber" value="${escapeHtml(item.questionNumber)}" aria-label="题号" /></div><div class="result-field"><label>QUESTION / 题目</label><textarea data-field="question">${escapeHtml(item.question)}</textarea>${flagHtml}</div><div class="result-field"><label>STUDENT ANSWER / 考生回答</label><textarea data-field="studentAnswer">${escapeHtml(item.studentAnswer)}</textarea><small class="source-note">${escapeHtml(item.sourceLabel || '')}${item.notes ? ` · ${escapeHtml(item.notes)}` : ''}</small></div><div class="confidence ${item.confidence < .65 ? 'warn' : ''}"><strong>${Math.round((item.confidence || 0) * 100)}%</strong>${formatMs(item.elapsedMs)}</div></div>`); }); target.innerHTML = html.join(''); target.querySelectorAll('textarea').forEach(autoSizeTextarea); target.querySelectorAll('[data-field]').forEach(node => node.addEventListener('input', event => { const row = event.target.closest('.result-row'); const item = state.results[Number(row.dataset.index)]; item[event.target.dataset.field] = event.target.value; if (event.target.matches('textarea')) autoSizeTextarea(event.target); })); target.querySelectorAll('[data-retry]').forEach(node => node.addEventListener('click', () => retryBlock(Number(node.dataset.retry), node))); target.querySelectorAll('[data-paper]').forEach(node => node.addEventListener('click', () => renamePaper(node.dataset.paper))); }
function renamePaper(oldKey) { const next = prompt('修改试卷身份（例如：符致凯_25）：', oldKey); if (!next || next.trim() === oldKey) return; const value = next.trim().slice(0, 80); state.results.forEach(item => { if ((item.paperKey || '未分组试卷') === oldKey) item.paperKey = value; }); state.blocks.forEach(item => { if ((item.paperKey || '未分组试卷') === oldKey) item.paperKey = value; }); state.layouts.forEach(layout => { if (paperKey(layout) === oldKey) { layout.studentKey = value; layout.studentLabel = value; } }); renderResults(); toast(`已将试卷身份改为 ${value}`); }
function escapeHtml(value) { return String(value || '').replace(/[&<>"']/g, char => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[char])); }

async function saveJob() { const title = prompt('给这次识别任务取一个名字：', `试卷识别 ${new Date().toLocaleString('zh-CN')}`); if (!title) return; const response = await fetch('/api/jobs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title, pages: state.pages.map(page => ({ id: page.id, fileName: page.fileName })), layouts: state.layouts, blocks: state.blocks.map(({ image, ...block }) => block), results: state.results, timing: state.timing }) }); const data = await response.json(); if (!response.ok) return toast(data.error || '保存失败'); state.jobId = data.id; $('#export-json').disabled = false; $('#export-md').disabled = false; loadHistory(); toast('任务已保存'); }
function exportJob(format) { if (!state.jobId) return; window.open(`/api/jobs/${state.jobId}/export?format=${format}`, '_blank'); }
async function retryBlock(index, button) { const failed = state.results[index]; const block = state.blocks.find(item => item.id === failed.blockId); if (!block?.image) return toast('历史任务没有保留裁块图片，请重新导入原图'); button.disabled = true; button.textContent = '重试中…'; try { const response = await fetch('/api/recognize', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ blocks: [block] }) }); const data = await response.json(); if (!response.ok) throw new Error(data.error); state.results[index] = data.results[0]; state.timing.ocrMs += data.elapsedMs || 0; state.timing.totalElapsedMs += data.elapsedMs || 0; renderResults(); toast('该题已重新识别'); } catch (error) { button.disabled = false; button.textContent = '重试此块'; toast(error.message); } }
async function loadJob(id) { try { const job = await (await fetch(`/api/jobs/${id}`)).json(); if (job.error) throw new Error(job.error); state.jobId = job.id; state.results = job.results || []; state.timing = job.timing || {}; state.layouts = []; state.blocks = job.blocks || []; $('#layout-summary').textContent = `${state.blocks.length || 0} 个已保存题块 · 原图未随任务保存`; $('#layout-grid').innerHTML = '<div class="blank-state compact history-layout-note"><span>↗</span><b>历史 OCR 已加载</b><small>当前任务只保存了版面元数据和识别结果，原图未写入任务文件。若要重新裁切或重试，请重新导入原图。</small></div>'; renderResults(); $('#total-time').textContent = formatMs(state.timing.totalElapsedMs); const batchNote = state.timing.modelRequestCount ? ` · ${state.timing.modelRequestCount} 次模型请求` : ''; setPhase(`已打开历史任务 · ${state.results.length} 题 · OCR ${formatMs(state.timing.ocrMs)}${batchNote}`); $('#save').disabled = false; $('#export-json').disabled = false; $('#export-md').disabled = false; toast(job.title || '历史任务已打开'); } catch (error) { toast(error.message); } }
async function loadHistory() { try { const data = await (await fetch('/api/jobs')).json(); $('#history-list').innerHTML = data.length ? data.slice(0, 6).map(item => `<button class="history-item" data-id="${item.id}"><span>${escapeHtml(item.title || '未命名任务').slice(0, 24)}</span><span>${item.paperCount || 1}卷 / ${item.resultCount}题</span></button>`).join('') : '<span>暂无已保存任务</span>'; $('#history-list').querySelectorAll('[data-id]').forEach(node => node.addEventListener('click', () => loadJob(node.dataset.id))); } catch { $('#history-list').textContent = '历史任务不可用'; } }

fileInput.addEventListener('change', event => acceptFiles(event.target.files)); const dropzone = $('#dropzone'); ['dragenter','dragover'].forEach(name => dropzone.addEventListener(name, event => { event.preventDefault(); dropzone.classList.add('drag'); })); ['dragleave','drop'].forEach(name => dropzone.addEventListener(name, event => { event.preventDefault(); dropzone.classList.remove('drag'); })); dropzone.addEventListener('drop', event => acceptFiles(event.dataTransfer.files)); $('#analyze').addEventListener('click', analyze); $('#recognize').addEventListener('click', recognize); $('#save').addEventListener('click', saveJob); $('#export-json').addEventListener('click', () => exportJob('json')); $('#export-md').addEventListener('click', () => exportJob('markdown')); document.addEventListener('keydown', event => { if ((event.metaKey || event.ctrlKey) && event.key === '1') analyze(); if ((event.metaKey || event.ctrlKey) && event.key === '2') recognize(); });
(async function init() { try { const health = await (await fetch('/api/health')).json(); state.ocrConcurrency = Number(health.ocrConcurrency || 0); state.ocrBatchSize = Number(health.ocrBlocksPerRequest || 1); $('#health').classList.toggle('ok', health.hasKey); $('#health span').textContent = health.hasKey ? `模型已连接 · ${state.ocrConcurrency} 路并发 · ${state.ocrBatchSize} 块/请求` : '待配置 API Key'; $('#model-label').textContent = `${health.model} / ${health.hasKey ? `READY · ${state.ocrConcurrency}x · BATCH ${state.ocrBatchSize}` : 'NO KEY'}`; } catch { $('#health span').textContent = '服务未启动'; } loadHistory(); })();
