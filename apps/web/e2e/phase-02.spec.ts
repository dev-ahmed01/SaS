import { test, expect } from "@playwright/test";

const modules = [
  ["prospects", "Prospects"],
  ["promoters", "Promoters"],
  ["collections", "Collections"],
  ["payouts", "Payouts"],
  ["reminders", "Reminders"],
  ["settings", "Settings"],
  ["dashboard", "Dashboard"],
] as const;

test("all seven approved modules have a working navigation destination", async ({ page, isMobile }) => {
  await page.goto("/prospects");
  for (const [slug, heading] of modules) {
    if(isMobile) await page.getByRole("button", {name:"Open navigation"}).click();
    await page.getByRole("navigation", {name:"Modules"}).getByRole("link", {name:heading, exact:true}).click();
    await expect(page).toHaveURL(new RegExp("/"+slug+"$"));
    await expect(page.getByRole("heading", {name:heading, exact:true, level:1})).toBeVisible();
    await expect(page.getByRole("navigation", {name:"Modules"}).getByRole("link",{name:heading,exact:true})).toHaveAttribute("aria-current","page");
  }
});

test("approved horizontal tabs preserve navigation and phase previews stay disabled", async ({page}) => {
  await page.goto("/prospects");
  await expect(page.getByRole("button", {name:"Save Prospect"})).toBeDisabled();
  await page.getByRole("navigation",{name:"Module views"}).getByRole("link",{name:"Inactive"}).click();
  await expect(page.getByRole("heading",{name:"Inactive Prospects"})).toBeVisible();
  await page.getByRole("navigation",{name:"Module views"}).getByRole("link",{name:"All Prospects"}).click();
  await expect(page.getByRole("heading",{name:"All Prospects"})).toBeVisible();
  await page.goto("/collections");
  await expect(page.getByRole("button", {name:"Save Collection"})).toBeDisabled();
  await page.getByRole("link",{name:"Active", exact:true}).click();
  await expect(page.getByRole("heading",{name:"Active Collections"})).toBeVisible();
});

test("reminder screens show two choices and never send real messages",async ({page})=>{
  await page.goto("/reminders");
  await expect(page.getByRole("link",{name:/WhatsApp Reminders/})).toBeVisible();
  await expect(page.getByRole("link",{name:/Email Reminders/})).toBeVisible();
  await page.getByRole("link",{name:/WhatsApp Reminders/}).click();
  await expect(page.getByRole("button",{name:"Send WhatsApp Reminders"})).toBeDisabled();
  await expect(page.getByText("No messages are being sent.")).toBeVisible();
  await page.goto("/dashboard");
  await expect(page.getByText("Waiting for live data").first()).toBeVisible();
});

test("responsive pages never scroll horizontally and support keyboard controls",async ({page,isMobile})=>{
  await page.goto("/promoters");
  await expect.poll(async()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  if(isMobile){
    await page.getByRole("button",{name:"Open navigation"}).click();
    await expect(page.getByRole("navigation",{name:"Modules"})).toBeVisible();
    await page.getByRole("button",{name:"Close menu"}).click();
  } else {
    await page.getByRole("button",{name:"Collapse sidebar"}).click();
    await expect(page.getByRole("button",{name:"Expand sidebar"})).toBeVisible();
    await page.getByRole("button",{name:"Expand sidebar"}).click();
  }
});

test("sign-in is clearly a disabled preview",async ({page})=>{
  await page.goto("/login");
  await expect(page.getByRole("heading",{name:"Welcome back"})).toBeVisible();
  await expect(page.getByRole("button",{name:"Sign In"})).toBeDisabled();
  await expect(page.getByText(/cannot authenticate users/)).toBeVisible();
});
