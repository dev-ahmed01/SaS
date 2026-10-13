import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir:"./e2e",
  fullyParallel:false,
  workers:process.env.CI?1:undefined,
  retries:process.env.CI?1:0,
  reporter:process.env.CI?"github":"list",
  use:{baseURL:"http://127.0.0.1:3000",trace:"retain-on-failure"},
  projects:[
    {name:"desktop-chromium",use:{...devices["Desktop Chrome"]}},
    {name:"mobile-chromium",use:{...devices["Pixel 7"]}},
  ],
  webServer:{
    command:"npm run start -- -p 3000 -H 127.0.0.1",
    url:"http://127.0.0.1:3000/login",
    reuseExistingServer:!process.env.CI,
    timeout:60_000,
  },
});
