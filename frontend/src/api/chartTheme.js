// 按当前主题的 CSS 变量，给 ECharts option 补充文字、边框与提示框配色。
// 系列数据色仍由各视图 option 决定，这里只负责跟随主题的中性色。

function cssVar(name) {
  if (typeof document === 'undefined') return ''
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

export function themedOption(option) {
  if (!option || typeof option !== 'object') return option

  const text = cssVar('--color-text')
  const muted = cssVar('--color-muted')
  const surface = cssVar('--color-surface')
  const border = cssVar('--color-border')

  const next = { ...option }

  next.tooltip = {
    ...(next.tooltip || {}),
    backgroundColor: surface,
    borderColor: border,
    textStyle: { color: text, ...((next.tooltip && next.tooltip.textStyle) || {}) },
  }

  if (next.legend) {
    next.legend = {
      ...next.legend,
      textStyle: { color: muted, ...((next.legend.textStyle) || {}) },
    }
  }

  for (const axisKey of ['xAxis', 'yAxis']) {
    if (!next[axisKey]) continue
    const axes = Array.isArray(next[axisKey]) ? next[axisKey] : [next[axisKey]]
    axes.forEach((axis) => {
      axis.axisLabel = { color: muted, ...(axis.axisLabel || {}) }
      axis.axisLine = { lineStyle: { color: border }, ...(axis.axisLine || {}) }
      axis.splitLine = { lineStyle: { color: border }, ...(axis.splitLine || {}) }
    })
  }

  return next
}
