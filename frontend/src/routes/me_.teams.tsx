import { createFileRoute } from "@tanstack/react-router"

import { requireSignedIn } from "@/features/identity/auth"
import { MyTeamsPage } from "@/features/registration/MyTeamsPage"

// 檔名 me_.teams：/me（S11 身分選擇）沒有 Outlet，S12 不巢狀在它底下
export const Route = createFileRoute("/me_/teams")({
  beforeLoad: requireSignedIn,
  head: () => ({ meta: [{ title: "我的隊伍 · FLOW" }] }),
  component: MyTeamsPage,
})
