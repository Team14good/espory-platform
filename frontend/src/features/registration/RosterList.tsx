import type { TeamMemberRead } from "@/client"
import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"

type RosterListProps = {
  members: TeamMemberRead[]
  /** 先發人數 */
  starters: number
  /** 人數上限（先發＋替補） */
  maxMembers: number
}

/** 名單下方的人數：「4／6 人（先發 5）」。 */
export function rosterCountText(
  count: number,
  maxMembers: number,
  starters: number,
): string {
  return `${count}／${maxMembers} 人（先發 ${starters}）`
}

/**
 * Roster list（UX-DR34，S17）：名單放在 Card 內、列間 1px 分隔，每人一列顯示名稱，
 * 隊長加 outline Badge「隊長」；下方顯示人數。參賽資料與完成度由 Story 3.2 加入。
 */
export function RosterList({ members, starters, maxMembers }: RosterListProps) {
  return (
    <div className="flex flex-col gap-2">
      <Card className="gap-0 py-0">
        <ul aria-label="隊伍名單" className="divide-y">
          {members.map((member) => (
            <li
              key={member.account_id}
              className="flex min-h-12 items-center gap-2 px-4 py-3"
            >
              <span className="min-w-0 break-words text-body">
                {member.display_name}
              </span>
              {member.role === "captain" && (
                <Badge variant="outline">隊長</Badge>
              )}
            </li>
          ))}
        </ul>
      </Card>
      <p className="text-caption text-muted-foreground">
        {rosterCountText(members.length, maxMembers, starters)}
      </p>
    </div>
  )
}
