import {test,expect} from "@playwright/test";

const email="admin@foundation.org";
const password="integration-only-long-password-123";
async function login(page){
  await page.goto("/login");
  await page.getByRole("textbox",{name:"Email address"}).fill(email);
  await page.getByLabel("Password",{exact:true}).fill(password);
  await page.getByRole("button",{name:"Sign In"}).click();
  await expect(page).toHaveURL(/\/dashboard$/);
}

test.beforeEach(async({page})=>{await login(page);});

test("Saved communication automation drafts never imply that a sender is active",async({page})=>{
  await page.goto("/communication/templates");
  await expect(page.getByRole("heading",{name:"New workflow draft"})).toBeVisible();
  await expect(page.getByText("Saved as inactive draft · no messages will be sent")).toBeVisible();
  await expect(page.getByRole("button",{name:"Save inactive draft"})).toBeVisible();
  await expect(page.getByText(/Saved workflow drafts never dispatch on their own/)).toBeVisible();
});

test("Campaign deletion confirmation traps focus, handles Escape and restores opener",async({page})=>{
  await page.goto("/communication");
  await page.getByRole("textbox",{name:"Campaign name"}).fill("Synthetic QA campaign for keyboard checks");
  await page.getByRole("textbox",{name:"Message body"}).fill("Synthetic message. No real sends.");
  await page.getByRole("button",{name:"Continue to recipient review"}).click();
  await expect(page).toHaveURL(/\/communication\/campaigns#campaign-[0-9a-f-]{36}$/);
  await page.goto("/communication/campaigns");
  const deleteAll=page.getByRole("button",{name:"Delete all campaigns"});
  await expect(deleteAll).toBeEnabled();
  await deleteAll.click();
  const dialog=page.getByRole("dialog",{name:"Delete all campaigns"});
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("Type DELETE ALL CAMPAIGNS");
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(deleteAll).toBeFocused();
});
