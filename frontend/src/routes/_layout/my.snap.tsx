import { useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import {
  Camera,
  CircleAlert,
  History,
  ImagePlus,
  Loader2,
  RefreshCw,
  Sparkles,
} from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { OpenAPI } from "@/client"
import { MarkdownMath } from "@/components/Common/MarkdownMath"
import { PageHead } from "@/components/Common/PageHead"
import {
  formatQuestionText,
  formatScore,
  ResultSection,
  SaveToWrongbookButton,
} from "@/components/Common/SnapRecordView"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { workflowApi } from "@/lib/workflow-api"

export const Route = createFileRoute("/_layout/my/snap")({
  component: MySnapPage,
  head: () => ({ meta: [{ title: "拍题答疑 - 点凡阅卷" }] }),
})

type SnapMode = "solve" | "grade"

/** 答疑（solve）流式卡：解答逐段流进对应卡片。 */
type StreamCard = {
  question: string
  answer: string
  state: "waiting" | "streaming" | "done" | "error"
  error?: string
}
/** 批改（grade）流式卡：判完一题填一题的分数和评语。 */
type GradeCard = {
  question: string
  studentAnswer: string
  score: number | null
  /** 卷面标注的该题满分；卷面没标时用页面上的默认满分 */
  maxScore: number | null
  comment: string
  state: "waiting" | "done" | "error"
  error?: string
}

/**
 * 页面状态缓存：跳到错题本再回来，识别结果不丢。
 * sessionStorage——关掉标签页自动清，不污染长期存储。
 */
const SNAP_STATE_KEY = "snap-page-state"

function loadSnapPageState(): {
  mode: SnapMode
  streamCards: StreamCard[]
  gradeCards: GradeCard[]
} | null {
  try {
    const raw = sessionStorage.getItem(SNAP_STATE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    const streamCards = (parsed.streamCards ?? []).map((card: StreamCard) =>
      // 流式中途离开的状态已死：标成错误，可「重试本题」
      card.state === "streaming" || card.state === "waiting"
        ? { ...card, state: "error" as const, error: "生成中断，可重试本题" }
        : card,
    )
    const gradeCards = (parsed.gradeCards ?? []).map((card: GradeCard) =>
      card.state === "waiting"
        ? { ...card, state: "error" as const, error: "批改中断，可重试本题" }
        : card,
    )
    return {
      mode: parsed.mode === "grade" ? "grade" : "solve",
      streamCards,
      gradeCards,
    }
  } catch {
    return null
  }
}

/** 手机/平板提供「拍照」直拍；桌面浏览器只给「上传图片」。 */
function isTouchDevice(): boolean {
  if (typeof window === "undefined") return false
  return (
    window.matchMedia("(pointer: coarse)").matches ||
    /Android|iPhone|iPad|Mobile/i.test(navigator.userAgent)
  )
}

/** SSE 事件流读取：逐事件回调。 */
async function consumeSse(
  response: Response,
  onEvent: (data: { type: string; [key: string]: unknown }) => void,
): Promise<void> {
  if (!response.body) throw new Error("响应为空")
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
      onEvent(JSON.parse(line.slice(5).trim()))
    }
  }
}

/** 非 200 响应体是 {"detail":"..."} JSON，别把整包 JSON 拍用户脸上。 */
async function errorMessage(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: unknown }
    if (typeof payload.detail === "string") return payload.detail
  } catch {
    /* fallthrough */
  }
  return `请求失败（${response.status}）`
}

/** 拍题流式接口（表单传图）：发图片、逐事件回调。 */
async function readSnapStream(
  path: string,
  file: File,
  fields: Record<string, string>,
  onEvent: (data: { type: string; [key: string]: unknown }) => void,
): Promise<void> {
  const body = new FormData()
  body.set("image", file)
  for (const [key, value] of Object.entries(fields)) body.set(key, value)
  const token = localStorage.getItem("access_token")
  const response = await fetch(`${OpenAPI.BASE || ""}/api/v1${path}`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body,
  })
  if (!response.ok) throw new Error(await errorMessage(response))
  await consumeSse(response, onEvent)
}

