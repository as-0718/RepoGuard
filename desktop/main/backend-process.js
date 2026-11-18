'use strict';

const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const { resolvePaths } = require('./paths');

const HOST = '127.0.0.1';
const PORT = 8000;
const HEALTH_URL = `http://${HOST}:${PORT}/api/health`;

// 开发态使用的 Python 解释器全路径。
// 【不同电脑需要替换】本机 uv cpython 3.11.15 全路径；
// 换电脑时可设置环境变量 REPOGUARD_PYTHON 指向该机 python.exe，否则回退下面这个默认值。
const DEFAULT_PYTHON =
  'C:\\Users\\anshuai\\AppData\\Roaming\\uv\\python\\cpython-3.11.15-windows-x86_64-none\\python.exe';

let child = null;

function buildEnv(paths) {
  const dataDir = paths.dataDir;
  fs.mkdirSync(dataDir, { recursive: true });
  const env = { ...process.env };
  env.REPOGUARD_STATIC_DIR = paths.webDir;
  env.REPOGUARD_DB_PATH = path.join(dataDir, 'repoguard.db');
  env.REPOGUARD_ALLOWED_REPOS = paths.demoRepoDir;
  env.REPOGUARD_DEFAULT_REPO = 'demo-repo';
  // 打包桌面态：放开为本机任意目录可选（仍排除系统敏感目录）；开发态保持白名单语义。
  env.REPOGUARD_DESKTOP_MODE = paths.packaged ? '1' : '0';
  return env;
}

function start() {
  const paths = resolvePaths();
  const env = buildEnv(paths);

  if (paths.packaged) {
    // 打包态：后端已封成独立 exe
    if (!fs.existsSync(paths.backendExe)) {
      throw new Error(`后端程序不存在：${paths.backendExe}`);
    }
    child = spawn(paths.backendExe, ['--host', HOST, '--port', String(PORT)], {
      cwd: paths.backendDir,
      env,
      windowsHide: true,
    });
  } else {
    // 开发态：用本机 Python 拉起 uvicorn
    const python = process.env.REPOGUARD_PYTHON || DEFAULT_PYTHON;
    child = spawn(
      python,
      ['-m', 'uvicorn', 'app.api.app:app', '--host', HOST, '--port', String(PORT)],
      { cwd: paths.backendDir, env, windowsHide: true }
    );
  }

  child.stdout && child.stdout.on('data', (d) => console.log('[backend]', d.toString().trim()));
  child.stderr && child.stderr.on('data', (d) => console.error('[backend]', d.toString().trim()));
  child.on('exit', (code) => console.log(`[backend] 退出，code=${code}`));

  return waitForHealth(30_000);
}

async function waitForHealth(timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (!child || child.exitCode !== null) {
      throw new Error('后端进程已提前退出');
    }
    try {
      const res = await fetch(HEALTH_URL, { signal: AbortSignal.timeout(2000) });
      if (res.ok) return { url: `http://${HOST}:${PORT}/`, health: HEALTH_URL };
    } catch (_) {
      // 尚未就绪，继续轮询
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`后端健康检查超时（${HEALTH_URL}）`);
}

function stop() {
  if (!child) return;
  const pid = child.pid;
  try {
    if (process.platform === 'win32') {
      // 终止整个进程树，避免 uvicorn 子进程残留
      spawn('taskkill', ['/PID', String(pid), '/T', '/F'], { windowsHide: true });
    } else {
      child.kill();
    }
  } catch (_) {
    // 忽略回收异常
  }
  child = null;
}

module.exports = { start, stop, PORT, HOST };
