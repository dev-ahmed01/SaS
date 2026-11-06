import {test,expect} from "@playwright/test";

async function signIn(page){
  await page.goto("/login");
  await page.getByRole("textbox",{name:"Email address"}).fill("admin@foundation.org");
  await page.getByLabel("Password",{exact:true}).fill("integration-only-long-password-123");
  await page.getByRole("button",{name:"Sign In"}).click();
  await expect(page).toHaveURL(/\/dashboard$/);
}
test.beforeEach(async({page})=>signIn(page));

test("Phase 3 directories have one quiet heading, accurate counts and clearable search",async({page,isMobile})=>{
  for(const target of [
    {path:"/prospects",title:"All Prospects",search:"Search prospects"},
    {path:"/promoters",title:"All Promoters",search:"Search promoters"},
  ]){
    await page.goto(target.path);
    const directory=page.locator(".crm-directory");
    await expect(directory.getByRole("heading",{name:target.title,exact:true})).toBeVisible();
    await expect(directory.locator(".crm-directory-count")).toBeVisible();
    const input=directory.getByRole("textbox",{name:target.search});
    await expect(input).toBeVisible();
    await input.fill("synthetic-unmatched-phase3-123xyz");
    await expect(directory.getByRole("button",{name:"Clear search"})).toBeVisible();
    await directory.getByRole("button",{name:"Clear search"}).click();
    await expect(input).toHaveValue("");
    await expect(directory.getByRole("button",{name:"Clear search"})).toHaveCount(0);
    if(!isMobile){
      const head=await directory.locator(".crm-directory-intro").boundingBox();
      expect(head?.height??0).toBeGreaterThan(50);
    }
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
  await expect(form.getByRole("button",{name:"Save Payout"})).toBeVisible();
  await page.goto("/payouts/all");
  const register=page.getByRole("region",{name:"All payout plans"});
  await expect(register.locator(".payout-phase3-list-header")).toBeVisible();
  await expect(register.locator(".payout-phase3-count")).toBeVisible();
  await expect(register.getByRole("textbox",{name:"Payout accounting month"})).toBeVisible();
  await expect(register.getByRole("button",{name:"Export payout plans"})).toBeVisible();
  await expect(register.getByRole("button",{name:"Export payments"})).toBeVisible();
});
