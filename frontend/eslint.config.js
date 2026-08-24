import js from '@eslint/js';
import tseslint from 'typescript-eslint';
import reactHooks from 'eslint-plugin-react-hooks';
import jsxA11y from 'eslint-plugin-jsx-a11y';
import prettier from 'eslint-config-prettier';
import globals from 'globals';

// Flat config. Real correctness rules (hooks, obvious bugs) are errors; stylistic
// and pre-existing-pattern rules are warnings so the check reports without blocking
// the whole pipeline on legacy style. Accessibility runs via jsx-a11y.
export default tseslint.config(
  { ignores: ['dist', 'coverage', 'playwright-report', 'test-results', 'node_modules'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  // Node scripts + config files run in Node, not the browser.
  {
    files: ['scripts/**/*.{js,mjs}', '*.config.{js,ts,mjs}'],
    languageOptions: { globals: { ...globals.node } },
  },
  {
    files: ['src/**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      globals: { ...globals.browser },
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    plugins: { 'react-hooks': reactHooks, 'jsx-a11y': jsxA11y },
    rules: {
      ...reactHooks.configs.recommended.rules,
      ...jsxA11y.configs.recommended.rules,
      // correctness → error
      'react-hooks/rules-of-hooks': 'error',
      'no-console': 'off',
      // pragmatic downgrades for this codebase's existing style
      'react-hooks/exhaustive-deps': 'warn',
      '@typescript-eslint/no-explicit-any': 'off',
      '@typescript-eslint/no-empty-object-type': 'off',
      '@typescript-eslint/ban-ts-comment': 'warn',
      '@typescript-eslint/no-unused-vars': [
        'warn',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      'no-empty': 'warn',
      // interaction a11y rules commonly hit by decorative click handlers → warn
      'jsx-a11y/no-static-element-interactions': 'warn',
      'jsx-a11y/click-events-have-key-events': 'warn',
      'jsx-a11y/no-noninteractive-element-interactions': 'warn',
      'jsx-a11y/label-has-associated-control': 'warn',
    },
  },
  // Last, so it wins: switches off every rule that would argue with Prettier.
  // Formatting is Prettier's job and is checked by `npm run format:check`;
  // ESLint stays responsible for correctness and accessibility only.
  prettier,
);
