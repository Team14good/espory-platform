import { createFileRoute } from "@tanstack/react-router"

import { JoinTeamPage } from "@/features/registration/JoinTeamPage"

// 不需登入：未登入時頁面提供註冊與登入（帶 redirect 回到這裡）
export const Route = createFileRoute("/join/$inviteToken")({
  head: () => ({ meta: [{ title: "加入隊伍 · FLOW" }] }),
  component: JoinRoute,
})

function JoinRoute() {
  const { inviteToken } = Route.useParams()
  return <JoinTeamPage key={inviteToken} token={inviteToken} />
}
