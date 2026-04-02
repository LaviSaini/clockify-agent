import { API_BASE } from '../config'

export type AnalyzeRequest = {
  startDate: string
  endDate: string
  writeExcel: boolean
  leaveFile: File | null
}

export type AnalyzeSuccessBody = {
  excel_filename?: string
  excel_path?: string
  counts?: Record<string, number | Record<string, number>>
  [key: string]: unknown
}

export type AnalyzeResponse =
  | { ok: true; status: number; bodyText: string }
  | { ok: false; status: number; bodyText: string }
  | { ok: false; error: string }

/**
 * POST /analyze — multipart form (same shape as curl).
 */
export async function postAnalyze(params: AnalyzeRequest): Promise<AnalyzeResponse> {
  const formData = new FormData()
  formData.append('start_date', params.startDate)
  formData.append('end_date', params.endDate)
  formData.append('write_excel', params.writeExcel ? 'true' : 'false')
  if (params.leaveFile) {
    formData.append('leave_file', params.leaveFile)
  }

  try {
    const res = await fetch(`${API_BASE}/analyze`, {
      method: 'POST',
      body: formData,
    })
    const bodyText = await res.text()
    if (!res.ok) {
      return { ok: false, status: res.status, bodyText }
    }
    return { ok: true, status: res.status, bodyText }
  } catch (e) {
    const message = e instanceof Error ? e.message : 'Request failed'
    return { ok: false, error: message }
  }
}

/**
 * GET generated workbook (must match server filename pattern).
 */
export async function downloadExcelFile(filename: string): Promise<Blob> {
  const res = await fetch(
    `${API_BASE}/download/excel/${encodeURIComponent(filename)}`,
  )
  if (!res.ok) {
    const t = await res.text().catch(() => '')
    throw new Error(t || `Download failed (${res.status})`)
  }
  return res.blob()
}

export function triggerBlobDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
