import { defineConfig, globalIgnores } from 'eslint/config';
import tseslint from 'typescript-eslint';
import pluginVue from 'eslint-plugin-vue';
import prettier from 'eslint-config-prettier/flat';

export default defineConfig([
  globalIgnores(['dist/', '.quasar/', 'quasar.config.*.temporary.compiled*']),

  // Rules order is important, please avoid shuffling them
  tseslint.configs.recommended,
  pluginVue.configs['flat/essential'],
  prettier,

  {
    // Flat config reports stale eslint-disable comments by default, and
    // `npm run lint` (--fix) would then delete them; eslintrc did neither.
    linterOptions: { reportUnusedDisableDirectives: 'off' },
  },

  {
    files: ['**/*.vue'],
    languageOptions: {
      parserOptions: { parser: tseslint.parser },
    },
  },

  {
    rules: {
      'prefer-promise-reject-errors': 'off',

      quotes: ['warn', 'single', { avoidEscape: true }],

      // this rule, if on, would require explicit return type on the `render` function
      '@typescript-eslint/explicit-function-return-type': 'off',

      // in plain CommonJS modules, you can't use `import foo = require('foo')` to pass this rule, so it has to be disabled
      '@typescript-eslint/no-require-imports': 'off',

      // typescript-eslint 6 turned these warnings into errors, and 8 also reports
      // unused `catch` bindings. The build stops on any lint error, so keep the
      // earlier behaviour.
      '@typescript-eslint/no-explicit-any': 'warn',
      '@typescript-eslint/no-unused-vars': ['warn', { caughtErrors: 'none' }],

      // typescript-eslint 8 leaves this check to ESLint's own rule, which only
      // 'eslint:recommended' (not used here) would turn on.
      'no-loss-of-precision': 'error',

      // The core 'no-unused-vars' rules (in the eslint:recommended ruleset)
      // does not work with type definitions
      'no-unused-vars': 'off',

      // allow debugger during development only
      'no-debugger': process.env.NODE_ENV === 'production' ? 'error' : 'off',
    },
  },
]);
