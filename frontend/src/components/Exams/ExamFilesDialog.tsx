import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { FileText, FileUp, Loader2 } from "lucide-react"
import { useState } from "react"

import { type ExamDocumentType, type ExamPublic, ExamsService } from "@/client"
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
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

function formatBytes(size: number) {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

function formatDocumentType(documentType?: ExamDocumentType) {
  if (documentType === "answer_key") return "Answer key"
  return "Blank exam"
}

export default function ExamFilesDialog({ exam }: { exam: ExamPublic }) {
  const [isOpen, setIsOpen] = useState(false)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const queryKey = ["exam-files", exam.id]

  const { data, isLoading } = useQuery({
    queryKey,
    queryFn: () => ExamsService.readExamFiles({ examId: exam.id }),
    enabled: isOpen,
  })

  const mutation = useMutation({
    mutationFn: (file: File) =>
      ExamsService.uploadExamFile({
        examId: exam.id,
        formData: {
          file: file as unknown as string,
          document_type: "blank_exam",
        },
      }),
    onSuccess: () => {
      showSuccessToast("Exam file uploaded")
      setSelectedFile(null)
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey })
    },
  })

  const documents = data?.data ?? []

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          <FileText />
          Files
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{exam.title}</DialogTitle>
          <DialogDescription>
            Upload the blank exam PDF or image for template marking.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <Input
              data-testid="exam-file-input"
              type="file"
              accept=".pdf,image/png,image/jpeg"
              onChange={(event) =>
                setSelectedFile(event.target.files?.[0] ?? null)
              }
            />
            <LoadingButton
              data-testid="exam-file-upload-button"
              type="button"
              loading={mutation.isPending}
              disabled={!selectedFile}
              onClick={() => selectedFile && mutation.mutate(selectedFile)}
              className="sm:w-32"
            >
              <FileUp />
              Upload
            </LoadingButton>
          </div>

          <div className="rounded-md border">
            <div className="flex items-center justify-between border-b px-4 py-3">
              <span className="text-sm font-medium">Uploaded files</span>
              <Badge variant="secondary">{documents.length}</Badge>
            </div>
            {isLoading ? (
              <div className="flex items-center gap-2 px-4 py-8 text-sm text-muted-foreground">
                <Loader2 className="size-4 animate-spin" />
                Loading files
              </div>
            ) : documents.length === 0 ? (
              <div className="px-4 py-8 text-sm text-muted-foreground">
                No files uploaded for this exam yet.
              </div>
            ) : (
              <div className="divide-y">
                {documents.map((document) => (
                  <div
                    key={document.id}
                    className="grid gap-1 px-4 py-3 sm:grid-cols-[1fr_auto] sm:items-center"
                  >
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium">
                        {document.stored_file.original_filename}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {formatDocumentType(document.document_type)} ·{" "}
                        {formatBytes(document.stored_file.size_bytes)}
                      </div>
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {document.created_at
                        ? new Date(document.created_at).toLocaleString()
                        : "No timestamp"}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
