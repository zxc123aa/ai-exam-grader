import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';

export const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
export const EVALUATION_DIR = path.resolve(SCRIPT_DIR, '..');

export async function readJson(filePath) {
  return JSON.parse(await fs.readFile(filePath, 'utf8'));
}

export async function writeJson(filePath, value) {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  await fs.writeFile(filePath, `${JSON.stringify(value, null, 2)}\n`, 'utf8');
}

export function resolveFromEvaluation(relativePath) {
  return path.resolve(EVALUATION_DIR, relativePath);
}

export async function loadManifest() {
  return readJson(path.join(EVALUATION_DIR, 'manifest.json'));
}

export function normalizeQuestionNumber(value) {
  const match = String(value ?? '').match(/\d+/);
  return match ? String(Number(match[0])) : '';
}

export function normalizeText(value) {
  return String(value ?? '')
    .normalize('NFKC')
    .replace(/[‐‑‒–—−]/g, '-')
    .replace(/[×xX＊*]/g, '×')
    .replace(/[，、；;]/g, ',')
    .replace(/[。．]/g, '.')
    .replace(/[（]/g, '(')
    .replace(/[）]/g, ')')
    .replace(/\s+/g, '')
    .toLowerCase();
}

export function levenshtein(left, right) {
  const a = [...normalizeText(left)];
  const b = [...normalizeText(right)];
  if (!a.length) return b.length;
  if (!b.length) return a.length;
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

export function characterAccuracy(actual, expected) {
  const denominator = Math.max(1, [...normalizeText(expected)].length);
  return Math.max(0, 1 - levenshtein(actual, expected) / denominator);
}

function splitDelimitedAnswers(text) {
  return String(text || '')
    .split(/[\n;；]+/)
    .flatMap(part => part.split(/(?<!\d),(?!\d)|(?<!\d)，(?!\d)/))
    .map(part => part.replace(/^\s*(?:解\s*[:：]\s*)?[（(]?\d+[）).、:]?\s*/, '').trim())
    .filter(Boolean);
}

export function inferAnswerSlots(result) {
  const explicit = result?.answerEntries ?? result?.answer_entries ?? result?.answerSlots ?? result?.answer_slots;
  if (Array.isArray(explicit) && explicit.length) {
    return explicit.map(item => String(item?.text ?? item?.value ?? item ?? '').trim()).filter(Boolean);
  }
  const text = String(result?.studentAnswer ?? result?.student_answer ?? '').trim();
  if (!text) return [];
  const markers = [...text.matchAll(/(?:^|\n)\s*(?:解\s*[:：]\s*)?[（(](\d+)[）)]/g)];
  if (!markers.length) return splitDelimitedAnswers(text);
  const slots = [];
  for (let index = 0; index < markers.length; index += 1) {
    const start = markers[index].index;
    const end = markers[index + 1]?.index ?? text.length;
    const value = text.slice(start, end)
      .replace(/^\s*(?:解\s*[:：]\s*)?[（(]\d+[）)]\s*/, '')
      .trim();
    if (value) slots.push(value);
  }
  const prefix = text.slice(0, markers[0].index).trim();
  return prefix ? [prefix, ...slots] : slots;
}

export function extractCriticalTokens(value) {
  const text = normalizeText(value)
    .replace(/m\^?2/g, 'm²')
    .replace(/m\^?3/g, 'm³');
  const tokens = [];
  const patterns = [
    /\d+(?:\.\d+)?(?:×10\^?-?\d+)?(?:km\/h|m\/s|n\/kg|kg\/m³|kg\/m3|m²|m³|pa|kw|w|kj|j|kg|cm²|cm2|cm|mm|ml|n|s|h|%|℃)?/g,
    /[a-zρ][a-zρ_\d]*(?:=[a-zρ\d_().+×\/-]+)+/g
  ];
  for (const pattern of patterns) {
    for (const match of text.matchAll(pattern)) tokens.push(match[0]);
  }
  return tokens;
}

function multisetCounts(values) {
  const counts = new Map();
  for (const value of values) counts.set(value, (counts.get(value) || 0) + 1);
  return counts;
}

export function tokenScores(actual, expected) {
  const actualCounts = multisetCounts(actual);
  const expectedCounts = multisetCounts(expected);
  let matches = 0;
  for (const [token, count] of actualCounts) matches += Math.min(count, expectedCounts.get(token) || 0);
  const precision = actual.length ? matches / actual.length : expected.length ? 0 : 1;
  const recall = expected.length ? matches / expected.length : actual.length ? 0 : 1;
  const f1 = precision + recall ? 2 * precision * recall / (precision + recall) : 0;
  const extra = [];
  for (const [token, count] of actualCounts) {
    const difference = count - (expectedCounts.get(token) || 0);
    for (let index = 0; index < difference; index += 1) extra.push(token);
  }
  return { precision, recall, f1, extra };
}

export function median(values) {
  const numbers = values.filter(value => Number.isFinite(value)).sort((a, b) => a - b);
  if (!numbers.length) return null;
  const middle = Math.floor(numbers.length / 2);
  return numbers.length % 2 ? numbers[middle] : (numbers[middle - 1] + numbers[middle]) / 2;
}

export function round(value, digits = 4) {
  if (!Number.isFinite(value)) return value;
  return Number(value.toFixed(digits));
}

export function indexResults(run, studentKey = '') {
  const source = Array.isArray(run) ? run : Array.isArray(run?.results) ? run.results : [];
  const selected = source.filter(item => !studentKey || !item.paperKey || item.paperKey === studentKey);
  const indexed = new Map();
  for (const item of selected) {
    const number = normalizeQuestionNumber(item.questionNumber ?? item.question_number);
    if (number && !indexed.has(number)) indexed.set(number, item);
  }
  return indexed;
}

export async function listJsonInputs(inputs) {
  const files = [];
  for (const input of inputs) {
    const resolved = path.resolve(input);
    const stat = await fs.stat(resolved);
    if (stat.isFile()) files.push(resolved);
    if (stat.isDirectory()) {
      const names = (await fs.readdir(resolved)).filter(name => name.endsWith('.json')).sort();
      files.push(...names.map(name => path.join(resolved, name)));
    }
  }
  return [...new Set(files)];
}
