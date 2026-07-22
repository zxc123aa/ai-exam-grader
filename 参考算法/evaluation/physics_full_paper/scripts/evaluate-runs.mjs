import fs from 'fs/promises';
import path from 'path';
import {
  EVALUATION_DIR,
  characterAccuracy,
  extractCriticalTokens,
  indexResults,
  inferAnswerSlots,
  listJsonInputs,
  loadManifest,
  median,
  normalizeText,
  readJson,
  resolveFromEvaluation,
  round,
  tokenScores,
  writeJson
} from './lib.mjs';

function parseArgs(argv) {
  const output = { baseline: [], candidate: [], out: path.join(EVALUATION_DIR, 'reports', 'latest'), ignoreStudentKey: false };
  for (let index = 0; index < argv.length; index += 1) {
    const key = argv[index];
    const value = argv[index + 1];
    if (key === '--ignore-student-key') {
      output.ignoreStudentKey = true;
      continue;
    }
    if (key === '--baseline') output.baseline.push(...value.split(',').filter(Boolean));
    if (key === '--candidate') output.candidate.push(...value.split(',').filter(Boolean));
    if (key === '--gold') output.gold = value;
    if (key === '--out') output.out = value;
    if (key.startsWith('--')) index += 1;
  }
  return output;
}

function slotAccuracy(actual, expected) {
  if (!expected.length && !actual.length) return 1;
  if (!expected.length || !actual.length) return 0;
  const compared = Math.max(actual.length, expected.length);
  let total = 0;
  for (let index = 0; index < compared; index += 1) {
    total += characterAccuracy(actual[index] || '', expected[index] || '');
  }
  return total / compared;
}

function contaminationScore(result, gold) {
  const answerSegments = String(result?.studentAnswer ?? result?.student_answer ?? '')
    .split(/[\n;；]+/)
    .map(value => normalizeText(value).replace(/^\(?\d+\)?/, ''))
    .filter(value => value.length >= 3);
  const question = normalizeText(result?.question || '');
  const goldAnswer = normalizeText(gold.student_answer || '');
  if (!answerSegments.length) return 0;
  const contaminated = answerSegments.filter(value => question.includes(value) && !goldAnswer.includes(value));
  return contaminated.length / answerSegments.length;
}

function weightedTextAccuracy(questionAccuracy, answerAccuracy, expectedQuestion, expectedAnswer) {
  const questionLength = [...normalizeText(expectedQuestion)].length;
  const answerLength = [...normalizeText(expectedAnswer)].length;
  const total = questionLength + answerLength;
  if (!total) return 1;
  return (questionAccuracy * questionLength + answerAccuracy * answerLength) / total;
}

function evaluateQuestion(result, gold) {
  if (!result) {
    return {
      present: false,
      block_completeness: 0,
      question_accuracy: 0,
      answer_accuracy: 0,
      text_accuracy: 0,
      text_cer: 1,
      critical_token_precision: 0,
      critical_token_recall: 0,
      critical_token_f1: 0,
      answer_slot_accuracy: 0,
      printed_text_contamination: 0,
      severe_error: true,
      severe_reasons: ['missing_question_block'],
      score: 0,
      confidence: null
    };
  }
  const actualQuestion = String(result.question || '');
  const actualAnswer = String(result.studentAnswer ?? result.student_answer ?? '');
  const expectedQuestion = String(gold.question || '');
  const expectedAnswer = String(gold.student_answer || '');
  const questionAccuracy = characterAccuracy(actualQuestion, expectedQuestion);
  const answerAccuracy = characterAccuracy(actualAnswer, expectedAnswer);
  const textAccuracy = weightedTextAccuracy(questionAccuracy, answerAccuracy, expectedQuestion, expectedAnswer);
  const questionPresent = Boolean(normalizeText(actualQuestion));
  const answerPresent = !normalizeText(expectedAnswer) || Boolean(normalizeText(actualAnswer));
  const noUnreadable = !/\[无法辨认\]|无法辨认/.test(`${actualQuestion}${actualAnswer}`);
  const blockCompleteness = (Number(questionPresent) + Number(answerPresent) + Number(noUnreadable)) / 3;
  const actualTokens = extractCriticalTokens(`${actualQuestion}\n${actualAnswer}`);
  const expectedTokens = extractCriticalTokens(`${expectedQuestion}\n${expectedAnswer}`);
  const critical = tokenScores(actualTokens, expectedTokens);
  const answerCritical = tokenScores(extractCriticalTokens(actualAnswer), extractCriticalTokens(expectedAnswer));
  const slots = slotAccuracy(inferAnswerSlots(result), gold.answer_slots || []);
  const contamination = contaminationScore(result, gold);
  const severeReasons = [];
  if (!questionPresent) severeReasons.push('missing_question_text');
  if (!answerPresent) severeReasons.push('missing_student_answer');
  if (answerCritical.extra.length && answerCritical.precision < 0.75) {
    severeReasons.push(`unsupported_answer_tokens:${answerCritical.extra.join('|')}`);
  }
  if (result.answerVerification?.status === 'evidence_disagreement' && result.gradingEligible) {
    severeReasons.push('unsafe_grading_on_disputed_evidence');
  }
  const severeError = severeReasons.length > 0;
  const score = Math.max(0, Math.min(1,
    blockCompleteness * 0.15
    + questionAccuracy * 0.25
    + answerAccuracy * 0.3
    + critical.f1 * 0.15
    + slots * 0.15
    - contamination * 0.1
    - (severeError ? 0.35 : 0)
  ));
  return {
    present: true,
    block_completeness: round(blockCompleteness),
    question_accuracy: round(questionAccuracy),
    question_cer: round(1 - questionAccuracy),
    answer_accuracy: round(answerAccuracy),
    answer_cer: round(1 - answerAccuracy),
    printed_question_text_accuracy: round(questionAccuracy),
    student_answer_text_accuracy: round(answerAccuracy),
    text_accuracy: round(textAccuracy),
    text_cer: round(1 - textAccuracy),
    critical_token_precision: round(critical.precision),
    critical_token_recall: round(critical.recall),
    critical_token_f1: round(critical.f1),
    answer_slot_accuracy: round(slots),
    printed_text_contamination: round(contamination),
    severe_error: severeError,
    severe_reasons: severeReasons,
    score: round(score),
    confidence: Number.isFinite(Number(result.confidence)) ? Number(result.confidence) : null,
    grading_eligible: result.gradingEligible ?? result.grading_eligible ?? null
  };
}

