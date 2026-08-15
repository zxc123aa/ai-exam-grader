import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import {
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Eye,
  FileUp,
  Loader2,
  Plus,
  SquarePen,
  Users,
  XCircle,
} from "lucide-react"
import {
  type ChangeEvent,
  type ReactNode,
  useEffect,
  useRef,
  useState,
} from "react"

import {
  ApiError,
  type ExamPublic,
  ExamsService,
  OpenAPI,
  type StudentSubmissionPublic,
} from "@/client"
import { EmptyState } from "@/components/Common/EmptyState"
import { Tag, type TagVariant } from "@/components/Common/Tag"
import { FolderBatchUpload } from "@/components/Exams/FolderBatchUpload"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { LoadingButton } from "@/components/ui/loading-button"
import useCustomToast from "@/hooks/useCustomToast"
import {
  checkPreprocessingAvailability,
  clientPreprocessWithQuads,
  detectDocumentWithScanic,
  loadImageElement,
  type NormalizedPageQuad,
} from "@/lib/document-normalizer"
import { handleError } from "@/utils"

function formatBytes(size: number) {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

function formatStatus(status?: string) {
  const value = status || "registration_pending"
  const labels: Record<string, string> = {
    registration_pending: "等待配准",
    pending: "等待处理",
    queued: "排队中",
    running: "处理中",
    processed: "已处理",
    completed: "已完成",
    failed: "失败",
    manual_confirmed: "人工确认",
    auto_registered: "自动配准",
    auto_confirmed: "自动配准",
  }
  return labels[value] || value
}

function formatQuality(quality?: number | null) {
  if (quality == null) return null
  return `${Math.round(quality * 100)}%`
}

/** 状态 → Tag 颜色：成功绿 / 待处理黄 / 进行中蓝 / 人工粉 / 失败红 */
function statusTagVariant(status?: string | null): TagVariant {
  const value = status || "registration_pending"
  if (value === "manual_confirmed") return "pink"
  if (
    ["processed", "completed", "auto_registered", "auto_confirmed"].includes(
      value,
    )
  ) {
    return "mint"
  }
  if (value === "failed") return "red"
  if (["queued", "running"].includes(value)) return "sky"
  return "amber"
}

function readSubmissionScanMetadata(submission: StudentSubmissionPublic) {
  const metadata = submission.registration_homography
  if (!metadata || typeof metadata !== "object") {
    return {
      status: null,
      warnings: [] as string[],
      totalMs: null as number | null,
    }
  }
  const quality = metadata.quality
  if (!quality || typeof quality !== "object") {
    return {
      status: null,
      warnings: [] as string[],
      totalMs: null as number | null,
    }
  }
  const qualityRecord = quality as Record<string, unknown>
  const warningLabels: Record<string, string> = {
    low_sharpness: "图片清晰度偏低",
    low_gutter_confidence: "双页中缝位置可能不准",
    split_half_page_fallback: "使用了左右页回退分割",
    vision_page_polygon_rejected: "页面边界未通过几何校验",
    doc_unwarping_unavailable: "请检查页面方向和纸张弯曲处",
    doc_unwarping_quality_rejected: "请检查纸张弯曲处是否影响文字",
  }
  const warnings = Array.isArray(qualityRecord.warnings)
    ? qualityRecord.warnings
        .map((warning) => {
          if (typeof warning !== "object" || warning === null) return null
          const item = warning as Record<string, unknown>
          const code = typeof item.code === "string" ? item.code : ""
          if (warningLabels[code]) return warningLabels[code]
          return typeof item.message === "string" ? item.message : null
        })
        .filter((message): message is string => typeof message === "string")
        .filter((message, index, items) => items.indexOf(message) === index)
    : []
  const debug = metadata.debug
  const timings =
    debug && typeof debug === "object"
      ? (debug as Record<string, unknown>).timings
      : null
  const totalMs =
    timings && typeof timings === "object"
      ? (timings as Record<string, unknown>).total_ms
      : null
  return {
    status:
      typeof qualityRecord.status === "string" ? qualityRecord.status : null,
    warnings,
    totalMs: typeof totalMs === "number" ? totalMs : null,
  }
}

async function fetchSubmissionPageImageBlob(
  examId: string,
  submissionId: string,
  pageNumber: number,
) {
  const token = localStorage.getItem("access_token")
  const base = OpenAPI.BASE || ""
  const response = await fetch(
    `${base}/api/v1/exams/${examId}/submissions/${submissionId}/pages/${pageNumber}/image`,
    {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    },
  )
  if (!response.ok) {
    throw new ApiError(
      {
        method: "GET",
        url: "/api/v1/exams/{exam_id}/submissions/{submission_id}/pages/{page_number}/image",
      },
      {
        url: response.url,
        ok: response.ok,
        status: response.status,
        statusText: response.statusText,
        body: await response.text(),
      },
      "Failed to load student submission preview",
    )
  }
  return response.blob()
}

function SubmissionPreview({
  examId,
  submission,
}: {
  examId: string
  submission: StudentSubmissionPublic
}) {
  const pageCount = submission.page_count ?? 1
  const [pageNumber, setPageNumber] = useState(1)
  const [contentUrl, setContentUrl] = useState<string | null>(null)
  const { data, isLoading, isError } = useQuery({
    queryKey: [
      "student-submission-page-image",
      examId,
      submission.id,
      pageNumber,
    ],
    queryFn: () =>
      fetchSubmissionPageImageBlob(examId, submission.id, pageNumber),
  })
  const regionsQuery = useQuery({
    queryKey: [
      "student-submission-template-regions",
      examId,
      submission.id,
      pageNumber,
    ],
    queryFn: () =>
      ExamsService.readStudentSubmissionTemplateRegions({
        examId,
        submissionId: submission.id,
        pageNumber,
      }),
  })

  useEffect(() => {
    if (!data) {
      setContentUrl(null)
      return
    }
    const url = URL.createObjectURL(data)
    setContentUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [data])

  useEffect(() => {
    setPageNumber((value) => Math.min(Math.max(value, 1), pageCount))
  }, [pageCount])

  return (
    <div className="grid gap-3 rounded-2xl border bg-card p-4 shadow-card">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-medium">
            {submission.stored_file.original_filename}
          </div>
          <div className="text-xs text-muted-foreground tabular-nums">
            第 {pageNumber} / {pageCount} 页
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={pageNumber <= 1}
            onClick={() => setPageNumber((value) => Math.max(1, value - 1))}
          >
            <ChevronLeft />
            上一页
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={pageNumber >= pageCount}
            onClick={() =>
              setPageNumber((value) => Math.min(pageCount, value + 1))
            }
          >
            下一页
            <ChevronRight />
          </Button>
        </div>
      </div>
      {isError ? (
        <div className="rounded-md border p-6 text-sm text-destructive">
          无法加载答卷预览。
        </div>
      ) : isLoading || !contentUrl ? (
        <div className="flex items-center gap-2 rounded-md border p-6 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" />
          正在加载预览
        </div>
      ) : (
        <div
          className="relative overflow-hidden rounded-md border bg-muted/20"
          data-testid="submission-preview-canvas"
        >
          <img
            alt={submission.stored_file.original_filename}
            className="block w-full select-none"
            draggable={false}
            src={contentUrl}
          />
          {(regionsQuery.data?.data ?? []).map((region) => (
            <div
              key={region.id}
              className="absolute border-2 border-sky-500 bg-sky-500/10"
              data-testid={`submission-overlay-region-${region.label}`}
              style={{
                left: `${region.x * 100}%`,
                top: `${region.y * 100}%`,
                width: `${region.width * 100}%`,
                height: `${region.height * 100}%`,
              }}
            >
              <span className="absolute left-1 top-1 rounded-sm bg-sky-600 px-1.5 py-0.5 text-xs font-medium text-white">
                {region.label}
              </span>
            </div>
          ))}
        </div>
      )}
      {!regionsQuery.isLoading &&
        !regionsQuery.isError &&
        (regionsQuery.data?.data ?? []).length === 0 && (
          <div className="text-xs text-muted-foreground">
            当前页面还没有模板题区。
          </div>
        )}
    </div>
  )
}

function isSubmissionPdf(file: File) {
  return (
    file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf")
  )
}

function isSubmissionZip(file: File) {
  return (
    file.type === "application/zip" || file.name.toLowerCase().endsWith(".zip")
  )
}

/** 横版双页摊开的照片：把检测到的整张三段式四角从中缝拆成左右两页 */
function splitNormalizedSpreadQuad(page: NormalizedPageQuad) {
  const [topLeft, topRight, bottomRight, bottomLeft] = page.points
  const midpoint = (
    a: { x: number; y: number },
    b: { x: number; y: number },
  ) => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 })
  const topMid = midpoint(topLeft, topRight)
  const bottomMid = midpoint(bottomLeft, bottomRight)
  const pages: NormalizedPageQuad[] = [
    {
      label: "left",
      points: [topLeft, topMid, bottomMid, bottomLeft],
    },
    {
      label: "right",
      points: [topMid, topRight, bottomRight, bottomMid],
    },
  ]
  return pages
}

