import { zodResolver } from "@hookform/resolvers/zod"
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react"
import { useForm } from "react-hook-form"
import { z } from "zod"

import { FormErrorAlert } from "@/components/common/FormErrorAlert"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form"
import { Input } from "@/components/ui/input"
import { LoadingButton } from "@/components/ui/loading-button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { useIsMobile } from "@/hooks/useMobile"
import { type ApiError, applyFieldErrors, parseApiError } from "@/lib/api-error"
import { ScreenshotUploader } from "./ScreenshotUploader"

export const GAME_ID_HINT = "上場時必須使用這個遊戲 ID"

// core.storage 的 415／413：屬於截圖欄位的錯誤
const SCREENSHOT_ERROR_CODES = ["UNSUPPORTED_FILE_TYPE", "FILE_TOO_LARGE"]

/** 賽事快照的段位對照表一列（tournaments 的 RankTierRead，積分由高到低）。 */
export type RankTierOption = { name: string; score: number }

/** 表單欄位名與 API 欄位同名，伺服器 422 的 loc 才能對應到欄位。 */
export type PlayerProfileValues = {
  game_account_id: string
  rank_tier: string
  /** 新選的段位截圖；沿用已上傳的截圖時為 null */
  rank_screenshot: File | null
}

export type PlayerProfileDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  rankTiers: RankTierOption[]
  /** 已儲存的資料：遊戲 ID、段位 */
  initialValues?: { game_account_id?: string; rank_tier?: string }
  /** 已上傳截圖的原始檔名；有值時截圖不必重選 */
  uploadedScreenshotName?: string | null
  /** 名單鎖定：欄位全部停用，沒有「儲存資料」 */
  readOnly?: boolean
  /** 上傳進度 0～100；沒有在上傳時為 null */
  uploadProgress?: number | null
  /** 送出；失敗時 reject，伺服器的欄位錯誤會顯示在對應欄位 */
  onSubmit: (values: PlayerProfileValues) => Promise<void>
}

function buildSchema(hasUploadedScreenshot: boolean) {
  return z
    .object({
      game_account_id: z.string().trim().min(1, "請輸入遊戲 ID"),
      rank_tier: z.string().min(1, "請選擇段位"),
      rank_screenshot: z.instanceof(File).nullable(),
    })
    .refine(
      (values) => hasUploadedScreenshot || values.rank_screenshot !== null,
      { message: "請選擇段位截圖", path: ["rank_screenshot"] },
    )
}

type FormInput = z.input<ReturnType<typeof buildSchema>>

/**
 * S18 選手參賽資料：手機用 Sheet、桌機用 Dialog（< 768px 為手機）。
 * 段位只能從賽事的段位對照表選；送出後截圖只顯示「已上傳」＋檔名。
 */
export function PlayerProfileDialog({
  open,
  onOpenChange,
  rankTiers,
  initialValues,
  uploadedScreenshotName = null,
  readOnly = false,
  uploadProgress = null,
  onSubmit,
}: PlayerProfileDialogProps) {
  const isMobile = useIsMobile()
  const [formError, setFormError] = useState<ApiError | null>(null)
  const schema = useMemo(
    () => buildSchema(Boolean(uploadedScreenshotName)),
    [uploadedScreenshotName],
  )
  const form = useForm<FormInput, unknown, PlayerProfileValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      game_account_id: initialValues?.game_account_id ?? "",
      rank_tier: initialValues?.rank_tier ?? "",
      rank_screenshot: null,
    },
  })

  // 每次「開啟」（關→開）都從已儲存的資料重新開始，不留上次沒送出的內容；
  // 開著時父層重新取得資料不重設，以免洗掉正在輸入的內容
  const initialValuesRef = useRef(initialValues)
  initialValuesRef.current = initialValues
  const wasOpen = useRef(false)
  useEffect(() => {
    if (open && !wasOpen.current) {
      const latest = initialValuesRef.current
      form.reset({
        game_account_id: latest?.game_account_id ?? "",
        rank_tier: latest?.rank_tier ?? "",
        rank_screenshot: null,
      })
      setFormError(null)
    }
    wasOpen.current = open
  }, [open, form])

  async function submit(values: PlayerProfileValues) {
    setFormError(null)
    try {
      await onSubmit(values)
    } catch (error) {
      // 伺服器的格式／大小錯誤與前端選檔時的錯誤顯示在同一處：截圖欄下方
      const parsed = parseApiError(error)
      if (
        parsed.kind === "business" &&
        SCREENSHOT_ERROR_CODES.includes(parsed.code)
      ) {
        form.setError("rank_screenshot", {
          type: "server",
          message: parsed.message,
        })
        return
      }
      setFormError(applyFieldErrors(form, error))
    }
  }

  const title = "我的參賽資料"
  const description = readOnly
    ? "名單已鎖定，資料無法修改。"
    : "填寫遊戲 ID、段位並上傳段位截圖。"

  const body = (
    <Form {...form}>
      <form
        noValidate
        onSubmit={form.handleSubmit(submit)}
        className="flex flex-col gap-5"
      >
        <FormErrorAlert error={formError} />
        <FormField
          control={form.control}
          name="game_account_id"
          render={({ field }) => (
            <FormItem>
              <FormLabel>遊戲 ID</FormLabel>
              <FormControl>
                <Input autoComplete="off" disabled={readOnly} {...field} />
              </FormControl>
              <FormDescription>{GAME_ID_HINT}</FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="rank_tier"
          render={({ field }) => (
            <FormItem>
              <FormLabel>段位</FormLabel>
              <Select
                value={field.value}
                onValueChange={field.onChange}
                disabled={readOnly}
              >
                <FormControl>
                  <SelectTrigger ref={field.ref} className="w-full">
                    <SelectValue placeholder="選擇段位" />
                  </SelectTrigger>
                </FormControl>
                <SelectContent>
                  {rankTiers.map((tier) => (
                    <SelectItem key={tier.name} value={tier.name}>
                      {tier.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="rank_screenshot"
          render={({ field, fieldState }) => (
            <FormItem>
              <FormLabel>段位截圖</FormLabel>
              <FormControl>
                <ScreenshotUploader
                  value={field.value ?? null}
                  onChange={field.onChange}
                  uploadedFileName={uploadedScreenshotName}
                  progress={uploadProgress}
                  error={fieldState.error?.message ?? null}
                  disabled={readOnly || form.formState.isSubmitting}
                />
              </FormControl>
            </FormItem>
          )}
        />
        {!readOnly && (
          <LoadingButton
            type="submit"
            loading={form.formState.isSubmitting}
            className="w-full sm:ml-auto sm:w-auto"
          >
            儲存資料
          </LoadingButton>
        )}
      </form>
    </Form>
  )

  return (
    <ResponsiveShell
      isMobile={isMobile}
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      description={description}
    >
      {body}
    </ResponsiveShell>
  )
}

function ResponsiveShell({
  isMobile,
  open,
  onOpenChange,
  title,
  description,
  children,
}: {
  isMobile: boolean
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description: string
  children: ReactNode
}) {
  if (isMobile) {
    return (
      <Sheet open={open} onOpenChange={onOpenChange}>
        <SheetContent
          side="bottom"
          className="max-h-[90dvh] overflow-y-auto"
          data-testid="player-profile-sheet"
        >
          <SheetHeader>
            <SheetTitle>{title}</SheetTitle>
            <SheetDescription>{description}</SheetDescription>
          </SheetHeader>
          <div className="px-4 pb-4">{children}</div>
        </SheetContent>
      </Sheet>
    )
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="player-profile-dialog">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        {children}
      </DialogContent>
    </Dialog>
  )
}
