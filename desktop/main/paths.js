'use strict';

const path = require('path');
const { app } = require('electron');

/**
 * 资源路径解析：区分「开发态」和「打包态」。
 *
 * 开发态（npm start 直接跑源码）：
 *   项目根 = desktop/ 的上一级；后端源码、前端 dist、样本仓库都在工程内。
 * 打包态（electron-builder 产出后）：
 *   extraResources 拷贝到 process.resourcesPath 下的 resources/ 目录。
 */

const ROOT = path.resolve(__dirname, '..', '..'); // 工程根（desktop 的上一级）

function resolvePaths() {
  const packaged = app.isPackaged;

  if (packaged) {
    // 打包态：process.resourcesPath 本身即 win-unpacked/resources 目录，
    // extraResources 的 to 子目录直接位于其下。
    const resources = process.resourcesPath;
    return {
      packaged: true,
      backendDir: path.join(resources, 'backend'),
      backendExe: path.join(resources, 'backend', 'repoguard-backend.exe'),
      webDir: path.join(resources, 'web'),
      demoRepoDir: path.join(resources, 'demo-repo'),
      dataDir: path.join(resources, 'data'),
    };
  }

  // 开发态：直接引用工程内现有目录
  return {
    packaged: false,
    backendDir: path.join(ROOT, 'backend'),
    backendExe: null,
    webDir: path.join(ROOT, 'frontend', 'dist'),
    demoRepoDir: path.join(ROOT, 'demo-repo'),
    dataDir: path.join(ROOT, 'data'),
  };
}

module.exports = { resolvePaths, ROOT };