/** 检测结果的可信下限：四角多边形至少要盖住画面 40%，否则视为误检 */
const MIN_DETECTION_AREA_RATIO = 0.4

/** 四角多边形占整图面积比例（归一化坐标，shoelace 公式） */
function quadAreaRatio(page: NormalizedPageQuad) {
  const [a, b, c, d] = page.points
  return (
    Math.abs(
      a.x * (b.y - d.y) +
        b.x * (c.y - a.y) +
        c.x * (d.y - b.y) +
        d.x * (a.y - c.y),
    ) / 2
  )
}

/** 检测失败/误检时的整图四角（内缩 3%），与模板卷四角编辑器同款兜底 */
function buildFullFrameQuad(inset = 0.03): NormalizedPageQuad {
  return {
    label: "full_frame",
    points: [
      { x: inset, y: inset },
      { x: 1 - inset, y: inset },
      { x: 1 - inset, y: 1 - inset },
      { x: inset, y: 1 - inset },
    ],
  }
}

export type ClientProcessedSubmissionPhoto = {
  pages: Array<{ name: string; blob: Blob }>
  /** 浏览器内文档检测置信度（0-1），检测失败取不到时为 null */
  quality: number | null
}

/**
 * 学生答卷照片的客户端预处理：浏览器内检测四角 → OpenCV.js（Web Worker）
 * 摆正/双页拆分/增强，返回可直接上传的 JPEG 页。
 *
 * 检测不到或误检（覆盖率过低）时退用整图四角继续做增强和双页拆分；
 * 只有 worker 处理本身失败才返回 null，调用方静默回退服务端 preprocess-photo。
 */
