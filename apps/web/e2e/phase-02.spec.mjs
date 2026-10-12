import { test, expect } from "@playwright/test";

const ADMIN_EMAIL = "admin@foundation.org";
const ADMIN_PASSWORD = "integration-only-long-password-123";
const modules = [
  ["prospects","Prospects"],["promoters","Promoters"],["collections","Collections"],
  ["payouts","Payouts"],["reminders","Reminders"],["settings","Settings"],
  ["dashboard","Dashboard"]
];

async function logIn(page) {
  await page.goto("/login");
  await page.getByRole("textbox",{name:"Email address"}).fill(ADMIN_EMAIL);
  await page.getByLabel("Password").fill(ADMIN_PASSWORD);
  await page.getByRole("button",{name:"Sign In"}).click();
  await expect(page).toHaveURL(/\/prospects$/);
}

test.beforeEach(async ({page}) => {
  await logIn(page);
});

test("all seven approved modules have a secure navigable destination",async ({page,isMobile})=>{
  for(const [slug,title] of modules){
    if(isMobile)await page.getByRole("button",{name:"Open navigation"}).click();
    await page.getByRole("navigation",{name:"Modules"}).getByRole("link",{name:title,exact:true}).click();
    await expect(page).toHaveURL(new RegExp("/"+slug+"$"));
    await expect(page.getByRole("heading",{name:title,exact:true,level:1})).toBeVisible();
  }
});

test("approved tabs remain functional and preview saves stay disabled",async ({page})=>{
  await expect(page.getByRole("button",{name:"Save Prospect"})).toBeDisabled();
  await page.getByRole("navigation",{name:"Module views"}).getByRole("link",{name:"Inactive"}).click();
  await expect(page.getByRole("heading",{name:"Inactive Prospects"})).toBeVisible();
  await page.getByRole("navigation",{name:"Module views"}).getByRole("link",{name:"All Prospects"}).click();
  await expect(page.getByRole("heading",{name:"All Prospects"})).toBeVisible();
  await page.goto("/collections");
  await expect(page.getByRole("button",{name:"Save Collection"})).toBeDisabled();
  await page.getByRole("link",{name:"Active",exact:true}).click();
  await expect(page.getByRole("heading",{name:"Active Collections"})).toBeVisible();
});

test("reminder screens do not send messages before Phase 11",async ({page})=>{
  await page.goto("/reminders");
  await expect(page.getByRole("link",{name:/WhatsApp Reminders/})).toBeVisible();
  await expect(page.getByRole("link",{name:/Email Reminders/})).toBeVisible();
  await page.getByRole("link",{name:/WhatsApp Reminders/}).click();
  await expect(page.getByRole("button",{name:"Send WhatsApp Reminders"})).toBeDisabled();
  await expect(page.getByText("No messages are being sent.")).toBeVisible();
  await page.goto("/dashboard");
  await expect(page.getByText("Waiting for live data").first()).toBeVisible();
});

test("responsive layout has no horizontal overflow and drawer controls work",async ({page,isMobile})=>{
  await page.goto("/promoters");
  await expect.poll(async()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  if(isMobile){
    await page.getByRole("button",{name:"Open navigation"}).click();
    await expect(page.getByRole("navigation",{name:"Modules"})).toBeVisible();
    await page.getByRole("button",{name:"Close menu"}).click();
  }else{
    await page.getByRole("button",{name:"Collapse sidebar"}).click();
    await expect(page.getByRole("button",{name:"Expand sidebar"})).toBeVisible();
    await page.getByRole("button",{name:"Expand sidebar"}).click();
  }
});

test("settings are persisted, edited and can be reloaded",async ({page})=>{
  await page.goto("/settings");
  await expect(page.getByRole("heading",{name:"Organisation Settings"})).toBeVisible();
  const amount=page.getByRole("spinbutton",{name:"Default monthly contribution (₹)"});
  await expect(amount).toHaveValue("250");
  await amount.fill("300");
  await page.getByRole("button",{name:"Save Changes"}).click();
  await expect(page.getByText(/Settings saved/)).toBeVisible();
  await page.reload();
  await expect(page.getByRole("spinbutton",{name:"Default monthly contribution (₹)"})).toHaveValue("300");
});

test("unauthenticated and forged browser sessions cannot access modules",async ({page,context})=>{
  await context.clearCookies();
  await page.goto("/prospects");
  await expect(page).toHaveURL(/\/login$/);
  await context.addCookies([{
    name:"sas_session",value:"not-a-valid-session",url:"http://127.0.0.1:3000"
  }]);
  await page.goto("/settings");
  await expect(page).toHaveURL(/\/login$/);
});

test("same-origin API rejects missing CSRF and foreign origins",async ({page})=>{
  const noCsrf=await page.evaluate(async()=>fetch("/api/admin/settings",{
    method:"PATCH",headers:{"content-type":"application/json"},
    body:JSON.stringify({inactivity_months:3})
  }).then(r=>r.status));
  expect(noCsrf).toBe(403);
  const forged=await page.request.patch("/api/admin/settings",{
    headers:{"origin":"https://malicious.invalid","content-type":"application/json"},
    data:{inactivity_months:3}
  });
  expect(forged.status()).toBe(403);
});

test("sign out ends the authenticated browser session",async ({page})=>{
  await page.getByRole("button",{name:"Sign out"}).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.goto("/collections");
  await expect(page).toHaveURL(/\/login$/);
});

test("wrong password never yields an authenticated session",async ({page,context})=>{
  await context.clearCookies();
  await page.goto("/login");
  await page.getByRole("textbox",{name:"Email address"}).fill(ADMIN_EMAIL);
  await page.getByLabel("Password").fill("incorrect-password");
  await page.getByRole("button",{name:"Sign In"}).click();
  await expect(page.getByRole("alert")).toContainText("Unable to sign in");
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login$/);
});
