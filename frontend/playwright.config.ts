import { defineConfig, devices } from '@playwright/test';

// Playwright drives the *already running* dev stack (Vite :5173 + backend
// :8000). It does not start servers — bring the stack up first:
//   docker compose up -d && uv run uvicorn app.main:app --reload   # backend
//   npm run dev                                                    # frontend
export default defineConfig({
  testDir: './e2e',
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  reporter: [['list']],
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    ...devices['Desktop Chrome'],
  },
});
