export const DEFAULT_TIMEOUT_MS = 15000

export const ERROR_CODE_MESSAGES = {
  INVALID_QUERY_PARAM: '查询参数不合法，请检查筛选条件',
  INVALID_REPO_PATH: '仓库路径格式不合法',
  REPO_FORBIDDEN: '仓库路径不在服务端允许范围内',
  REPO_NOT_FOUND: '仓库目录不存在或不可用',
  METHOD_NOT_ALLOWED: '该接口不支持当前请求方法',
  VALIDATION_ERROR: '请求字段校验未通过',
  DASHBOARD_BUSY: '当前看板请求较多，请稍后重试',
  DASHBOARD_UNAVAILABLE: '看板数据服务当前不可用',
  DASHBOARD_TIMEOUT: '扫描耗时过长，请稍后重试或缩小巡检范围',
  INTERNAL_ERROR: '服务处理请求时发生异常，请稍后重试',
  STATIC_NOT_FOUND: '页面资源缺失，请检查部署',
  NETWORK_ERROR: '无法连接看板服务，请检查后端是否启动',
  CLIENT_TIMEOUT: '请求超时，请稍后重试',
}

export class ApiClientError extends Error {
  constructor(code, message, { status = 0, detail = '', requestId = '' } = {}) {
    super(message)
    this.name = 'ApiClientError'
    this.code = code
    this.status = status
    this.detail = detail
    this.requestId = requestId
  }
}

export function buildQuery(params = {}) {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    search.append(key, String(value))
  }
  return search.toString()
}

function toClientError(payload, status) {
  const body = payload && typeof payload === 'object' ? payload : {}
  const error = body.error && typeof body.error === 'object' ? body.error : {}
  const code = typeof error.code === 'string' && error.code ? error.code : `HTTP_${status}`
  const message =
    ERROR_CODE_MESSAGES[code] ||
    (typeof error.message === 'string' && error.message) ||
    `请求失败（${status}）`
  return new ApiClientError(code, message, {
    status,
    detail: typeof error.detail === 'string' ? error.detail : '',
    requestId: body.request_id || error.request_id || '',
  })
}

export async function requestJson(path, { params, signal, timeoutMs = DEFAULT_TIMEOUT_MS } = {}) {
  const controller = new AbortController()
  let timedOut = false
  const timer = setTimeout(() => {
    timedOut = true
    controller.abort()
  }, timeoutMs)
  const abortFromOutside = () => controller.abort()
  if (signal) {
    if (signal.aborted) controller.abort()
    else signal.addEventListener('abort', abortFromOutside, { once: true })
  }

  const query = buildQuery(params)
  const url = query ? `${path}?${query}` : path

  try {
    const response = await fetch(url, {
      headers: { Accept: 'application/json' },
      signal: controller.signal,
    })

    if (!response.ok) {
      let payload = null
      try {
        payload = await response.json()
      } catch {
        payload = null
      }
      throw toClientError(payload, response.status)
    }

    try {
      return await response.json()
    } catch {
      throw new ApiClientError('NETWORK_ERROR', '看板服务返回了无法解析的数据', {
        status: response.status,
      })
    }
  } catch (error) {
    if (error instanceof ApiClientError) throw error
    if (error?.name === 'AbortError') {
      if (!timedOut) throw error
      throw new ApiClientError('CLIENT_TIMEOUT', ERROR_CODE_MESSAGES.CLIENT_TIMEOUT)
    }
    throw new ApiClientError('NETWORK_ERROR', ERROR_CODE_MESSAGES.NETWORK_ERROR, {
      detail: String(error?.message || error),
    })
  } finally {
    clearTimeout(timer)
    if (signal) signal.removeEventListener('abort', abortFromOutside)
  }
}