import { Link } from "@tanstack/react-router"
import { ChevronRightIcon } from "lucide-react"

import type { MyTeamCard } from "@/client"
import { RegistrationStatusBadge } from "./registration-status"

/**
 * Registration status card（UX-DR35，S12）：賽事名＋遊戲、隊伍名、右側狀態徽章；
 * 整張卡片點擊 → S17。候補順位與原因由之後的 Story 加入。
 */
export function RegistrationStatusCard({ card }: { card: MyTeamCard }) {
  return (
    <Link
      to="/teams/$teamId"
      params={{ teamId: card.team_id }}
      className="flex min-h-16 items-center gap-3 rounded-lg border bg-card px-4 py-3 outline-none transition-colors hover:bg-accent focus-visible:ring-[3px] focus-visible:ring-ring/50"
    >
      <span className="flex min-w-0 flex-1 flex-col gap-1">
        <span className="text-caption text-muted-foreground">
          {card.tournament_name} · {card.game_name}
        </span>
        <span className="break-words font-semibold text-body">
          {card.team_name}
        </span>
      </span>
      <RegistrationStatusBadge status={card.registration_status} />
      <ChevronRightIcon
        aria-hidden="true"
        className="size-4 shrink-0 text-muted-foreground"
      />
    </Link>
  )
}
