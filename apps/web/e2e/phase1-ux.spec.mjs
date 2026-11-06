import { test, expect } from "@playwright/test";

async function signIn(page){
  await page.goto("/login");
  await page.getByRole("textbox",{name:"Email address"}).fill("admin@foundation.org");
  await page.getByLabel("Password",{exact:true}).fill("integration-only-long-password-123");
  await page.getByRole("button",{name:"Sign In"}).click();
  await expect(page).toHaveURL(/\/dashboard$/);
}

test.beforeEach(async({page})=>{await signIn(page);});

test("Prospects has one responsive search/import/export toolbar and no row selection",async({page,isMobile})=>{
  await page.goto("/prospects");
  const toolbar=page.locator(".prospect-list-toolbar");
  const search=toolbar.getByRole("textbox",{name:"Search prospects"});
  const importAction=toolbar.getByRole("link",{name:"Import prospects"});
  const exportAction=toolbar.getByRole("button",{name:"Export all results"});
  await expect(search).toBeVisible();
  await expect(importAction).toBeVisible();
  await expect(exportAction).toBeVisible();
  await expect(page.getByRole("button",{name:/Export selected/})).toHaveCount(0);
  await expect(page.getByRole("checkbox",{name:"Select all prospects on this page"})).toHaveCount(0);
  if(!isMobile){
    const positions=await Promise.all([search,importAction,exportAction].map(x=>x.boundingBox()));
    expect(Math.max(...positions.map(x=>x.y))-Math.min(...positions.map(x=>x.y)))
      .toBeLessThanOrEqual(5);
  }
});

test("Prospect registration groups three fields and never implies WhatsApp opt-in",async({page,isMobile})=>{
  await page.goto("/prospects/add");
  const grid=page.locator(".prospect-financial-row");
  await expect(grid.locator(".field")).toHaveCount(3);
  const labels=await grid.locator(".field-label").allTextContents();
  expect(labels).toEqual(["City","Sponsorship Tokens *","Tentative Start (month)"]);
  if(!isMobile){
    const boxes=await Promise.all([0,1,2].map(i=>grid.locator(".field").nth(i).boundingBox()));
    expect(Math.max(...boxes.map(x=>x.y))-Math.min(...boxes.map(x=>x.y))).toBeLessThanOrEqual(5);
  }
  await expect(page.getByRole("textbox",{name:"Search promoters"})).toHaveCount(0);
  await expect(page.getByRole("checkbox",{name:/sponsor has explicitly agreed/})).toHaveCount(0);
  const assignment=page.getByRole("combobox",{name:"Assign promoter"});
  await expect(assignment).toBeVisible();
  await assignment.focus();
  await expect(page.getByRole("listbox",{name:"Active promoters"})).toBeVisible();
  await page.getByRole("option",{name:"Unassigned"}).click();
  const suffix=String(Date.now()%1000000).padStart(6,"0");
  await page.getByRole("textbox",{name:/First Name/}).fill("Phase One "+suffix);
  await page.getByRole("textbox",{name:"Mobile (WhatsApp)"}).fill("9632"+suffix);
  await page.getByRole("button",{name:"Add Prospect",exact:true}).click();
  await expect(page).toHaveURL(/\/prospects\/[0-9a-f-]{36}$/);
  const id=page.url().split("/").at(-1);
  const response=await page.request.get("/api/admin/prospects/"+id);
  expect(response.ok()).toBe(true);
  const saved=await response.json();
  expect(saved.whatsapp_opt_in).toBe(false);
});

test("Collections export sits beside the date filter and remains a button",async({page})=>{
  await page.goto("/collections/active");
  const bar=page.locator(".review-heading");
  await expect(bar.getByRole("button",{name:"Export all receipts"})).toBeVisible();
  await expect(bar.getByRole("textbox",{name:"Filter collection history by month"})).toBeVisible();
  await expect(bar.locator(".review-heading-actions")).toBeVisible();
});
