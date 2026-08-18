import { useMutation } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import {
  BookMarked,
  Camera,
  CircleAlert,
  History,
  ImagePlus,
  Loader2,
  RefreshCw,
  Sparkles,
} from "lucide-react"
import { useEffect, useRef, useState } from "react"
import type { SnapGradePublic, SnapSolvePublic } from "@/client"
import { OpenAPI } from "@/client"
import {
  MarkdownMath,
  MarkdownMathSections,
} from "@/components/Common/MarkdownMath"
import { PageHead } from "@/components/Common/PageHead"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { workflowApi } from "@/lib/workflow-api"

export const Route = createFileRoute("/_layout/my/snap")({
  component: MySnapPage,
  head: () => ({ meta: [{ title: "拍题答疑 - 点凡阅卷" }] }),
})

type SnapMode = "solve" | "grade"
type SnapResult = SnapSolvePublic | SnapGradePublic

type SnapHistoryItem = {
  id: number
  result: SnapResult
}

/** 手机/平板提供「拍照」直拍；桌面浏览器只给「上传图片」。 */
function isTouchDevice(): boolean {
  if (typeof window === "undefined") return false
  return (
    window.matchMedia("(pointer: coarse)").matches ||
    /Android|iPhone|iPad|Mobile/i.test(navigator.userAgent)
  )
}

function formatScore(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
}

