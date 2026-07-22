const $ = (selector) => document.querySelector(selector);
const state = {
  pages: [],
  layouts: [],
  blocks: [],
  results: [],
  jobId: null,
  timing: {},
  ocrConcurrency: 0,
  ocrBatchSize: 1,
  providers: [],
  defaultProvider: "",
  activeProvider: "",
  models: [],
  defaultModel: "",
  activeModel: "",
  runStartedAt: 0,
  benchmarkId: null,
  inputSignature: "",
  benchmarks: [],
};
const fileInput = $("#file-input");

function paperKey(layout) {
  return (
    String(layout?.studentKey || layout?.studentLabel || "未分组试卷").trim() ||
    "未分组试卷"
  );
}

function toast(message) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.add("show");
  setTimeout(() => node.classList.remove("show"), 2600);
}
function setPhase(text) {
  $("#phase").textContent = text;
}
function setBusy(button, busy, text) {
  button.disabled = busy;
  if (busy) button.dataset.old = button.textContent;
  button.querySelector("span").textContent = busy
    ? text
    : button === $("#analyze")
      ? "分析版面"
      : "逐块识别";
}
function formatMs(value) {
  if (!Number.isFinite(value)) return "—";
  return value > 999 ? `${(value / 1000).toFixed(1)} s` : `${value} ms`;
}
async function sha256(value) {
  const bytes =
    value instanceof ArrayBuffer
      ? value
      : new TextEncoder().encode(String(value));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}
async function readImage(file) {
  const buffer = await file.arrayBuffer();
  const image = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const img = new Image();
      img.onload = () => resolve({ dataUrl: reader.result, element: img });
      img.onerror = reject;
      img.src = reader.result;
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
  return {
    id: crypto.randomUUID(),
    fileName: file.name,
    image: image.dataUrl,
    width: image.element.naturalWidth,
    height: image.element.naturalHeight,
    element: image.element,
    size: file.size,
    lastModified: file.lastModified,
    hash: await sha256(buffer),
  };
}

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = reject;
    image.src = src;
  });
}

async function prepareWorkingPage(page, layout) {
  page.layout = layout;
  if (layout.coordinateSpace !== "upright" || !layout.rotation) {
    page.workingImage = page.image;
    page.workingWidth = page.width;
    page.workingHeight = page.height;
    page.workingElement = page.element || (await loadImage(page.image));
    return;
  }
  const swapSides = [90, 270].includes(layout.rotation);
  const canvas = document.createElement("canvas");
  canvas.width = swapSides ? page.height : page.width;
  canvas.height = swapSides ? page.width : page.height;
  const context = canvas.getContext("2d");
  context.translate(canvas.width / 2, canvas.height / 2);
  context.rotate((layout.rotation * Math.PI) / 180);
  context.drawImage(page.element, -page.width / 2, -page.height / 2);
  page.workingImage = canvas.toDataURL("image/jpeg", 0.92);
  page.workingWidth = canvas.width;
  page.workingHeight = canvas.height;
  page.workingElement = await loadImage(page.workingImage);
}

function renderFiles() {
  const target = $("#file-list");
  target.innerHTML = state.pages.length
    ? state.pages
        .map(
          (page, index) =>
            `<div class="file-item"><span class="num">${String(index + 1).padStart(2, "0")}</span><span class="name">${page.fileName}</span></div>`,
        )
        .join("")
    : '<div class="empty-note">还没有图片。建议一次放入同一份试卷的所有页。</div>';
  $("#analyze").disabled = !state.pages.length;
}
async function acceptFiles(files) {
  const images = [...files].filter((file) => file.type.startsWith("image/"));
  if (!images.length) return;
  state.pages = await Promise.all(images.map(readImage));
  state.inputSignature = await sha256(
    state.pages
      .map((page) => `${page.fileName}:${page.size}:${page.hash}`)
      .join("|"),
  );
  state.layouts = [];
  state.blocks = [];
  state.results = [];
  state.jobId = null;
  state.activeProvider = "";
  state.activeModel = "";
  state.benchmarkId = null;
  state.timing = {};
  $("#provider-select").disabled = !state.providers.length;
  $("#model-select").disabled = !state.models.length;
  renderFiles();
  renderLayout();
  renderResults();
  renderBenchmarks();
  $("#recognize").disabled = true;
  $("#save").disabled = true;
  $("#export-json").disabled = true;
  $("#export-md").disabled = true;
  setPhase(`${state.pages.length} 张图片待分析`);
  toast(`已载入 ${state.pages.length} 张图片`);
}

function cropRegion(page, region) {
  return new Promise((resolve) => {
    if (page.layout?.coordinateSpace === "upright") {
      const xmin = Math.max(0, region.xmin - 12);
      const ymin = Math.max(0, region.ymin - 8);
      const xmax = Math.min(1000, region.xmax + 12);
      const ymax = Math.min(1000, region.ymax + 8);
      const sx = (page.workingWidth * xmin) / 1000;
      const sy = (page.workingHeight * ymin) / 1000;
      const sw = (page.workingWidth * (xmax - xmin)) / 1000;
      const sh = (page.workingHeight * (ymax - ymin)) / 1000;
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(sw));
      canvas.height = Math.max(1, Math.round(sh));
      canvas
        .getContext("2d")
        .drawImage(
          page.workingElement,
          sx,
          sy,
          sw,
          sh,
          0,
          0,
          canvas.width,
          canvas.height,
        );
      resolve(canvas.toDataURL("image/jpeg", 0.92));
      return;
    }
    const sx = (page.width * region.xmin) / 1000;
    const sy = (page.height * region.ymin) / 1000;
    const sw = (page.width * (region.xmax - region.xmin)) / 1000;
    const sh = (page.height * (region.ymax - region.ymin)) / 1000;
    const angle = ((page.layout?.rotation || 0) * Math.PI) / 180;
    const canvas = document.createElement("canvas");
    const rotated = [90, 270].includes(page.layout?.rotation)
      ? [sh, sw]
      : [sw, sh];
    canvas.width = Math.max(1, Math.round(rotated[0]));
    canvas.height = Math.max(1, Math.round(rotated[1]));
    const context = canvas.getContext("2d");
    context.translate(canvas.width / 2, canvas.height / 2);
    context.rotate(angle);
    context.drawImage(page.element, sx, sy, sw, sh, -sw / 2, -sh / 2, sw, sh);
    resolve(canvas.toDataURL("image/jpeg", 0.92));
  });
}

