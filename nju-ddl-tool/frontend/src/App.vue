<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  checkPlatformLogin,
  deletePlatform,
  getAssignments,
  getPlatforms,
  login,
  logout,
  refreshPlatform,
  setCompletion,
  startPlatformLogin,
} from './api'
import type { Assignment, PlatformInfo } from './api'

type SortKey = 'deadline' | 'course' | 'platform' | 'status'

const username = ref('')
const password = ref('')
const authToken = ref(localStorage.getItem('nju-ddl-token') || '')
const currentUser = ref(localStorage.getItem('nju-ddl-username') || '')
const authError = ref('')
const registerMode = ref(false)
const platforms = ref<PlatformInfo[]>([])
const assignments = ref<Assignment[]>([])
const includeCompleted = ref(false)
const selectedPlatform = ref('all')
const sortBy = ref<SortKey>('deadline')
const busy = ref('')
const message = ref('')
const loading = ref(false)
const loadError = ref('')
const confirmDelete = ref<string | null>(null)
const formErrors = ref<{ username?: string; password?: string }>({})
const virtualDesktopUrl = (import.meta.env.VITE_NOVNC_URL || '').trim()
const activeLogin = ref<{ virtualDesktopUrl: string } | null>(null)

const fallbackPlatformNames: Record<string, string> = {
  educoder: 'Educoder',
  nju_lms: 'NJU LMS',
  cslab_cms: 'CSLab CMS',
}

const sortOptions: { value: SortKey; label: string }[] = [
  { value: 'deadline', label: '按截止时间' },
  { value: 'course', label: '按课程' },
  { value: 'platform', label: '按平台' },
  { value: 'status', label: '按完成状态' },
]

const isAuthed = computed(() => Boolean(authToken.value))
const visibleAssignments = computed(() => {
  let list = assignments.value
  if (selectedPlatform.value !== 'all') {
    list = list.filter((item) => item.platform_id === selectedPlatform.value)
  }
  if (!includeCompleted.value) {
    list = list.filter((item) => !isManuallyCompleted(item))
  }
  return [...list].sort(compareAssignments)
})

function compareAssignments(a: Assignment, b: Assignment) {
  const fallback = compareText(platformLabel(a.platform_id), platformLabel(b.platform_id))
    || compareText(displayCourseName(a) || a.title, displayCourseName(b) || b.title)
    || compareText(a.title, b.title)
    || a.id - b.id

  switch (sortBy.value) {
    case 'deadline': return compareDeadlineDesc(a, b) || fallback
    case 'course':   return compareText(displayCourseName(a) || platformLabel(a.platform_id), displayCourseName(b) || platformLabel(b.platform_id)) || fallback
    case 'platform': return compareText(platformLabel(a.platform_id), platformLabel(b.platform_id)) || fallback
    case 'status':   return Number(isManuallyCompleted(a)) - Number(isManuallyCompleted(b)) || compareDeadlineDesc(a, b) || fallback
    default: return fallback
  }
}

function compareDeadlineDesc(a: Assignment, b: Assignment) {
  const aTime = deadlineTime(a.deadline)
  const bTime = deadlineTime(b.deadline)
  if (aTime === null && bTime === null) return 0
  if (aTime === null) return 1
  if (bTime === null) return -1
  return bTime - aTime
}

function deadlineTime(value: string | null) {
  if (!value) return null
  const time = new Date(value).getTime()
  return Number.isFinite(time) ? time : null
}

function compareText(a: string, b: string) {
  return a.localeCompare(b, 'zh-CN')
}

function isManuallyCompleted(item: Assignment) {
  return item.manual_status === 'completed'
}

function platformLabel(platformId: string) {
  return platforms.value.find((platform) => platform.id === platformId)?.name
    || fallbackPlatformNames[platformId]
    || platformId
}

function platformBadgeClass(platformId: string) {
  switch (platformId) {
    case 'educoder': return 'platform-educoder'
    case 'nju_lms': return 'platform-nju-lms'
    case 'cslab_cms': return 'platform-cslab-cms'
    default: return 'platform-default'
  }
}

function displayCourseName(item: Assignment) {
  const name = item.course_name.trim()
  if (!name || name === item.platform_course_id.trim()) return ''
  if (/^[a-z0-9_-]{4,}$/i.test(name) && !/[\u4e00-\u9fff]/.test(name)) return ''
  return name
}

