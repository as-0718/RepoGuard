'use strict';

const path = require('path');
const { app, BrowserWindow, dialog, ipcMain } = require('electron');
const backend = require('./backend-process');

// 受限/无独显环境下降低崩溃概率：关闭硬件加速与 GPU 沙箱。
app.disableHardwareAcceleration();
app.commandLine.appendSwitch('no-sandbox');
app.commandLine.appendSwitch('disable-gpu');
app.commandLine.appendSwitch('disable-software-rasterizer');

let mainWindow = null;

// 渲染进程请求弹出系统目录选择框，返回所选文件夹绝对路径（取消则返回 null）。
ipcMain.handle('repoguard:pick-directory', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: '选择要巡检的仓库文件夹',
    properties: ['openDirectory'],
  });
  if (result.canceled || result.filePaths.length === 0) return null;
  return result.filePaths[0];
});

function createWindow(targetUrl) {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 1024,
    minHeight: 680,
    title: 'RepoGuard 代码巡检看板',
    backgroundColor: '#0f172a',
    autoHideMenuBar: true,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, 'preload.js'),
    },
  });

  mainWindow.loadURL(targetUrl);
  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

async function bootstrap() {
  const lock = app.requestSingleInstanceLock();
  if (!lock) {
    app.quit();
    return;
  }
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });

  try {
    const { url } = await backend.start();
    createWindow(url);
  } catch (err) {
    dialog.showErrorBox('RepoGuard 启动失败', String(err && err.message ? err.message : err));
    backend.stop();
    app.quit();
  }
}

app.whenReady().then(bootstrap);

app.on('window-all-closed', () => {
  backend.stop();
  if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', () => {
  backend.stop();
});
