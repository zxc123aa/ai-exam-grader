import assert from 'assert/strict';
import { characterAccuracy, extractCriticalTokens, inferAnswerSlots, tokenScores } from './lib.mjs';

assert.equal(characterAccuracy('同一\n匀速直线运动\nC', '同一 匀速直线运动 C'), 1);
assert.deepEqual(inferAnswerSlots({ studentAnswer: '(1)液体密度;2.4\n(2)增大;无关' }), ['液体密度;2.4', '增大;无关']);
const exact = tokenScores(extractCriticalTokens('P=Fv=1500W'), extractCriticalTokens('P=Fv=1500W'));
assert.equal(exact.f1, 1);
const conflict = tokenScores(extractCriticalTokens('F=100N'), extractCriticalTokens('F=600N'));
assert.equal(conflict.precision, 0);
assert.ok(conflict.extra.includes('100n'));
console.log('Evaluator unit tests passed');
