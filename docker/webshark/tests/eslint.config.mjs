// Bug rules only. index.html's inline JS is ES5 living beside vendored code, so style rules
// would report hundreds of things nobody intends to change.
//
// Do not declare the file's own g_* variables as globals: eslint then reads every real
// declaration as a redeclaration and the output is unusable.
export default [
  {
    files: ['.inline.js'],
    languageOptions: {
      ecmaVersion: 2020,
      sourceType: 'script',
      globals: {
        window: 'readonly', document: 'readonly', console: 'readonly',
        setTimeout: 'readonly', clearTimeout: 'readonly', setInterval: 'readonly',
        clearInterval: 'readonly', fetch: 'readonly', location: 'readonly',
        localStorage: 'readonly', sessionStorage: 'readonly', navigator: 'readonly',
        URL: 'readonly', URLSearchParams: 'readonly', Blob: 'readonly', alert: 'readonly',
        XMLHttpRequest: 'readonly', WebSocket: 'readonly', Event: 'readonly',
        c3: 'readonly', d3: 'readonly', Awesomplete: 'readonly', Clusterize: 'readonly',
      },
    },
    linterOptions: { reportUnusedDisableDirectives: true },
    rules: {
      'no-undef': 'error',
      'no-redeclare': 'error',
      'no-dupe-keys': 'error',
      'no-dupe-args': 'error',
      'no-duplicate-case': 'error',
      'no-unreachable': 'error',
      'no-cond-assign': 'error',
      'no-constant-condition': 'error',
      'no-empty': 'error',
      'no-func-assign': 'error',
      'no-obj-calls': 'error',
      'no-sparse-arrays': 'error',
      'use-isnan': 'error',
      'valid-typeof': 'error',
      'no-unused-vars': ['error', { args: 'none', caughtErrors: 'none' }],
    },
  },
];
