import type { RegistrationStatus } from "@/client"
import { cn } from "@/lib/utils"

/** 報名狀態的介面標籤（EXPERIENCE.md〈報名狀態〉）。 */
export const REGISTRATION_STATUS_LABELS: Record<RegistrationStatus, string> = {
  forming: "組隊中",
  pending: "已送出・待分配",
  accepted: "正取",
  waitlisted: "候補",
  rejected: "退回",
  withdrawn: "撤回",
  drawn: "已參賽",
  retired: "退賽",
  disqualified: "取消資格",
}

// DESIGN.md〈Components〉Status badge：文字色＝tone，底色同色 15%、外框同色 38%
const MUTED_TONE =
  "border-muted-foreground/40 bg-muted-foreground/15 text-muted-foreground"
const STATUS_TONES: Record<RegistrationStatus, string> = {
  forming: MUTED_TONE,
  pending: "border-status-appeal/40 bg-status-appeal/15 text-status-appeal",
  accepted:
    "border-status-confirmed/40 bg-status-confirmed/15 text-status-confirmed",
  waitlisted:
    "border-status-waitlist/40 bg-status-waitlist/15 text-status-waitlist",
  rejected: "border-destructive/40 bg-destructive/15 text-destructive",
  withdrawn: MUTED_TONE,
  drawn:
    "border-status-confirmed/40 bg-status-confirmed/15 text-status-confirmed",
  retired: MUTED_TONE,
  disqualified: "border-destructive/40 bg-destructive/15 text-destructive",
}

/** 報名狀態徽章：永遠帶文字，顏色只是輔助；不可點擊。 */
export function RegistrationStatusBadge({
  status,
  className,
}: {
  status: RegistrationStatus
  className?: string
}) {
  return (
    <span
      data-slot="status-badge"
      className={cn(
        "inline-flex shrink-0 items-center whitespace-nowrap rounded-full border px-2 py-0.5 text-label",
        STATUS_TONES[status],
        className,
      )}
    >
      {REGISTRATION_STATUS_LABELS[status]}
    </span>
  )
}
