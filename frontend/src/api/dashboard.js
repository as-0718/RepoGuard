import { requestJson } from './client.js'

export function listRepos({ signal } = {}) {
  return requestJson('/api/dashboard/repos', { signal })
}

export function getOverview({ repo, refresh, signal } = {}) {
  return requestJson('/api/dashboard/overview', {
    params: { repo, refresh: refresh ? 1 : undefined },
    signal,
  })
}

export function getIssues({
  repo,
  refresh,
  riskLevel,
  sourceModule,
  keyword,
  page,
  pageSize,
  sort,
  order,
  signal,
} = {}) {
  return requestJson('/api/dashboard/issues', {
    params: {
      repo,
      refresh: refresh ? 1 : undefined,
      risk_level: riskLevel,
      source_module: sourceModule,
      keyword,
      page,
      page_size: pageSize,
      sort,
      order,
    },
    signal,
  })
}

export function getStructure({ repo, refresh, signal } = {}) {
  return requestJson('/api/dashboard/structure', {
    params: { repo, refresh: refresh ? 1 : undefined },
    signal,
  })
}

export function getHealth({ signal } = {}) {
  return requestJson('/api/health', { signal })
}