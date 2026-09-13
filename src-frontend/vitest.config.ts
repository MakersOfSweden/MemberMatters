import { defineConfig } from 'vitest/config';
import path from 'path';

// Standalone from quasar.config.js: Quasar builds its Vite config through the
// CLI, and Vitest ships its own Vite. Only the aliases that pure `src/` modules
// actually import need mirroring here — keep this in sync with the `alias`
// block in quasar.config.js and the `paths` in tsconfig.json.
export default defineConfig({
  resolve: {
    alias: {
      '@components': path.join(__dirname, 'src/components'),
      '@icons': path.join(__dirname, 'src/icons'),
      '@store': path.join(__dirname, 'src/store'),
      '@mixins': path.join(__dirname, 'src/mixins'),
      '@assets': path.join(__dirname, 'src/assets'),
      types: path.join(__dirname, 'src/types'),
      src: path.join(__dirname, 'src'),
    },
  },
  test: {
    // Node, not jsdom — this covers pure logic (helpers, store mutations,
    // guards). Component tests would need @vue/test-utils + jsdom on top.
    environment: 'node',
    include: ['src/**/*.spec.ts'],
    passWithNoTests: true,
  },
});