export async function preprocessSubmissionPhotoOnClient(
  file: File,
): Promise<ClientProcessedSubmissionPhoto | null> {
  if (!checkPreprocessingAvailability().supported) return null
  try {
    const image = await loadImageElement(file)
    const detection = await detectDocumentWithScanic(image)
    const detected =
      detection.success && detection.pages.length > 0
        ? detection.pages[0]
        : null
    const baseQuad =
      detected && quadAreaRatio(detected) >= MIN_DETECTION_AREA_RATIO
        ? detected
        : buildFullFrameQuad()

    // 横版照片视为双页摊开，从中缝拆成左右两页（与模板卷 spread 模式一致）
    const width = image.naturalWidth || image.width
    const height = image.naturalHeight || image.height
    const pages =
      width >= height * 1.18 ? splitNormalizedSpreadQuad(baseQuad) : [baseQuad]

    const result = await clientPreprocessWithQuads(file, pages)
    if (!result.clientProcessed || result.pages.length === 0) return null

    const stem = file.name.replace(/\.[^.]+$/, "") || "scan"
    return {
      pages: result.pages.map((page, index) => ({
        name: `${stem}-p${index + 1}.jpg`,
        blob: page.blob,
      })),
      quality: detection.confidence,
    }
  } catch (err) {
    console.warn(
      "[submission-photo] Client preprocessing failed, falling back to server:",
      err,
    )
    return null
  }
}