async function loadRuns(files, manifest, goldByNumber, options = {}) {
  return Promise.all(files.map(async file => {
    const payload = await readJson(file);
    const indexed = indexResults(payload, options.ignoreStudentKey ? '' : manifest.student_key);
    const questions = {};
    for (const number of manifest.question_numbers) questions[number] = evaluateQuestion(indexed.get(number), goldByNumber.get(number));
    const totalElapsedMs = Number(payload?.timing?.totalElapsedMs ?? payload?.metadata?.timing?.totalElapsedMs ?? payload?.metadata?.timing?.total_elapsed_ms);
    return {
      file: path.relative(EVALUATION_DIR, file),
      metadata: payload.metadata || {},
      total_elapsed_ms: Number.isFinite(totalElapsedMs) ? totalElapsedMs : null,
      question_count: indexed.size,
      average_confidence: round(median([...indexed.values()].map(item => Number(item.confidence)).filter(Number.isFinite))),
      severe_error_count: Object.values(questions).filter(item => item.severe_error).length,
      questions
    };
  }));
}

function aggregateRuns(runs, questionNumbers) {
  const questions = {};
  for (const number of questionNumbers) {
    const samples = runs.map(run => run.questions[number]);
    questions[number] = {
      median_score: round(median(samples.map(item => item.score))),
      median_text_accuracy: round(median(samples.map(item => item.text_accuracy))),
      median_text_cer: round(median(samples.map(item => item.text_cer))),
      median_question_accuracy: round(median(samples.map(item => item.question_accuracy))),
      median_answer_accuracy: round(median(samples.map(item => item.answer_accuracy))),
      median_critical_token_f1: round(median(samples.map(item => item.critical_token_f1))),
      median_answer_slot_accuracy: round(median(samples.map(item => item.answer_slot_accuracy))),
      severe_error_runs: samples.filter(item => item.severe_error).length,
      present_runs: samples.filter(item => item.present).length
    };
  }
  const questionValues = Object.values(questions);
  return {
    run_count: runs.length,
    median_total_elapsed_ms: round(median(runs.map(run => run.total_elapsed_ms))),
    median_average_confidence: round(median(runs.map(run => run.average_confidence))),
    median_text_accuracy: round(median(questionValues.map(item => item.median_text_accuracy))),
    median_question_accuracy: round(median(questionValues.map(item => item.median_question_accuracy))),
    median_answer_accuracy: round(median(questionValues.map(item => item.median_answer_accuracy))),
    text_accuracy_pass_count_95: questionValues.filter(item => Number.isFinite(item.median_text_accuracy) && item.median_text_accuracy >= 0.95).length,
    question_text_accuracy_pass_count_95: questionValues.filter(item => Number.isFinite(item.median_question_accuracy) && item.median_question_accuracy >= 0.95).length,
    answer_text_accuracy_pass_count_95: questionValues.filter(item => Number.isFinite(item.median_answer_accuracy) && item.median_answer_accuracy >= 0.95).length,
    severe_error_count: runs.reduce((sum, run) => sum + run.severe_error_count, 0),
    questions
  };
}

