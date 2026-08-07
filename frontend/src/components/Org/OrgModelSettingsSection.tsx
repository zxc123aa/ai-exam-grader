import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import {
  OrgService,
  type SchoolModelScope,
  type SchoolModelScopePublic,
} from "@/client"
import { Tag } from "@/components/Common/Tag"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

const SCOPE_COPY: Record<
  SchoolModelScope,
  { title: string; description: string }
> = {
  vision: {
    title: "卷面识别",
    description: "用于读取题目、图表和学生作答。",
  },
  reference_answer: {
    title: "参考答案",
    description: "用于生成参考答案和评分点。",
  },
  grading: {
    title: "建议评分",
    description: "用于主观题判分和复核建议。",
  },
}

function ScopeRow({
  item,
  canEdit,
  onChange,
}: {
  item: SchoolModelScopePublic
  canEdit: boolean
  onChange: (scope: SchoolModelScope, offeringId: string) => void
}) {
  const copy = SCOPE_COPY[item.scope]
  const options = item.options ?? []
  const selected = options.find(
    (option) => option.id === item.selected_option_id,
  )
  return (
    <div className="grid gap-3 py-4 sm:grid-cols-[minmax(0,1fr)_minmax(14rem,20rem)] sm:items-center">
      <div>
        <div className="flex items-center gap-2">
          <span className="font-medium text-sm">{copy.title}</span>
          {!options.length && <Tag variant="neutral">由点凡默认配置</Tag>}
        </div>
        <p className="mt-1 text-muted-foreground text-sm">
          {selected?.description || copy.description}
        </p>
      </div>
      {options.length ? (
        <Select
          value={item.selected_option_id ?? undefined}
          disabled={!canEdit}
          onValueChange={(value) => onChange(item.scope, value)}
        >
          <SelectTrigger aria-label={`${copy.title}方案`}>
            <SelectValue placeholder="使用点凡默认方案" />
          </SelectTrigger>
          <SelectContent>
            {options.map((option) => (
              <SelectItem key={option.id} value={option.id}>
                {option.display_name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : (
        <div className="text-right text-muted-foreground text-sm">
          点凡自动维护
        </div>
      )}
    </div>
  )
}

export function OrgModelSettingsSection({ canEdit }: { canEdit: boolean }) {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const settings = useQuery({
    queryKey: ["org-model-settings"],
    queryFn: () => OrgService.readOrgModelSettings(),
  })
  const update = useMutation({
    mutationFn: ({
      scope,
      offeringId,
    }: {
      scope: SchoolModelScope
      offeringId: string
    }) =>
      OrgService.updateOrgModelSetting({
        scope,
        requestBody: { offering_id: offeringId },
      }),
    onSuccess: () => {
      showSuccessToast("处理方案已更新，之后的新任务生效")
      queryClient.invalidateQueries({ queryKey: ["org-model-settings"] })
    },
    onError: handleError.bind(showErrorToast),
  })

  return (
    <section className="rounded-2xl bg-card p-6 shadow-card">
      <div>
        <h3 className="font-semibold">处理方案</h3>
        <p className="mt-1 text-muted-foreground text-sm">
          点凡已完成服务接入和稳定性配置，学校只需选择适合自己的方案。
        </p>
      </div>
      <div className="mt-4 divide-y border-y">
        {(settings.data?.scopes ?? []).map((item) => (
          <ScopeRow
            key={item.scope}
            item={item}
            canEdit={canEdit && !update.isPending}
            onChange={(scope, offeringId) =>
              update.mutate({ scope, offeringId })
            }
          />
        ))}
        {settings.isPending && (
          <div className="py-6 text-muted-foreground text-sm">
            正在读取方案…
          </div>
        )}
      </div>
    </section>
  )
}
