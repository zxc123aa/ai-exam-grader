import fs from 'fs/promises';
import path from 'path';
import { createRequire } from 'module';

const require = createRequire(new URL('../源码/package.json', import.meta.url));
const sharp = require('sharp');

const api = process.env.EXAM_API || 'http://127.0.0.1:3417';
const root = new URL('../', import.meta.url);
const defaultRaw = new URL('../outputs/ocr-ground-truth/physics-2021-2022-b/reference-node-run/raw_response.json', root);
const defaultOut = new URL('../outputs/ocr-ground-truth/physics-2021-2022-b/evidence-pressure-test/', root);
const defaultAnswerGold = new URL('../data/golden/physics-2021-2022-b/student_answer_keypoints_gold.json', root);
const defaultAnswerTextGold = new URL('../data/golden/physics-2021-2022-b/student_answer_text_gold.json', root);

function argValue(name, fallback = '') {
  const prefix = `--${name}=`;
  const hit = process.argv.find(item => item.startsWith(prefix));
  return hit ? hit.slice(prefix.length) : fallback;
}

function dataUrlToBuffer(value) {
  const text = String(value || '');
  const comma = text.indexOf(',');
  return Buffer.from(comma >= 0 ? text.slice(comma + 1) : text, 'base64');
}

function imageDataUrl(buffer, type = 'image/jpeg') {
  return `data:${type};base64,${buffer.toString('base64')}`;
}

function normalizedToPixels(bounds, width, height) {
  const xmin = Math.max(0, Math.min(1000, Number(bounds.xmin ?? 0)));
  const ymin = Math.max(0, Math.min(1000, Number(bounds.ymin ?? 0)));
  const xmax = Math.max(xmin + 1, Math.min(1000, Number(bounds.xmax ?? 1000)));
  const ymax = Math.max(ymin + 1, Math.min(1000, Number(bounds.ymax ?? 1000)));
  const left = Math.max(0, Math.floor(xmin / 1000 * width));
  const top = Math.max(0, Math.floor(ymin / 1000 * height));
  const right = Math.min(width, Math.ceil(xmax / 1000 * width));
  const bottom = Math.min(height, Math.ceil(ymax / 1000 * height));
  return {
    left,
    top,
    width: Math.max(1, right - left),
    height: Math.max(1, bottom - top)
  };
}

