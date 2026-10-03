import skipFormatting from '@vue/eslint-config-prettier/skip-formatting'
import { defineConfigWithVueTs, vueTsConfigs } from '@vue/eslint-config-typescript'
import pluginVue from 'eslint-plugin-vue'

export default defineConfigWithVueTs(
  {
    name: 'labhq/files-to-lint',
    files: ['**/*.{ts,mts,tsx,vue}'],
  },
  {
    name: 'labhq/files-to-ignore',
    ignores: [
      'dist/**',
      'coverage/**',
      'playwright-report/**',
      'test-results/**',
      '.lighthouseci/**',
    ],
  },
  pluginVue.configs['flat/recommended'],
  vueTsConfigs.recommendedTypeChecked,
  {
    name: 'labhq/rules',
    rules: {
      // CONTRIBUTING.md §3: depth over three is a refactor.
      'max-depth': ['error', 3],
    },
  },
  {
    // shadcn-vue primitives and Mono keep their single-word names.
    name: 'labhq/ui-primitives',
    files: ['src/ui/**/*.vue'],
    rules: { 'vue/multi-word-component-names': 'off' },
  },
  skipFormatting,
)
