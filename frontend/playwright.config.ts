import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "tests",
  timeout: 60000,
  use: {
    baseURL: process.env.BASE_URL || "http://127.0.0.1:5173",
    headless: true,
    channel: process.env.CI ? undefined : "chrome",
    screenshot: "only-on-failure",
  },
  reporter: "list",
});
