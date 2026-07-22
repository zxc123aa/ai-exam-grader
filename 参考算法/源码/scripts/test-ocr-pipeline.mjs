process.env.NODE_ENV = 'test';
const { groupBlocksForOcr, mergeRecognizedResults, addUsage, reconcileStudentAnswer, buildExpandedHandwritingClusters, evidenceViewsAgree, separatePrintedQuestionMarks, structureStudentAnswerEvidence, finalizeFastRecognition, isTransientModelError } = await import('../server.js');

const block = (id, paperKey, pageId, questionNumber, continuationOf = null) => ({
  id, paperKey, pageId, questionNumber, continuationOf,
  image: `data:image/jpeg;base64,${id}`
});

const samePaper = [
  block('a1', 'paper-a', 'page-1', '1'),
  block('a2', 'paper-a', 'page-1', '2'),
  block('a3', 'paper-a', 'page-2', '3'),
  block('a4', 'paper-a', 'page-2', '4')
];
const groups = groupBlocksForOcr(samePaper, { maxBlocksPerRequest: 3 });
if (groups.length !== 2 || groups[0].length !== 3 || groups[1].length !== 1) {
  throw new Error(`跨页同卷批次错误：${groups.map(group => group.length).join(',')}`);
}
const separated = groupBlocksForOcr([
  block('a1', 'paper-a', 'page-1', '1'),
  block('b1', 'paper-b', 'page-1', '1')
], { maxBlocksPerRequest: 3 });
if (separated.length !== 2) throw new Error('不同试卷不应进入同一批次');

const merged = mergeRecognizedResults([
  { blockId: 'a1', paperKey: 'paper-a', questionNumber: '7', question: '题干上半段', studentAnswer: 'A', notes: '', sourceLabel: '上半页', confidence: 0.9, elapsedMs: 120 },
  { blockId: 'a2', paperKey: 'paper-a', questionNumber: '7', mergeWithBlockId: 'a1', question: '题干下半段', studentAnswer: '补充', notes: '', sourceLabel: '下半页', confidence: 0.8, elapsedMs: 140 },
  { blockId: 'b1', paperKey: 'paper-a', questionNumber: '8', question: '另一题', studentAnswer: 'B', notes: '', sourceLabel: '同页', confidence: 0.9, elapsedMs: 130 }
]);
if (merged.length !== 2 || merged[0].mergedBlockCount !== 2 || !merged[0].question.includes('题干下半段') || merged[0].elapsedMs !== 140) {
  throw new Error('模型判断续题后的服务端拼接错误');
}
console.log('OCR pipeline tests passed: cross-page batching, paper isolation, model-directed merge');
const fastPreview = finalizeFastRecognition({
  questionNumber: '1',
  question: '题目____',
  studentAnswer: '考生原文',
  confidence: 0.99
});
if (fastPreview.gradingEligible || fastPreview.answerVerification?.status !== 'not_run_fast_recognition') {
  throw new Error('快速识别只能用于预览，未做证据核验时不得进入自动判分');
}
console.log('Fast recognition safety test passed: no evidence verification and no grading eligibility');
if (!isTransientModelError(new TypeError('fetch failed')) || !isTransientModelError(new Error('socket hang up'))) {
  throw new Error('连接重置和 fetch failed 必须进入退避重试，不得立即触发单题回退风暴');
}
console.log('Transient network retry test passed: retry fetch/socket failures before fallback');
const usage = addUsage({ prompt_tokens: 1200, completion_tokens: 300, total_tokens: 1500 }, { input_tokens: 500, output_tokens: 100 });
if (usage.inputTokens !== 1700 || usage.outputTokens !== 400 || usage.totalTokens !== 2100) throw new Error('token usage aggregation failed');
console.log('Token usage tests passed: OpenAI and generic usage field aliases');

const hallucinated = reconcileStudentAnswer(
  { studentAnswer: '(3) F=P/v=1500W/15m/s=100N', confidence: 0.9, notes: '' },
  { studentAnswer: '(3) F=SP=0.4m²×1500W=600N', confidence: 0.88, notes: '逐字核对原图', consensus: true }
);
if (!hallucinated.studentAnswer.includes('600N') || hallucinated.studentAnswer.includes('100N')) {
  throw new Error('手写证据双视图一致时必须采用证据转写，而不是完整题块的推算结果');
}
if (hallucinated.answerVerification.status !== 'evidence_consensus') {
  throw new Error('双视图一致结果必须标记为 evidence_consensus');
}
console.log('Answer verification tests passed: use isolated evidence consensus over semantic completion');