async function post(route, body) {
  const response = await fetch(`${api}${route}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  const text = await response.text();
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    data = { error: text };
  }
  if (!response.ok) {
    const error = new Error(data.error || `${route} failed with HTTP ${response.status}`);
    error.data = data;
    throw error;
  }
  return data;
}

function addTokenUsage(...values) {
  return values.reduce((total, value) => ({
    inputTokens: total.inputTokens + Number(value?.inputTokens || value?.promptTokens || 0),
    outputTokens: total.outputTokens + Number(value?.outputTokens || value?.completionTokens || 0),
    totalTokens: total.totalTokens + Number(value?.totalTokens || 0)
  }), { inputTokens: 0, outputTokens: 0, totalTokens: 0 });
}

async function recognizeInChunks(blocks, verificationMode, chunkSize) {
  const responses = [];
  const started = performance.now();
  for (let index = 0; index < blocks.length; index += chunkSize) {
    responses.push(await post('/api/recognize', {
      blocks: blocks.slice(index, index + chunkSize),
      verificationMode
    }));
  }
  return {
    results: responses.flatMap(response => response.results || []),
    verificationMode,
    elapsedMs: responses.reduce((sum, response) => sum + Number(response.elapsedMs || 0), 0),
    wallElapsedMs: Math.round(performance.now() - started),
    ocrModelCriticalPathMs: Math.max(0, ...responses.map(response => Number(response.ocrModelCriticalPathMs || 0))),
    answerVerificationWorkMs: responses.reduce((sum, response) => sum + Number(response.answerVerificationWorkMs || 0), 0),
    answerVerificationCriticalPathMs: Math.max(0, ...responses.map(response => Number(response.answerVerificationCriticalPathMs || 0))),
    concurrency: Math.max(0, ...responses.map(response => Number(response.concurrency || 0))),
    blocksPerRequest: Math.max(0, ...responses.map(response => Number(response.blocksPerRequest || 0))),
    completedCount: responses.reduce((sum, response) => sum + Number(response.completedCount || 0), 0),
    rawResultCount: responses.reduce((sum, response) => sum + Number(response.rawResultCount || 0), 0),
    mergedContinuationCount: responses.reduce((sum, response) => sum + Number(response.mergedContinuationCount || 0), 0),
    batchCount: responses.reduce((sum, response) => sum + Number(response.batchCount || 0), 0),
    modelRequestCount: responses.reduce((sum, response) => sum + Number(response.modelRequestCount || 0), 0),
    fallbackBatchCount: responses.reduce((sum, response) => sum + Number(response.fallbackBatchCount || 0), 0),
    tokenUsage: addTokenUsage(...responses.map(response => response.tokenUsage)),
    tokenUsageRecorded: responses.some(response => response.tokenUsageRecorded),
    estimatedCostUsd: responses.reduce((sum, response) => sum + Number(response.estimatedCostUsd || 0), 0),
    requestChunkCount: responses.length,
    requestChunkSize: chunkSize
  };
}

function oneLine(value, limit = 220) {
  return String(value || '')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, limit);
}

function normalizeForKeypoint(value) {
  return String(value || '')
    .normalize('NFKC')
    .toLowerCase()
    .replace(/[（(]\s*\d+\s*[）)]/g, '')
    .replace(/^(?:解|答)\s*[:：]?/g, '')
    .replace(/[０-９]/g, char => String.fromCharCode(char.charCodeAt(0) - 0xfee0))
    .replace(/[ａ-ｚＡ-Ｚ]/g, char => String.fromCharCode(char.charCodeAt(0) - 0xfee0))
    .replace(/[×＊]/g, 'x')
    .replace(/\^([+-]?\d+)/g, '$1')
    .replace(/[²]/g, '2')
    .replace(/[³]/g, '3')
    .replace(/[⁴]/g, '4')
    .replace(/[，。；：、,.，\s_\\{}()[\]（）]/g, '')
    .trim();
}

function percent(numerator, denominator) {
  if (!denominator) return null;
  return Number((numerator / denominator * 100).toFixed(2));
}

function levenshteinDistance(left, right) {
  const a = [...String(left || '')];
  const b = [...String(right || '')];
  let previous = Array.from({ length: b.length + 1 }, (_, index) => index);
  for (let i = 1; i <= a.length; i += 1) {
    const current = [i];
    for (let j = 1; j <= b.length; j += 1) {
      current[j] = Math.min(
        current[j - 1] + 1,
        previous[j] + 1,
        previous[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1)
      );
    }
    previous = current;
  }
  return previous[b.length];
}

function regexEscape(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function forbiddenMentionIsNegated(answer, forbidden) {
  const raw = String(answer || '');
  const variants = [
    String(forbidden || ''),
    String(forbidden || '').replace(/x/gi, '×'),
    String(forbidden || '').replace(/x/gi, '*'),
    String(forbidden || '').replace(/10³/g, '10\\^3'),
    String(forbidden || '').replace(/10³/g, '10的3次方')
  ].filter(Boolean);
  for (const variant of variants) {
    const pattern = new RegExp(regexEscape(variant).replace(/\\x|×|\\\*/gi, '[x×＊*]'), 'i');
    const match = raw.match(pattern);
    if (!match || match.index == null) continue;
    const context = raw.slice(Math.max(0, match.index - 24), Math.min(raw.length, match.index + match[0].length + 24));
    if (/划掉|划去|划掉改写|划去改写|改写|修改为|原写|被划|涂改/.test(context)) return true;
  }
  return false;
}

async function loadJsonIfExists(filePath) {
  if (!filePath) return null;
  try {
    return JSON.parse(await fs.readFile(filePath, 'utf8'));
  } catch (error) {
    if (error.code === 'ENOENT') return null;
    throw error;
  }
}

function pickResult(response, questionNumber) {
  return (response.results || []).find(item => String(item.questionNumber) === String(questionNumber)) ||
    (response.results || []).find(item => String(item.blockId || item.id || '').includes(`q${questionNumber}`)) ||
    null;
}

function markdownTable(rows) {
  const header = [
    '题号',
    '关键点准确率',
    '答案栏字符准确率',
    'fast答案摘要',
    'evidence答案摘要',
    '核验状态',
    '可批改',
    '置信度',
    '风险'
  ];
  const lines = [
    `| ${header.join(' | ')} |`,
    `| ${header.map(() => '---').join(' | ')} |`
  ];
  for (const row of rows) {
    lines.push(`| ${[
      row.questionNumber,
      row.answerKeypointAccuracy == null ? '未评估' : `${row.requiredMatchedCount}/${row.requiredCount} (${row.answerKeypointAccuracy}%)`,
      row.answerCharAccuracy == null ? '未评估' : `${row.answerCharAccuracy}%`,
      row.fastAnswer,
      row.evidenceAnswer,
      row.verificationStatus,
      row.gradingEligible,
      row.confidence,
      row.risk
    ].map(cell => String(cell ?? '').replace(/\|/g, '/')).join(' | ')} |`);
  }
  return lines.join('\n');
}

const rawPath = argValue('raw', defaultRaw.pathname);
const outDir = argValue('out', defaultOut.pathname);
const answerGoldPath = argValue('answer-gold', defaultAnswerGold.pathname);
const answerTextGoldPath = argValue('answer-text-gold', defaultAnswerTextGold.pathname);
const reuseResponses = argValue('reuse', 'false') === 'true';
const requestChunkSize = Math.max(1, Number(argValue('request-chunk-size', '6')) || 6);
const comparisonVerificationMode = ['evidence', 'selective'].includes(argValue('verification-mode', 'evidence'))
  ? argValue('verification-mode', 'evidence')
  : 'evidence';
const requestedQuestions = argValue('questions', '17,18,19,20,21,22')
  .split(',')
  .map(item => item.trim())
  .filter(Boolean);

await fs.mkdir(outDir, { recursive: true });

const raw = JSON.parse(await fs.readFile(rawPath, 'utf8'));
const answerGold = await loadJsonIfExists(answerGoldPath);
const answerTextGold = await loadJsonIfExists(answerTextGoldPath);
const layoutsByPage = new Map((raw.layouts || []).map(layout => [String(layout.pageId), layout]));
const blocks = [];

for (const questionNumber of requestedQuestions) {
  const source = (raw.blocks || []).find(block => String(block.questionNumber) === String(questionNumber));
  if (!source) {
    console.warn(`skip Q${questionNumber}: block not found`);
    continue;
  }
  const layout = layoutsByPage.get(String(source.pageId));
  if (!layout?.uprightImage) {
    console.warn(`skip Q${questionNumber}: uprightImage not found`);
    continue;
  }
  const pageBuffer = dataUrlToBuffer(layout.uprightImage);
  const metadata = await sharp(pageBuffer).metadata();
  const cropBounds = source.cropBounds || source;
  const crop = await sharp(pageBuffer)
    .extract(normalizedToPixels(cropBounds, metadata.width || 1, metadata.height || 1))
    .jpeg({ quality: 92 })
    .toBuffer();
  await fs.writeFile(path.join(outDir, `q${questionNumber}_block.jpg`), crop);
  const pageRegions = layout.regions || [];
  const regionIndex = pageRegions.findIndex(region => String(region.questionNumber) === String(questionNumber) || String(region.id) === String(source.id).split('_').at(-1));
  blocks.push({
    ...source,
    pageId: source.pageId,
    fileName: source.fileName || layout.fileName,
    paperKey: layout.studentKey || layout.studentLabel || '',
    cropBounds,
    image: imageDataUrl(crop),
    _pageImage: layout.uprightImage,
    _nextRegionYmin: Number(pageRegions[regionIndex + 1]?.ymin ?? 1000)
  });
}

if (!blocks.length) throw new Error('No test blocks were built.');

await fs.writeFile(path.join(outDir, 'request_blocks.json'), JSON.stringify(
  blocks.map(({ image, _pageImage, ...block }) => ({ ...block, image: '[image]', _pageImage: '[page]' })),
  null,
  2
), 'utf8');

const started = performance.now();
let fastResponse;
let evidenceResponse;
if (reuseResponses) {
  fastResponse = await loadJsonIfExists(path.join(outDir, 'fast_response.json'));
  evidenceResponse = await loadJsonIfExists(path.join(outDir, 'evidence_response.json'));
  if (!fastResponse || !evidenceResponse) throw new Error('--reuse=true requires existing fast_response.json and evidence_response.json');
} else {
  const fastStarted = performance.now();
  try {
    fastResponse = await recognizeInChunks(blocks, 'fast', requestChunkSize);
  } catch (error) {
    fastResponse = { error: error.message, results: [] };
  }
  fastResponse.wallElapsedMs ??= Math.round(performance.now() - fastStarted);

  const evidenceStarted = performance.now();
  try {
    evidenceResponse = await recognizeInChunks(blocks, comparisonVerificationMode, requestChunkSize);
  } catch (error) {
    evidenceResponse = { error: error.message, results: [] };
  }
  evidenceResponse.wallElapsedMs ??= Math.round(performance.now() - evidenceStarted);

  await fs.writeFile(path.join(outDir, 'fast_response.json'), JSON.stringify(fastResponse, null, 2), 'utf8');
  await fs.writeFile(path.join(outDir, 'evidence_response.json'), JSON.stringify(evidenceResponse, null, 2), 'utf8');
}

const rows = blocks.map(block => {
  const q = String(block.questionNumber);
  const fast = pickResult(fastResponse, q);
  const evidence = pickResult(evidenceResponse, q);
  const verificationStatus = evidence?.answerVerification?.status || evidence?.answerStructure?.verificationStatus || evidence?.error || evidenceResponse.error || '';
  const gradingEligible = Boolean(evidence?.gradingEligible);
  const confidence = Number(evidence?.confidence ?? 0).toFixed(2);
  const risk = [
    evidence?.answerVerification?.status === 'evidence_disagreement' ? '双视图冲突已阻断' : '',
    evidence?.answerVerification?.status === 'failed' ? '核验失败' : '',
    evidence?.answerVerification?.status === 'evidence_consensus' && !evidence?.answerVerification?.regions?.length ? '无区域证据' : '',
    evidence?.notes || ''
  ].filter(Boolean).join('；');
  const gold = answerGold?.questions?.[q] || null;
  const answerTextForAccuracy = String(evidence?.studentAnswer || evidence?.answerVerification?.candidateStudentAnswer || '');
  const normalizedAnswer = normalizeForKeypoint(answerTextForAccuracy);
  const required = Array.isArray(gold?.required) ? gold.required : [];
  const forbidden = Array.isArray(gold?.forbidden) ? gold.forbidden : [];
  const matchedRequired = required.filter(item => normalizedAnswer.includes(normalizeForKeypoint(item)));
  const forbiddenHits = forbidden.filter(item => (
    normalizedAnswer.includes(normalizeForKeypoint(item)) &&
    !forbiddenMentionIsNegated(answerTextForAccuracy, item)
  ));
  const negatedForbiddenMentions = forbidden.filter(item => (
    normalizedAnswer.includes(normalizeForKeypoint(item)) &&
    forbiddenMentionIsNegated(answerTextForAccuracy, item)
  ));
  const requiredCount = required.length;
  const requiredMatchedCount = matchedRequired.length;
  const answerKeypointAccuracy = requiredCount ? percent(requiredMatchedCount, requiredCount) : null;
  const keypointPassed = requiredCount ? requiredMatchedCount === requiredCount && forbiddenHits.length === 0 : null;
  const textGold = answerTextGold?.questions?.[q] || null;
  const charGoldScorable = ['gold_verified', 'gold_model_assisted'].includes(String(textGold?.status || ''));
  const charGoldText = charGoldScorable && typeof textGold?.text === 'string' && textGold.text.trim()
    ? textGold.text
    : null;
  const charPredictionText = String(evidence?.gradingAnswer || evidence?.studentAnswer || evidence?.answerVerification?.candidateStudentAnswer || '');
  const normalizedCharGold = charGoldText ? normalizeForKeypoint(charGoldText) : '';
  const normalizedCharPrediction = charGoldText ? normalizeForKeypoint(charPredictionText) : '';
  const charEditDistance = charGoldText ? levenshteinDistance(normalizedCharGold, normalizedCharPrediction) : null;
  const charDenominator = charGoldText ? Math.max(normalizedCharGold.length, normalizedCharPrediction.length, 1) : null;
  const answerCharAccuracy = charGoldText
    ? Number((Math.max(0, 1 - charEditDistance / charDenominator) * 100).toFixed(2))
    : null;
  return {
    questionNumber: q,
    blockId: block.id,
    requiredCount,
    requiredMatchedCount,
    answerKeypointAccuracy,
    keypointPassed,
    forbiddenHits,
    negatedForbiddenMentions,
    answerCharAccuracy,
    charEditDistance,
    charDenominator,
    charGoldStatus: textGold?.status || null,
    fastAnswer: oneLine(fast?.studentAnswer),
    evidenceAnswer: oneLine(evidence?.studentAnswer),
    verificationStatus,
    gradingEligible,
    confidence,
    risk: oneLine(risk, 180),
    fast,
    evidence
  };
});

const evaluatedRows = rows.filter(row => row.requiredCount > 0);
const totalRequired = evaluatedRows.reduce((sum, row) => sum + row.requiredCount, 0);
const totalMatched = evaluatedRows.reduce((sum, row) => sum + row.requiredMatchedCount, 0);
const passedQuestions = evaluatedRows.filter(row => row.keypointPassed === true).length;
const forbiddenViolationRows = evaluatedRows.filter(row => row.forbiddenHits.length > 0);
const eligibleRows = evaluatedRows.filter(row => row.gradingEligible);
const eligibleCorrectRows = eligibleRows.filter(row => row.keypointPassed === true);
const charEvaluatedRows = rows.filter(row => row.charDenominator > 0);
const totalCharEditDistance = charEvaluatedRows.reduce((sum, row) => sum + row.charEditDistance, 0);
const totalCharDenominator = charEvaluatedRows.reduce((sum, row) => sum + row.charDenominator, 0);
const accuracy = {
  answerGoldPath: answerGold ? answerGoldPath : null,
  answerTextGoldPath: answerTextGold ? answerTextGoldPath : null,
  evaluatedQuestionCount: evaluatedRows.length,
  answerKeypointAccuracy: percent(totalMatched, totalRequired),
  matchedKeypoints: totalMatched,
  totalKeypoints: totalRequired,
  questionKeypointPassRate: percent(passedQuestions, evaluatedRows.length),
  passedQuestions,
  forbiddenViolationCount: forbiddenViolationRows.length,
  forbiddenAutoGradingEscapeCount: forbiddenViolationRows.filter(row => row.gradingEligible).length,
  gradingEligibleCount: eligibleRows.length,
  autoEligiblePrecision: percent(eligibleCorrectRows.length, eligibleRows.length),
  answerCharAccuracy: totalCharDenominator
    ? Number((Math.max(0, 1 - totalCharEditDistance / totalCharDenominator) * 100).toFixed(2))
    : null,
  charEvaluatedQuestionCount: charEvaluatedRows.length,
  charEditDistance: totalCharEditDistance,
  charDenominator: totalCharDenominator,
  evidenceConsensusCount: rows.filter(row => row.verificationStatus === 'evidence_consensus').length,
  evidenceDisagreementCount: rows.filter(row => row.verificationStatus === 'evidence_disagreement').length
};

const summary = {
  generatedAt: new Date().toISOString(),
  api,
  comparisonVerificationMode,
  rawPath,
  outDir,
  questions: blocks.map(block => String(block.questionNumber)),
  elapsedMs: Math.round(performance.now() - started),
  fast: {
    error: fastResponse.error || null,
    wallElapsedMs: fastResponse.wallElapsedMs,
    elapsedMs: fastResponse.elapsedMs ?? null,
    batchCount: fastResponse.batchCount ?? null,
    modelRequestCount: fastResponse.modelRequestCount ?? null,
    fallbackBatchCount: fastResponse.fallbackBatchCount ?? null
  },
  evidence: {
    error: evidenceResponse.error || null,
    wallElapsedMs: evidenceResponse.wallElapsedMs,
    elapsedMs: evidenceResponse.elapsedMs ?? null,
    batchCount: evidenceResponse.batchCount ?? null,
    modelRequestCount: evidenceResponse.modelRequestCount ?? null,
    fallbackBatchCount: evidenceResponse.fallbackBatchCount ?? null,
    answerVerificationWorkMs: evidenceResponse.answerVerificationWorkMs ?? null,
    answerVerificationCriticalPathMs: evidenceResponse.answerVerificationCriticalPathMs ?? null
  },
  accuracy,
  rows: rows.map(({ fast, evidence, ...row }) => row)
};

await fs.writeFile(path.join(outDir, 'summary.json'), JSON.stringify(summary, null, 2), 'utf8');
await fs.writeFile(path.join(outDir, 'summary.md'), [
  '# Evidence pressure test',
  '',
  `- API: ${api}`,
  `- Questions: ${summary.questions.join(', ')}`,
  `- Total wall time: ${summary.elapsedMs} ms`,
  `- Fast: ${JSON.stringify(summary.fast)}`,
  `- Evidence: ${JSON.stringify(summary.evidence)}`,
  `- Accuracy: ${JSON.stringify(summary.accuracy)}`,
  '',
  markdownTable(summary.rows),
  ''
].join('\n'), 'utf8');

console.log(JSON.stringify(summary, null, 2));
