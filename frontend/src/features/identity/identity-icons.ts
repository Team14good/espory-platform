import {
  CompassIcon,
  type LucideIcon,
  ShieldCheckIcon,
  UserIcon,
  UsersIcon,
} from "lucide-react"

import type { IdentityKey } from "@/client"

// 以產生的 IdentityKey 為鍵：後端新增身分、重新產生 client 後，忘了補圖示會編譯失敗
const IDENTITY_ICONS: Record<IdentityKey, LucideIcon> = {
  browse: CompassIcon,
  platform_admin: ShieldCheckIcon,
  my_teams: UsersIcon,
}

/** 身分的圖示（身分切換器與 S11 共用）；不認得的身分用通用的人像圖示。 */
export function identityIcon(key: string | undefined): LucideIcon {
  return (key && IDENTITY_ICONS[key as IdentityKey]) || UserIcon
}