function completionTitle(item: Assignment) {
  return isManuallyCompleted(item) ? '取消手动完成' : '标记为手动完成'
}

async function signIn() {
  authError.value = ''
  formErrors.value = {}
  const normalizedUsername = username.value.trim()
  if (normalizedUsername.length < 2) {
    formErrors.value.username = '用户名至少 2 个字符'
  }
  if (password.value.length < 8) {
    formErrors.value.password = '密码至少 8 个字符'
  }
  if (formErrors.value.username || formErrors.value.password) return
  try {
    const result = await login(normalizedUsername, password.value, registerMode.value)
    localStorage.setItem('nju-ddl-token', result.token)
    localStorage.setItem('nju-ddl-username', result.username)
    authToken.value = result.token
    currentUser.value = result.username
    username.value = result.username
    password.value = ''
    await loadAll()
  } catch (error) {
    authError.value = error instanceof Error ? error.message : '登录失败'
  }
}

async function signOut() {
  await logout()
  localStorage.removeItem('nju-ddl-token')
  localStorage.removeItem('nju-ddl-username')
  authToken.value = ''
  currentUser.value = ''
  platforms.value = []
  assignments.value = []
  activeLogin.value = null
  message.value = ''
}

async function loadAll() {
  if (!isAuthed.value) return
  loading.value = true
  loadError.value = ''
  try {
    platforms.value = await getPlatforms()
    assignments.value = await getAssignments(true)
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : '加载失败'
  } finally {
    loading.value = false
  }
}

async function beginLogin(platform: PlatformInfo) {
  busy.value = platform.id
  message.value = ''
  activeLogin.value = null
  const desktopWindow = openVirtualDesktop()
  try {
    const loginSession = await startPlatformLogin(platform.id)
    activeLogin.value = {
      virtualDesktopUrl,
    }
    if (desktopWindow && !desktopWindow.closed) desktopWindow.focus()
    message.value = virtualDesktopUrl
      ? `${platform.name} 登录会话已启动。请在虚拟桌面中完成登录，然后等待检测。`
      : `${platform.name} 登录会话已启动。请在服务器浏览器中完成登录，然后等待检测。`
    for (let i = 0; i < 60; i += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 2000))
      const status = await checkPlatformLogin(platform.id, loginSession.login_id)
      if (status.status === 'complete') {
        message.value = `${platform.name} 已连接。`
        activeLogin.value = null
        await loadAll()
        return
      }
    }
    message.value = `${platform.name} 登录仍未完成，请稍后重试检测。`
  } catch (error) {
    message.value = error instanceof Error ? error.message : '启动登录失败'
    activeLogin.value = null
  } finally {
    busy.value = ''
  }
}

function openVirtualDesktop() {
  if (!virtualDesktopUrl) return null
  return window.open(virtualDesktopUrl, 'nju-ddl-virtual-desktop')
}

async function refresh(platform: PlatformInfo) {
  busy.value = platform.id
  message.value = ''
  try {
    const result = await refreshPlatform(platform.id)
    message.value = `${platform.name} 刷新完成，发现 ${result.count} 条作业。`
    await loadAll()
  } catch (error) {
    message.value = error instanceof Error ? error.message : '刷新失败'
    await loadAll()
  } finally {
    busy.value = ''
  }
}

async function removePlatform(platform: PlatformInfo) {
  if (confirmDelete.value !== platform.id) {
    confirmDelete.value = platform.id
    return
  }
  confirmDelete.value = null
  busy.value = platform.id
  try {
    await deletePlatform(platform.id)
    message.value = `${platform.name} 会话已删除。`
    await loadAll()
  } finally {
    busy.value = ''
  }
}

async function toggleComplete(item: Assignment) {
  try {
    const updated = await setCompletion(item.id, !isManuallyCompleted(item))
    const index = assignments.value.findIndex((entry) => entry.id === item.id)
    if (index >= 0) assignments.value[index] = updated
    if (!includeCompleted.value) {
      assignments.value = assignments.value.filter((entry) => !isManuallyCompleted(entry))
    }
  } catch (error) {
    message.value = error instanceof Error ? error.message : '操作失败'
  }
}