const args = parseArgs(process.argv.slice(2));
const manifest = await loadManifest();
if (!args.baseline.length) args.baseline = [path.join(EVALUATION_DIR, 'baselines')];
if (!args.candidate.length) args.candidate = [path.join(EVALUATION_DIR, 'runs', 'candidate')];
const goldPath = path.resolve(args.gold || resolveFromEvaluation(manifest.gold_file));
const gold = await readJson(goldPath);
const goldByNumber = new Map(gold.questions.map(item => [String(item.question_number), item]));
for (const number of manifest.question_numbers) {
  if (!goldByNumber.has(number)) throw new Error(`金标缺少第 ${number} 题`);
}

const baselineFiles = await listJsonInputs(args.baseline);
const candidateFiles = await listJsonInputs(args.candidate);
const baselineRuns = await loadRuns(baselineFiles, manifest, goldByNumber, { ignoreStudentKey: args.ignoreStudentKey });
const candidateRuns = await loadRuns(candidateFiles, manifest, goldByNumber, { ignoreStudentKey: args.ignoreStudentKey });
const baseline = aggregateRuns(baselineRuns, manifest.question_numbers);
const candidate = aggregateRuns(candidateRuns, manifest.question_numbers);
const gates = manifest.gates;
const failures = [];
const goldConfirmed = gold.questions.every(item => item.confirmed === true && item.confirmation_status === 'confirmed');
if (gates.require_all_gold_confirmed && !goldConfirmed) failures.push('gold_not_fully_human_confirmed');
if (baselineRuns.length < gates.minimum_runs_per_variant) failures.push(`baseline_runs_${baselineRuns.length}_below_${gates.minimum_runs_per_variant}`);
if (candidateRuns.length < gates.minimum_runs_per_variant) failures.push(`candidate_runs_${candidateRuns.length}_below_${gates.minimum_runs_per_variant}`);
if (gates.require_all_questions_in_every_candidate_run) {
  for (const run of candidateRuns) {
    if (run.question_count < manifest.question_numbers.length || Object.values(run.questions).some(item => !item.present)) {
      failures.push(`candidate_missing_questions:${run.file}`);
    }
  }
}
if (candidate.severe_error_count > gates.maximum_new_severe_errors) failures.push(`candidate_severe_errors:${candidate.severe_error_count}`);
if (Number.isFinite(candidate.median_total_elapsed_ms) && candidate.median_total_elapsed_ms > gates.maximum_median_total_elapsed_ms) {
  failures.push(`candidate_median_time_exceeded:${candidate.median_total_elapsed_ms}`);
}

const comparisons = {};
let strictImprovement = false;
for (const number of manifest.question_numbers) {
  const oldScore = baseline.questions[number].median_score;
  const newScore = candidate.questions[number].median_score;
  const oldTextAccuracy = baseline.questions[number].median_text_accuracy;
  const newTextAccuracy = candidate.questions[number].median_text_accuracy;
  const delta = Number.isFinite(oldScore) && Number.isFinite(newScore) ? round(newScore - oldScore) : null;
  const textDelta = Number.isFinite(oldTextAccuracy) && Number.isFinite(newTextAccuracy) ? round(newTextAccuracy - oldTextAccuracy) : null;
  const regressed = delta === null || delta < -gates.per_question_regression_tolerance;
  const textRegressed = textDelta === null || textDelta < -gates.per_question_regression_tolerance;
  if (regressed) failures.push(`question_${number}_regressed:${delta}`);
  if (textRegressed) failures.push(`question_${number}_text_regressed:${textDelta}`);
  if (Number.isFinite(delta) && oldScore < 0.999 && delta >= gates.strict_improvement_minimum) strictImprovement = true;
  comparisons[number] = {
    baseline_score: oldScore,
    candidate_score: newScore,
    delta,
    regressed,
    baseline_text_accuracy: oldTextAccuracy,
    candidate_text_accuracy: newTextAccuracy,
    text_delta: textDelta,
    text_regressed: textRegressed,
    baseline_question_accuracy: baseline.questions[number].median_question_accuracy,
    candidate_question_accuracy: candidate.questions[number].median_question_accuracy,
    baseline_answer_accuracy: baseline.questions[number].median_answer_accuracy,
    candidate_answer_accuracy: candidate.questions[number].median_answer_accuracy
  };
}
if (!strictImprovement) failures.push('no_strict_improvement_on_previous_failure');

