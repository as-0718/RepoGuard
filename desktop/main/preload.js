'use strict'

const { contextBridge, ipcRenderer } = require('electron')

// 仅暴露必要的目录选择能力，渲染进程不直接接触 Node/Electron 主进程接口。
contextBridge.exposeInMainWorld('repoguard', {
  pickDirectory: () => ipcRenderer.invoke('repoguard:pick-directory'),
})