function renderLayout() {
  const grid = $("#layout-grid");
  if (!state.layouts.length) {
    grid.innerHTML =
      '<div class="blank-state"><span>◎</span><b>先放入试卷图片</b><small>版面分析后，这里会显示每张原图与题目块。</small></div>';
    $("#layout-summary").textContent = state.pages.length
      ? "尚未分析"
      : "等待图片";
    return;
  }
  const valid = state.layouts.filter((item) => Array.isArray(item.regions));
  const paperCount = new Set(valid.map(paperKey)).size;
  $("#layout-summary").textContent =
    `${valid.reduce((n, item) => n + item.regions.length, 0)} 个题目块 · ${paperCount} 份试卷 · ${valid.length}/${state.layouts.length} 张成功`;
  grid.innerHTML = state.layouts
    .map((layout) => {
      const page = state.pages.find((item) => item.id === layout.pageId);
      if (layout.error)
        return `<article class="page-card"><div class="page-card-head"><b>${escapeHtml(layout.fileName || page?.fileName || "未知图片")}</b><span>FAILED</span></div><div class="blank-state compact"><span>!</span><b>版面分析失败</b><small>${escapeHtml(layout.error)}</small></div></article>`;
      const boxes = layout.regions
        .map((region) => {
          const left = region.xmin / 10,
            top = region.ymin / 10,
            width = (region.xmax - region.xmin) / 10,
            height = (region.ymax - region.ymin) / 10;
          return `<div class="region-box" style="left:${left}%;top:${top}%;width:${width}%;height:${height}%"><span>${escapeHtml(region.questionNumber || region.label)}</span></div>`;
        })
        .join("");
      const chips = layout.regions
        .map(
          (region) =>
            `<span class="region-chip ${region.continuationOf ? "cont" : ""}">${escapeHtml(region.questionNumber || "未编号")}${region.continuationOf ? " ↳续" : ""}</span>`,
        )
        .join("");
      const image = page.workingImage || page.image;
      const width = page.workingWidth || page.width;
      const height = page.workingHeight || page.height;
      const rotationLabel = layout.rotation
        ? `已校正 ${layout.rotation}°`
        : "方向正常";
      return `<article class="page-card"><div class="page-card-head"><b>${escapeHtml(layout.pageLabel || page.fileName)}</b><span>${escapeHtml(paperKey(layout))} · ${rotationLabel} · ${formatMs(layout.elapsedMs)}</span></div><div class="page-image-wrap" style="aspect-ratio:${width}/${height}"><img src="${image}" alt="${escapeHtml(page.fileName)}" /><div class="boxes-overlay">${boxes}</div></div><div class="region-list">${chips}</div></article>`;
    })
    .join("");
}