const report = {
  schema_version: 1,
  generated_at: new Date().toISOString(),
  paper_id: manifest.paper_id,
  gold: {
    file: path.relative(EVALUATION_DIR, goldPath),
    status: gold.status,
    all_human_confirmed: goldConfirmed,
    confirmed_count: gold.questions.filter(item => item.confirmed).length,
    total_count: gold.questions.length
  },
  baseline,
  candidate,
  comparisons,
  gate: {
    passed: failures.length === 0,
    failures: [...new Set(failures)],
    policy: gates,
    ignore_student_key: args.ignoreStudentKey,
    note: '平均置信度只作模型自评参考，不参与准确率门禁。'
  },
  runs: { baseline: baselineRuns, candidate: candidateRuns }
};

const outputDir = path.resolve(args.out);
await fs.mkdir(outputDir, { recursive: true });
await writeJson(path.join(outputDir, 'report.json'), report);
const failedQuestions = manifest.question_numbers.filter(number => comparisons[number].regressed || comparisons[number].text_regressed || candidate.questions[number].severe_error_runs > 0);
const lines = [
  '# 物理完卷 1–22 题 A/B 评测',
  '',
  `- 发布门：**${report.gate.passed ? '通过' : '拒绝'}**`,
  `- 人工确认金标：${report.gold.confirmed_count}/${report.gold.total_count}`,
  `- 准确率口径：${goldConfirmed ? '正式金标准确率' : '临时对照准确率，gold 未人工确认，不能作为正式验收'}`,
  `- 旧版/新版运行数：${baseline.run_count}/${candidate.run_count}`,
  `- 新版中位总耗时：${candidate.median_total_elapsed_ms ?? '无数据'} ms`,
  `- 新版中位平均置信度：${candidate.median_average_confidence ?? '无数据'}（不是准确率）`,
  `- 新版综合文字准确率中位数：${candidate.median_text_accuracy ?? '无数据'}`,
  `- 新版题干文字准确率中位数：${candidate.median_question_accuracy ?? '无数据'}，≥95% 题数：${candidate.question_text_accuracy_pass_count_95}/${manifest.question_numbers.length}`,
  `- 新版学生答案文字准确率中位数：${candidate.median_answer_accuracy ?? '无数据'}，≥95% 题数：${candidate.answer_text_accuracy_pass_count_95}/${manifest.question_numbers.length}`,
  '',
  '## 门禁失败原因',
  '',
  ...(report.gate.failures.length ? report.gate.failures.map(item => `- ${item}`) : ['- 无']),
  '',
  '## 逐题对比',
  '',
  '| 题号 | 旧版文字准确率 | 新版文字准确率 | 文字差值 | 题干准确率 新/旧 | 答案准确率 新/旧 | 综合分差值 | 新版严重错误运行数 |',
  '|---:|---:|---:|---:|---:|---:|---:|---:|',
  ...manifest.question_numbers.map(number => {
    const row = comparisons[number];
    return `| ${number} | ${row.baseline_text_accuracy ?? '—'} | ${row.candidate_text_accuracy ?? '—'} | ${row.text_delta ?? '—'} | ${row.candidate_question_accuracy ?? '—'} / ${row.baseline_question_accuracy ?? '—'} | ${row.candidate_answer_accuracy ?? '—'} / ${row.baseline_answer_accuracy ?? '—'} | ${row.delta ?? '—'} | ${candidate.questions[number].severe_error_runs} |`;
  }),
  '',
  `失败队列：${failedQuestions.length ? failedQuestions.join('、') : '无'}`,
  ''
];
await fs.writeFile(path.join(outputDir, 'report.md'), lines.join('\n'), 'utf8');
console.log(JSON.stringify({
  output_dir: outputDir,
  passed: report.gate.passed,
  failures: report.gate.failures,
  candidate_text_accuracy: {
    median_overall: candidate.median_text_accuracy,
    median_question_text: candidate.median_question_accuracy,
    median_student_answer_text: candidate.median_answer_accuracy,
    overall_pass_count_95: `${candidate.text_accuracy_pass_count_95}/${manifest.question_numbers.length}`,
    question_text_pass_count_95: `${candidate.question_text_accuracy_pass_count_95}/${manifest.question_numbers.length}`,
    student_answer_text_pass_count_95: `${candidate.answer_text_accuracy_pass_count_95}/${manifest.question_numbers.length}`
  },
  confidence_note: 'average_confidence 是模型自评，不等于文字准确率'
}, null, 2));
if (!report.gate.passed) process.exitCode = 2;