function formatDate(value: string | null) {
  if (!value) return '未提供'
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

onMounted(loadAll)
</script>

<template>
  <main class="app-shell">
    <section v-if="!isAuthed" class="auth-panel">
      <h1>NJU DDL Tool</h1>
      <div class="auth-grid">
        <label>
          用户名
          <input v-model="username" autocomplete="username" />
          <p v-if="formErrors.username" class="field-error">{{ formErrors.username }}</p>
        </label>
        <label>
          密码
          <input v-model="password" type="password" autocomplete="current-password" />
          <p v-if="formErrors.password" class="field-error">{{ formErrors.password }}</p>
        </label>
      </div>
      <div class="actions">
        <button @click="signIn">{{ registerMode ? '注册并登录' : '登录' }}</button>
        <button class="secondary" @click="registerMode = !registerMode">
          {{ registerMode ? '已有账号' : '注册账号' }}
        </button>
      </div>
      <p v-if="authError" class="error">{{ authError }}</p>
    </section>

    <template v-else>
      <header class="topbar">
        <div>
          <h1>NJU DDL Tool</h1>
          <p>{{ currentUser }}</p>
        </div>
        <button class="secondary" @click="signOut">退出</button>
      </header>

      <section class="platforms">
        <article v-for="platform in platforms" :key="platform.id" class="platform-card">
          <div>
            <h2>{{ platform.name }}</h2>
            <p>{{ platform.connected ? '已连接' : '未连接' }} · {{ platform.login_state }}</p>
            <p v-if="platform.last_refresh_at">上次刷新：{{ formatDate(platform.last_refresh_at) }}</p>
            <p v-if="platform.last_error" class="error">{{ platform.last_error }}</p>
          </div>
          <div class="card-actions">
            <button :disabled="busy === platform.id" @click="beginLogin(platform)">登录</button>
            <button :disabled="!platform.connected || busy === platform.id" @click="refresh(platform)">刷新</button>
            <template v-if="confirmDelete === platform.id">
              <span class="confirm-text">确认删除？</span>
              <button class="danger" @click="removePlatform(platform)">确认</button>
              <button class="secondary" @click="confirmDelete = null">取消</button>
            </template>
            <button v-else class="secondary" :disabled="busy === platform.id" @click="removePlatform(platform)">删除会话</button>
          </div>
        </article>
      </section>

      <p v-if="loadError" class="error">{{ loadError }}</p>
      <div v-if="message || activeLogin?.virtualDesktopUrl" class="message-row">
        <p v-if="message" class="message">{{ message }}</p>
        <button v-if="activeLogin?.virtualDesktopUrl" class="secondary" @click="openVirtualDesktop">
          打开虚拟桌面
        </button>
      </div>

      <section class="toolbar">
        <select v-model="selectedPlatform">
          <option value="all">全部平台</option>
          <option v-for="platform in platforms" :key="platform.id" :value="platform.id">{{ platform.name }}</option>
        </select>
        <select v-model="sortBy">
          <option v-for="option in sortOptions" :key="option.value" :value="option.value">
            {{ option.label }}
          </option>
        </select>
        <label class="inline">
          <input v-model="includeCompleted" type="checkbox" />
          显示已完成
        </label>
        <button class="secondary" @click="loadAll">重新加载</button>
      </section>

      <section class="assignments">
        <article v-for="item in visibleAssignments" :key="item.id" class="assignment-row">
          <button
            class="check"
            :class="{ checked: isManuallyCompleted(item) }"
            :title="completionTitle(item)"
            :aria-pressed="isManuallyCompleted(item)"
            @click="toggleComplete(item)"
          >
            {{ isManuallyCompleted(item) ? '✓' : '' }}
          </button>
          <div class="assignment-main">
            <div class="assignment-title">
              <strong>{{ item.title }}</strong>
            </div>
            <div class="assignment-source">
              <span :class="['platform-badge', platformBadgeClass(item.platform_id)]">
                {{ platformLabel(item.platform_id) }}
              </span>
              <span v-if="displayCourseName(item)" class="course-name">{{ displayCourseName(item) }}</span>
            </div>
            <p v-if="item.description">{{ item.description }}</p>
            <a v-if="item.source_url" :href="item.source_url" target="_blank" rel="noreferrer">来源链接</a>
          </div>
          <div class="assignment-meta">
            <strong>{{ formatDate(item.deadline) }}</strong>
            <span v-if="isManuallyCompleted(item)" class="manual-status">已手动完成</span>
          </div>
        </article>
        <p v-if="loading" class="empty">加载中…</p>
        <p v-else-if="visibleAssignments.length === 0" class="empty">暂无 DDL</p>
      </section>
    </template>
  </main>
</template>
