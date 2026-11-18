import { requestJson } from './client.js'

const TIMEOUT_MS = 60000

export const FIXER_MESSAGES = {
  FIXER_INVALID_SELECTION: '所选补丁定位不合法，请重新预览后再试',
  FIXER_BACKUP_DIR_FORBIDDEN: '备份目录必须位于被巡检仓库之外且可写',
  FIXER_BACKUP_PATH_FORBIDDEN: '备份路径超出允许范围，已拒绝',
  FIXER_STALE_PATCH: '文件内容已变化，请重新预览后再试',
  FIXER_FILE_UNDECODABLE: '文件不是可处理的 UTF-8 文本',
  FIXER_ROLLBACK_CONFLICT: '文件已被手工修改，已拒绝覆盖',
  FIXER_IO_ERROR: '当前仓库有写操作正在进行或备份失败，请稍后重试',
  UNSUPPORTED_MEDIA_TYPE: '请求格式不受支持',
  PAYLOAD_TOO_LARGE: '请求内容超过 2 MB 限制',
}

export function previewFix({ repo, issues, strict, signal } = {}) {
  return requestJson('/api/fixer/preview', {
    method: 'POST',
    body: { repo, issues, strict },
    signal,
    timeoutMs: TIMEOUT_MS,
  })
}

export function applyFix({ repo, backupDir, selections, onStale, strict, signal } = {}) {
  return requestJson('/api/fixer/apply', {
    method: 'POST',
    body: {
      repo,
      backup_dir: backupDir,
      selections,
      on_stale: onStale,
      strict,
    },
    signal,
    timeoutMs: TIMEOUT_MS,
  })
}

export function rollbackFix({ repo, backupDir, backupId, backups, force, strict, signal } = {}) {
  return requestJson('/api/fixer/rollback', {
    method: 'POST',
    body: {
      repo,
      backup_dir: backupDir,
      backup_id: backupId,
      backups,
      force,
      strict,
    },
    signal,
    timeoutMs: TIMEOUT_MS,
  })
}