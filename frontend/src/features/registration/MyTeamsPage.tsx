import { useQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"

import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { getErrorMessage, parseApiError } from "@/lib/api-error"
import { myTeamsQueryOptions } from "./queries"
import { RegistrationStatusCard } from "./RegistrationStatusCard"

export const NO_TEAMS_TEXT = "你還沒有加入任何隊伍。"

/** S12 沒有隊伍時的 Empty state：L2 標誌＋一句話＋說明＋「瀏覽賽事」。 */
function NoTeams() {
  return (
    <div className="flex flex-col items-center gap-3 py-12 text-center">
      <img
        src="/brand/flow-logo-L2-mark.svg"
        alt=""
        width={48}
        height={48}
        className="size-12 opacity-60 grayscale"
      />
      <p className="text-heading-md">{NO_TEAMS_TEXT}</p>
      <p className="text-body text-muted-foreground">
        在賽事頁建立隊伍，或開啟隊長分享的邀請連結加入隊伍。
      </p>
      <Button asChild className="mt-2">
        <Link to="/">瀏覽賽事</Link>
      </Button>
    </div>
  )
}

/** S12 我的隊伍：每支隊伍一張 Registration status card，點擊到 S17。 */
export function MyTeamsPage() {
  const teams = useQuery(myTeamsQueryOptions())

  return (
    <section className="mx-auto flex w-full max-w-2xl flex-col gap-6 py-8 sm:py-12">
      <h1 className="text-heading-lg">我的隊伍</h1>
      {teams.isPending ? (
        <div role="status" aria-busy="true" className="flex flex-col gap-3">
          <Skeleton className="h-16 w-full rounded-lg" />
          <Skeleton className="h-16 w-full rounded-lg" />
          <span className="sr-only">載入中</span>
        </div>
      ) : teams.isError ? (
        <div className="flex flex-col items-start gap-3">
          <p className="text-body text-destructive">
            {getErrorMessage(parseApiError(teams.error))}
          </p>
          <Button variant="outline" onClick={() => teams.refetch()}>
            重新載入
          </Button>
        </div>
      ) : teams.data.length === 0 ? (
        <NoTeams />
      ) : (
        <ul className="flex flex-col gap-3">
          {teams.data.map((card) => (
            <li key={card.team_id}>
              <RegistrationStatusCard card={card} />
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