function combinedTokenUsage(...values) {
  return values.reduce(
    (sum, value) => ({
      inputTokens: sum.inputTokens + Number(value?.inputTokens || 0),
      outputTokens: sum.outputTokens + Number(value?.outputTokens || 0),
      totalTokens: sum.totalTokens + Number(value?.totalTokens || 0),
    }),
    { inputTokens: 0, outputTokens: 0, totalTokens: 0 },
  );
}
function benchmarkPayload(status, error = "") {
  const confidenceValues = state.results
    .filter((item) => !item.error && Number.isFinite(Number(item.confidence)))
    .map((item) => Number(item.confidence));
  return {
    provider: state.activeProvider || $("#provider-select").value,
    model: state.activeModel || $("#model-select").value,
    inputSignature: state.inputSignature,
    inputLabel: state.pages.map((page) => page.fileName).join("、"),
    pageCount: state.pages.length,
    status,
    timings: {
      orientationModelMs: state.timing.orientationModelMs || 0,
      regionModelMs: state.timing.regionModelMs || 0,
      layoutWallMs: state.timing.layoutMs || 0,
      cropMs: state.timing.cropMs || 0,
      ocrWallMs: state.timing.ocrMs || 0,
      totalWallMs:
        state.timing.totalElapsedMs ||
        Math.round(
          performance.now() - (state.runStartedAt || performance.now()),
        ),
    },
    counts: {
      blocks:
        state.timing.blockCount ||
        state.layouts.reduce(
          (sum, layout) => sum + (layout.regions?.length || 0),
          0,
        ),
      results: state.results.length,
      failed: state.results.filter((item) => item.error).length,
      batches: state.timing.ocrBatchCount || 0,
      requests: state.timing.modelRequestCount || 0,
      fallbacks: state.timing.fallbackBatchCount || 0,
      mergedContinuations: state.timing.mergedContinuationCount || 0,
      reviewRequired: state.results.filter((item) => item.reviewRequired).length,
    },
    layoutTokenUsage: state.timing.layoutTokenUsage || {},
    ocrTokenUsage: state.timing.tokenUsage || {},
    averageConfidence: confidenceValues.length
      ? confidenceValues.reduce((sum, value) => sum + value, 0) /
        confidenceValues.length
      : 0,
    error,
  };
}
async function saveBenchmark(status, error = "") {
  try {
    const route = state.benchmarkId
      ? `/api/benchmarks/${state.benchmarkId}`
      : "/api/benchmarks";
    const response = await fetch(route, {
      method: state.benchmarkId ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(benchmarkPayload(status, error)),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error);
    state.benchmarkId = data.id;
    await loadBenchmarks();
  } catch (benchmarkError) {
    console.warn("benchmark save failed", benchmarkError);
  }
}
function renderBenchmarks() {
  const body = $("#benchmark-body");
  if (!body) return;
  if (!state.benchmarks.length) {
    body.innerHTML = '<tr><td colspan="9">暂无模型对比记录</td></tr>';
    return;
  }
  body.innerHTML = state.benchmarks
    .map((item) => {
      const sameInput =
        state.inputSignature && item.inputSignature === state.inputSignature;
      const token = combinedTokenUsage(
        item.layoutTokenUsage,
        item.ocrTokenUsage,
      ).totalTokens;
      const status =
        item.status === "completed"
          ? `成功 ${item.counts?.results || 0}/${item.counts?.blocks || 0}`
          : item.status === "layout_complete"
            ? `版面 ${item.counts?.blocks || 0}块`
            : `失败 ${item.error || ""}`;
      const averageConfidence =
        item.status === "completed" && Number(item.averageConfidence) > 0
          ? `${(Number(item.averageConfidence) * 100).toFixed(1)}%`
          : "—";
      return `<tr class="${sameInput ? "same-input" : ""}"><td><strong>${escapeHtml(item.providerLabel || item.provider || "旧记录")} / ${escapeHtml(item.model)}</strong><small>${escapeHtml(item.inputLabel || "未命名输入")} · ${new Date(item.createdAt).toLocaleString("zh-CN")}</small></td><td>${formatMs(item.timings?.orientationModelMs)}</td><td>${formatMs(item.timings?.regionModelMs)}</td><td>${formatMs(item.timings?.cropMs)}</td><td>${formatMs(item.timings?.ocrWallMs)}</td><td><strong>${formatMs(item.timings?.totalWallMs || item.timings?.layoutWallMs)}</strong></td><td>${averageConfidence}</td><td>${escapeHtml(status)}</td><td>${token || "—"}</td></tr>`;
    })
    .join("");
}
async function loadBenchmarks() {
  try {
    const response = await fetch("/api/benchmarks");
    const data = await response.json();
    if (!response.ok) throw new Error(data.error);
    state.benchmarks = data;
    renderBenchmarks();
  } catch {
    $("#benchmark-body").innerHTML =
      '<tr><td colspan="9">对比记录不可用</td></tr>';
  }
}

async function analyze() {
  const button = $("#analyze");
  state.activeProvider = $("#provider-select").value || state.defaultProvider;
  state.activeModel = $("#model-select").value || state.defaultModel;
  state.runStartedAt = performance.now();
  state.benchmarkId = null;
  const providerConfig = state.providers.find(
    (provider) => provider.id === state.activeProvider,
  );
  state.timing = {
    provider: state.activeProvider,
    providerLabel: providerConfig?.label || state.activeProvider,
    model: state.activeModel,
  };
  state.results = [];
  state.blocks = [];
  setBusy(button, true, "分析中…");
  $("#provider-select").disabled = true;
  $("#model-select").disabled = true;
  setPhase(
    `正在用 ${providerConfig?.label || state.activeProvider} / ${state.activeModel} 分析题目块`,
  );
  const started = performance.now();
  try {
    const response = await fetch("/api/layout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        provider: state.activeProvider,
        model: state.activeModel,
        pages: state.pages.map(({ id, fileName, image }) => ({
          id,
          fileName,
          image,
        })),
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error);
    state.layouts = data.layouts || [];
    state.timing.layoutMs =
      data.elapsedMs || Math.round(performance.now() - started);
    state.timing.orientationModelMs = data.orientationModelMs || 0;
    state.timing.regionModelMs = data.regionModelMs || 0;
    state.timing.layoutTokenUsage = data.tokenUsage || null;
    state.timing.layoutTokenUsageRecorded = Boolean(data.tokenUsageRecorded);
    state.timing.layoutEstimatedCostUsd = data.estimatedCostUsd ?? null;
    state.timing.blockCount = state.layouts.reduce(
      (n, layout) => n + (layout.regions?.length || 0),
      0,
    );
    if (!state.layouts.some((layout) => Array.isArray(layout.regions)))
      throw new Error(
        state.layouts.find((layout) => layout.error)?.error ||
          "版面分析未返回可用题块",
      );
    setPhase("正在生成转正版面预览");
    await Promise.all(
      state.layouts.map(async (layout) => {
        const page = state.pages.find((item) => item.id === layout.pageId);
        if (page && !layout.error) await prepareWorkingPage(page, layout);
      }),
    );
    renderLayout();
    renderResults();
    $("#recognize").disabled = false;
    state.timing.totalElapsedMs = state.timing.layoutMs;
    await saveBenchmark("layout_complete");
    setPhase(
      `${state.timing.providerLabel} / ${state.activeModel} 版面完成 · ${formatMs(state.timing.layoutMs)} · 方向 ${formatMs(state.timing.orientationModelMs)} · 分块 ${formatMs(state.timing.regionModelMs)}`,
    );
    toast(`版面分析完成，共 ${state.timing.blockCount} 个块`);
  } catch (error) {
    state.timing.totalElapsedMs = Math.round(
      performance.now() - state.runStartedAt,
    );
    await saveBenchmark("failed", error.message);
    toast(error.message);
    setPhase("分析失败");
  } finally {
    setBusy(button, false);
    $("#provider-select").disabled = false;
    $("#model-select").disabled = false;
  }
}

async function recognize() {
  const button = $("#recognize");
  setBusy(button, true, "识别中…");
  $("#provider-select").disabled = true;
  $("#model-select").disabled = true;
  setPhase(
    `正在用 ${state.timing.providerLabel} / ${state.activeModel} 裁切并准备多图识别`,
  );
  try {
    const cropStarted = performance.now();
    const blocks = [];
    for (const layout of state.layouts.filter((item) =>
      Array.isArray(item.regions),
    )) {
      const page = state.pages.find((item) => item.id === layout.pageId);
      if (!page.workingElement) await prepareWorkingPage(page, layout);
      for (const region of layout.regions)
        blocks.push({
          ...region,
          provider: state.activeProvider,
          model: state.activeModel,
          pageId: page.id,
          paperKey: paperKey(layout),
          studentKey: layout.studentKey || "",
          studentLabel: layout.studentLabel || "",
          image: await cropRegion(page, region),
        });
    }
    state.timing.cropMs = Math.round(performance.now() - cropStarted);
    state.blocks = blocks;
    setPhase(
      `正在识别 ${blocks.length} 个题块 · ${state.ocrConcurrency || "—"} 路并发 · 每请求最多 ${state.ocrBatchSize} 块`,
    );
    const response = await fetch("/api/recognize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        provider: state.activeProvider,
        model: state.activeModel,
        blocks,
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error);
    state.ocrConcurrency = Number(
      data.concurrency || state.ocrConcurrency || 0,
    );
    state.ocrBatchSize = Number(
      data.blocksPerRequest || state.ocrBatchSize || 1,
    );
    state.results = mergeContinuation(data.results || []);
    state.timing.ocrMs = data.elapsedMs || 0;
    state.timing.totalElapsedMs =
      Number(state.timing.layoutMs || 0) +
      Number(state.timing.cropMs || 0) +
      Number(state.timing.ocrMs || 0);
    state.timing.blockCount = blocks.length;
    state.timing.paperCount = new Set(
      state.results.map((item) => item.paperKey || "未分组试卷"),
    ).size;
    state.timing.ocrBatchCount = Number(data.batchCount || 0);
    state.timing.modelRequestCount = Number(data.modelRequestCount || 0);
    state.timing.fallbackBatchCount = Number(data.fallbackBatchCount || 0);
    state.timing.mergedContinuationCount = Number(
      data.mergedContinuationCount || 0,
    );
    state.timing.tokenUsage = data.tokenUsage || null;
    state.timing.tokenUsageRecorded = Boolean(data.tokenUsageRecorded);
    state.timing.estimatedCostUsd = data.estimatedCostUsd ?? null;
    state.timing.ocrConcurrency = state.ocrConcurrency;
    state.timing.ocrBatchSize = state.ocrBatchSize;
    await saveBenchmark("completed");
    renderResults();
    $("#save").disabled = false;
    $("#export-json").disabled = true;
    $("#export-md").disabled = true;
    const fallbackNote = state.timing.fallbackBatchCount
      ? ` · ${state.timing.fallbackBatchCount} 批降级`
      : "";
    const tokenNote = state.timing.tokenUsage?.totalTokens
      ? ` · ${state.timing.tokenUsage.totalTokens} tokens`
      : "";
    setPhase(
      `${state.timing.providerLabel} / ${state.activeModel} 完成 · OCR ${formatMs(state.timing.ocrMs)} · 总耗时 ${formatMs(state.timing.totalElapsedMs)} · ${state.timing.modelRequestCount} 次请求${fallbackNote}${tokenNote}`,
    );
    $("#total-time").textContent = formatMs(state.timing.totalElapsedMs);
    toast(
      `识别完成，${state.timing.paperCount} 份试卷，共 ${state.results.length} 道题`,
    );
  } catch (error) {
    state.timing.totalElapsedMs = Math.round(
      performance.now() - state.runStartedAt,
    );
    await saveBenchmark("failed", error.message);
    toast(error.message);
    setPhase("识别失败");
  } finally {
    setBusy(button, false);
    $("#provider-select").disabled = false;
    $("#model-select").disabled = false;
  }
}

function mergeContinuation(results) {
  const merged = [];
  const byKey = new Map();
  for (const item of results) {
    if (item.error) {
      merged.push(item);
      continue;
    }
    const paper = item.paperKey || "未分组试卷";
    let parent = null;
    const reference = item.mergeWithBlockId || item.continuationOf;
    if (reference) {
      parent =
        byKey.get(`${paper}::${reference}`) ||
        byKey.get(`${paper}::q:${reference}`);
    }
    if (parent) {
      parent.question = [parent.question, item.question]
        .filter(Boolean)
        .join("\n");
      parent.studentAnswer = [parent.studentAnswer, item.studentAnswer]
        .filter(Boolean)
        .join("\n");
      parent.notes = [parent.notes, item.notes].filter(Boolean).join("；");
      parent.sourceLabel = `${parent.sourceLabel} + ${item.sourceLabel}`;
      parent.elapsedMs = Math.max(parent.elapsedMs || 0, item.elapsedMs || 0);
      parent.confidence = Math.min(
        parent.confidence || 0,
        item.confidence || 0,
      );
    } else {
      const copy = { ...item, paperKey: paper };
      merged.push(copy);
      const aliases = [
        `${paper}::${copy.blockId}`,
        `${paper}::${copy.id || ""}`,
      ];
      if (copy.questionNumber)
        aliases.push(
          `${paper}::${copy.questionNumber}`,
          `${paper}::q:${copy.questionNumber}`,
        );
      aliases.forEach((alias) => byKey.set(alias, copy));
    }
  }
  return merged;
}

function normalizedQuestionText(value) {
  return String(value || "")
    .replace(/\[截断\]|\[无法辨认\]/g, "")
    .replace(/[\s\d，。！？、；：,.!?;:()[\]{}"“”‘’（）【】_]+/g, "");
}
function hasQuestionOverlap(left, right) {
  const a = normalizedQuestionText(left);
  const b = normalizedQuestionText(right);
  if (a.length < 10 || b.length < 10) return false;
  const tail = a.slice(-Math.min(28, a.length));
  for (let size = Math.min(28, tail.length); size >= 10; size -= 1)
    if (b.includes(tail.slice(-size))) return true;
  return false;
}

function auditResults(results) {
  const issues = new Map();
  const byPaper = new Map();
  results.forEach((item, index) => {
    const flags = [];
    if (item.error) flags.push("识别失败");
    if (item.confidence < 0.65) flags.push("低置信度");
    if (item.reviewRequired && Array.isArray(item.reviewReasons)) {
      item.reviewReasons.forEach((reason) => {
        const label = reason?.message || reason?.code;
        if (label && !flags.includes(label)) flags.push(label);
      });
    }
    const riskText =
      `${item.question || ""} ${item.studentAnswer || ""} ${item.notes || ""}`
        .replace(
          /轻微(?:裁剪|裁切)[^。；\n]*(?:不影响文字辨认|不影响)[^。；\n]*/g,
          "",
        )
        .replace(/无截断|无缺失|不影响文字辨认|没有截断/g, "");
    if (/无法辨认|截断|缺失|不完整|残缺|裁切|裁剪|看不清/.test(riskText))
      flags.push("内容不完整");
    issues.set(index, flags);
    const key = item.paperKey || "未分组试卷";
    if (!byPaper.has(key)) byPaper.set(key, []);
    byPaper.get(key).push({ item, index });
  });
  const paperSummaries = [];
  for (const [paper, entries] of byPaper) {
    const numbered = entries
      .map(
        (entry) => String(entry.item.questionNumber || "").match(/^\d+$/)?.[0],
      )
      .filter(Boolean)
      .map(Number);
    const seen = new Set();
    const duplicate = new Set();
    numbered.forEach((number) => {
      if (seen.has(number)) duplicate.add(number);
      seen.add(number);
    });
    duplicate.forEach((number) =>
      entries
        .filter((entry) => Number(entry.item.questionNumber) === number)
        .forEach((entry) => {
          const flags = issues.get(entry.index) || [];
          if (!flags.includes("题号重复")) flags.push("题号重复");
        }),
    );
    const min = numbered.length > 2 ? Math.min(...numbered) : 0;
    const max = numbered.length > 2 ? Math.max(...numbered) : 0;
    const missing =
      max - min > 1
        ? Array.from(
            { length: max - min + 1 },
            (_, offset) => min + offset,
          ).filter((number) => !seen.has(number))
        : [];
    entries.forEach((entry, index) => {
      const next = entries[index + 1];
      if (next && hasQuestionOverlap(entry.item.question, next.item.question)) {
        const flags = issues.get(entry.index) || [];
        if (!flags.includes("疑似串入相邻题")) flags.push("疑似串入相邻题");
        const nextFlags = issues.get(next.index) || [];
        if (!nextFlags.includes("疑似相邻题重复"))
          nextFlags.push("疑似相邻题重复");
      }
    });
    paperSummaries.push({
      paper,
      duplicate: [...duplicate],
      missing,
      flagged: entries.filter((entry) => (issues.get(entry.index) || []).length)
        .length,
    });
  }
  return { issues, paperSummaries };
}

function autoSizeTextarea(node) {
  node.style.height = "auto";
  node.style.height = `${Math.max(66, node.scrollHeight)}px`;
}

function renderResults() {
  const target = $("#results");
  if (!state.results.length) {
    target.innerHTML =
      '<div class="blank-state compact"><span>⌁</span><b>识别结果会出现在这里</b><small>每道题可直接修改，之后再保存。</small></div>';
    $("#results-summary").textContent = "";
    return;
  }
  const audit = auditResults(state.results);
  const totalFlags = [...audit.issues.values()].filter(
    (flags) => flags.length,
  ).length;
  const reviewRequired = state.results.filter(
    (item) => item.reviewRequired,
  ).length;
  const hasNumberingIssues = audit.paperSummaries.some(
    (summary) => summary.duplicate.length || summary.missing.length,
  );
  $("#results-summary").textContent = totalFlags
    ? `复核提示：${totalFlags} 题（门禁 ${reviewRequired} 题） · ${hasNumberingIssues ? "含重复或缺题，" : "题号连续，"}低置信度或不完整内容已标记`
    : "结构检查通过 · 仍请核对手写内容";
  const paperOrder = new Map();
  state.results.forEach((item) => {
    const key = item.paperKey || "未分组试卷";
    if (!paperOrder.has(key)) paperOrder.set(key, paperOrder.size);
  });
  const displayEntries = state.results
    .map((item, index) => ({ item, index }))
    .sort((left, right) => {
      const leftPaper = left.item.paperKey || "未分组试卷";
      const rightPaper = right.item.paperKey || "未分组试卷";
      const paperDifference =
        paperOrder.get(leftPaper) - paperOrder.get(rightPaper);
      if (paperDifference) return paperDifference;
      const leftNumber = Number(left.item.questionNumber);
      const rightNumber = Number(right.item.questionNumber);
      if (
        Number.isFinite(leftNumber) &&
        Number.isFinite(rightNumber) &&
        leftNumber !== rightNumber
      )
        return leftNumber - rightNumber;
      return left.index - right.index;
    });
  let previousPaper = "";
  const html = [];
  displayEntries.forEach(({ item, index }) => {
    const currentPaper = item.paperKey || "未分组试卷";
    const flags = audit.issues.get(index) || [];
    if (currentPaper !== previousPaper) {
      const paper = audit.paperSummaries.find(
        (summary) => summary.paper === currentPaper,
      );
      const paperNote =
        paper && (paper.duplicate.length || paper.missing.length)
          ? ` · ${paper.duplicate.length ? `重复${paper.duplicate.join("、")}` : ""}${paper.missing.length ? ` 缺${paper.missing.join("、")}` : ""}`
          : "";
      html.push(
        `<div class="paper-divider"><span>试卷</span><strong>${escapeHtml(currentPaper)}</strong><button class="rename-paper" type="button" data-paper="${escapeHtml(currentPaper)}">修改身份</button><small>${escapeHtml(paperNote)}</small></div>`,
      );
      previousPaper = currentPaper;
    }
    const flagHtml = flags.length
      ? `<div class="result-flags">${flags.map((flag) => `<span>${escapeHtml(flag)}</span>`).join("")}</div>`
      : "";
    html.push(
      item.error
        ? `<div class="result-row flagged" data-index="${index}"><div class="result-num">${String(index + 1).padStart(2, "0")}</div><div class="result-error">${escapeHtml(item.error)} <button class="retry-block" data-retry="${index}">重试此块</button></div></div>`
        : `<div class="result-row ${flags.length ? "flagged" : ""}" data-index="${index}"><div class="result-num"><label>题号</label><input data-field="questionNumber" value="${escapeHtml(item.questionNumber)}" aria-label="题号" /></div><div class="result-field"><label>QUESTION / 题目</label><textarea data-field="question">${escapeHtml(item.question)}</textarea>${flagHtml}</div><div class="result-field"><label>STUDENT ANSWER / 考生回答</label><textarea data-field="studentAnswer">${escapeHtml(item.studentAnswer)}</textarea><small class="source-note">${escapeHtml(item.sourceLabel || "")}${item.notes ? ` · ${escapeHtml(item.notes)}` : ""}</small></div><div class="confidence ${item.confidence < 0.65 ? "warn" : ""}"><strong>${Math.round((item.confidence || 0) * 100)}%</strong>${formatMs(item.elapsedMs)}</div></div>`,
    );
  });
  target.innerHTML = html.join("");
  target.querySelectorAll("textarea").forEach(autoSizeTextarea);
  target.querySelectorAll("[data-field]").forEach((node) =>
    node.addEventListener("input", (event) => {
      const row = event.target.closest(".result-row");
      const item = state.results[Number(row.dataset.index)];
      item[event.target.dataset.field] = event.target.value;
      if (event.target.matches("textarea")) autoSizeTextarea(event.target);
    }),
  );
  target
    .querySelectorAll("[data-retry]")
    .forEach((node) =>
      node.addEventListener("click", () =>
        retryBlock(Number(node.dataset.retry), node),
      ),
    );
  target
    .querySelectorAll("[data-paper]")
    .forEach((node) =>
      node.addEventListener("click", () => renamePaper(node.dataset.paper)),
    );
}
function renamePaper(oldKey) {
  const next = prompt("修改试卷身份（例如：符致凯_25）：", oldKey);
  if (!next || next.trim() === oldKey) return;
  const value = next.trim().slice(0, 80);
  state.results.forEach((item) => {
    if ((item.paperKey || "未分组试卷") === oldKey) item.paperKey = value;
  });
  state.blocks.forEach((item) => {
    if ((item.paperKey || "未分组试卷") === oldKey) item.paperKey = value;
  });
  state.layouts.forEach((layout) => {
    if (paperKey(layout) === oldKey) {
      layout.studentKey = value;
      layout.studentLabel = value;
    }
  });
  renderResults();
  toast(`已将试卷身份改为 ${value}`);
}
function escapeHtml(value) {
  return String(value || "").replace(
    /[&<>"']/g,
    (char) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        char
      ],
  );
}

const batchImport = {
  subjects: [],
  batchId: null,
  busy: false,
  pollTimer: null,
};
state.batchImport = batchImport;
function naturalFileCompare(left, right) {
  return left.localeCompare(right, undefined, {
    numeric: true,
    sensitivity: "base",
  });
}
function parseStudentFolder(value) {
  const text = String(value || "").trim();
  const separator = text.lastIndexOf("_");
  if (separator > 0 && /^[A-Za-z0-9-]+$/.test(text.slice(separator + 1)))
    return {
      name: text.slice(0, separator),
      identifier: text.slice(separator + 1),
    };
  return { name: text, identifier: "" };
}
function providerOptions(selected) {
  return state.providers
    .map(
      (provider) =>
        `<option value="${escapeHtml(provider.id)}" ${provider.id === selected ? "selected" : ""}>${escapeHtml(provider.label)}</option>`,
    )
    .join("");
}
function modelOptions(providerId, selected) {
  const provider = state.providers.find((item) => item.id === providerId);
  return (provider?.models || [])
    .map(
      (model) =>
        `<option value="${escapeHtml(model.id)}" ${model.id === selected ? "selected" : ""}>${escapeHtml(model.label)}</option>`,
    )
    .join("");
}
const importStatusLabels = {
  pending: "待确认",
  uploaded: "已上传",
  queued: "排队中",
  processing_layout: "分析版面",
  processing_ocr: "识别中",
  completed: "已完成",
  failed: "处理失败",
  conflict: "重复冲突",
};
function importStatusText(student) {
  const status =
    importStatusLabels[student.status] || student.status || "待确认";
  if (student.status === "completed") {
    const confidence = Number.isFinite(Number(student.averageConfidence))
      ? `${Math.round(Number(student.averageConfidence) * 100)}%`
      : "—";
    return `${status} · ${student.resultCount || 0} 题 · ${confidence}`;
  }
  return status;
}
function updateBatchSummary() {
  const subjects = batchImport.subjects;
  const students = subjects.reduce(
    (sum, subject) => sum + subject.students.length,
    0,
  );
  const files = subjects.reduce(
    (sum, subject) =>
      sum +
      subject.students.reduce(
        (count, student) => count + student.pages.length,
        0,
      ),
    0,
  );
  const warnings = subjects.reduce(
    (sum, subject) =>
      sum +
      subject.students.filter(
        (student) =>
          student.pages.length < 2 ||
          student.pages.length > 3 ||
          !student.identifier,
      ).length,
    0,
  );
  $("#batch-summary").innerHTML = subjects.length
    ? `<span><strong>${subjects.length}</strong> 科目</span><span><strong>${students}</strong> 名学生</span><span><strong>${files}</strong> 张图片</span><span class="${warnings ? "warn" : "ok"}"><strong>${warnings}</strong> 项待复核</span>`
    : "<span>还没有读取总目录</span>";
  $("#order-pages").disabled = !subjects.length || batchImport.busy;
  $("#upload-batch").disabled = !subjects.length || batchImport.busy;
}
function renderBatchSubjects() {
  const target = $("#batch-subjects");
  if (!batchImport.subjects.length) {
    target.innerHTML =
      '<div class="blank-state compact"><span>◇</span><b>选择包含多个科目的总目录</b><small>每名学生可包含 2–3 张试卷图片</small></div>';
    updateBatchSummary();
    return;
  }
  target.innerHTML = batchImport.subjects
    .map(
      (subject) =>
        `<section class="subject-import"><div class="subject-import-head"><div><span class="eyebrow">SUBJECT</span><h4>${escapeHtml(subject.name)}</h4></div><span>${subject.students.length} 名学生 · ${subject.students.reduce((sum, student) => sum + student.pages.length, 0)} 页</span></div><div class="subject-settings"><div class="subject-assets"><label>空白卷（必需）<input type="file" multiple accept=".pdf,image/jpeg,image/png,image/webp" data-template="${subject.id}" /><small>${subject.templateFiles?.length ? `已选 ${subject.templateFiles.length} 个文件` : "未选择"}</small></label><label>答案卷（必需）<input type="file" multiple accept=".pdf,image/jpeg,image/png,image/webp" data-answer="${subject.id}" /><small>${subject.answerFiles?.length ? `已选 ${subject.answerFiles.length} 个文件` : "未选择"}</small></label></div><div class="subject-model"><label>提供者<select data-subject-provider="${subject.id}">${providerOptions(subject.provider)}</select></label><label>模型<select data-subject-model="${subject.id}">${modelOptions(subject.provider, subject.model)}</select></label></div></div><div class="student-import-table"><div class="student-import-row header"><span>学生</span><span>页面</span><span>页序</span><span>结果 / 平均置信度</span><span>状态</span></div>${subject.students.map((student) => `<div class="student-import-row"><strong>${escapeHtml(student.name)}${student.identifier ? ` <small>${escapeHtml(student.identifier)}</small>` : ""}</strong><span>${student.pages.length} 张${student.pages.length < 2 || student.pages.length > 3 ? ' <i class="import-warning">页数</i>' : ""}</span><span class="page-order-list">${student.pages.map((page, pageIndex) => `<span title="${escapeHtml(page.fileName)}">${pageIndex + 1}. ${escapeHtml(page.fileName)} <button type="button" title="向前移动" data-move-page="-1" data-subject="${subject.id}" data-student="${student.id}" data-page="${page.id}" ${pageIndex === 0 || batchImport.busy ? "disabled" : ""}>↑</button><button type="button" title="向后移动" data-move-page="1" data-subject="${subject.id}" data-student="${student.id}" data-page="${page.id}" ${pageIndex === student.pages.length - 1 || batchImport.busy ? "disabled" : ""}>↓</button></span>`).join("")}</span><span>${student.status === "completed" ? `${student.resultCount || 0} 题 / ${Math.round(Number(student.averageConfidence || 0) * 100)}%${student.identityCheck === "mismatch" ? ' <i class="import-warning">身份异常</i>' : ""}` : "—"}</span><span class="import-student-status ${student.status === "failed" || student.status === "conflict" ? "error" : ""}">${escapeHtml(importStatusText(student))}${student.status === "failed" ? ` <button class="retry-import" type="button" data-retry-import="${student.remoteId || ""}">重试</button>` : ""}${student.error ? `<small title="${escapeHtml(student.error)}">${escapeHtml(student.error)}</small>` : ""}</span></div>`).join("")}</div></section>`,
    )
    .join("");
  target.querySelectorAll("[data-answer]").forEach((node) =>
    node.addEventListener("change", (event) => {
      const subject = batchImport.subjects.find(
        (item) => item.id === event.target.dataset.answer,
      );
      subject.answerFiles = [...event.target.files];
      renderBatchSubjects();
    }),
  );
  target.querySelectorAll("[data-template]").forEach((node) =>
    node.addEventListener("change", (event) => {
      const subject = batchImport.subjects.find(
        (item) => item.id === event.target.dataset.template,
      );
      subject.templateFiles = [...event.target.files];
      renderBatchSubjects();
    }),
  );
  target.querySelectorAll("[data-subject-provider]").forEach((node) =>
    node.addEventListener("change", (event) => {
      const subject = batchImport.subjects.find(
        (item) => item.id === event.target.dataset.subjectProvider,
      );
      subject.provider = event.target.value;
      subject.model =
        state.providers.find((item) => item.id === subject.provider)?.models[0]
          ?.id || "";
      renderBatchSubjects();
    }),
  );
  target.querySelectorAll("[data-subject-model]").forEach((node) =>
    node.addEventListener("change", (event) => {
      const subject = batchImport.subjects.find(
        (item) => item.id === event.target.dataset.subjectModel,
      );
      subject.model = event.target.value;
    }),
  );
  target.querySelectorAll("[data-move-page]").forEach((node) =>
    node.addEventListener("click", () => {
      const subject = batchImport.subjects.find(
        (item) => item.id === node.dataset.subject,
      );
      const student = subject?.students.find(
        (item) => item.id === node.dataset.student,
      );
      const index = student?.pages.findIndex(
        (page) => page.id === node.dataset.page,
      );
      const nextIndex = index + Number(node.dataset.movePage);
      if (
        !student ||
        index < 0 ||
        nextIndex < 0 ||
        nextIndex >= student.pages.length
      )
        return;
      [student.pages[index], student.pages[nextIndex]] = [
        student.pages[nextIndex],
        student.pages[index],
      ];
      student.orderStatus = "manual";
      renderBatchSubjects();
    }),
  );
  target
    .querySelectorAll("[data-retry-import]")
    .forEach((node) =>
      node.addEventListener("click", () =>
        retryImportedSubmission(node.dataset.retryImport),
      ),
    );
  updateBatchSummary();
}
function parseBatchDirectory(files) {
  const subjects = new Map();
  [...files]
    .filter((file) => /\.(jpe?g|png|webp)$/i.test(file.name))
    .forEach((file) => {
      const pathParts = String(file.webkitRelativePath || file.name)
        .split(/[\\/]/)
        .filter(Boolean);
      const parts = pathParts.length >= 4 ? pathParts.slice(-3) : pathParts;
      if (parts.length < 3) return;
      const [subjectName, studentFolder, fileName] = parts;
      if (!subjects.has(subjectName))
        subjects.set(subjectName, {
          id: crypto.randomUUID(),
          name: subjectName,
          students: new Map(),
          templateFiles: [],
          answerFiles: [],
          provider: state.activeProvider || state.defaultProvider,
          model: state.activeModel || state.defaultModel,
        });
      const subject = subjects.get(subjectName);
      const identity = parseStudentFolder(studentFolder);
      const studentKey = identity.identifier
        ? `${identity.name}::${identity.identifier}`
        : identity.name;
      if (!subject.students.has(studentKey))
        subject.students.set(studentKey, {
          id: crypto.randomUUID(),
          name: identity.name,
          identifier: identity.identifier,
          pages: [],
          orderStatus: "pending",
          orderConfidence: 0,
          status: "待确认",
        });
      subject.students
        .get(studentKey)
        .pages.push({ id: crypto.randomUUID(), file, fileName });
    });
  batchImport.subjects = [...subjects.values()].map((subject) => ({
    ...subject,
    students: [...subject.students.values()].map((student) => ({
      ...student,
      pages: student.pages.sort((a, b) =>
        naturalFileCompare(a.fileName, b.fileName),
      ),
    })),
  }));
  renderBatchSubjects();
  $("#batch-status").textContent =
    `已读取 ${batchImport.subjects.length} 个科目，请校验目录结构`;
}
function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}
async function orderBatchPages() {
  if (!batchImport.subjects.length) return;
  batchImport.busy = true;
  updateBatchSummary();
  $("#batch-status").textContent = "AI 正在判断各名学生的页序…";
  try {
    const students = batchImport.subjects.flatMap((subject) =>
      subject.students.map((student) => ({ subject, student })),
    );
    let cursor = 0;
    const worker = async () => {
      while (cursor < students.length) {
        const current = students[cursor++];
        if (current.student.pages.length < 2) {
          current.student.orderStatus = "ready";
          current.student.orderConfidence = 1;
          continue;
        }
        try {
          const images = await Promise.all(
            current.student.pages.map(async (page) => ({
              id: page.id,
              fileName: page.fileName,
              dataUrl: await fileToDataUrl(page.file),
            })),
          );
          const response = await fetch("/api/page-order", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              provider: current.subject.provider,
              model: current.subject.model,
              images,
            }),
          });
          const data = await response.json();
          if (!response.ok) throw new Error(data.error);
          const byId = new Map(
            current.student.pages.map((page) => [page.id, page]),
          );
          current.student.pages = data.orderedImageIds
            .map((id) => byId.get(id))
            .filter(Boolean);
          current.student.orderStatus = "ready";
          current.student.orderConfidence = Number(data.confidence || 0);
          current.student.orderWarnings = data.warnings || "";
        } catch (error) {
          current.student.orderStatus = "warning";
          current.student.orderWarnings = error.message;
        }
        renderBatchSubjects();
      }
    };
    await Promise.all(
      Array.from({ length: Math.min(3, students.length) }, worker),
    );
    $("#batch-status").textContent = "AI 页序完成，请检查警告后上传";
  } finally {
    batchImport.busy = false;
    updateBatchSummary();
  }
}
async function uploadBatch() {
  if (!batchImport.subjects.length) return;
  const title = $("#batch-title").value.trim();
  if (!title) return toast("请先填写批次名称");
  const missingAssets = batchImport.subjects.find(
    (subject) => !subject.templateFiles?.length || !subject.answerFiles?.length,
  );
  if (missingAssets)
    return toast(`请为“${missingAssets.name}”选择空白卷和答案卷`);
  batchImport.busy = true;
  updateBatchSummary();
  $("#batch-status").textContent = "正在创建批次…";
  try {
    const createResponse = await fetch("/api/import-batches", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title,
        academicYear: $("#batch-year").value.trim(),
        grade: $("#batch-grade").value.trim(),
        className: $("#batch-class").value.trim(),
        examName: $("#batch-exam").value.trim(),
        defaultProvider: state.activeProvider || $("#provider-select").value,
        defaultModel: state.activeModel || $("#model-select").value,
        subjects: batchImport.subjects.map((subject) => ({
          name: subject.name,
          provider: subject.provider,
          model: subject.model,
        })),
      }),
    });
    const manifest = await createResponse.json();
    if (!createResponse.ok) throw new Error(manifest.error);
    batchImport.batchId = manifest.id;
    const subjectPairs = batchImport.subjects.map((subject, index) => ({
      local: subject,
      remote: manifest.subjects[index],
    }));
    batchImport.subjects.forEach((subject, index) => {
      subject.remoteId = manifest.subjects[index]?.id;
    });
    let cursor = 0;
    const worker = async () => {
      while (cursor < subjectPairs.length) {
        const pair = subjectPairs[cursor++],
          subject = pair.local,
          remote = pair.remote;
        subject.students.forEach((student) => {
          student.status = "上传中";
        });
        renderBatchSubjects();
        if (subject.templateFiles?.length || subject.answerFiles?.length) {
          const assets = new FormData();
          subject.templateFiles?.forEach((file) =>
            assets.append("template", file),
          );
          subject.answerFiles?.forEach((file) =>
            assets.append("answerKey", file),
          );
          const assetResponse = await fetch(
            `/api/import-batches/${manifest.id}/subjects/${remote.id}/assets`,
            { method: "POST", body: assets },
          );
          if (!assetResponse.ok)
            throw new Error((await assetResponse.json()).error);
        }
        for (const student of subject.students) {
          const form = new FormData();
          form.append("studentName", student.name);
          form.append("studentIdentifier", student.identifier);
          form.append(
            "pageOrder",
            JSON.stringify(student.pages.map((page) => page.id)),
          );
          student.pages.forEach((page) =>
            form.append("pages", page.file, page.fileName),
          );
          const response = await fetch(
            `/api/import-batches/${manifest.id}/subjects/${remote.id}/submissions`,
            { method: "POST", body: form },
          );
          const data = await response.json();
          student.status = response.ok
            ? "queued"
            : response.status === 409
              ? "conflict"
              : "failed";
          if (response.ok) student.remoteId = data.submission.id;
          else student.error = data.error;
          renderBatchSubjects();
        }
      }
    };
    await Promise.all(
      Array.from({ length: Math.min(2, subjectPairs.length) }, worker),
    );
    $("#batch-status").textContent = `批次已上传：${manifest.id.slice(0, 8)}`;
    toast("批次上传完成");
    await pollImportBatch();
    if (batchImport.pollTimer) clearInterval(batchImport.pollTimer);
    batchImport.pollTimer = setInterval(pollImportBatch, 2200);
  } catch (error) {
    $("#batch-status").textContent = "上传失败";
    toast(error.message);
  } finally {
    batchImport.busy = false;
    updateBatchSummary();
  }
}
async function pollImportBatch() {
  if (!batchImport.batchId) return;
  try {
    const response = await fetch(`/api/import-batches/${batchImport.batchId}`);
    if (!response.ok) return;
    const manifest = await response.json();
    const subjectsById = new Map(
      manifest.subjects.map((subject) => [subject.id, subject]),
    );
    batchImport.subjects.forEach((subject, index) => {
      const remote = subject.remoteId
        ? subjectsById.get(subject.remoteId)
        : manifest.subjects[index];
      if (!remote) return;
      subject.remoteId = remote.id;
      const submissions = new Map(
        remote.submissions.map((item) => [item.id, item]),
      );
      subject.students.forEach((student) => {
        const remoteSubmission =
          student.remoteId && submissions.get(student.remoteId);
        if (!remoteSubmission) return;
        student.status = remoteSubmission.status;
        student.resultCount = remoteSubmission.resultCount;
        student.averageConfidence = remoteSubmission.averageConfidence;
        student.identityCheck = remoteSubmission.identityCheck;
        student.error = remoteSubmission.error;
        student.warnings = remoteSubmission.warnings;
      });
    });
    const all = batchImport.subjects.flatMap((subject) => subject.students);
    const complete =
      all.length &&
      all.every((student) =>
        ["completed", "failed", "conflict"].includes(student.status),
      );
    $("#batch-status").textContent =
      `批次 ${manifest.id.slice(0, 8)} · ${importStatusLabels[manifest.status] || manifest.status}`;
    renderBatchSubjects();
    if (complete && batchImport.pollTimer) {
      clearInterval(batchImport.pollTimer);
      batchImport.pollTimer = null;
    }
  } catch {
    // The upload result remains visible while a transient polling request fails.
  }
}
async function retryImportedSubmission(submissionId) {
  if (!submissionId || !batchImport.batchId) return;
  const response = await fetch(
    `/api/import-batches/${batchImport.batchId}/submissions/${submissionId}/retry`,
    { method: "POST" },
  );
  const data = await response.json();
  if (!response.ok) return toast(data.error || "重试失败");
  toast("已重新加入处理队列");
  await pollImportBatch();
  if (!batchImport.pollTimer)
    batchImport.pollTimer = setInterval(pollImportBatch, 2200);
}
$("#batch-folder-input")?.addEventListener("change", (event) =>
  parseBatchDirectory(event.target.files),
);
$("#order-pages")?.addEventListener("click", orderBatchPages);
$("#upload-batch")?.addEventListener("click", uploadBatch);

