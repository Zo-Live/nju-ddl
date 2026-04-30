const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000'

export type PlatformInfo = {
  id: string
  name: string
  login_url: string
  connected: boolean
  login_state: string
  last_login_at: string | null
  last_refresh_at: string | null
  last_error: string | null
}

export type Assignment = {
  id: number
  platform_id: string
  platform_course_id: string
  course_name: string
  platform_assignment_id: string
  title: string
  description: string | null
  deadline: string | null
  published_at: string | null
  remote_status: string
  manual_status: string | null
  effective_status: string
  source_url: string | null
  last_seen_at: string
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = localStorage.getItem('nju-ddl-token')
  const headers = new Headers(options.headers)
  headers.set('Content-Type', 'application/json')
  if (token) headers.set('Authorization', `Bearer ${token}`)
  try {
    const response = await fetch(`${API_BASE}${path}`, { ...options, headers })
    const body = await response.json().catch(() => ({}))
    if (!response.ok) {
      throw new Error(body.detail || body.message || `请求失败 (${response.status})`)
    }
    return body as T
  } catch (error) {
    if (error instanceof TypeError && error.message === 'Failed to fetch') {
      throw new Error('无法连接服务器，请检查网络')
    }
    throw error
  }
}

export async function login(username: string, password: string, register = false) {
  const path = register ? '/api/auth/register' : '/api/auth/login'
  return request<{ token: string; username: string }>(path, {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  })
}

export function getPlatforms() {
  return request<PlatformInfo[]>('/api/platforms')
}

export function startPlatformLogin(platformId: string) {
  return request<{ login_id: string; platform_id: string; login_url: string; message: string }>(
    `/api/platforms/${platformId}/login/start`,
    { method: 'POST' },
  )
}

export function checkPlatformLogin(platformId: string, loginId: string) {
  return request<{ login_id: string; platform_id: string; status: string; current_url: string | null }>(
    `/api/platforms/${platformId}/login/${loginId}`,
  )
}

export function refreshPlatform(platformId: string) {
  return request<{ ok: boolean; count: number }>(`/api/platforms/${platformId}/refresh`, { method: 'POST' })
}

export function deletePlatform(platformId: string) {
  return request<{ ok: boolean }>(`/api/platforms/${platformId}`, { method: 'DELETE' })
}

export function getAssignments(includeCompleted: boolean) {
  return request<Assignment[]>(`/api/assignments?include_completed=${includeCompleted ? 'true' : 'false'}`)
}

export function logout() {
  return request<{ ok: boolean }>('/api/auth/logout', { method: 'POST' }).catch(() => ({ ok: false }))
}

export function setCompletion(id: number, completed: boolean) {
  return request<Assignment>(`/api/assignments/${id}/completion`, {
    method: 'POST',
    body: JSON.stringify({ completed }),
  })
}
