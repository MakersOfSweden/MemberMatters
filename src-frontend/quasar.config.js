/*
 * This file runs in a Node context (it's NOT transpiled by Babel), so use only
 * the ES6 features that are supported by your Node version. https://node.green/
 */

// Configuration for your app
// https://v2.quasar.dev/quasar-cli-vite/quasar-config-js

import { defineConfig } from '#q-app';
import path from 'path';
import { fileURLToPath } from 'url';

const esbuildShim = fileURLToPath(
  import.meta.resolve('node-stdlib-browser/helpers/esbuild/shim')
);
const emptyModule = fileURLToPath(
  import.meta.resolve('node-stdlib-browser/mock/empty')
);

export default defineConfig(async function () {
  const { default: stdLibBrowser } = await import('node-stdlib-browser');
  return {
    // https://v2.quasar.dev/quasar-cli-vite/prefetch-feature
    // preFetch: true,

    // app boot file (/src/boot)
    // --> boot files are part of "main.js"
    // https://v2.quasar.dev/quasar-cli-vite/boot-files
    boot: ['store', 'i18n', 'axios', 'routeGuards', 'apexcharts'],

    // https://v2.quasar.dev/quasar-cli-vite/quasar-config-js#css
    css: ['app.scss'],

    // https://github.com/quasarframework/quasar/tree/dev/extras
    extras: [
      'mdi-v7',
      'roboto-font', // optional, you are not bound to it
    ],

    // Full list of options: https://v2.quasar.dev/quasar-cli-vite/quasar-config-js#build
    build: {
      target: {
        browser: ['es2019', 'edge88', 'firefox78', 'chrome87', 'safari13.1'],
        node: 'node24',
      },

      defineEnv: {
        // Base URL for API requests when the app is not served by the portal itself (the Electron kiosk)
        apiBaseUrl: process.env.API_BASE_URL,
      },

      vueRouterMode: 'history', // available values: 'hash', 'history'
      // vueRouterBase,
      // vueDevtools,
      vueOptionsAPI: true,

      // rebuildCache: true, // rebuilds Vite/linter/etc cache on startup

      minify: true,

      extendViteConf(viteConf, {}) {
        // The Node polyfills are for the page only. @quasar/app-vite 3 also
        // applies `alias` to the kiosk's main process and preload, which need
        // the real Node modules.
        viteConf.resolve.alias = {
          ...viteConf.resolve.alias,
          ...stdLibBrowser,
          // crypto-js only falls back to Node's crypto when the browser has
          // none, so the old build never bundled it. Rolldown follows that
          // guarded require and would put crypto-browserify (about 600 KB)
          // into every page.
          crypto: emptyModule,
        };

        // Rolldown's own inject rather than @rollup/plugin-inject: Vite 8
        // replaces process.env.NODE_ENV in that same native pass, before
        // `process` becomes the polyfill. Through the plugin, libraries read
        // the polyfill's empty env and run their development code.
        viteConf.build.rolldownOptions = {
          ...viteConf.build.rolldownOptions,
          transform: {
            ...viteConf.build.rolldownOptions?.transform,
            inject: {
              global: [esbuildShim, 'global'],
              process: [esbuildShim, 'process'],
              Buffer: [esbuildShim, 'Buffer'],
            },
          },
        };

        viteConf.optimizeDeps.rolldownOptions = {
          ...viteConf.optimizeDeps.rolldownOptions,
          transform: {
            ...viteConf.optimizeDeps.rolldownOptions?.transform,
            define: {
              global: 'globalThis',
            },
            // The dev server serves dependencies pre-bundled, so they need
            // the polyfills injected here as well.
            inject: {
              process: [esbuildShim, 'process'],
              Buffer: [esbuildShim, 'Buffer'],
            },
          },
        };

        viteConf.optimizeDeps.include = ['buffer', 'process'];
      },
      viteVuePluginOptions: {},

      alias: {
        // Every import prefix the code uses. @quasar/app-vite 3 only adds `@`
        // by itself, so the ones version 1 added that the code needs are
        // listed here, plus `types`, which came from tsconfig.json through
        // vite-tsconfig-paths.
        src: path.join(__dirname, 'src'),
        app: __dirname,
        components: path.join(__dirname, 'src/components'),
        layouts: path.join(__dirname, 'src/layouts'),
        pages: path.join(__dirname, 'src/pages'),
        boot: path.join(__dirname, 'src/boot'),
        types: path.join(__dirname, 'src/types'),
        '@components': path.join(__dirname, 'src/components/'),
        '@icons': path.join(__dirname, 'src/icons/'),
        '@store': path.join(__dirname, 'src/store/'),
        '@mixins': path.join(__dirname, 'src/mixins/'),
        '@assets': path.join(__dirname, 'src/assets/'),
      },

      vitePlugins: [
        [
          'vite-plugin-checker',
          {
            // Lints in dev and on build, and a lint error fails the build,
            // like the ESLint support built into @quasar/app-vite 1 did.
            eslint: { lintCommand: 'eslint --ext .js,.ts,.vue ./' },
            // Warnings stay in the terminal, as before; only errors cover
            // the page.
            overlay: { initialIsOpen: 'error' },
          },
        ],
      ],
    },

    // Full list of options: https://v2.quasar.dev/quasar-cli-vite/quasar-config-js#devServer
    devServer: {
      https: false,
      port: 8080,
      open: false, // opens browser window automatically
      proxy: {
        // proxy requests when running dev server
        '/api/ws/access': {
          target: 'ws://127.0.0.1:8000',
          ws: true,
          changeOrigin: false,
          rewrite: (path) => path.replace(/^\/api/, ''),
        },
        '/api': {
          target: 'http://127.0.0.1:8000',
          changeOrigin: false,
        },
        '/admin': {
          target: 'http://127.0.0.1:8000',
          changeOrigin: true,
        },
        '/openid': {
          target: 'http://127.0.0.1:8000',
          changeOrigin: true,
        },
        '/static': {
          target: 'http://127.0.0.1:8000',
          changeOrigin: true,
        },
      },
    },

    // https://v2.quasar.dev/quasar-cli-vite/quasar-config-js#framework
    framework: {
      lang: 'en-US', // Quasar language pack
      iconSet: 'mdi-v7',
      config: {
        dark: 'auto', // or Boolean true/false
        loadingBar: { color: 'accent' },
        iconSet: 'mdi-v7', // Quasar icon set

        // For special cases outside of where the auto-import strategy can have an impact
        // (like functional components as one of the examples),
        // you can manually specify Quasar components/directives to be available everywhere:
        //
        // components: [],
        // directives: [],
      },
      // Quasar plugins
      plugins: ['Dialog', 'LoadingBar', 'Cookies', 'Notify'],

      // animations: 'all', // --- includes all animations
      // https://v2.quasar.dev/options/animations
      // animations: ['fadeIn', 'fadeOut', 'bounceInLeft', 'bounceOutRight'],

      // https://v2.quasar.dev/quasar-cli-vite/quasar-config-js#sourcefiles
      // sourceFiles: {
      //   rootComponent: 'src/App.vue',
      //   router: 'src/router/index',
      //   store: 'src/store/index',
      //   electronMain: 'src-electron/electron-main',
      //   electronPreload: 'src-electron/electron-preload'
      // },
    },

    // Full list of options: https://v2.quasar.dev/quasar-cli-vite/developing-electron-apps/configuring-electron
    electron: {
      // extendElectronMainConf (esbuildConf)
      // extendElectronPreloadConf (esbuildConf)

      inspectPort: 5858,

      bundler: 'packager', // 'packager' or 'builder'

      packager: {
        // https://electron.github.io/packager/main/
        // OS X / Mac App Store
        // appBundleId: '',
        // appCategoryType: '',
        // osxSign: '',
        // protocol: 'myapp://path',
        // Windows only
        // win32metadata: { ... }
      },

      builder: {
        // https://www.electron.build/configuration/configuration

        appId: 'membermatters',
      },
    },
  };
});