async function saveJob() {
  const title = prompt(
    "给这次识别任务取一个名字：",
    `试卷识别 ${new Date().toLocaleString("zh-CN")}`,
  );
  if (!title) return;
  const response = await fetch("/api/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title,
      pages: state.pages.map((page) => ({
        id: page.id,
        fileName: page.fileName,
      })),
      layouts: state.layouts,
      blocks: state.blocks.map(({ image, ...block }) => block),
      results: state.results,
      timing: state.timing,
    }),
  });
  const data = await response.json();
  if (!response.ok) return toast(data.error || "保存失败");
  state.jobId = data.id;
  $("#export-json").disabled = false;
  $("#export-md").disabled = false;
  loadHistory();
  toast("任务已保存");
}
function exportJob(format) {
  if (!state.jobId) return;
  window.open(`/api/jobs/${state.jobId}/export?format=${format}`, "_blank");
}
async function retryBlock(index, button) {
  const failed = state.results[index];
  const block = state.blocks.find((item) => item.id === failed.blockId);
  if (!block?.image) return toast("历史任务没有保留裁块图片，请重新导入原图");
  const model = state.timing.model || block.model || state.defaultModel;
  const provider =
    state.timing.provider || block.provider || state.defaultProvider;
  button.disabled = true;
  button.textContent = "重试中…";
  try {
    const response = await fetch("/api/recognize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        provider,
        model,
        blocks: [{ ...block, provider, model }],
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error);
    state.results[index] = data.results[0];
    state.timing.ocrMs += data.elapsedMs || 0;
    state.timing.totalElapsedMs += data.elapsedMs || 0;
    renderResults();
    toast("该题已重新识别");
  } catch (error) {
    button.disabled = false;
    button.textContent = "重试此块";
    toast(error.message);
  }
}
async function loadJob(id) {
  try {
    const job = await (await fetch(`/api/jobs/${id}`)).json();
    if (job.error) throw new Error(job.error);
    state.jobId = job.id;
    state.results = job.results || [];
    state.timing = job.timing || {};
    state.layouts = [];
    state.blocks = job.blocks || [];
    $("#layout-summary").textContent =
      `${state.blocks.length || 0} 个已保存题块 · 原图未随任务保存`;
    $("#layout-grid").innerHTML =
      '<div class="blank-state compact history-layout-note"><span>↗</span><b>历史 OCR 已加载</b><small>当前任务只保存了版面元数据和识别结果，原图未写入任务文件。若要重新裁切或重试，请重新导入原图。</small></div>';
    renderResults();
    $("#total-time").textContent = formatMs(state.timing.totalElapsedMs);
    const batchNote = state.timing.modelRequestCount
      ? ` · ${state.timing.modelRequestCount} 次模型请求`
      : "";
    setPhase(
      `已打开历史任务 · ${state.results.length} 题 · OCR ${formatMs(state.timing.ocrMs)}${batchNote}`,
    );
    $("#save").disabled = false;
    $("#export-json").disabled = false;
    $("#export-md").disabled = false;
    toast(job.title || "历史任务已打开");
  } catch (error) {
    toast(error.message);
  }
}
async function loadHistory() {
  try {
    const data = await (await fetch("/api/jobs")).json();
    $("#history-list").innerHTML = data.length
      ? data
          .slice(0, 6)
          .map(
            (item) =>
              `<button class="history-item" data-id="${item.id}"><span>${escapeHtml(item.title || "未命名任务").slice(0, 24)}</span><span>${escapeHtml(item.provider || "")} / ${escapeHtml(item.model || "")} · ${item.resultCount}题</span></button>`,
          )
          .join("")
      : "<span>暂无已保存任务</span>";
    $("#history-list")
      .querySelectorAll("[data-id]")
      .forEach((node) =>
        node.addEventListener("click", () => loadJob(node.dataset.id)),
      );
  } catch {
    $("#history-list").textContent = "历史任务不可用";
  }
}

