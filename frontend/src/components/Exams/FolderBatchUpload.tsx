import { useQueryClient } from "@tanstack/react-query"
import {
  CheckCircle2,
  FolderUp,
  Loader2,
  RotateCcw,
  XCircle,
} from "lucide-react"
import { type ChangeEvent, useMemo, useRef, useState } from "react"

import { ExamsService } from "@/client"
import { ProgressBar } from "@/components/Common/ProgressBar"
import { Tag } from "@/components/Common/Tag"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import useCustomToast from "@/hooks/useCustomToast"
import { workflowApi } from "@/lib/workflow-api"

const SUPPORTED_FILE_PATTERN = /\.(pdf|jpe?g|png|zip)$/i
const ZIP_FILE_PATTERN = /\.zip$/i
// 页照片名几乎都是编号（1.jpg、0_0.jpg），学生姓名不会以数字/下划线开头；
// 用于区分「学生/页.pdf」与「班级/姓名.pdf」两种三层路径
const PAGE_LIKE_STEM_PATTERN = /^[\d_]/
const UPLOAD_CONCURRENCY = 3
const pathCollator = new Intl.Collator("zh-Hans-CN", { numeric: true })

function isPdfFile(file: File) {
  return (
    file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf")
  )
}

function isZipFile(file: File) {
  return file.type === "application/zip" || ZIP_FILE_PATTERN.test(file.name)
}

function fileStem(name: string) {
  return name.replace(/\.[^.]+$/, "") || name
}

type GroupStatus = "pending" | "uploading" | "done" | "failed"

interface StudentUploadGroup {
  id: string
  className: string
  studentName: string
  files: File[]
  uploadedCount: number
  /** 第一个文件创建出的答卷 ID，后续文件追加到该答卷 */
  submissionId?: string
  status: GroupStatus
  error?: string
}

interface UngroupedFile {
  file: File
  relativePath: string
}

/**
 * 解析 webkitdirectory 选中的文件列表。
 * webkitRelativePath 第一段始终是所选根文件夹名，支持的目录形态：
 * - 4 段及以上：根/班级/学生/文件 → 倒数第二段 = 学生姓名，倒数第三段 = 班级名
 * - 3 段「根/班级-姓名/文件」或「根/考试-班级-姓名/文件」→ 文件夹名按 `-`
 *   分段：两段 = 班级/姓名；三段及以上 = 倒数第二段班级、最后一段姓名
 * - 3 段「根/班级/学生.zip」（一生一 zip）→ 整个 zip 是一份答卷，学生名 = zip 文件名
 * - 3 段「根/班级/学生.pdf」（一生一 PDF，文件名不是页编号）→ 同上
 * - 3 段「根/学生/文件」（只有两层）→ 学生姓名取倒数第二段，班级为空
 * - 2 段：文件直接位于所选根目录 → 无法归组，交给用户决定
 * 非 PDF/JPG/PNG/ZIP 文件直接忽略并计数。
 */
