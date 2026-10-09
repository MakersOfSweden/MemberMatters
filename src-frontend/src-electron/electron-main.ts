import { app, BrowserWindow, nativeTheme, session } from 'electron';
import fs from 'fs';
import path from 'path';
import os from 'os';
import { resolveElectronAssetsPath } from '#q-app/electron/main';

// needed in case process is undefined under Linux
const platform = process.platform || os.platform();

try {
  if (platform === 'win32' && nativeTheme.shouldUseDarkColors === true) {
    fs.unlinkSync(path.join(app.getPath('userData'), 'DevTools Extensions'));
  }
} catch (_) {}

let mainWindow: BrowserWindow | undefined;

function createWindow() {
  /**
   * Initial window options
   */
  mainWindow = new BrowserWindow({
    icon: resolveElectronAssetsPath('icons/icon.png'), // tray icon
    fullscreen: process.env.NODE_ENV !== 'Development',
    useContentSize: true,
    webPreferences: {
      contextIsolation: true,
      // More info: https://v2.quasar.dev/quasar-cli-vite/developing-electron-apps/electron-preload-script
      preload: path.resolve(import.meta.dirname, 'electron-preload.cjs'),
    },
  });

  // Set the SameSite attribute to "None" for all cookies
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    if (details.responseHeaders && details.responseHeaders['set-cookie']) {
      details.responseHeaders['set-cookie'] = details.responseHeaders[
        'set-cookie'
      ].map((cookie: string) => {
        return cookie + '; SameSite=None; Secure';
      });
    }
    callback({ cancel: false, responseHeaders: details.responseHeaders });
  });

  if (import.meta.env.QUASAR_DEV) {
    mainWindow.loadURL(import.meta.env.QUASAR_APP_URL);
  } else {
    mainWindow.loadFile('index.html');
  }

  if (import.meta.env.QUASAR_DEBUG) {
    // if on DEV or Production with debug enabled
    mainWindow.webContents.openDevTools();
  } else {
    // TODO: comment out if you want to block access to dev tools in production
    // mainWindow.webContents.on('devtools-opened', () => {
    //   mainWindow?.webContents.closeDevTools();
    // });
  }

  mainWindow.on('closed', () => {
    mainWindow = undefined;
  });
}

app.whenReady().then(createWindow);

app.on('window-all-closed', () => {
  if (platform !== 'darwin') {
    app.quit();
  }
});

app.on('activate', () => {
  if (mainWindow === undefined) {
    createWindow();
  }
});