/** 单题重试流式接口（JSON 传题干）：事件流与整页一致。 */
async function readSnapStreamJson(
  path: string,
  payload: Record<string, unknown>,
  onEvent: (data: { type: string; [key: string]: unknown }) => void,
): Promise<void> {
  const token = localStorage.getItem("access_token")
  const response = await fetch(`${OpenAPI.BASE || ""}/api/v1${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(payload),
  })
  if (!response.ok) throw new Error(await errorMessage(response))
  await consumeSse(response, onEvent)
}

function MySnapPage() {
  const [mode, setMode] = useState<SnapMode>(
    () => loadSnapPageState()?.mode ?? "solve",
  )
  const [file, setFile] = useState<File | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [maxScore, setMaxScore] = useState("10")
  const queryClient = useQueryClient()
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

  const [streamCards, setStreamCards] = useState<StreamCard[]>(
    () => loadSnapPageState()?.streamCards ?? [],
  )
  const [gradeCards, setGradeCards] = useState<GradeCard[]>(
    () => loadSnapPageState()?.gradeCards ?? [],
  )
  const [cardView, setCardView] = useState<"all" | "single">("all")
  const [cardIndex, setCardIndex] = useState(0)
  const [streamError, setStreamError] = useState<string | null>(null)
  const [streaming, setStreaming] = useState(false)

  // 卡片每次更新都写进 sessionStorage——生成中途跳走也要能恢复；
  // 恢复时进行中的卡片会被标成「中断，可重试本题」。清空结果时同步清缓存
  useEffect(() => {
    try {
      if (streamCards.length === 0 && gradeCards.length === 0) {
        sessionStorage.removeItem(SNAP_STATE_KEY)
      } else {
        sessionStorage.setItem(
          SNAP_STATE_KEY,
          JSON.stringify({ mode, streamCards, gradeCards }),
        )
      }
    } catch {
      // 存储满了就放弃，缓存只是体验优化
    }
  }, [mode, streamCards, gradeCards])

  const submitSolveStream = async (fileToSubmit: File) => {
    setStreaming(true)
    setStreamError(null)
    setStreamCards([])
    setGradeCards([])
    try {
      await readSnapStream(
        "/students/me/snap/stream",
        fileToSubmit,
        {},
        (data) => {
          if (data.type === "questions") {
            setStreamCards(
              (data.items as string[]).map((question) => ({
                question,
                answer: "",
                state: "waiting" as const,
              })),
            )
          } else if (data.type === "answer-start") {
            setStreamCards((cards) =>
              cards.map((card, i) =>
                i === data.index ? { ...card, state: "streaming" } : card,
              ),
            )
          } else if (data.type === "answer-delta") {
            setStreamCards((cards) =>
              cards.map((card, i) =>
                i === data.index
                  ? { ...card, answer: card.answer + (data.text as string) }
                  : card,
              ),
            )
          } else if (data.type === "answer-done") {
            setStreamCards((cards) =>
              cards.map((card, i) =>
                i === data.index ? { ...card, state: "done" } : card,
              ),
            )
          } else if (data.type === "answer-error") {
            setStreamCards((cards) =>
              cards.map((card, i) =>
                i === data.index
                  ? { ...card, state: "error", error: data.text as string }
                  : card,
              ),
            )
          } else if (data.type === "done") {
            // 服务端已把本次解答留档，刷新历史列表
            queryClient.invalidateQueries({ queryKey: ["snap-records"] })
          } else if (data.type === "error") {
            throw new Error(data.text as string)
          }
        },
      )
    } catch (error) {
      setStreamError(error instanceof Error ? error.message : String(error))
    } finally {
      setStreaming(false)
    }
  }

  // 批改（grade）也走流式：识别完先亮出全部题目卡，逐题判完逐题填分
  const submitGradeStream = async (fileToSubmit: File) => {
    setStreaming(true)
    setStreamError(null)
    setStreamCards([])
    setGradeCards([])
    try {
      await readSnapStream(
        "/students/me/snap/grade/stream",
        fileToSubmit,
        { max_score: maxScore || "10" },
        (data) => {
          if (data.type === "grade-questions") {
            setGradeCards(
              (
                data.items as {
                  question_text: string
                  student_answer: string
                  max_score?: number
                }[]
              ).map((item) => ({
                question: item.question_text,
                studentAnswer: item.student_answer,
                score: null,
                maxScore: item.max_score ?? null,
                comment: "",
                state: "waiting" as const,
              })),
            )
          } else if (data.type === "grade-item") {
            const item = data.item as {
              score: number
              comment: string
              max_score?: number
            }
            setGradeCards((cards) =>
              cards.map((card, i) =>
                i === data.index
                  ? {
                      ...card,
                      score: item.score,
                      maxScore: item.max_score ?? card.maxScore,
                      comment: item.comment,
                      state: "done",
                    }
                  : card,
              ),
            )
          } else if (data.type === "grade-item-error") {
            setGradeCards((cards) =>
              cards.map((card, i) =>
                i === data.index
                  ? { ...card, state: "error", error: data.text as string }
                  : card,
              ),
            )
          } else if (data.type === "done") {
            queryClient.invalidateQueries({ queryKey: ["snap-records"] })
          } else if (data.type === "error") {
            throw new Error(data.text as string)
          }
        },
      )
    } catch (error) {
      setStreamError(error instanceof Error ? error.message : String(error))
    } finally {
      setStreaming(false)
    }
  }

  const busy = streaming

  // 单题重试：整页里某张卡失败时只重做这一题，不动其他卡
  const retrySolveOne = async (index: number) => {
    const card = streamCards[index]
    if (!card) return
    setStreamCards((cards) =>
      cards.map((c, i) =>
        i === index
          ? { ...c, state: "streaming", answer: "", error: undefined }
          : c,
      ),
    )
    try {
      await readSnapStreamJson(
        "/students/me/snap/solve-one/stream",
        { question_text: card.question },
        (data) => {
          if (data.type === "answer-delta") {
            setStreamCards((cards) =>
              cards.map((c, i) =>
                i === index
                  ? { ...c, answer: c.answer + (data.text as string) }
                  : c,
              ),
            )
          } else if (data.type === "done") {
            setStreamCards((cards) =>
              cards.map((c, i) => (i === index ? { ...c, state: "done" } : c)),
            )
          } else if (data.type === "error") {
            throw new Error(data.text as string)
          }
        },
      )
    } catch (error) {
      setStreamCards((cards) =>
        cards.map((c, i) =>
          i === index
            ? {
                ...c,
                state: "error",
                error: error instanceof Error ? error.message : String(error),
              }
            : c,
        ),
      )
    }
  }

  const retryGradeOne = async (index: number) => {
    const card = gradeCards[index]
    if (!card) return
    setGradeCards((cards) =>
      cards.map((c, i) =>
        i === index ? { ...c, state: "waiting", error: undefined } : c,
      ),
    )
    try {
      const item = await workflowApi<{ score: number; comment: string }>(
        "/students/me/snap/grade-one",
        {
          method: "POST",
          body: JSON.stringify({
            question_text: card.question,
            student_answer: card.studentAnswer,
            max_score: card.maxScore ?? (Number(maxScore) || 10),
          }),
        },
      )
      setGradeCards((cards) =>
        cards.map((c, i) =>
          i === index
            ? { ...c, score: item.score, comment: item.comment, state: "done" }
            : c,
        ),
      )
    } catch (error) {
      setGradeCards((cards) =>
        cards.map((c, i) =>
          i === index
            ? {
                ...c,
                state: "error",
                error: error instanceof Error ? error.message : String(error),
              }
            : c,
        ),
      )
    }
  }

  const pickFile = (selected: File | null) => {
    if (!selected) return
    setFile(selected)
    setStreamCards([])
    setGradeCards([])
    setStreamError(null)
  }

  const switchMode = (next: string) => {
    setMode(next as SnapMode)
    setStreamCards([])
    setGradeCards([])
    setStreamError(null)
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
                    : submitGradeStream(file as File)
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
            <span className="text-muted-foreground">
              默认满分（卷面没标分值时按这个）
            </span>
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
        {streamError && (
          <div
            className="flex items-center gap-2 rounded-[10px] border border-destructive/30 bg-destructive/5 px-3 py-2 text-destructive text-sm"
            data-testid="snap-error"
          >
            <CircleAlert className="size-4 shrink-0" />
            <span className="flex-1">{streamError}</span>
            {file && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() =>
                  mode === "solve"
                    ? submitSolveStream(file)
                    : submitGradeStream(file)
                }
              >
                <RefreshCw />
                重试
              </Button>
            )}
          </div>
        )}
      </div>

      {streaming && streamCards.length === 0 && gradeCards.length === 0 && (
        <div className="flex items-center gap-2 text-muted-foreground text-sm">
          <Sparkles className="size-4" />
          正在看题，照片大的话可能要一两分钟，请别关闭页面…
        </div>
      )}
      {/* 流式答疑：每题一张卡，题目在上、解答逐段流进对应卡片 */}
      {streamCards.length > 0 && (
        <div className="grid gap-4" data-testid="snap-stream-result">
          {streamCards.length > 1 && (
            <div className="flex items-center gap-1 rounded-lg border p-0.5 text-xs">
              <button
                type="button"
                className={`rounded-md px-2.5 py-1 ${cardView === "all" ? "bg-primary text-primary-foreground" : "text-muted-foreground"}`}
                onClick={() => setCardView("all")}
              >
                全部展示
              </button>
              <button
                type="button"
                className={`rounded-md px-2.5 py-1 ${cardView === "single" ? "bg-primary text-primary-foreground" : "text-muted-foreground"}`}
                onClick={() => setCardView("single")}
              >
                逐题切换
              </button>
              {cardView === "single" && (
                <span className="ml-auto pr-2 text-muted-foreground tabular-nums">
                  {Math.min(cardIndex + 1, streamCards.length)} /{" "}
                  {streamCards.length}
                </span>
              )}
            </div>
          )}
          {(cardView === "single"
            ? [streamCards[Math.min(cardIndex, streamCards.length - 1)]]
            : streamCards
          ).map((card, viewIndex) => {
            const index =
              cardView === "single"
                ? Math.min(cardIndex, streamCards.length - 1)
                : viewIndex
            return (
              <div
                key={`stream-card-${index}`}
                className="grid gap-4 rounded-[10px] border bg-card p-5"
              >
                <ResultSection title={`第 ${index + 1} 题`}>
                  <span className="whitespace-pre-wrap">
                    {formatQuestionText(card.question)}
                  </span>
                </ResultSection>
                <ResultSection
                  title={
                    card.state === "streaming"
                      ? "解答（生成中…）"
                      : card.state === "waiting"
                        ? "解答（排队中…）"
                        : "解答"
                  }
                >
                  {card.answer ? (
                    <MarkdownMath text={card.answer} className="text-sm" />
                  ) : (
                    <span className="text-muted-foreground">…</span>
                  )}
                </ResultSection>
                {card.state === "error" && (
                  <div className="flex items-center gap-2 text-destructive text-sm">
                    <CircleAlert className="size-4 shrink-0" />
                    <span className="flex-1">{card.error || "生成失败"}</span>
                    <Button
                      variant="ghost"
                      size="sm"
                      data-testid="snap-retry-one"
                      onClick={() => retrySolveOne(index)}
                    >
                      <RefreshCw />
                      重试本题
                    </Button>
                  </div>
                )}
                {card.state === "done" && (
                  <SaveToWrongbookButton
                    questionText={card.question}
                    comment={`解答：${card.answer.slice(0, 1500)}`}
                  />
                )}
              </div>
            )
          })}
          {cardView === "single" && streamCards.length > 1 && (
            <div className="flex items-center justify-between">
              <Button
                variant="outline"
                size="sm"
                disabled={cardIndex === 0}
                onClick={() => setCardIndex(cardIndex - 1)}
              >
                上一题
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={cardIndex >= streamCards.length - 1}
                onClick={() => setCardIndex(cardIndex + 1)}
              >
                下一题
              </Button>
            </div>
          )}
        </div>
      )}
      {/* 流式批改：识别完先亮全部题目卡，逐题判完逐题填分 */}
      {gradeCards.length > 0 && (
        <div className="grid gap-4" data-testid="snap-grade-stream-result">
          {gradeCards.map((card, index) => (
            <div
              key={`grade-card-${index}`}
              className="grid gap-4 rounded-[10px] border bg-card p-5"
            >
              <ResultSection title={`第 ${index + 1} 题`}>
                <span className="whitespace-pre-wrap">
                  {formatQuestionText(card.question)}
                </span>
              </ResultSection>
              <ResultSection title="你的作答">
                {card.studentAnswer}
              </ResultSection>
              {card.state === "done" && card.score !== null ? (
                <>
                  <div className="flex items-baseline gap-1.5 border-t pt-4">
                    <span className="font-bold text-3xl tracking-tight">
                      {formatScore(card.score)}
                    </span>
                    <span className="text-muted-foreground text-sm">
                      / {card.maxScore ?? (maxScore || "10")} 分
                    </span>
                  </div>
                  <ResultSection title="点评">{card.comment}</ResultSection>
                  <SaveToWrongbookButton
                    questionText={card.question}
                    studentAnswer={card.studentAnswer}
                    comment={card.comment}
                  />
                </>
              ) : card.state === "error" ? (
                <div className="flex items-center gap-2 border-t pt-4 text-destructive text-sm">
                  <CircleAlert className="size-4 shrink-0" />
                  <span className="flex-1">
                    {card.error || "这道题批改失败"}
                  </span>
                  <Button
                    variant="ghost"
                    size="sm"
                    data-testid="snap-retry-one"
                    onClick={() => retryGradeOne(index)}
                  >
                    <RefreshCw />
                    重试本题
                  </Button>
                </div>
              ) : (
                <div className="flex items-center gap-2 border-t pt-4 text-muted-foreground text-sm">
                  <Loader2 className="size-4 animate-spin" />
                  批改中…
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="flex justify-center">
        <Link
          to="/my/snap-history"
          className="inline-flex items-center gap-1.5 text-muted-foreground text-sm transition-colors hover:text-foreground"
        >
          <History className="size-4" />
          查看拍题记录
        </Link>
      </div>
    </div>
  )
}
