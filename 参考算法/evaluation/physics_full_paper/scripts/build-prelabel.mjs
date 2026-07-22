import fs from 'fs/promises';
import path from 'path';
import { createHash } from 'crypto';
import {
  EVALUATION_DIR,
  indexResults,
  inferAnswerSlots,
  loadManifest,
  readJson,
  resolveFromEvaluation,
  writeJson
} from './lib.mjs';

const manifest = await loadManifest();
const baselineRuns = [];

for (const sourceRelative of manifest.baseline_sources) {
  const sourcePath = resolveFromEvaluation(sourceRelative);
  const source = await readJson(sourcePath);
  const indexed = indexResults(source, manifest.student_key);
  const normalized = {
    schema_version: 1,
    variant: 'legacy_frozen',
    source_file: path.relative(EVALUATION_DIR, sourcePath),
    source_job_id: source.id || null,
    created_at: source.createdAt || null,
    metadata: {
      pipeline_version: 'legacy-unversioned',
      prompt_hash: null,
      model: null,
      provider: null,
      thresholds: null,
      git_commit: null,
      timing: source.timing || null,
      token_usage: source.timing?.tokenUsage || null
    },
    results: manifest.question_numbers
      .map(number => indexed.get(number))
      .filter(Boolean)
  };
  const outputPath = path.join(EVALUATION_DIR, 'baselines', `legacy-${source.id || baselineRuns.length + 1}.json`);
  await writeJson(outputPath, normalized);
  baselineRuns.push({ outputPath, normalized, indexed });
}

if (!baselineRuns.length) throw new Error('没有可用的历史基线');

const imageEvidence = [];
for (const imageRelative of manifest.images) {
  const imagePath = resolveFromEvaluation(imageRelative);
  const buffer = await fs.readFile(imagePath);
  imageEvidence.push({
    file: path.relative(EVALUATION_DIR, imagePath),
    sha256: createHash('sha256').update(buffer).digest('hex'),
    bytes: buffer.length
  });
}

const questions = manifest.question_numbers.map(number => {
  const candidates = baselineRuns
    .map(run => run.indexed.get(number))
    .filter(Boolean);
  const primary = candidates[0] || {};
  const alternatives = candidates.slice(1).map((candidate, index) => ({
    source_run: path.basename(baselineRuns[index + 1].outputPath),
    question: String(candidate.question || ''),
    student_answer: String(candidate.studentAnswer || ''),
    differs_from_primary: String(candidate.question || '') !== String(primary.question || '')
      || String(candidate.studentAnswer || '') !== String(primary.studentAnswer || '')
  }));
  return {
    question_number: number,
    confirmation_status: 'needs_human_confirmation',
    confirmed: false,
    question: String(primary.question || ''),
    student_answer: String(primary.studentAnswer || ''),
    answer_slots: inferAnswerSlots(primary),
    source: {
      type: 'legacy_prelabel_only',
      run: path.basename(baselineRuns[0].outputPath),
      block_id: primary.blockId || null,
      confidence: Number.isFinite(Number(primary.confidence)) ? Number(primary.confidence) : null
    },
    alternatives,
    reviewer: null,
    confirmed_at: null,
    notes: '必须对照原图确认；历史模型输出不是金标。'
  };
});

const gold = {
  schema_version: 1,
  paper_id: manifest.paper_id,
  paper_label: manifest.paper_label,
  student_key: manifest.student_key,
  status: 'prelabel_unconfirmed',
  generated_at: new Date().toISOString(),
  generation_policy: '仅从冻结历史输出生成预标，不自动解题、不自动纠错、不用于发布通过。',
  image_evidence: imageEvidence,
  questions
};

await writeJson(path.join(EVALUATION_DIR, manifest.gold_file), gold);
console.log(JSON.stringify({
  gold_file: manifest.gold_file,
  question_count: questions.length,
  confirmed_count: questions.filter(item => item.confirmed).length,
  baseline_runs: baselineRuns.map(run => path.relative(EVALUATION_DIR, run.outputPath))
}, null, 2));
