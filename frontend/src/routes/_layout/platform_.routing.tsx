import { createFileRoute } from "@tanstack/react-router"

import { PageHead } from "@/components/Common/PageHead"
import { FunctionRoutingSection } from "@/components/Platform/FunctionRoutingSection"
import { requirePlatformSuperuser } from "@/components/Platform/orgMeta"

export const Route = createFileRoute("/_layout/platform_/routing")({
  component: PlatformRouting,
  beforeLoad: requirePlatformSuperuser,
  head: () => ({
    meta: [{ title: "功能调度 - 点凡阅卷" }],
  }),
})

function PlatformRouting() {
  return (
    <div className="flex flex-col gap-6" data-testid="platform-routing-page">
      <PageHead
        title="功能调度"
        subtitle="将业务功能绑定到标准模型，并在多个中转通道间自动调度"
      />
      <FunctionRoutingSection />
    </div>
  )
}

export default PlatformRouting
