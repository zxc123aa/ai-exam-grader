import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  FileKey2,
  FileText,
  FileUp,
  Loader2,
  Upload,
  Users,
} from "lucide-react"
import { type ReactNode, useEffect, useState } from "react"

import { type ExamPublic, ExamsService } from "@/client"
import { ExamFilesContent } from "@/components/Exams/ExamFilesDialog"
import { StudentSubmissionsContent } from "@/components/Exams/StudentSubmissionsDialog"
import { Badge } from "@/components/ui/badge"
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import useCustomToast from "@/hooks/useCustomToast"
import { workflowApi } from "@/lib/workflow-api"

export type ImportCenterTab = "blank" | "submission" | "answer"

function formatBytes(size: number) {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

function AnswerDocumentsContent({
  exam,
  active = true,
}: {
  exam: ExamPublic
  active?: boolean
}) {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [inputKey, setInputKey] = useState(0)
  const queryKey = ["exam-files", exam.id]

  const files = useQuery({
    queryKey,
    queryFn: () => ExamsService.readExamFiles({ examId: exam.id }),
    enabled: active,
  })

  const upload = useMutation({
    mutationFn: (file: File) => {
      const body = new FormData()
      body.set("file", file)
      body.set("document_type", "answer_key")
      return workflowApi<{ id: string }>(`/exams/${exam.id}/files`, {
        method: "POST",
        body,
      })
    },
    onSuccess: () => {
      setUploadFile(null)
      setInputKey((value) => value + 1)
      showSuccessToast("答案文件已上传")
    },
    onError: (error) =>
      showErrorToast(error instanceof Error ? error.message : "上传失败"),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey })
    },
  })

  const answerDocuments = (files.data?.data ?? []).filter(
    (document) => document.document_type === "answer_key",
  )

  return (
    <div className="grid gap-5">
      <div className="grid gap-3 rounded-md border p-4">
        <div>
          <div className="text-sm font-medium">上传标准答案文档</div>
          <p className="mt-1 text-xs text-muted-foreground">
            支持 PDF
            或图片（JPG/PNG）。上传后到“标准答案”页选择该文档，整理出答案与评分准则。
          </p>
        </div>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <Input
            key={inputKey}
            data-testid="answer-file-input"
            type="file"
            accept=".pdf,image/png,image/jpeg"
            onChange={(event) => setUploadFile(event.target.files?.[0] ?? null)}
          />
          <LoadingButton
            data-testid="answer-file-upload-button"
            type="button"
            loading={upload.isPending}
            disabled={!uploadFile}
            onClick={() => uploadFile && upload.mutate(uploadFile)}
            className="sm:w-36"
          >
            <FileUp />
            上传答案
          </LoadingButton>
        </div>
      </div>

      <div className="rounded-md border">
        <div className="flex items-center justify-between border-b px-4 py-3">
          <span className="text-sm font-medium">已上传的答案文档</span>
          <Badge variant="secondary">{answerDocuments.length}</Badge>
        </div>
        {files.isLoading ? (
          <div className="flex items-center gap-2 px-4 py-8 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" />
            正在加载文档
          </div>
        ) : answerDocuments.length === 0 ? (
          <div className="px-4 py-8 text-sm text-muted-foreground">
            还没有上传答案文档。
          </div>
        ) : (
          <div className="divide-y">
            {answerDocuments.map((document) => (
              <div
                key={document.id}
                className="flex items-center gap-3 px-4 py-3 text-sm"
              >
                <FileKey2 className="size-4 shrink-0 text-muted-foreground" />
                <span className="min-w-0 flex-1 truncate">
                  {document.stored_file.original_filename}
                </span>
                <span className="text-xs text-muted-foreground">
                  {formatBytes(document.stored_file.size_bytes)} ·{" "}
                  {document.page_count ?? 1} 页
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

/**
 * 考试级唯一导入入口：模板卷 / 学生答卷 / 标准答案文档 三个 tab。
 * 支持受控打开（open/onOpenChange）和自渲染触发按钮（trigger 或默认按钮），
 * initialTab 指定打开时的初始 tab。
 */
export function ImportCenterDialog({
  exam,
  trigger,
  open,
  onOpenChange,
  initialTab = "blank",
}: {
  exam: ExamPublic
  trigger?: ReactNode
  open?: boolean
  onOpenChange?: (open: boolean) => void
  initialTab?: ImportCenterTab
}) {
  const [internalOpen, setInternalOpen] = useState(false)
  const [tab, setTab] = useState<ImportCenterTab>(initialTab)
  const [isBatchUploading, setIsBatchUploading] = useState(false)
  const { showErrorToast } = useCustomToast()
  const isOpen = open ?? internalOpen
  const setOpen = (nextOpen: boolean) => {
    if (!nextOpen && isBatchUploading) {
      showErrorToast("正在批量上传答卷，请等待完成后再关闭")
      return
    }
    if (onOpenChange) onOpenChange(nextOpen)
    else setInternalOpen(nextOpen)
  }

  useEffect(() => {
    if (isOpen) setTab(initialTab)
  }, [isOpen, initialTab])

  return (
    <Dialog open={isOpen} onOpenChange={setOpen}>
      {trigger !== undefined ? (
        <DialogTrigger asChild>{trigger}</DialogTrigger>
      ) : open === undefined ? (
        <DialogTrigger asChild>
          <Button variant="outline" size="sm">
            <Upload />
            导入中心
          </Button>
        </DialogTrigger>
      ) : null}
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle>{exam.title} · 导入中心</DialogTitle>
          <DialogDescription>
            模板卷、学生答卷和标准答案文档都从这里导入。
          </DialogDescription>
        </DialogHeader>
        <Tabs
          value={tab}
          onValueChange={(value) => setTab(value as ImportCenterTab)}
        >
          <TabsList>
            <TabsTrigger value="blank" disabled={isBatchUploading}>
              <FileText />
              模板卷（空白试卷）
            </TabsTrigger>
            <TabsTrigger value="submission">
              <Users />
              学生答卷（待批改）
            </TabsTrigger>
            <TabsTrigger value="answer" disabled={isBatchUploading}>
              <FileKey2 />
              标准答案文档
            </TabsTrigger>
          </TabsList>
          <TabsContent value="blank" className="pt-4">
            <ExamFilesContent exam={exam} />
          </TabsContent>
          <TabsContent value="submission" className="pt-4">
            <StudentSubmissionsContent
              exam={exam}
              onUploadingChange={setIsBatchUploading}
            />
          </TabsContent>
          <TabsContent value="answer" className="pt-4">
            <AnswerDocumentsContent exam={exam} />
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  )
}
