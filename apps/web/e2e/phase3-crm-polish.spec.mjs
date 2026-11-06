import {test,expect} from "@playwright/test";

async function signIn(page){
  await page.goto("/login");
  await page.getByRole("textbox",{name:"Email address"}).fill("admin@foundation.org");
  await page.getByLabel("Password",{exact:true}).fill("integration-only-long-password-123");
  await page.getByRole("button",{name:"Sign In"}).click();
  await expect(page).toHaveURL(/\/dashboard$/);
}
test.beforeEach(async({page})=>signIn(page));

test("CRM lists use compact headings, clearable search and no Created column",async({page})=>{
  const targets=[
    {path:"/prospects",title:"All Prospects",search:"Search prospects"},
    {path:"/prospects/active",title:"Active Prospects",search:"Search prospects"},
    {path:"/prospects/inactive",title:"Inactive Prospects",search:"Search prospects"},
    {path:"/promoters",title:"All Promoters",search:"Search promoters"},
    {path:"/promoters/inactive",title:"Inactive Promoters",search:"Search promoters"},
  ];
  for(const target of targets){
    await page.goto(target.path);
    const directory=page.locator(".crm-directory");
    const header=directory.locator(".crm-list-header-compact");
    await expect(header.getByRole("heading",{name:target.title,exact:true})).toBeVisible();
    await expect(directory.locator(".crm-directory-intro, .crm-directory-count, .crm-directory-eyebrow")).toHaveCount(0);
    await expect(directory.getByText(/Review registrations, contributions and follow-ups|Manage prospects in this status without losing their history|Find promoters, review their assigned sponsors/)).toHaveCount(0);
    const columns=await directory.locator("thead th").allTextContents();
    expect(columns).not.toContain("Created");
    const input=directory.getByRole("textbox",{name:target.search});
    await expect(input).toBeVisible();
    await input.fill("synthetic-unmatched-phase3-123xyz");
    await expect(directory.getByRole("button",{name:"Clear search"})).toBeVisible();
    await directory.getByRole("button",{name:"Clear search"}).click();
    await expect(input).toHaveValue("");
    await expect(directory.getByRole("button",{name:"Clear search"})).toHaveCount(0);
  }
});

test("Phase 3 prospect profile matches Promoter hierarchy without changing OTP or accounting",async({page,isMobile})=>{
  const number="9745"+String(Date.now()%1000000).padStart(6,"0");
  await page.goto("/prospects/add");
  await page.getByRole("textbox",{name:/First Name/}).fill("Phase Three");
  await page.getByRole("textbox",{name:"Mobile (WhatsApp)"}).fill(number);
  await page.getByRole("button",{name:"Add Prospect",exact:true}).click();
  await expect(page).toHaveURL(/\/prospects\/[0-9a-f-]{36}$/);
  const hero=page.locator(".prospect-hero");
  await expect(hero).toBeVisible();
  await expect(hero.getByRole("button",{name:"Edit details"})).toBeVisible();
  await expect(hero.getByRole("button",{name:"Mark Active"})).toBeVisible();
  await expect(page.getByRole("button",{name:"Edit details"})).toHaveCount(1);
  await expect(page.getByRole("button",{name:"Mark Active"})).toHaveCount(1);
  const metrics=page.locator(".prospect-overview-metric");
  await expect(metrics).toHaveCount(4);
  for(const heading of ["Total contribution","Monthly sponsorship","Assigned promoter","Next follow-up"]){
    await expect(page.locator(".prospect-overview-metrics").getByText(heading,{exact:true})).toBeVisible();
  }
  await expect(page.locator(".crm-followup-wide")).toBeVisible();
  await expect(page.getByRole("heading",{name:"Personal details",exact:true})).toBeVisible();
  await expect(page.getByRole("heading",{name:"Activity timeline"})).toBeVisible();
  await expect(page.getByText("Never paid")).toBeVisible();
  if(!isMobile){
    const boxes=await Promise.all([0,1,2,3].map(i=>metrics.nth(i).boundingBox()));
    expect(Math.max(...boxes.map(b=>b.y))-Math.min(...boxes.map(b=>b.y))).toBeLessThan(10);
  }
  await hero.getByRole("button",{name:"Edit details"}).click();
  await expect(page.getByRole("button",{name:"Save Changes"})).toBeVisible();
});

test("Phase 3 payout entry and register keep disbursement attestation explicit",async({page})=>{
  await page.goto("/payouts");
  const form=page.getByRole("region",{name:"Record payout"});
  await expect(form.getByRole("heading",{name:"Record an outgoing payment"})).toBeVisible();
  await expect(form.getByText(/does not initiate a bank transfer/)).toBeVisible();
  await expect(form.getByRole("combobox",{name:"Payout purpose"})).toBeVisible();
  await expect(form.getByText(/Managed from Settings/)).toHaveCount(0);
  await expect(form.getByText(/Every outgoing payment requires a unique bank or receipt reference/)).toHaveCount(0);
  await expect(form.getByRole("button",{name:"Save Payout"})).toBeVisible();
  await page.goto("/payouts/all");
  const register=page.getByRole("region",{name:"All payout plans"});
  await expect(register.locator(".payout-phase3-list-header")).toBeVisible();
  await expect(register.locator(".payout-phase3-count")).toBeVisible();
  await expect(register.getByLabel("Payout accounting month")).toBeVisible();
  await expect(register.getByRole("button",{name:"Export payout plans"})).toBeVisible();
  await expect(register.getByRole("button",{name:"Export payments"})).toBeVisible();
});