function parseFolderFiles(files: File[]) {
  const groupMap = new Map<string, StudentUploadGroup>()
  const ungrouped: UngroupedFile[] = []
  let skipped = 0
  for (const file of files) {
    if (!SUPPORTED_FILE_PATTERN.test(file.name)) {
      skipped += 1
      continue
    }
    const relativePath = file.webkitRelativePath || file.name
    const segments = relativePath.split("/").filter(Boolean)
    if (segments.length < 3) {
      ungrouped.push({ file, relativePath })
      continue
    }
    let studentName: string
    let className: string
    if (segments.length >= 4) {
      studentName = segments[segments.length - 2]
      className = segments[segments.length - 3]
    } else {
      const parent = segments[segments.length - 2]
      const stem = fileStem(file.name)
      const flatParts = parent.split("-").filter(Boolean)
      if (flatParts.length >= 2) {
        // 平铺命名：班级-姓名 / 考试-班级-姓名
        studentName = flatParts[flatParts.length - 1]
        className = flatParts[flatParts.length - 2]
      } else if (
        isZipFile(file) ||
        (isPdfFile(file) && !PAGE_LIKE_STEM_PATTERN.test(stem))
      ) {
        // 一生一 zip / 一生一 PDF：文件名即学生姓名
        studentName = stem
        className = parent
      } else {
        studentName = parent
        className = ""
      }
    }
    const key = `${className}/${studentName}`
    const existing = groupMap.get(key)
    if (existing) {
      existing.files.push(file)
    } else {
      groupMap.set(key, {
        id: key,
        className,
        studentName,
        files: [file],
        uploadedCount: 0,
        status: "pending",
      })
    }
  }
  const groups = Array.from(groupMap.values())
  for (const group of groups) {
    group.files.sort((a, b) => pathCollator.compare(a.name, b.name))
  }
  groups.sort(
    (a, b) =>
      pathCollator.compare(a.className, b.className) ||
      pathCollator.compare(a.studentName, b.studentName),
  )
  return { groups, ungrouped, skipped }
}

function fileNameAsStudentName(file: File) {
  return fileStem(file.name)
}

function groupLabel(group: StudentUploadGroup) {
  return `${group.className || "未分班"}·${group.studentName}`
}