export function StudentSubmissionsContent({
  exam,
  active = true,
  onUploadingChange,
}: {
  exam: ExamPublic
  active?: boolean
  onUploadingChange?: (uploading: boolean) => void
}) {
  const [selectedFiles, setSelectedFiles] = useState<File[]>([])
  const [inputKey, setInputKey] = useState(0)
  const [studentName, setStudentName] = useState("")
  const [studentIdentifier, setStudentIdentifier] = useState("")
  const [previewSubmission, setPreviewSubmission] =
    useState<StudentSubmissionPublic | null>(null)
  const appendInputRef = useRef<HTMLInputElement | null>(null)
  const [appendTarget, setAppendTarget] =
    useState<StudentSubmissionPublic | null>(null)
  const [localProcessing, setLocalProcessing] = useState(false)
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const queryKey = ["student-submissions", exam.id]

  const { data, isLoading } = useQuery({
    queryKey,
    queryFn: () => ExamsService.readStudentSubmissions({ examId: exam.id }),
    enabled: active,
  })

  // 单个上传控件按文件类型分流：PDF/zip 直接作为答卷导入（zip 由后端解包合并），
  // JPG/PNG 照片先在浏览器本地校正（四角检测 → 摆正/双页拆分/增强）再上传，
  // 本地处理失败时静默回退服务端 preprocess-photo。
  const uploadMutation = useMutation({
    mutationFn: async (files: File[]) => {
      // 姓名/学号只在单份上传时预填，避免批量上传张冠李戴
      const name =
        files.length === 1 ? studentName.trim() || undefined : undefined
      const identifier =
        files.length === 1 ? studentIdentifier.trim() || undefined : undefined
      let succeeded = 0
      const failed: string[] = []
      for (const file of files) {
        try {
          if (isSubmissionPdf(file) || isSubmissionZip(file)) {
            await ExamsService.uploadStudentSubmission({
              examId: exam.id,
              formData: {
                file: file as unknown as string,
                student_name: name,
                student_identifier: identifier,
                preprocess: "auto",
              },
            })
          } else {
            setLocalProcessing(true)
            let clientPhoto: ClientProcessedSubmissionPhoto | null = null
            try {
              clientPhoto = await preprocessSubmissionPhotoOnClient(file)
            } finally {
              setLocalProcessing(false)
            }
            if (clientPhoto) {
              // 客户端已校正：第一页建答卷，其余页追加；preprocess=none
              // 避免服务端重复处理，自动归位（班级+姓名）仍由这两个入口完成。
              // 原始照片与检测置信度随第一页上传留存（原图回溯 + 质量元数据）。
              const [firstPage, ...restPages] = clientPhoto.pages
              const submission = await ExamsService.uploadStudentSubmission({
                examId: exam.id,
                formData: {
                  file: new File([firstPage.blob], firstPage.name, {
                    type: "image/jpeg",
                  }) as unknown as string,
                  original_file: file as unknown as string,
                  student_name: name,
                  student_identifier: identifier,
                  preprocess: "none",
                  client_quality: clientPhoto.quality ?? undefined,
                },
              })
              for (const page of restPages) {
                await ExamsService.appendStudentSubmissionPages({
                  examId: exam.id,
                  submissionId: submission.id,
                  formData: {
                    file: new File([page.blob], page.name, {
                      type: "image/jpeg",
                    }) as unknown as string,
                    preprocess: "none",
                  },
                })
              }
            } else {
              await ExamsService.preprocessStudentSubmissionPhoto({
                examId: exam.id,
                formData: {
                  file: file as unknown as string,
                  student_name: name,
                  student_identifier: identifier,
                },
              })
            }
          }
          succeeded += 1
        } catch {
          failed.push(file.name)
        }
      }
      return { succeeded, failed }
    },
    onSuccess: ({ succeeded, failed }) => {
      if (failed.length === 0) {
        showSuccessToast(`已上传 ${succeeded} 份学生答卷`)
      } else if (succeeded > 0) {
        showErrorToast(
          `已上传 ${succeeded} 份，${failed.length} 份失败：${failed.join("、")}`,
        )
      } else {
        showErrorToast("学生答卷上传失败")
      }
      setSelectedFiles([])
      setInputKey((value) => value + 1)
      setStudentName("")
      setStudentIdentifier("")
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey })
    },
  })

  const registrationMutation = useMutation({
    mutationFn: ({
      submission,
      registrationStatus,
    }: {
      submission: StudentSubmissionPublic
      registrationStatus: "manual_confirmed" | "failed"
    }) =>
      ExamsService.updateStudentSubmissionRegistration({
        examId: exam.id,
        submissionId: submission.id,
        requestBody:
          registrationStatus === "manual_confirmed"
            ? {
                registration_status: "manual_confirmed",
                registration_quality: 1,
                registration_notes: "教师已确认模板配准正确",
                registration_homography: {
                  matrix: [
                    [1, 0, 0],
                    [0, 1, 0],
                    [0, 0, 1],
                  ],
                },
              }
            : {
                registration_status: "failed",
                registration_quality: 0,
                registration_notes: "教师已将配准标记为失败",
              },
      }),
    onSuccess: () => {
      showSuccessToast("配准状态已更新")
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey })
    },
  })

  // 给已上传的答卷追加页面：PDF 全部页追加，照片先在浏览器本地校正
  // （失败静默回退服务端摆正分割）再追加。
  // 已配准或已有批改数据的答卷后端返回 409，不允许追加。
  const appendPagesMutation = useMutation({
    mutationFn: async ({
      submission,
      file,
    }: {
      submission: StudentSubmissionPublic
      file: File
    }) => {
      if (!isSubmissionPdf(file) && !isSubmissionZip(file)) {
        setLocalProcessing(true)
        let clientPhoto: ClientProcessedSubmissionPhoto | null = null
        try {
          clientPhoto = await preprocessSubmissionPhotoOnClient(file)
        } finally {
          setLocalProcessing(false)
        }
        if (clientPhoto) {
          let latest = submission
          for (const page of clientPhoto.pages) {
            latest = await ExamsService.appendStudentSubmissionPages({
              examId: exam.id,
              submissionId: submission.id,
              formData: {
                file: new File([page.blob], page.name, {
                  type: "image/jpeg",
                }) as unknown as string,
                preprocess: "none",
              },
            })
          }
          return latest
        }
      }
      return ExamsService.appendStudentSubmissionPages({
        examId: exam.id,
        submissionId: submission.id,
        formData: {
          file: file as unknown as string,
          preprocess: "auto",
        },
      })
    },
    onSuccess: (_data, { submission }) => {
      showSuccessToast(
        `已向「${submission.student_name || "未命名学生"}」的答卷追加页面`,
      )
    },
    onError: (error: ApiError) => {
      if (error.status === 409) {
        showErrorToast("该答卷已配准或已批改，不能追加页面")
      } else {
        handleError.call(showErrorToast, error)
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey })
      queryClient.invalidateQueries({
        queryKey: ["exam-score-summary", exam.id],
      })
    },
  })

  const handleAppendFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    // 允许再次选择同一文件时重新触发 change
    event.target.value = ""
    if (!file || !appendTarget) return
    appendPagesMutation.mutate({ submission: appendTarget, file })
  }

  const submissions = data?.data ?? []

  return (
    <div className="grid gap-5">
      <div className="grid gap-3 rounded-2xl border bg-card p-5 shadow-card">
        <div>
          <div className="text-sm font-medium">上传学生答卷</div>
          <p className="mt-1 text-xs text-muted-foreground">
            一次多选会为每个文件各创建一份答卷，适合「不同学生各传一份」的场景；同一学生有多个文件请用下方文件夹批量上传，或先传一份再用列表里的「追加页面」。PDF
            直接导入，zip（内装照片）自动解包合并，照片（JPG/PNG）会先在浏览器本地自动校正再转成答卷。姓名/学号可留空，仅单份上传时支持预填。
          </p>
        </div>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <Input
            key={inputKey}
            data-testid="submission-file-input"
            type="file"
            accept=".pdf,.jpg,.jpeg,.png,.zip,image/png,image/jpeg,application/zip"
            multiple
            onChange={(event) =>
              setSelectedFiles(Array.from(event.target.files ?? []))
            }
          />
          <LoadingButton
            data-testid="submission-upload-button"
            type="button"
            loading={uploadMutation.isPending}
            disabled={selectedFiles.length === 0}
            onClick={() => uploadMutation.mutate(selectedFiles)}
            className="sm:w-36 bg-gradient-primary text-white hover:opacity-90"
          >
            <FileUp />
            上传 {selectedFiles.length || ""}
          </LoadingButton>
        </div>
        {localProcessing && (
          <div
            data-testid="submission-local-processing-hint"
            className="flex items-center gap-2 text-xs text-muted-foreground"
          >
            <Loader2 className="size-3.5 animate-spin" />
            本地处理中…照片在你的浏览器里完成校正，首次使用需加载本地处理引擎（约
            11 MB），请稍候
          </div>
        )}
        {selectedFiles.length === 1 && (
          <div className="grid gap-3 sm:grid-cols-2">
            <Input
              data-testid="submission-student-name-input"
              value={studentName}
              onChange={(event) => setStudentName(event.target.value)}
              placeholder="学生姓名（可选）"
            />
            <Input
              data-testid="submission-student-identifier-input"
              value={studentIdentifier}
              onChange={(event) => setStudentIdentifier(event.target.value)}
              placeholder="学号（可选）"
            />
          </div>
        )}
      </div>

      <FolderBatchUpload
        examId={exam.id}
        onUploadingChange={onUploadingChange}
      />

      <div className="rounded-2xl border bg-card shadow-card">
        <input
          ref={appendInputRef}
          data-testid="submission-append-input"
          type="file"
          accept=".pdf,.jpg,.jpeg,.png,.zip,image/png,image/jpeg,application/zip"
          className="hidden"
          onChange={handleAppendFileChange}
        />
        <div className="flex items-center justify-between border-b px-4 py-3">
          <span className="text-sm font-medium">学生答卷</span>
          <Tag variant="indigo">{submissions.length}</Tag>
        </div>
        {isLoading ? (
          <div className="flex items-center gap-2 px-4 py-8 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" />
            正在加载答卷
          </div>
        ) : submissions.length === 0 ? (
          <EmptyState
            className="border-0 py-10"
            icon={FileUp}
            title="还没有学生答卷"
            description="上传 PDF 或照片后，在这里与试卷模板配准并预览"
          />
        ) : (
          <div className="divide-y">
            {submissions.map((submission) => {
              const scanMetadata = readSubmissionScanMetadata(submission)
              return (
                <div
                  key={submission.id}
                  className="grid gap-3 px-4 py-3 lg:grid-cols-[1fr_auto] lg:items-center"
                >
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium">
                      {submission.student_name || "未命名学生"}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {submission.student_identifier || "无学号"} ·{" "}
                      {submission.stored_file.original_filename} ·{" "}
                      {formatBytes(submission.stored_file.size_bytes)} ·{" "}
                      {submission.page_count} 页
                    </div>
                    {submission.original_stored_file_id && (
                      <div className="mt-1 flex flex-wrap items-center gap-1.5">
                        <Tag variant="indigo">已保留原图</Tag>
                        {scanMetadata.status && (
                          <Tag
                            variant={
                              scanMetadata.status === "pass" ? "mint" : "amber"
                            }
                          >
                            {scanMetadata.status === "pass"
                              ? "扫描通过"
                              : "扫描需复核"}
                          </Tag>
                        )}
                        {scanMetadata.totalMs != null && (
                          <Tag variant="sky">
                            扫描 {(scanMetadata.totalMs / 1000).toFixed(1)} 秒
                          </Tag>
                        )}
                      </div>
                    )}
                    {scanMetadata.warnings.length > 0 && (
                      <div className="mt-2 rounded-lg bg-amber-500/10 px-3 py-2 text-xs text-amber-600 dark:text-amber-400">
                        {scanMetadata.warnings.slice(0, 2).join("；")}
                        {scanMetadata.warnings.length > 2
                          ? `；另有 ${scanMetadata.warnings.length - 2} 项提示`
                          : ""}
                      </div>
                    )}
                  </div>
                  <div className="flex flex-wrap items-center gap-2 lg:justify-end">
                    <Tag variant={statusTagVariant(submission.status)}>
                      {formatStatus(submission.status)}
                    </Tag>
                    <Tag
                      variant={statusTagVariant(submission.registration_status)}
                    >
                      {formatStatus(submission.registration_status)}
                      {formatQuality(submission.registration_quality)
                        ? ` · ${formatQuality(submission.registration_quality)}`
                        : ""}
                    </Tag>
                    <Button
                      data-testid={`confirm-registration-${submission.id}`}
                      variant="outline"
                      size="sm"
                      disabled={registrationMutation.isPending}
                      onClick={() =>
                        registrationMutation.mutate({
                          submission,
                          registrationStatus: "manual_confirmed",
                        })
                      }
                    >
                      <CheckCircle2 />
                      确认配准
                    </Button>
                    <Button
                      data-testid={`fail-registration-${submission.id}`}
                      variant="outline"
                      size="sm"
                      disabled={registrationMutation.isPending}
                      onClick={() =>
                        registrationMutation.mutate({
                          submission,
                          registrationStatus: "failed",
                        })
                      }
                    >
                      <XCircle />
                      标记失败
                    </Button>
                    <Button
                      data-testid={`submission-append-button-${submission.id}`}
                      variant="outline"
                      size="sm"
                      disabled={appendPagesMutation.isPending}
                      onClick={() => {
                        setAppendTarget(submission)
                        appendInputRef.current?.click()
                      }}
                    >
                      <Plus />
                      追加页面
                    </Button>
                    <Button
                      data-testid={`submission-preview-button-${submission.id}`}
                      variant="outline"
                      size="sm"
                      onClick={() => setPreviewSubmission(submission)}
                    >
                      <Eye />
                      预览
                    </Button>
                    <Button variant="outline" size="sm" asChild>
                      <Link
                        to="/exams/$examId/workbench"
                        params={{ examId: exam.id }}
                        search={{ student: submission.student_name ?? "" }}
                      >
                        <SquarePen />
                        复核
                      </Link>
                    </Button>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {previewSubmission && (
        <SubmissionPreview examId={exam.id} submission={previewSubmission} />
      )}
    </div>
  )
}

export default function StudentSubmissionsDialog({
  exam,
  trigger,
}: {
  exam: ExamPublic
  trigger?: ReactNode
}) {
  const [isOpen, setIsOpen] = useState(false)
  const [isBatchUploading, setIsBatchUploading] = useState(false)
  const { showErrorToast } = useCustomToast()

  const handleOpenChange = (nextOpen: boolean) => {
    if (!nextOpen && isBatchUploading) {
      showErrorToast("正在批量上传答卷，请等待完成后再关闭")
      return
    }
    setIsOpen(nextOpen)
  }

  return (
    <Dialog open={isOpen} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        {trigger ?? (
          <Button variant="outline" size="sm">
            <Users />
            学生答卷
          </Button>
        )}
      </DialogTrigger>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle>{exam.title} · 学生答卷</DialogTitle>
          <DialogDescription>
            上传学生答卷 PDF 或图片，并与试卷模板进行配准。
          </DialogDescription>
        </DialogHeader>
        <StudentSubmissionsContent
          exam={exam}
          active={isOpen}
          onUploadingChange={setIsBatchUploading}
        />
      </DialogContent>
    </Dialog>
  )
}
