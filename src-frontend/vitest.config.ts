import { defineConfig } from 'vitest/config';
import path from 'path';

// Standalone from quasar.config.js: Quasar builds its Vite config through the
// CLI, so Vitest can't load it. Only the aliases that pure `src/` modules
// actually import need mirroring here — keep this in sync with the `alias`
// block in quasar.config.js, from which Quasar also generates tsconfig paths.
export default defineConfig({
  resolve: {
    alias: {
      '@components': path.join(import.meta.dirname, 'src/components'),
      '@icons': path.join(import.meta.dirname, 'src/icons'),
      '@store': path.join(import.meta.dirname, 'src/store'),
      '@mixins': path.join(import.meta.dirname, 'src/mixins'),
      '@assets': path.join(import.meta.dirname, 'src/assets'),
      types: path.join(import.meta.dirname, 'src/types'),
      src: path.join(import.meta.dirname, 'src'),
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
