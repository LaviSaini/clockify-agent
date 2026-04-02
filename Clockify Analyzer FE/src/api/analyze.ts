import { API_BASE } from '../config'

export type AnalyzeRequest = {
  startDate: string
  endDate: string
  writeExcel: boolean
  leaveFile: File | null
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
