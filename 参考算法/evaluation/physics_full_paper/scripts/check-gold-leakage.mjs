import fs from 'fs/promises';
import path from 'path';
import { EVALUATION_DIR, loadManifest, resolveFromEvaluation } from './lib.mjs';

const manifest = await loadManifest();
const extensions = new Set(['.js', '.mjs', '.cjs', '.ts', '.tsx', '.py']);

async function collect(target) {
  const stat = await fs.stat(target);
  if (stat.isFile()) return [target];
  const files = [];
  for (const entry of await fs.readdir(target, { withFileTypes: true })) {
    if (entry.name === 'tests' || entry.name === '__pycache__' || entry.name === 'node_modules') continue;
    const child = path.join(target, entry.name);
    if (entry.isDirectory()) files.push(...await collect(child));
    else if (extensions.has(path.extname(entry.name))) files.push(child);
  }
  return files;
}

const files = [];
for (const root of manifest.production_scan_roots) files.push(...await collect(resolveFromEvaluation(root)));
const violations = [];
for (const file of files) {
  const content = await fs.readFile(file, 'utf8');
  if (/evaluation[\\/]physics_full_paper/.test(content)) {
    violations.push({ file: path.relative(EVALUATION_DIR, file), probe: 'runtime_dependency_on_evaluation_directory' });
  }
  for (const probe of manifest.leakage_probes) {
    if (content.includes(probe)) violations.push({ file: path.relative(EVALUATION_DIR, file), probe });
  }
}

console.log(JSON.stringify({ scanned_files: files.length, violations }, null, 2));
if (violations.length) process.exitCode = 1;
