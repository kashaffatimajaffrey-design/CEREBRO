#!/usr/bin/env node
// Bundle-size budget. Run after `vite build`. Fails CI if the gzipped JS/CSS in
// dist/assets exceeds the budget — a cheap guard against dependency bloat.
import { readdirSync, readFileSync } from 'node:fs';
import { gzipSync } from 'node:zlib';
import { join } from 'node:path';

const DIST = 'dist/assets';
// Gzipped budgets (what the user actually downloads).
const BUDGET = { js: 750 * 1024, css: 100 * 1024 };

let files;
try {
  files = readdirSync(DIST);
} catch {
  console.error(`No build output at ${DIST}. Run \`npm run build:client\` first.`);
  process.exit(1);
}

const totals = { js: 0, css: 0 };
const rows = [];
for (const f of files) {
  const ext = f.endsWith('.js') ? 'js' : f.endsWith('.css') ? 'css' : null;
  if (!ext) continue;
  const buf = readFileSync(join(DIST, f));
  const gz = gzipSync(buf).length;
  totals[ext] += gz;
  rows.push({
    file: f,
    raw: `${(buf.length / 1024).toFixed(1)} KB`,
    gzip: `${(gz / 1024).toFixed(1)} KB`,
  });
}

console.table(rows);
let failed = false;
for (const ext of ['js', 'css']) {
  const ok = totals[ext] <= BUDGET[ext];
  console.log(
    `${ext.toUpperCase()} total: ${(totals[ext] / 1024).toFixed(1)} KB gzip ` +
      `(budget ${(BUDGET[ext] / 1024).toFixed(0)} KB) — ${ok ? 'OK' : 'OVER BUDGET'}`,
  );
  if (!ok) failed = true;
}
if (failed) {
  console.error('\nBundle-size budget exceeded. Trim dependencies or code-split before merging.');
  process.exit(1);
}
console.log('\nBundle within budget.');
