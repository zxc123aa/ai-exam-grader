import { Plus, Trash2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

export type ScoringPoint = Record<string, unknown>

export function ScoringPointsEditor({
  points,
  disabled,
  onChange,
}: {
  points: ScoringPoint[]
  disabled?: boolean
  onChange: (points: ScoringPoint[]) => void
}) {
  const updatePoint = (index: number, patch: ScoringPoint) =>
    onChange(
      points.map((point, current) =>
        current === index ? { ...point, ...patch } : point,
      ),
    )

  return (
    <div className="grid gap-2">
      {points.map((point, index) => (
        <div
          key={String(point.id ?? index)}
          className="flex items-center gap-2"
        >
          <Input
            type="number"
            min="0"
            step="0.5"
            className="w-24 shrink-0"
            value={String(point.points ?? 0)}
            disabled={disabled}
            aria-label={`评分点 ${index + 1} 分值`}
            onChange={(event) =>
              updatePoint(index, { points: Number(event.target.value) })
            }
          />
          <span className="shrink-0 text-sm text-muted-foreground">分</span>
          <Input
            className="min-w-0 flex-1"
            value={String(point.description ?? "")}
            placeholder="可判定条件"
            disabled={disabled}
            aria-label={`评分点 ${index + 1} 判定条件`}
            onChange={(event) =>
              updatePoint(index, { description: event.target.value })
            }
          />
          <Button
            type="button"
            size="icon"
            variant="ghost"
            className="text-muted-foreground hover:text-destructive"
            disabled={disabled}
            aria-label={`删除评分点 ${index + 1}`}
            onClick={() =>
              onChange(points.filter((_, current) => current !== index))
            }
          >
            <Trash2 />
          </Button>
        </div>
      ))}
      <div>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={disabled}
          onClick={() =>
            onChange([
              ...points,
              {
                id: `p${points.length + 1}`,
                description: "",
                points: 0,
                required: true,
              },
            ])
          }
        >
          <Plus />
          添加评分点
        </Button>
      </div>
    </div>
  )
}
