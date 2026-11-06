import { defineConfig } from 'vitest/config'

// Unit tests for pure helpers only (no DOM, no React rendering).
export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
})
