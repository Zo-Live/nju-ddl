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

const username = ref('')
const password = ref('')
const currentUser = ref(localStorage.getItem('nju-ddl-username') || '')
const authError = ref('')
const registerMode = ref(false)
const platforms = ref<PlatformInfo[]>([])
const assignments = ref<Assignment[]>([])
const includeCompleted = ref(false)
const selectedPlatform = ref('all')
const busy = ref('')
const message = ref('')
const loading = ref(false)
const loadError = ref('')
const confirmDelete = ref<string | null>(null)
const formErrors = ref<{ username?: string; password?: string }>({})

const isAuthed = computed(() => Boolean(localStorage.getItem('nju-ddl-token')))
const visibleAssignments = computed(() => {
  if (selectedPlatform.value === 'all') return assignments.value
  return assignments.value.filter((item) => item.platform_id === selectedPlatform.value)
})

async function signIn() {
  authError.value = ''
  formErrors.value = {}
  if (username.value.trim().length < 2) {
    formErrors.value.username = '用户名至少 2 个字符'
  }
  if (password.value.length < 8) {
    formErrors.value.password = '密码至少 8 个字符'
  }
  if (formErrors.value.username || formErrors.value.password) return
  try {
    const result = await login(username.value, password.value, registerMode.value)
    localStorage.setItem('nju-ddl-token', result.token)
    localStorage.setItem('nju-ddl-username', result.username)
    currentUser.value = result.username
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
  currentUser.value = ''
  platforms.value = []
  assignments.value = []
}

async function loadAll() {
  if (!isAuthed.value) return
  loading.value = true
  loadError.value = ''
  try {
    platforms.value = await getPlatforms()
    assignments.value = await getAssignments(includeCompleted.value)
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : '加载失败'
  } finally {
    loading.value = false
  }
}

async function beginLogin(platform: PlatformInfo) {
  busy.value = platform.id
  message.value = ''
  try {
    const loginSession = await startPlatformLogin(platform.id)
    message.value = `${platform.name} 登录会话已启动。请在服务器浏览器中完成登录，然后等待检测。`
    for (let i = 0; i < 60; i += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 2000))
      const status = await checkPlatformLogin(platform.id, loginSession.login_id)
      if (status.status === 'complete') {
        message.value = `${platform.name} 已连接。`
        await loadAll()
        return
      }
    }
    message.value = `${platform.name} 登录仍未完成，请稍后重试检测。`
  } catch (error) {
    message.value = error instanceof Error ? error.message : '启动登录失败'
  } finally {
    busy.value = ''
  }
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
    const updated = await setCompletion(item.id, item.effective_status !== 'completed')
    const index = assignments.value.findIndex((entry) => entry.id === item.id)
    if (index >= 0) assignments.value[index] = updated
    if (!includeCompleted.value) assignments.value = assignments.value.filter((entry) => entry.effective_status !== 'completed')
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
      <p v-if="message" class="message">{{ message }}</p>

      <section class="toolbar">
        <select v-model="selectedPlatform">
          <option value="all">全部平台</option>
          <option v-for="platform in platforms" :key="platform.id" :value="platform.id">{{ platform.name }}</option>
        </select>
        <label class="inline">
          <input v-model="includeCompleted" type="checkbox" @change="loadAll" />
          显示已完成
        </label>
        <button class="secondary" @click="loadAll">重新加载</button>
      </section>

      <section class="assignments">
        <article v-for="item in visibleAssignments" :key="item.id" class="assignment-row">
          <button class="check" @click="toggleComplete(item)">
            {{ item.effective_status === 'completed' ? '✓' : '' }}
          </button>
          <div class="assignment-main">
            <div class="assignment-title">
              <strong>{{ item.title }}</strong>
              <span>{{ item.course_name }}</span>
            </div>
            <p v-if="item.description">{{ item.description }}</p>
            <a v-if="item.source_url" :href="item.source_url" target="_blank" rel="noreferrer">来源链接</a>
          </div>
          <div class="assignment-meta">
            <strong>{{ formatDate(item.deadline) }}</strong>
            <span>{{ item.effective_status }}</span>
          </div>
        </article>
        <p v-if="loading" class="empty">加载中…</p>
        <p v-else-if="visibleAssignments.length === 0" class="empty">暂无 DDL</p>
      </section>
    </template>
  </main>
</template>
