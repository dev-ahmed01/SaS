import {test,expect} from "@playwright/test";
const admin="admin@foundation.org";
const password="integration-only-long-password-123";
async function login(page){
  await page.goto("/login");
  await page.getByRole("textbox",{name:"Email address"}).fill(admin);
  await page.getByLabel("Password",{exact:true}).fill(password);
  await page.getByRole("button",{name:"Sign In"}).click();
  await expect(page).toHaveURL(/\/dashboard$/);
}
test.beforeEach(async({page})=>{await login(page);});
test("Custom sponsorship tokens require explicit entry, not ₹25,250 preset",async({page})=>{
  await page.goto("/prospects/add");
  const select=page.getByRole("combobox",{name:"Sponsorship Tokens"});
  await select.selectOption("custom");
  const input=page.getByRole("spinbutton",{name:"Custom sponsorship tokens"});
  await expect(input).toHaveValue("");
  await input.fill("2");
  await expect(input).toHaveValue("2");
  await expect(page.getByText("₹500 / month")).toBeVisible();
});
test("Mobile Escape closes drawer without losing access to navigation",async({page})=>{
  await page.setViewportSize({width:375,height:812});
  await page.goto("/dashboard");
  await page.getByRole("button",{name:"Open navigation"}).click();
  await expect(page.getByRole("navigation",{name:"Modules"})).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button",{name:"Open navigation"})).toHaveAttribute("aria-expanded","false");
  await page.getByRole("button",{name:"Open navigation"}).click();
  await expect(page.getByRole("navigation",{name:"Modules"})).toBeVisible();
});
test("320px CRM screens keep entire document within viewport",async({page})=>{
  await page.setViewportSize({width:320,height:700});
  for(const route of ["/dashboard","/prospects/add","/promoters","/collections",
    "/payouts","/communication","/communication/campaigns","/settings"]){
    await page.goto(route);
    await page.locator(".topbar h1").waitFor();
    await expect.poll(()=>page.evaluate(()=>
      document.documentElement.scrollWidth<=window.innerWidth+1),{timeout:6000})
      .toBe(true);
  }
});

test("Complete prospects and promoters exports download valid CSV headers",async({page})=>{
  for(const [path,header] of [["/prospects","Name,Mobile"],["/promoters","Name,Mobile"]]){
    await page.goto(path);
    const download=page.waitForEvent("download");
    await page.getByRole("button",{name:"Export all results"}).click();
    const file=await download;
    expect(file.suggestedFilename().endsWith(".csv")).toBe(true);
    const bytes=await file.createReadStream();
    const chunks=[];
    for await(const chunk of bytes)chunks.push(Buffer.from(chunk));
    const content=Buffer.concat(chunks).toString("utf8").replace(/^\uFEFF/,"");
    expect(content).toContain('"'+header.replace(",",'","')+'"');
    expect(content.length).toBeGreaterThan(10);
  }
});
test("Owner can see staff management without exposing a password",async({page})=>{
  await page.goto("/settings");
  await expect(page.getByRole("heading",{name:"Staff access"})).toBeVisible();
  await expect(page.getByRole("button",{name:"Create staff account"})).toBeVisible();
  await expect(page.getByRole("textbox",{name:"Staff email"})).toHaveCount(1);
});
