import { useMutation } from "@tanstack/react-query"
import { BookMarked } from "lucide-react"
import { useState } from "react"
import type { SnapGradePublic, SnapSolvePublic } from "@/client"
import { MarkdownMath } from "@/components/Common/MarkdownMath"
import { Button } from "@/components/ui/button"
import { workflowApi } from "@/lib/workflow-api"

/**
 * 拍题结果展示组件：拍题答疑页（刚拍完）和拍题记录页（历史回看）共用。
 */

export type SnapResult = SnapSolvePublic | SnapGradePublic

/** 服务端拍题历史（snaprecord）：列表项 + 详情载荷。 */
export type SnapRecordListItem = {
  id: string
  mode: string
  title: string
  created_at: string
}
export type SnapRecordPayload =
  | { kind: "solve"; items: { question: string; answer: string }[] }
  | {
      kind: "solve"
      question_text: string
      answer: string
      explanation: string
    }
  | { kind: "grade"; result: SnapGradePublic }

export function formatScore(value: number | null | undefined): string {
  if (value == null) return "—"
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
}

/** 连排选项拆行：「A.条形 B.柱形」→ 每个选项一行，题目更好读。 */
export function formatQuestionText(text: string): string {
  return text.replace(/(?<!^)\s+([A-F])[.、]\s*/gm, "\n$1. ")
}

export function ResultSection({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}) {
  return (
    <div className="grid gap-1.5">
      <div className="font-medium text-muted-foreground text-xs">{title}</div>
      <div className="whitespace-pre-wrap text-sm leading-relaxed">
        {children}
      </div>
    </div>
  )
}

/** 把拍到的题收进错题本：成功后记 state 置灰。 */
export function SaveToWrongbookButton({
  questionText,
  studentAnswer,
  comment,
}: {
  questionText: string
  studentAnswer?: string
  comment?: string
}) {
  const [saved, setSaved] = useState(false)
  const save = useMutation({
    mutationFn: () =>
      workflowApi("/students/me/wrongbook/entries/from-snap", {
        method: "POST",
        body: JSON.stringify({
          question_text: questionText,
          student_answer: studentAnswer ?? "",
          comment: comment ?? "",
        }),
      }),
    onSuccess: () => setSaved(true),
  })
  return (
    <span className="inline-flex items-center gap-2">
      <Button
        variant="outline"
        size="sm"
        disabled={save.isPending || saved || !questionText.trim()}
        onClick={() => save.mutate()}
      >
        <BookMarked className="size-4" />
        {saved ? "已收进错题本" : save.isPending ? "保存中…" : "收进错题本"}
      </Button>
      {save.isError && (
        <span className="text-destructive text-xs">保存失败，请重试</span>
      )}
    </span>
  )
}

export function SnapResultCard({ result }: { result: SnapResult }) {
  // 批改模式：整页多题时逐题展示
  if ("student_answer" in result && (result.items?.length ?? 0) > 1) {
    return (
      <div className="grid gap-4" data-testid="snap-result">
        {result.items!.map((item, index) => (
          <div
            key={`snap-item-${index}`}
            className="grid gap-4 rounded-[10px] border bg-card p-5"
          >
            <ResultSection title={`第 ${index + 1} 题`}>
              {item.question_text}
            </ResultSection>
            <ResultSection title="你的作答">
              {item.student_answer}
            </ResultSection>
            <div className="flex items-baseline gap-1.5 border-t pt-4">
              {item.score == null ? (
                <span className="font-medium text-amber-600 text-sm dark:text-amber-400">
                  请人工评分
                </span>
              ) : (
                <>
                  <span className="font-bold text-3xl tracking-tight">
                    {formatScore(item.score)}
                  </span>
                  <span className="text-muted-foreground text-sm">
                    / {formatScore(item.max_score)} 分
                  </span>
                </>
              )}
            </div>
            <ResultSection title="点评">{item.comment}</ResultSection>
            <SaveToWrongbookButton
              questionText={item.question_text}
              studentAnswer={item.student_answer}
              comment={item.comment}
            />
          </div>
        ))}
      </div>
    )
  }
  return (
    <div
      className="grid gap-4 rounded-[10px] border bg-card p-5"
      data-testid="snap-result"
    >
      <ResultSection title="题目">{result.question_text}</ResultSection>
      {"student_answer" in result ? (
        <>
          <ResultSection title="你的作答">
            {result.student_answer}
          </ResultSection>
          <div className="flex items-baseline gap-1.5 border-t pt-4">
            {result.score == null ? (
              <span className="font-medium text-amber-600 text-sm dark:text-amber-400">
                请人工评分
              </span>
            ) : (
              <>
                <span className="font-bold text-3xl tracking-tight">
                  {formatScore(result.score)}
                </span>
                <span className="text-muted-foreground text-sm">
                  / {formatScore(result.max_score)} 分
                </span>
              </>
            )}
          </div>
          <ResultSection title="点评">{result.comment}</ResultSection>
          <SaveToWrongbookButton
            questionText={result.question_text}
            studentAnswer={result.student_answer}
            comment={result.comment}
          />
        </>
      ) : (
        <>
          <ResultSection title="参考答案">{result.answer}</ResultSection>
          <ResultSection title="讲解">{result.explanation}</ResultSection>
          <SaveToWrongbookButton
            questionText={result.question_text}
            comment={`参考答案：${result.answer}`}
          />
        </>
      )}
    </div>
  )
}

/** 历史记录详情：三种载荷——流式多题、单题答疑、拍照批改。 */
export function SnapRecordView({ payload }: { payload: SnapRecordPayload }) {
  if (payload.kind === "grade") {
    return <SnapResultCard result={payload.result} />
  }
  if ("items" in payload) {
    return (
      <div className="grid gap-4">
        {payload.items.map((item, index) => (
          <div
            key={`record-item-${index}`}
            className="grid gap-4 rounded-[10px] border bg-card p-5"
          >
            <ResultSection title={`第 ${index + 1} 题`}>
              <span className="whitespace-pre-wrap">
                {formatQuestionText(item.question)}
              </span>
            </ResultSection>
            <ResultSection title="解答">
              <MarkdownMath text={item.answer} className="text-sm" />
            </ResultSection>
          </div>
        ))}
      </div>
    )
  }
  return (
    <SnapResultCard
      result={{
        mode: "solve",
        question_text: payload.question_text,
        answer: payload.answer,
        explanation: payload.explanation,
      }}
    />
  )
}
