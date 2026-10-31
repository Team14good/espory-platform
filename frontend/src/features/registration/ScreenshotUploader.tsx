import { CircleCheckIcon, ImageUpIcon } from "lucide-react"
import {
  type ChangeEvent,
  type DragEvent,
  useEffect,
  useRef,
  useState,
} from "react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import {
  ACCEPTED_SCREENSHOT_TYPES,
  validateScreenshotFile,
} from "./screenshot-file"

export type ScreenshotUploaderProps = {
  /** 目前選取、尚未送出的檔案 */
  value: File | null
  onChange: (file: File | null) => void
  /** 上傳進度 0～100；null 或省略時不顯示進度條 */
  progress?: number | null
  /** 已上傳截圖的原始檔名：只顯示「已上傳」＋檔名，不顯示圖片（AD-15） */
  uploadedFileName?: string | null
  /** 外部（表單或伺服器）的錯誤訊息；選檔當下的格式／大小錯誤由元件自己顯示 */
  error?: string | null
  disabled?: boolean
  /** 給隱藏的檔案欄位用，讓 FormLabel 能對應（FormControl 會自動帶入） */
  id?: string
  "aria-describedby"?: string
  "aria-invalid"?: boolean
}

/**
 * Screenshot uploader（DESIGN.md〈Screenshot uploader〉）：虛線拖放區＋「選擇圖片」，
 * 選檔後顯示本機縮圖預覽、檔名與「移除截圖」，可移除重選直到表單送出。
 * 選檔當下就檢查 JPG／PNG 與 5 MB；錯誤時外框與說明文字用 destructive。
 */
export function ScreenshotUploader({
  value,
  onChange,
  progress = null,
  uploadedFileName = null,
  error = null,
  disabled = false,
  id,
  "aria-describedby": ariaDescribedBy,
  "aria-invalid": ariaInvalid,
}: ScreenshotUploaderProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [fileError, setFileError] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)

  // 本機預覽：換檔、移除或卸載時釋放 object URL
  useEffect(() => {
    if (!value) {
      setPreviewUrl(null)
      return
    }
    const url = URL.createObjectURL(value)
    setPreviewUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [value])

  const uploading = typeof progress === "number"
  // 上傳中與停用相同：不能換檔
  const blocked = disabled || uploading
  const displayedError = fileError ?? error
  const errorId = id ? `${id}-error` : undefined

  function pick(file: File | undefined) {
    if (!file || blocked) return
    const message = validateScreenshotFile(file)
    setFileError(message)
    onChange(message ? null : file)
  }

  function remove() {
    setFileError(null)
    onChange(null)
  }

  function openPicker() {
    inputRef.current?.click()
  }

  function handleInputChange(event: ChangeEvent<HTMLInputElement>) {
    pick(event.target.files?.[0])
    // 清空，讓同一個檔案可以再選一次
    event.target.value = ""
  }

  // 一律 preventDefault：即使不能換檔，也不讓瀏覽器直接開啟拖進來的檔案而離開頁面
  const dropHandlers = {
    onDragOver: (event: DragEvent<HTMLDivElement>) => {
      event.preventDefault()
      if (!blocked) setDragging(true)
    },
    onDragLeave: (event: DragEvent<HTMLDivElement>) => {
      // 移到子元素（圖示、按鈕、文字）上時也會觸發，不算離開
      const next = event.relatedTarget
      if (next instanceof Node && event.currentTarget.contains(next)) return
      setDragging(false)
    },
    onDrop: (event: DragEvent<HTMLDivElement>) => {
      event.preventDefault()
      setDragging(false)
      pick(event.dataTransfer.files?.[0])
    },
  }

  const describedBy =
    [ariaDescribedBy, displayedError ? errorId : undefined]
      .filter(Boolean)
      .join(" ") || undefined

  return (
    <div className="flex flex-col gap-2">
      <input
        ref={inputRef}
        id={id}
        type="file"
        accept={ACCEPTED_SCREENSHOT_TYPES.join(",")}
        className="sr-only"
        tabIndex={-1}
        disabled={disabled}
        aria-describedby={describedBy}
        aria-invalid={ariaInvalid || Boolean(displayedError)}
        onChange={handleInputChange}
      />

      {value ? (
        <div
          data-testid="screenshot-preview"
          className={cn(
            "flex items-center gap-3 rounded-lg border p-3",
            dragging && "border-primary",
          )}
          {...dropHandlers}
        >
          {previewUrl && (
            <img
              src={previewUrl}
              alt={`${value.name} 預覽`}
              className="size-16 shrink-0 rounded-md object-cover"
            />
          )}
          <span className="min-w-0 flex-1 truncate text-sm">{value.name}</span>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={disabled || uploading}
            onClick={remove}
          >
            移除截圖
          </Button>
        </div>
      ) : uploadedFileName ? (
        <div
          data-testid="screenshot-uploaded"
          className={cn(
            "flex items-center gap-3 rounded-lg border p-3",
            dragging && "border-primary",
            displayedError && "border-destructive",
          )}
          {...dropHandlers}
        >
          <CircleCheckIcon className="size-4 shrink-0 text-status-confirmed" />
          <span className="min-w-0 flex-1 truncate text-sm">
            已上傳<span className="mx-1 text-muted-foreground">·</span>
            {uploadedFileName}
          </span>
          {!disabled && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={uploading}
              onClick={openPicker}
            >
              更換圖片
            </Button>
          )}
        </div>
      ) : (
        <div
          data-testid="screenshot-dropzone"
          data-dragging={dragging}
          className={cn(
            "flex flex-col items-center gap-2 rounded-lg border-2 border-dashed p-6 text-center",
            dragging && "border-primary",
            displayedError && "border-destructive",
            disabled && "opacity-50",
          )}
          {...dropHandlers}
        >
          <ImageUpIcon className="size-6 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">拖曳圖片到這裡，或</p>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={blocked}
            onClick={openPicker}
          >
            選擇圖片
          </Button>
          <p className="text-xs text-muted-foreground">JPG 或 PNG，5 MB 以內</p>
        </div>
      )}

      {uploading && (
        <div className="flex flex-col gap-1">
          <div
            role="progressbar"
            aria-label="上傳進度"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={clampProgress(progress)}
            className="h-0.5 w-full overflow-hidden rounded-full bg-muted"
          >
            <div
              className="h-full bg-brand transition-[width]"
              style={{ width: `${clampProgress(progress)}%` }}
            />
          </div>
          <p className="text-xs text-muted-foreground">
            上傳中 {clampProgress(progress)}%
          </p>
        </div>
      )}

      {displayedError && (
        <p id={errorId} className="text-sm text-destructive">
          {displayedError}
        </p>
      )}
    </div>
  )
}

function clampProgress(progress: number): number {
  // axios 不知道總大小時可能算出 NaN 或 Infinity
  if (!Number.isFinite(progress)) return 0
  return Math.min(100, Math.max(0, Math.round(progress)))
}