const disagreement = reconcileStudentAnswer(
  { studentAnswer: '完整题块的文本', confidence: 0.9, notes: '' },
  { candidateStudentAnswer: '扩边候选', confidence: 0.88, notes: '', consensus: false }
);
if (disagreement.studentAnswer !== '扩边候选' || disagreement.confidence !== 0.6 || disagreement.answerVerification.status !== 'evidence_disagreement') {
  throw new Error('双视图不一致时应优先显示证据候选，并标记低置信度复核');
}

const blocked = reconcileStudentAnswer(
  { studentAnswer: '模型自行计算出的100N', confidence: 0.9, notes: '' },
  { error: '手写证据定位失败' }
);
if (blocked.studentAnswer !== '模型自行计算出的100N' || blocked.confidence !== 0.85 || blocked.answerVerification.blockedInitialTranscription) {
  throw new Error('核验服务失败时应保留首轮转写，且不应误判为内容冲突压到 0.6');
}
console.log('Verification failure test passed: preserve initial transcription with a mild confidence penalty');

if (!evidenceViewsAgree(
  'F阻 = F牵 = SP = 0.4 m² × 1500 W = 600 N',
  'F阻=F牵=SP=0.4m²×1500W=600N'
)) throw new Error('同内容的换行、空格和标点差异应判为一致');

if (!evidenceViewsAgree(
  '草稿：1500\nF阻=F牵=SP=0.4m²×1500W=600N',
  'F阻=F牵=SP=0.4m²×1500W=600N'
)) throw new Error('宽视图多识别一个草稿数字时，核心数字证据兼容应判为一致');

if (evidenceViewsAgree('F=P/v=1500W/15m/s=100N', 'F=SP=0.4m²×1500W=600N')) {
  throw new Error('100N 与 600N 这类最终数字证据冲突必须进入复核');
}
console.log('Evidence agreement tests passed: tolerate formatting/draft context, reject numeric conflicts');

const question19 = '在探究“阻力对物体运动的影响”时，(1)将小车从斜面上____(选填“同一”或“不同”)位置释放；(2)小车将做____；(3)反映的是____。A.阻力大小 B.影响情况 C.A、B均正确';
const separatedMarks = separatePrintedQuestionMarks({
  question: question19,
  studentAnswer: '阻力对\n同一\n匀速直线运动\nC',
  confidence: 0.9,
  notes: ''
});
if (separatedMarks.studentAnswer !== '同一\n匀速直线运动\nC') {
  throw new Error('印刷题干圈画应从 studentAnswer 分离，但选填词和选项字母必须保留');
}
if (separatedMarks.printedQuestionMarks?.[0]?.text !== '阻力对') {
  throw new Error('被分离的印刷题干标记必须保留为可审计证据');
}
const preservedCrossout = separatePrintedQuestionMarks({
  question: '请用物理知识解释为什么要涂镁粉',
  studentAnswer: '［划去：物理知识］摩擦力\n增大接触面的粗糙程度',
  confidence: 0.9,
  notes: ''
});
if (!preservedCrossout.studentAnswer.includes('［划去：物理知识］摩擦力')) {
  throw new Error('考生对印刷文字的实际改写证据不能被反污染规则删除');
}
const preservedFillChoice = separatePrintedQuestionMarks({
  question: '物体将____（填“上浮”、“下沉”或“悬浮”）。',
  studentAnswer: '20\n上浮',
  confidence: 0.9,
  notes: ''
});
if (preservedFillChoice.studentAnswer !== '20\n上浮') {
  throw new Error('题干明确列出的选填词属于正式答案，不得被当作印刷圈画删除');
}
console.log('Printed-question mark separation tests passed: remove circled print, preserve valid choices and explicit edits');

const structured19 = structureStudentAnswerEvidence({
  question: question19,
  studentAnswer: '同一\n匀速直线运动\nC',
  confidence: 0.9,
  answerVerification: { regions: [{ xmin: 1, ymin: 2, xmax: 3, ymax: 4 }] }
});
if (structured19.answerEntries.map(item => item.text).join('|') !== '同一|匀速直线运动|C') {
  throw new Error('无小问标签的顺序答案应按题目答题槽依次归属');
}
if (structured19.unassignedEvidence.length) {
  throw new Error('已按顺序归属的答案不得在未归属证据中重复出现');
}
if (structured19.answerEntries.some(item => item.coordinatePrecision !== 'answer_region_union')) {
  throw new Error('答题槽坐标必须如实标明为题内手写区联集，不得伪装成逐字坐标');
}