function ResultSection({
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
function SaveToWrongbookButton({
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

function SnapResultCard({ result }: { result: SnapResult }) {
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
              <span className="font-bold text-3xl tracking-tight">
                {formatScore(item.score)}
              </span>
              <span className="text-muted-foreground text-sm">
                / {formatScore(item.max_score)} 分
              </span>
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
            <span className="font-bold text-3xl tracking-tight">
              {formatScore(result.score)}
            </span>
            <span className="text-muted-foreground text-sm">
              / {formatScore(result.max_score)} 分
            </span>
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

/** 连排选项拆行：「A.条形 B.柱形」→ 每个选项一行，题目更好读。 */
function formatQuestionText(text: string): string {
  return text.replace(/(?<!^)\s+([A-F])[.、]\s*/gm, "\n$1. ")
}

function MySnapPage() {
  const [mode, setMode] = useState<SnapMode>("solve")
  const [file, setFile] = useState<File | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [maxScore, setMaxScore] = useState("10")
  const [result, setResult] = useState<SnapResult | null>(null)
  const [history, setHistory] = useState<SnapHistoryItem[]>([])
  const cameraInputRef = useRef<HTMLInputElement>(null)
  const albumInputRef = useRef<HTMLInputElement>(null)
  const touchDevice = isTouchDevice()

  useEffect(() => {
    if (!file) {
      setPreviewUrl(null)
      return
    }
    const url = URL.createObjectURL(file)
    setPreviewUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [file])

  const snap = useMutation({
    mutationFn: (input: { file: File; mode: SnapMode; maxScore: string }) => {
      const body = new FormData()
      body.set("image", input.file)
      body.set("mode", input.mode)
      if (input.mode === "grade") {
        body.set("max_score", input.maxScore || "10")
      }
      return workflowApi<SnapResult>("/students/me/snap", {
        method: "POST",
        body,
      })
    },
    onSuccess: (data) => {
      setResult(data)
      setHistory((items) =>
        [{ id: Date.now(), result: data }, ...items].slice(0, 5),
      )
    },
  })

  // 答疑（solve）走流式：解答像打字一样逐段出来，不用干等
  const [streamText, setStreamText] = useState("")
  const [questionExpanded, setQuestionExpanded] = useState(false)
  const [streamQuestion, setStreamQuestion] = useState("")
  const [streamError, setStreamError] = useState<string | null>(null)
  const [streaming, setStreaming] = useState(false)

  const submitSolveStream = async (fileToSubmit: File) => {
    setStreaming(true)
    setStreamError(null)
    setStreamText("")
    setStreamQuestion("")
    setResult(null)
    try {
      const body = new FormData()
      body.set("image", fileToSubmit)
      const token = localStorage.getItem("access_token")
      const response = await fetch(
        `${OpenAPI.BASE || ""}/api/v1/students/me/snap/stream`,
        {
          method: "POST",
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          body,
        },
      )
      if (!response.ok || !response.body) {
        const text = await response.text().catch(() => "")
        throw new Error(text || `请求失败（${response.status}）`)
      }
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ""
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const events = buffer.split("\n\n")
        buffer = events.pop() ?? ""
        for (const event of events) {
          const line = event.split("\n").find((l) => l.startsWith("data:"))
          if (!line) continue
          const data = JSON.parse(line.slice(5).trim())
          if (data.type === "question") {
            setStreamQuestion(data.text)
          } else if (data.type === "delta") {
            setStreamText((current) => current + data.text)
          } else if (data.type === "error") {
            throw new Error(data.text)
          }
        }
      }
    } catch (error) {
      setStreamError(error instanceof Error ? error.message : String(error))
    } finally {
      setStreaming(false)
    }
  }

  const busy = snap.isPending || streaming

  const pickFile = (selected: File | null) => {
    if (!selected) return
    setFile(selected)
    setResult(null)
    snap.reset()
  }

  const switchMode = (next: string) => {
    setMode(next as SnapMode)
    setResult(null)
    snap.reset()
  }

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6">
      <PageHead
        title="拍题答疑"
        subtitle="拍一道题，看参考答案和讲解；也能给写了答案的题目打分"
      />
      <Tabs value={mode} onValueChange={switchMode}>
        <TabsList className="w-full">
          <TabsTrigger value="solve" data-testid="tab-solve">
            拍题答疑
          </TabsTrigger>
          <TabsTrigger value="grade" data-testid="tab-grade">
            拍照批改
          </TabsTrigger>
        </TabsList>
      </Tabs>

      <div className="grid gap-4 rounded-[10px] border bg-card p-5">
        <p className="text-muted-foreground text-sm">
          {mode === "solve"
            ? "拍一道完整的题目，帮你读出题目并给出答案和讲解。"
            : "拍一道写了你答案的题，帮你读出作答并打分点评。"}
        </p>
        {/* 隐藏的文件入口：相机直拍 / 相册或文件选择 */}
        <input
          ref={cameraInputRef}
          data-testid="snap-camera-input"
          type="file"
          accept="image/*"
          capture="environment"
          className="hidden"
          onChange={(e) => {
            pickFile(e.target.files?.[0] ?? null)
            e.target.value = ""
          }}
        />
        <input
          ref={albumInputRef}
          data-testid="snap-upload-input"
          type="file"
          accept="image/*"
          className="hidden"
          onChange={(e) => {
            pickFile(e.target.files?.[0] ?? null)
            e.target.value = ""
          }}
        />
        {previewUrl ? (
          <div className="grid gap-3">
            <img
              src={previewUrl}
              alt="题目照片预览"
              className="max-h-44 w-fit rounded-[10px] border object-contain"
            />
            <div className="flex flex-wrap items-center gap-2">
              <Button
                data-testid="snap-submit"
                disabled={busy}
                onClick={() =>
                  mode === "solve"
                    ? submitSolveStream(file as File)
                    : snap.mutate({ file: file as File, mode, maxScore })
                }
              >
                {busy ? (
                  <>
                    <Loader2 className="animate-spin" />
                    正在看题…
                  </>
                ) : (
                  "开始识别"
                )}
              </Button>
              <Button
                variant="ghost"
                disabled={busy}
                onClick={() =>
                  (touchDevice
                    ? cameraInputRef
                    : albumInputRef
                  ).current?.click()
                }
              >
                重新选择
              </Button>
            </div>
          </div>
        ) : touchDevice ? (
          <div className="flex flex-wrap gap-2">
            <Button
              data-testid="snap-camera-button"
              onClick={() => cameraInputRef.current?.click()}
            >
              <Camera />
              拍照
            </Button>
            <Button
              variant="outline"
              data-testid="snap-album-button"
              onClick={() => albumInputRef.current?.click()}
            >
              <ImagePlus />
              从相册选
            </Button>
          </div>
        ) : (
          <div>
            <Button
              data-testid="snap-upload-button"
              onClick={() => albumInputRef.current?.click()}
            >
              <ImagePlus />
              上传题目照片
            </Button>
          </div>
        )}
        {mode === "grade" && (
          <div className="flex items-center gap-2 text-sm">
            <span className="text-muted-foreground">这道题满分</span>
            <Input
              data-testid="snap-max-score"
              type="number"
              min={1}
              max={100}
              value={maxScore}
              onChange={(e) => setMaxScore(e.target.value)}
              className="h-8 w-20"
            />
            <span className="text-muted-foreground">分</span>
          </div>
        )}
        {snap.isError && (
          <div
            className="flex items-center gap-2 rounded-[10px] border border-destructive/30 bg-destructive/5 px-3 py-2 text-destructive text-sm"
            data-testid="snap-error"
          >
            <CircleAlert className="size-4 shrink-0" />
            <span className="flex-1">
              {snap.error instanceof Error
                ? snap.error.message
                : "识别失败，请重试"}
            </span>
            {file && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => snap.mutate({ file, mode, maxScore })}
              >
                <RefreshCw />
                重试
              </Button>
            )}
          </div>
        )}
      </div>

      {snap.isPending && (
        <div className="flex items-center gap-2 text-muted-foreground text-sm">
          <Sparkles className="size-4" />
          正在看题，照片大的话可能要一两分钟，请别关闭页面…
        </div>
      )}
      {/* 流式答疑：识别出题目后逐段输出解答 */}
      {(streaming || streamText || streamError) && (
        <div
          className="grid gap-4 rounded-[10px] border bg-card p-5"
          data-testid="snap-stream-result"
        >
          {streamQuestion && (
            <ResultSection title="题目">
              <span className="block">
                <span
                  className={`block whitespace-pre-wrap ${questionExpanded ? "" : "max-h-28 overflow-hidden"}`}
                  style={
                    questionExpanded
                      ? undefined
                      : {
                          maskImage:
                            "linear-gradient(to bottom, black 60%, transparent)",
                        }
                  }
                >
                  {formatQuestionText(streamQuestion)}
                </span>
                <button
                  type="button"
                  className="mt-1 text-primary text-xs hover:underline"
                  onClick={() => setQuestionExpanded((value) => !value)}
                >
                  {questionExpanded ? "收起" : "展开全文"}
                </button>
              </span>
            </ResultSection>
          )}
          <ResultSection title={streaming ? "解答（生成中…）" : "解答"}>
            {streaming ? (
              <MarkdownMath text={streamText || "…"} className="text-sm" />
            ) : (
              <MarkdownMathSections text={streamText} className="text-sm" />
            )}
          </ResultSection>
          {streamError && (
            <div className="flex items-center gap-2 text-destructive text-sm">
              <CircleAlert className="size-4 shrink-0" />
              <span className="flex-1">{streamError}</span>
              {file && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => submitSolveStream(file)}
                >
                  <RefreshCw />
                  重试
                </Button>
              )}
            </div>
          )}
          {!streaming && !streamError && streamText && (
            <SaveToWrongbookButton
              questionText={streamQuestion}
              comment={`解答：${streamText.slice(0, 1500)}`}
            />
          )}
        </div>
      )}
      {result && !snap.isPending && <SnapResultCard result={result} />}

      {history.length > 0 && (
        <div className="grid gap-2">
          <div className="flex items-center gap-1.5 font-medium text-muted-foreground text-xs">
            <History className="size-3.5" />
            本次看过的题
          </div>
          <div className="grid gap-2">
            {history.map((item) => (
              <button
                key={item.id}
                type="button"
                className="truncate rounded-[10px] border bg-card px-4 py-2.5 text-left text-sm transition-colors hover:border-primary"
                onClick={() => setResult(item.result)}
              >
                <span className="mr-2 text-muted-foreground text-xs">
                  {"student_answer" in item.result ? "批改" : "答疑"}
                </span>
                {item.result.question_text}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
