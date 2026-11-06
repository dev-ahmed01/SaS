import {test,expect} from "@playwright/test";

async function signIn(page){
  await page.goto("/login");
  await page.getByRole("textbox",{name:"Email address"}).fill("admin@foundation.org");
  await page.getByLabel("Password",{exact:true})
    .fill("integration-only-long-password-123");
  await page.getByRole("button",{name:"Sign In"}).click();
  await expect(page).toHaveURL(/\/dashboard$/);
}
test.beforeEach(async({page})=>signIn(page));

test("Owner edits payout purpose options in the existing Settings module",async({page})=>{
  await page.goto("/settings");
  const section=page.getByRole("region",{name:"Field Options"});
  await expect(section.getByRole("heading",{name:"Manage field options"})).toBeVisible();
  await expect(section.getByRole("heading",{name:"Payout purpose"})).toBeVisible();
  const label="Synthetic Office Equipment "+(Date.now()%1000000);
  await section.getByRole("textbox",{name:"Add a payout purpose"}).fill(label);
  await section.getByRole("button",{name:"Add option"}).click();
  await expect(section.getByText(label,{exact:true})).toBeVisible();
  await page.goto("/payouts");
  const purpose=page.getByRole("combobox",{name:"Payout purpose"});
  await expect(purpose).toBeVisible();
  await expect(page.getByRole("textbox",{name:"Payout purpose"})).toHaveCount(0);
  await expect(purpose.locator("option",{hasText:label})).toHaveCount(1);
  await purpose.selectOption({label});
  await expect(purpose).not.toHaveValue("");
  await page.goto("/settings");
  await expect(section.getByText(label,{exact:true})).toBeVisible();
  const item=section.locator(".field-option-item").filter({hasText:label});
  page.once("dialog",dialog=>dialog.accept());
  await item.getByRole("button",{name:"Deactivate"}).click();
  await expect(item.getByText(/Inactive/)).toBeVisible();
  await page.goto("/payouts");
  await expect(page.getByRole("combobox",{name:"Payout purpose"})
    .locator("option",{hasText:label})).toHaveCount(0);
});

test("Redesigned promoter profile remains editable and has aligned assignment cards",async({page,isMobile})=>{
  const number="9667"+String(Date.now()%1000000).padStart(6,"0");
  await page.goto("/promoters/add");
  await page.getByRole("textbox",{name:/First Name/}).fill("Redesign Demo");
  await page.getByRole("textbox",{name:/Mobile/}).fill(number);
  await page.getByRole("button",{name:"Add Promoter",exact:true}).click();
  await expect(page).toHaveURL(/\/promoters\/[0-9a-f-]{36}$/);
  const hero=page.locator(".promoter-hero");
  await expect(hero.getByRole("button",{name:"Edit details"})).toBeVisible();
  await expect(hero.getByRole("button",{name:"Mark Inactive"})).toBeVisible();
  await expect(page.locator(".promoter-metric")).toHaveCount(3);
  await expect(page.getByRole("region",{name:"Personal details"})).toBeVisible();
  const panels=page.locator(".promoter-assignments-grid .crm-assignment-card");
  await expect(panels).toHaveCount(2);
  await expect(page.getByRole("region",{name:"Internal promoter notes"})).toBeVisible();
  if(!isMobile){
    const boxes=await Promise.all([0,1].map(i=>panels.nth(i).boundingBox()));
    expect(Math.abs(boxes[0].y-boxes[1].y)).toBeLessThan(8);
    const facts=page.locator(".promoter-profile-fact");
    const positions=await Promise.all([0,1,2,3].map(i=>facts.nth(i).boundingBox()));
    expect(Math.max(...positions.map(x=>x.y))-Math.min(...positions.map(x=>x.y)))
      .toBeLessThan(8);
  }
  await hero.getByRole("button",{name:"Edit details"}).click();
  await expect(page.getByRole("button",{name:"Save Changes"})).toBeVisible();
});
