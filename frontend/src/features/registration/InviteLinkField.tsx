import { CopyIcon, LinkIcon } from "lucide-react"
import { type ReactNode, useId } from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { notifySuccess } from "@/lib/feedback"
import { cn } from "@/lib/utils"

export const COPIED_TEXT = "已複製"
export const COPY_FAILED_TEXT = "無法複製連結，請手動選取後複製。"
export const LINK_INVALID_TEXT = "連結已失效"

type InviteLinkFieldProps = {
  /** 欄位標籤，例如「隊伍邀請連結」 */
  label: string
  /** 要分享的完整網址 */
  url: string
  /**
   * 連結失效時：整列改為 muted，停用「複製連結」並顯示標題與原因。
   * 例如 `{ title: "連結已失效", reason: "隊伍已滿" }`；裁判邀請過期可傳「連結已過期」。
   */
  invalid?: { title?: string; reason: string } | null
  /** 下方的補充說明（例如裁判邀請連結的到期時間），以 caption 顯示 */
  note?: ReactNode
  /** 連結失效時額外的動作（例如「產生新連結」） */
  action?: ReactNode
  className?: string
}

/**
 * Invite link field（UX-DR19）：唯讀輸入框＋「複製連結」，複製後 Toast「已複製」。
 * 隊伍邀請（S17）與裁判邀請（S31，Story 2.7）共用。
 */
export function InviteLinkField({
  label,
  url,
  invalid,
  note,
  action,
  className,
}: InviteLinkFieldProps) {
  const inputId = useId()
  const statusId = useId()

  async function copy() {
    try {
      await navigator.clipboard.writeText(url)
      notifySuccess(COPIED_TEXT)
    } catch {
      toast.error(COPY_FAILED_TEXT, { id: COPY_FAILED_TEXT })
    }
  }

  return (
    <div
      data-slot="invite-link-field"
      data-invalid={invalid ? "true" : undefined}
      className={cn(
        "flex flex-col gap-2",
        invalid && "text-muted-foreground",
        className,
      )}
    >
      <Label htmlFor={inputId}>{label}</Label>
      <div className="flex flex-col gap-2 sm:flex-row">
        <Input
          id={inputId}
          value={url}
          readOnly
          aria-describedby={invalid ? statusId : undefined}
          onFocus={(event) => event.currentTarget.select()}
          className={cn("font-mono", invalid && "text-muted-foreground")}
        />
        <Button
          type="button"
          variant="outline"
          disabled={Boolean(invalid)}
          onClick={copy}
          className="shrink-0"
        >
          <CopyIcon aria-hidden="true" />
          複製連結
        </Button>
      </div>
      {invalid && (
        <p id={statusId} className="flex items-start gap-2 text-body">
          <LinkIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          <span>
            <span className="font-semibold">
              {invalid.title ?? LINK_INVALID_TEXT}
            </span>
            ：{invalid.reason}
          </span>
        </p>
      )}
      {note && <p className="text-caption text-muted-foreground">{note}</p>}
      {action}
    </div>
  )
}