const structured20 = structureStudentAnswerEvidence({
  question: '(1)研究与____的关系，浮力为____N；(2)浮力____，与深度____；(3)密度为____kg/m³。',
  studentAnswer: '(1)液体密度 2.4\n(2)增大 无关\n(3)4×10³',
  confidence: 0.8,
  answerVerification: { regions: [] }
});
if (structured20.answerEntries.map(item => item.text).join('|') !== '液体密度|2.4|增大|无关|4×10³') {
  throw new Error('一个小问的多个填空应拆成独立答题槽');
}
const structured20WithDraft = structureStudentAnswerEvidence({
  question: '(1)研究与____的关系，浮力为____N；(2)浮力____，与深度____；(3)密度为____kg/m³。',
  studentAnswer: '(1)液体密度 2.4\n(2)增大 无关\n(3)4×10³ 草稿计算：8-5.6=2.4 ρ=m/V',
  confidence: 0.8,
  answerVerification: { regions: [] }
});
if (
  structured20WithDraft.answerEntries.map(item => item.text).join('|') !== '液体密度|2.4|增大|无关|4×10³' ||
  structured20WithDraft.gradingAnswer.includes('草稿') ||
  !structured20WithDraft.unassignedEvidence.join('\n').includes('8-5.6')
) {
  throw new Error('草稿/计算过程必须退出 gradingAnswer，但保留为未归属证据');
}

const structured22 = structureStudentAnswerEvidence({
  question: '(1)拉力；(2)做功；(3)功率；(4)解释镁粉。',
  studentAnswer: '1\nP=W/t\n解:(1)600N\n(2)360J\n(3)480W\n(4)增大粗糙程度',
  confidence: 0.9,
  answerVerification: { regions: [] }
});
if (structured22.unassignedEvidence.join('|') !== '1|P=W/t' || structured22.gradingAnswer.includes('P=W/t')) {
  throw new Error('无法归属到小问的题干批注/草稿必须退出 gradingAnswer');
}
if (structured22.answerEntries[0].text !== '600N') {
  throw new Error('“解:(1)”前缀不得导致第一小问丢失');
}
if (!structured22.gradingEligible) {
  throw new Error('高置信度、无缺失的已归属作答应可进入自动判分');
}

const blockedDisagreement = structureStudentAnswerEvidence({
  question: '(1)计算阻力。',
  studentAnswer: '(1)P/v=100N',
  confidence: 0.6,
  answerVerification: {
    status: 'evidence_disagreement',
    candidateStudentAnswer: '(1)SP=600N',
    regions: []
  }
});
if (blockedDisagreement.gradingEligible) {
  throw new Error('双视图分歧或低置信度作答不得标记为可直接自动判分');
}

const modelReportedMarks = reconcileStudentAnswer(
  {
    question: '在探究“阻力对物体运动的影响”时……',
    studentAnswer: '同一',
    printedQuestionMarks: [{ text: '阻力对', type: 'circle' }],
    confidence: 0.9,
    notes: ''
  },
  {
    studentAnswer: '同一',
    printedQuestionMarks: [{ text: '阻力对', markType: 'circle' }],
    confidence: 0.9,
    consensus: true
  }
);
if (modelReportedMarks.printedQuestionMarks.length !== 1 || modelReportedMarks.printedQuestionMarks[0].text !== '阻力对') {
  throw new Error('模型显式返回的题干圈画必须跨双视图去重保留');
}
console.log('Answer-slot structure tests passed: map subquestions/blanks, preserve honest coordinates, isolate unassigned evidence');

const handwritingClusters = buildExpandedHandwritingClusters([
  { xmin: 15, ymin: 378, xmax: 627, ymax: 530 },
  { xmin: 109, ymin: 486, xmax: 655, ymax: 625 },
  { xmin: 82, ymin: 631, xmax: 455, ymax: 743 },
  { xmin: 149, ymin: 646, xmax: 795, ymax: 833 },
  { xmin: 194, ymin: 802, xmax: 584, ymax: 951 },
  { xmin: 91, ymin: 943, xmax: 583, ymax: 1000 }
]);
if (handwritingClusters.length !== 1 || handwritingClusters[0].expanded.ymin > 345 || handwritingClusters[0].expanded.ymax !== 1000) {
  throw new Error('贴近页底的手写公式必须合并为带上下文的扩展证据范围');
}
console.log('Expanded handwriting crop tests passed: preserve edge formula context');