fileInput.addEventListener("change", (event) =>
  acceptFiles(event.target.files),
);
const dropzone = $("#dropzone");
["dragenter", "dragover"].forEach((name) =>
  dropzone.addEventListener(name, (event) => {
    event.preventDefault();
    dropzone.classList.add("drag");
  }),
);
["dragleave", "drop"].forEach((name) =>
  dropzone.addEventListener(name, (event) => {
    event.preventDefault();
    dropzone.classList.remove("drag");
  }),
);
dropzone.addEventListener("drop", (event) =>
  acceptFiles(event.dataTransfer.files),
);
$("#analyze").addEventListener("click", analyze);
$("#recognize").addEventListener("click", recognize);
$("#save").addEventListener("click", saveJob);
$("#export-json").addEventListener("click", () => exportJob("json"));
$("#export-md").addEventListener("click", () => exportJob("markdown"));
function populateModelSelect(preferredModel = "") {
  const provider = state.providers.find(
    (item) => item.id === $("#provider-select").value,
  );
  state.models = provider?.models || [];
  const select = $("#model-select");
  select.innerHTML = state.models
    .map(
      (model) =>
        `<option value="${escapeHtml(model.id)}">${escapeHtml(model.label)}</option>`,
    )
    .join("");
  select.value = state.models.some((model) => model.id === preferredModel)
    ? preferredModel
    : state.models[0]?.id || "";
  select.disabled = !state.models.length;
}
function invalidateModelRun(message) {
  if (!state.layouts.length) return;
  state.activeProvider = "";
  state.activeModel = "";
  state.benchmarkId = null;
  state.layouts = [];
  state.blocks = [];
  state.results = [];
  state.timing = {};
  renderLayout();
  renderResults();
  $("#recognize").disabled = true;
  $("#save").disabled = true;
  setPhase(message);
}
$("#provider-select").addEventListener("change", () => {
  populateModelSelect();
  invalidateModelRun("已切换提供者，请重新分析版面");
});
$("#model-select").addEventListener("change", () => {
  if (
    state.activeProvider === $("#provider-select").value &&
    state.activeModel === $("#model-select").value
  )
    return;
  invalidateModelRun("已切换模型，请重新分析版面");
});
$("#clear-benchmarks").addEventListener("click", async () => {
  if (!confirm("确定清空所有模型耗时记录？")) return;
  const response = await fetch("/api/benchmarks", { method: "DELETE" });
  if (!response.ok) return toast("清空失败");
  state.benchmarks = [];
  renderBenchmarks();
  toast("已清空对比记录");
});
document.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key === "1") analyze();
  if ((event.metaKey || event.ctrlKey) && event.key === "2") recognize();
});
(async function init() {
  try {
    const health = await (await fetch("/api/health")).json();
    state.ocrConcurrency = Number(health.ocrConcurrency || 0);
    state.ocrBatchSize = Number(health.ocrBlocksPerRequest || 1);
    state.providers = health.availableProviders || [];
    state.defaultProvider = health.defaultProvider || health.provider;
    state.defaultModel = health.defaultModel || health.model;
    const providerSelect = $("#provider-select");
    providerSelect.innerHTML = state.providers
      .map(
        (provider) =>
          `<option value="${escapeHtml(provider.id)}">${escapeHtml(provider.label)}</option>`,
      )
      .join("");
    providerSelect.value = state.defaultProvider;
    providerSelect.disabled = !state.providers.length;
    populateModelSelect(state.defaultModel);
    const modelCount = state.providers.reduce(
      (sum, provider) => sum + provider.models.length,
      0,
    );
    $("#health").classList.toggle("ok", health.hasKey);
    $("#health span").textContent = health.hasKey
      ? `${state.providers.length} 家提供者 · ${modelCount} 个模型组合 · ${state.ocrConcurrency} 路并发`
      : "待配置 API Key";
    $("#model-label").textContent =
      `${state.defaultProvider} / ${state.defaultModel} / ${health.hasKey ? `READY · ${state.ocrConcurrency}x · BATCH ${state.ocrBatchSize}` : "NO KEY"}`;
  } catch {
    $("#health span").textContent = "服务未启动";
  }
  loadHistory();
  loadBenchmarks();
})();