export function FolderBatchUpload({
  examId,
  onUploadingChange,
}: {
  examId: string
  onUploadingChange?: (uploading: boolean) => void
}) {
  const [phase, setPhase] = useState<"idle" | "preview" | "started">("idle")
  const [groups, setGroups] = useState<StudentUploadGroup[]>([])
  const [ungrouped, setUngrouped] = useState<UngroupedFile[]>([])
  const [skippedCount, setSkippedCount] = useState(0)
  const [includeUngrouped, setIncludeUngrouped] = useState(false)
  const [isUploading, setIsUploading] = useState(false)
  /** 花名册比对结果：group.id → 疑似错别字/不在册提示 */
  const [rosterHints, setRosterHints] = useState<
    Record<string, { status: string; suggestion: string | null }>
  >({})
  const inputRef = useRef<HTMLInputElement | null>(null)
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const totalFiles = useMemo(
    () => groups.reduce((sum, group) => sum + group.files.length, 0),
    [groups],
  )
  const uploadedFiles = useMemo(
    () => groups.reduce((sum, group) => sum + group.uploadedCount, 0),
    [groups],
  )
  const failedCount = useMemo(
    () => groups.filter((group) => group.status === "failed").length,
    [groups],
  )
  const activeGroups = useMemo(
    () => groups.filter((group) => group.status === "uploading"),
    [groups],
  )
  const classSummaries = useMemo(() => {
    const summaryMap = new Map<string, { students: number; files: number }>()
    for (const group of groups) {
      const key = group.className || "未分班"
      const entry = summaryMap.get(key) ?? { students: 0, files: 0 }
      entry.students += 1
      entry.files += group.files.length
      summaryMap.set(key, entry)
    }
    return Array.from(summaryMap.entries())
  }, [groups])

  const updateGroup = (id: string, patch: Partial<StudentUploadGroup>) => {
    setGroups((previous) =>
      previous.map((group) =>
        group.id === id ? { ...group, ...patch } : group,
      ),
    )
  }

  const reset = () => {
    setPhase("idle")
    setGroups([])
    setUngrouped([])
    setSkippedCount(0)
    setIncludeUngrouped(false)
  }

  const handleFolderChange = (event: ChangeEvent<HTMLInputElement>) => {
    const parsed = parseFolderFiles(Array.from(event.target.files ?? []))
    // 允许再次选择同一文件夹时重新触发 change
    event.target.value = ""
    if (parsed.groups.length === 0 && parsed.ungrouped.length === 0) {
      showErrorToast("所选文件夹中没有可上传的 PDF/JPG/PNG/ZIP 文件")
      return
    }
    setGroups(parsed.groups)
    setUngrouped(parsed.ungrouped)
    setSkippedCount(parsed.skipped)
    setIncludeUngrouped(false)
    setRosterHints({})
    setPhase("preview")
    // 花名册比对：标出疑似错别字/不在册的组，不阻塞上传
    void (async () => {
      try {
        const res = await workflowApi<{
          results: { status: string; suggestion: string | null }[]
        }>(`/exams/${examId}/roster-check`, {
          method: "POST",
          body: JSON.stringify({
            entries: parsed.groups.map((group) => ({
              class_name: group.className || null,
              student_name: group.studentName,
            })),
          }),
        })
        const hints: Record<
          string,
          { status: string; suggestion: string | null }
        > = {}
        parsed.groups.forEach((group, index) => {
          const result = res.results[index]
          if (result && result.status !== "exact") hints[group.id] = result
        })
        setRosterHints(hints)
      } catch {
        // 比对服务异常不影响上传
      }
    })()
  }

  // 单个学生组内文件顺序上传；第一个文件创建答卷，从第二个起追加到同一份答卷，
  // 即"一个学生 = 一份答卷"。任一文件失败则该组标记失败并保留已传进度与 submissionId，
  // 重试时从未传文件继续追加，避免重复创建。
  const uploadGroup = async (group: StudentUploadGroup) => {
    updateGroup(group.id, { status: "uploading", error: undefined })
    let uploaded = group.uploadedCount
    let submissionId = group.submissionId
    for (let index = uploaded; index < group.files.length; index += 1) {
      const file = group.files[index]
      try {
        if (index === 0 && !submissionId) {
          // 第一个文件：PDF/zip 直接导入（zip 由后端解包），照片先自动校正，创建答卷
          const submission =
            isPdfFile(file) || isZipFile(file)
              ? await ExamsService.uploadStudentSubmission({
                  examId,
                  formData: {
                    file: file as unknown as string,
                    student_name: group.studentName,
                    class_name: group.className || undefined,
                    preprocess: "auto",
                  },
                })
              : await ExamsService.preprocessStudentSubmissionPhoto({
                  examId,
                  formData: {
                    file: file as unknown as string,
                    student_name: group.studentName,
                    class_name: group.className || undefined,
                  },
                })
          submissionId = submission.id
          updateGroup(group.id, { submissionId })
        } else {
          // 后续文件：追加到同一份答卷（已配准/已批改的答卷会返回 409）
          if (!submissionId) {
            throw new Error("答卷创建失败，无法追加页面")
          }
          await ExamsService.appendStudentSubmissionPages({
            examId,
            submissionId,
            formData: {
              file: file as unknown as string,
              preprocess: "auto",
            },
          })
        }
        uploaded += 1
        updateGroup(group.id, { uploadedCount: uploaded })
      } catch (error) {
        updateGroup(group.id, {
          status: "failed",
          error: error instanceof Error ? error.message : "上传失败",
        })
        return false
      }
    }
    updateGroup(group.id, { status: "done" })
    return true
  }

  // 组级并发 3 的队列：组间并行、组内串行，单组失败不中断整批。
  const runQueue = async (targets: StudentUploadGroup[]) => {
    if (targets.length === 0) return
    setIsUploading(true)
    onUploadingChange?.(true)
    let cursor = 0
    let done = 0
    let failed = 0
    const workerCount = Math.min(UPLOAD_CONCURRENCY, targets.length)
    const workers = Array.from({ length: workerCount }, async () => {
      while (cursor < targets.length) {
        const group = targets[cursor]
        cursor += 1
        if (await uploadGroup(group)) done += 1
        else failed += 1
      }
    })
    await Promise.all(workers)
    setIsUploading(false)
    onUploadingChange?.(false)
    queryClient.invalidateQueries({
      queryKey: ["student-submissions", examId],
    })
    if (failed === 0) {
      showSuccessToast(`已上传 ${done} 名学生的答卷`)
    } else {
      showErrorToast(`${done} 名学生上传完成，${failed} 名失败，可单独重试`)
    }
  }

  const startUpload = () => {
    const ungroupedGroups =
      includeUngrouped && ungrouped.length > 0
        ? ungrouped.map(({ file }) => ({
            id: `/${fileNameAsStudentName(file)}`,
            className: "",
            studentName: fileNameAsStudentName(file),
            files: [file],
            uploadedCount: 0,
            status: "pending" as const,
          }))
        : []
    const queue = [...groups, ...ungroupedGroups]
    if (ungroupedGroups.length > 0) {
      setGroups(queue)
    }
    setPhase("started")
    void runQueue(queue.filter((group) => group.status !== "done"))
  }

  const retryGroup = (group: StudentUploadGroup) => {
    void runQueue([group])
  }

  const progressPercent =
    totalFiles > 0 ? Math.round((uploadedFiles / totalFiles) * 100) : 0

  return (
    <div className="grid gap-3 rounded-xl border p-4">
      <div>
        <div className="font-medium text-sm">按文件夹批量上传</div>
        <p className="mt-1 text-xs text-muted-foreground">
          三种收卷方式都支持，混放也可以：① 照片文件夹「班级/学生姓名/照片」；②
          一生一 zip「班级/李坤清.zip」，zip 内照片自动解包合并；③ 一生一
          PDF「班级/李思远.pdf」。也支持「班级-姓名/照片」平铺命名；只有「学生/文件」
          两层时按未分班处理。同一学生的所有文件合并为一份答卷：第一个文件创建答卷，
          其余文件追加为后续页面，组内按文件名编号顺序（1、2、…、10）排列。
        </p>
      </div>

      <input
        ref={(node) => {
          inputRef.current = node
          node?.setAttribute("webkitdirectory", "")
        }}
        data-testid="folder-batch-input"
        type="file"
        multiple
        className="hidden"
        onChange={handleFolderChange}
      />

      {phase === "idle" && (
        <button
          data-testid="folder-batch-picker"
          type="button"
          onClick={() => inputRef.current?.click()}
          className="flex flex-col items-center gap-2 rounded-xl border border-dashed px-4 py-8 text-muted-foreground text-sm transition-colors hover:border-primary/60 hover:text-foreground"
        >
          <FolderUp className="size-6" />
          选择班级文件夹批量上传
        </button>
      )}

      {phase === "preview" && (
        <div className="grid gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm">解析结果</span>
            {classSummaries.map(([className, summary]) => (
              <Tag key={className} variant="indigo">
                {className}（{summary.students} 人）
              </Tag>
            ))}
            <Tag variant="sky">{totalFiles} 个文件</Tag>
          </div>
          <div className="max-h-48 divide-y overflow-y-auto rounded-xl border">
            {groups.map((group) => (
              <div
                key={group.id}
                className="flex items-center justify-between gap-3 px-3 py-2 text-sm"
              >
                <span className="min-w-0 truncate">{groupLabel(group)}</span>
                {rosterHints[group.id] && (
                  <span
                    className="shrink-0 text-amber-600 text-xs dark:text-amber-400"
                    data-testid="roster-hint"
                  >
                    {rosterHints[group.id].status === "fuzzy"
                      ? `不在花名册，是否是 ${rosterHints[group.id].suggestion}？`
                      : "不在花名册，将新建学生"}
                  </span>
                )}
                <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
                  {group.files.length} 个文件
                </span>
              </div>
            ))}
          </div>
          {skippedCount > 0 && (
            <p className="text-xs text-muted-foreground">
              已忽略 {skippedCount} 个不支持的文件（仅支持 PDF/JPG/PNG/ZIP）。
            </p>
          )}
          {ungrouped.length > 0 && (
            <div className="grid gap-2 rounded-md bg-muted/40 px-3 py-2">
              <div className="text-xs font-medium">
                以下 {ungrouped.length}{" "}
                个文件直接位于所选文件夹根目录，无法按目录归组：
              </div>
              <ul className="max-h-24 overflow-y-auto text-xs text-muted-foreground">
                {ungrouped.map(({ relativePath }) => (
                  <li key={relativePath} className="truncate">
                    {relativePath}
                  </li>
                ))}
              </ul>
              <div className="flex items-center gap-2 text-xs">
                <Checkbox
                  id="folder-batch-include-ungrouped"
                  data-testid="folder-batch-include-ungrouped"
                  checked={includeUngrouped}
                  onCheckedChange={(value) =>
                    setIncludeUngrouped(value === true)
                  }
                />
                <label htmlFor="folder-batch-include-ungrouped">
                  按「未分班 + 文件名作为学生姓名」一并上传（不勾选则跳过）
                </label>
              </div>
            </div>
          )}
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={reset}>
              重新选择
            </Button>
            <Button data-testid="folder-batch-start" onClick={startUpload}>
              <FolderUp />
              开始上传
            </Button>
          </div>
        </div>
      )}

      {phase === "started" && (
        <div className="grid gap-3">
          <div className="flex items-center justify-between gap-3 text-sm">
            <span>{isUploading ? "正在批量上传" : "批量上传结果"}</span>
            <span className="text-xs text-muted-foreground tabular-nums">
              {uploadedFiles}/{totalFiles} 个文件
            </span>
          </div>
          <ProgressBar
            value={progressPercent}
            striped={isUploading}
            tone={!isUploading && failedCount > 0 ? "amber" : "indigo"}
          />
          {isUploading && activeGroups.length > 0 && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="size-3.5 animate-spin" />
              <span className="truncate">
                正在上传：
                {activeGroups
                  .map((group) => {
                    const pageIndex = Math.min(
                      group.uploadedCount + 1,
                      group.files.length,
                    )
                    const action =
                      pageIndex === 1 && !group.submissionId ? "创建" : "追加"
                    return `${groupLabel(group)} 第 ${pageIndex}/${group.files.length} 页（${action}）`
                  })
                  .join("；")}
              </span>
            </div>
          )}
          {isUploading && (
            <p className="text-xs text-muted-foreground">
              上传完成前请勿关闭本对话框。
            </p>
          )}
          <div className="max-h-56 divide-y overflow-y-auto rounded-xl border">
            {groups.map((group) => (
              <div
                key={group.id}
                className="flex items-center gap-3 px-3 py-2 text-sm"
              >
                {group.status === "done" ? (
                  <CheckCircle2 className="size-4 shrink-0 text-emerald-600" />
                ) : group.status === "failed" ? (
                  <XCircle className="size-4 shrink-0 text-destructive" />
                ) : group.status === "uploading" ? (
                  <Loader2 className="size-4 shrink-0 animate-spin text-primary" />
                ) : (
                  <span className="size-4 shrink-0 rounded-full border" />
                )}
                <span className="min-w-0 flex-1 truncate">
                  {groupLabel(group)}
                  {group.status === "failed" && group.error && (
                    <span className="ml-2 text-xs text-destructive">
                      {group.error}
                    </span>
                  )}
                </span>
                <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
                  {group.uploadedCount}/{group.files.length}
                </span>
                {group.status === "failed" && !isUploading && (
                  <Button
                    data-testid={`folder-batch-retry-${group.id}`}
                    variant="outline"
                    size="sm"
                    onClick={() => retryGroup(group)}
                  >
                    <RotateCcw />
                    重试
                  </Button>
                )}
              </div>
            ))}
          </div>
          {!isUploading && (
            <div className="flex justify-end">
              <Button variant="outline" onClick={reset}>
                继续选择文件夹
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
