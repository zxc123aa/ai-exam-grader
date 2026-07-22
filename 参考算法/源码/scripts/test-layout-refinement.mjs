import assert from 'node:assert/strict';
import sharp from 'sharp';

process.env.NODE_ENV = 'test';
const { applyPrintedBoundaryAnchors, refineLayoutRegions } = await import('../server.js');

const width = 1000;
const height = 900;
const pixels = Buffer.alloc(width * height, 245);

function drawTextRows(left, right, top, bottom, spacing = 18) {
  for (let y = top; y <= bottom; y += spacing) {
    for (let lineY = y; lineY < Math.min(y + 3, height); lineY += 1) {
      for (let x = left; x < right; x += 1) pixels[lineY * width + x] = 25;
    }
  }
}

drawTextRows(90, 430, 100, 220);
drawTextRows(90, 430, 330, 470);
drawTextRows(90, 430, 600, 820);
drawTextRows(570, 910, 120, 120);
drawTextRows(590, 910, 138, 138);
drawTextRows(570, 910, 156, 400);
drawTextRows(570, 910, 520, 800);

// Simulate a handwritten stroke crossing the otherwise quiet right-column gap.
for (let x = 610; x < 860; x += 1) {
  const y = Math.round(455 + (x - 610) * 0.2);
  for (let offset = -2; offset <= 2; offset += 1) pixels[(y + offset) * width + x] = 35;
}

const image = await sharp(pixels, { raw: { width, height, channels: 1 } }).jpeg().toBuffer();
const dataUrl = `data:image/jpeg;base64,${image.toString('base64')}`;
const rawRegions = [
  { id: 'q18', questionNumber: '18', readingOrder: 1, xmin: 70, xmax: 460, ymin: 80, ymax: 320 },
  { id: 'q19', questionNumber: '19', readingOrder: 2, xmin: 70, xmax: 460, ymin: 280, ymax: 570 },
  { id: 'q20', questionNumber: '20', readingOrder: 3, xmin: 70, xmax: 460, ymin: 540, ymax: 880 },
  { id: 'q21', questionNumber: '21', readingOrder: 4, xmin: 540, xmax: 930, ymin: 90, ymax: 500 },
  { id: 'q22', questionNumber: '22', readingOrder: 5, xmin: 540, xmax: 930, ymin: 470, ymax: 860 }
];

const refined = await refineLayoutRegions(dataUrl, rawRegions);
const byId = Object.fromEntries(refined.map(region => [region.id, region]));

assert.equal(byId.q18.ymax, byId.q19.ymin);
assert.equal(byId.q19.ymax, byId.q20.ymin);
assert.equal(byId.q21.ymax, byId.q22.ymin);
assert.notEqual(byId.q18.ymax, rawRegions[0].ymax);
assert.notEqual(byId.q21.ymax, rawRegions[3].ymax);
assert.ok(byId.q18.ymin > rawRegions[0].ymin + 20);
assert.ok(byId.q21.ymin > rawRegions[3].ymin + 20);
assert.equal(byId.q18.refinement.topBoundary.source, 'printed_question_anchor_v1');
assert.equal(byId.q21.refinement.topBoundary.source, 'printed_question_anchor_v1');
assert.equal(byId.q18.refinement.topBoundary.applied, true);
assert.equal(byId.q21.refinement.topBoundary.applied, true);
assert.equal(byId.q18.refinement.topBoundary.questionLineIndex, 1);
assert.equal(byId.q21.refinement.topBoundary.questionLineIndex, 2);
assert.equal(byId.q18.refinement.bottomBoundary.applied, true);
assert.equal(byId.q21.refinement.bottomBoundary.applied, true);
assert.ok(byId.q18.refinement.bottomBoundary.inkRatio < 0.03);
assert.ok(byId.q21.refinement.bottomBoundary.inkRatio < 0.03);

const upwardRisk = [{
  pairId: 'q21->q22',
  previousIndex: 3,
  nextIndex: 4,
  previousQuestionNumber: '21',
  nextQuestionNumber: '22',
  rawBoundary: 500,
  projectedBoundary: 486
}];
const anchored = applyPrintedBoundaryAnchors(refined, upwardRisk, [{
  pairId: 'q21->q22',
  nextQuestionNumber: '22',
  visible: true,
  anchorY: 520,
  confidence: 0.91
}]);
assert.equal(anchored[3].ymax, 510);
assert.equal(anchored[4].ymin, 510);
assert.equal(anchored[3].refinement.bottomBoundary.source, 'gemini_printed_question_anchor_v1');

const rejected = applyPrintedBoundaryAnchors(refined, upwardRisk, []);
assert.equal(rejected[3].ymax, 500);
assert.equal(rejected[4].ymin, 500);
assert.equal(rejected[3].refinement.bottomBoundary.applied, false);
assert.equal(
  rejected[3].refinement.bottomBoundary.rejectedReason,
  'upward_projection_requires_printed_question_anchor'
);

console.log(JSON.stringify(refined.map(region => ({
  id: region.id,
  ymin: region.ymin,
  ymax: region.ymax,
  confidence: region.refinement.confidence,
  topBoundary: region.refinement.topBoundary,
  bottomBoundary: region.refinement.bottomBoundary
})), null, 2));
