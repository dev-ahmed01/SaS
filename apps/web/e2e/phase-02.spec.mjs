import { test, expect } from "@playwright/test";

const ADMIN_EMAIL = "admin@foundation.org";
const ADMIN_PASSWORD = "integration-only-long-password-123";
const modules = [
  ["prospects","Prospects"],["promoters","Promoters"],["collections","Collections"],
  ["payouts","Payouts"],["communication","Communication"],["settings","Settings"],
  ["dashboard","Dashboard"]
];

async function logIn(page) {
  await page.goto("/login");
  await page.getByRole("textbox",{name:"Email address"}).fill(ADMIN_EMAIL);
  await page.getByLabel("Password",{exact:true}).fill(ADMIN_PASSWORD);
  const loginResponse = page.waitForResponse(r => r.url().endsWith("/api/admin/login"),{timeout:5000});
  await page.getByRole("button",{name:"Sign In"}).click();
  const response=await loginResponse;
  if(response.status()!==200) {
    const payload=await response.json();
    throw new Error("Login gateway refused credentials: HTTP "+response.status()+" "+JSON.stringify(payload));
  }
  const session=await page.request.get("/api/admin/session");
  if(session.status()!==200) {
    throw new Error("Login cookie not accepted by session gateway: HTTP "+session.status());
  }
  await expect(page).toHaveURL(/\/dashboard$/);
}

test.beforeEach(async ({page}) => {
  await logIn(page);
});

test("login password can be revealed and hidden without submitting",async ({page})=>{
  await page.context().clearCookies();
  await page.goto("/login");
  const input=page.getByLabel("Password",{exact:true});
  await expect(input).toHaveAttribute("type","password");
  await input.fill("sample-visible-password");
  const reveal=page.getByRole("button",{name:"Show password"});
  await expect(reveal.locator("svg")).toBeVisible();
  await expect(reveal).toHaveAttribute("aria-pressed","false");
  await reveal.click();
  await expect(input).toHaveAttribute("type","text");
  await expect(page.getByRole("button",{name:"Hide password"})).toHaveAttribute("aria-pressed","true");
  await expect(input).toHaveValue("sample-visible-password");
  await page.getByRole("button",{name:"Hide password"}).click();
  await expect(input).toHaveAttribute("type","password");
  await expect(input).toHaveValue("sample-visible-password");
  await expect(page).toHaveURL(/\/login$/);
});

test("home and authenticated login open Dashboard",async ({page})=>{
  await page.goto("/");
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole("region",{name:"Foundation dashboard"})).toBeVisible();
  await page.goto("/login");
  await expect(page).toHaveURL(/\/dashboard$/);
});

test("all seven approved modules have a secure navigable destination",async ({page,isMobile})=>{
  for(const [slug,title] of modules){
    if(isMobile)await page.getByRole("button",{name:"Open navigation"}).click();
    await page.getByRole("navigation",{name:"Modules"}).getByRole("link",{name:title,exact:true}).click();
    await expect(page).toHaveURL(new RegExp("/"+slug+"$"));
    await expect(page.getByRole("heading",{name:title,exact:true,level:1})).toBeVisible();
    await expect(page.locator(".topbar h1")).toHaveCount(1);
    await expect(page.locator(".page-content h1")).toHaveCount(0);
  }
});

test("approved tabs remain functional and preview saves stay disabled",async ({page})=>{
  await page.goto("/prospects/add");
  await expect(page.getByRole("button",{name:"Add Prospect"})).toBeEnabled();
  await page.getByRole("navigation",{name:"Module views"}).getByRole("link",{name:"Inactive"}).click();
  await expect(page.getByRole("region",{name:"Inactive Prospects"})).toBeVisible();
  await page.getByRole("navigation",{name:"Module views"}).getByRole("link",{name:"All Prospects"}).click();
  await expect(page.getByRole("region",{name:"All Prospects"})).toBeVisible();
  await page.goto("/collections");
  await expect(page.getByRole("button",{name:"Save Collection"})).toBeDisabled();
  await page.getByRole("link",{name:"Received This Month",exact:true}).click();
  await expect(page.getByRole("heading",{name:"Received this month"})).toBeVisible();
});

test("Communication replaces Reminders with a safe compose-first workspace",async ({page})=>{
  await page.goto("/reminders/whatsapp");
  await expect(page).toHaveURL(/\/communication$/);
  await expect(page.getByRole("heading",{name:"Communication",level:1})).toBeVisible();
  await expect(page.getByRole("heading",{name:"New message"})).toBeVisible();
  const tabs=page.getByRole("navigation",{name:"Communication views"});
  await expect(tabs.getByRole("link").allTextContents()).resolves.toEqual([
    "Compose","Campaigns","Templates","Automations"
  ]);
  await expect(page.getByRole("button",{name:"Save draft"})).toBeVisible();
  await expect(page.getByRole("button",{name:/^Send now/})).toHaveCount(0);
  await expect(page.getByRole("region",{name:"Reminder preparation history"})).toHaveCount(0);
  const clock=page.locator(".topbar-ist-clock");
  await expect(clock).toContainText("IST");
  await expect(clock).not.toContainText("Loading time");
  await page.getByRole("button",{name:"Email"}).click();
  await expect(page.getByRole("textbox",{name:"Email subject"})).toBeVisible();
  await page.goto("/dashboard");
  await expect(page.getByRole("region",{name:"Foundation dashboard"})).toBeVisible();
});

test("desktop branding and landscape artwork have the right proportions",async ({page,isMobile})=>{
  await page.goto("/dashboard");
  if(isMobile)await page.getByRole("button",{name:"Open navigation"}).click();
  const sidebar=page.locator(".site-sidebar");
  const art=page.locator(".sidebar-art");
  await expect(art).toBeVisible();
  await expect(sidebar.getByText("Emlen Foundation",{exact:true})).toHaveCount(1);
  await expect(sidebar.getByText("Sponsor a Salah",{exact:true})).toHaveCount(1);
  await expect(page.locator(".topbar .top-avatar")).toHaveCount(0);
  await expect(page.locator(".topbar h1")).toHaveText("Dashboard");
  await expect(page.locator(".page-content h1")).toHaveCount(0);
  await expect.poll(async()=>art.evaluate(el=>getComputedStyle(el).backgroundImage.includes("sponsor-salah-panorama.avif"))).toBe(true);
  // The image must reach both edges of the padded sidebar on desktop and mobile.
  await expect.poll(async()=>art.evaluate(el=>{
    const sidebar=el.closest(".site-sidebar");
    if(!sidebar)return false;
    const artBounds=el.getBoundingClientRect();
    const sidebarBounds=sidebar.getBoundingClientRect();
    const style=getComputedStyle(el);
    return Math.abs(artBounds.left-sidebarBounds.left)<=1
      && Math.abs(artBounds.right-sidebarBounds.right)<=2
      && style.backgroundSize==="cover"
      && style.backgroundPosition==="50% 100%";
  })).toBe(true);
  if(!isMobile){
    await expect.poll(async()=>sidebar.evaluate(el=>Math.round(el.getBoundingClientRect().width))).toBe(248);
    const metrics=await page.evaluate(()=>{
      const moduleHeading=document.querySelector(".topbar-name");
      const foundationName=document.querySelector(".brand-copy strong");
      const brandCopy=document.querySelector(".brand-copy");
      const panel=document.querySelector(".site-sidebar");
      return {
        moduleSize:parseFloat(getComputedStyle(moduleHeading).fontSize),
        foundationSize:parseFloat(getComputedStyle(foundationName).fontSize),
        brandFits:brandCopy.scrollWidth<=brandCopy.clientWidth+1,
        scroll:panel.scrollHeight<=panel.clientHeight+1
      };
    });
    expect(metrics.moduleSize).toBeGreaterThan(metrics.foundationSize);
    expect(metrics.brandFits).toBe(true);
    expect(metrics.scroll).toBe(true);
  }
});

test("login hero and sidebar decode the shared illustration on desktop and mobile",async ({page})=>{
  // These browser suites authenticate in beforeEach; end that session so the
  // login route can be inspected without its intended redirect.
  await page.context().clearCookies();
  await page.goto("/login");
  const loginArt=page.locator(".login-mosque");
  await expect(loginArt).toBeVisible();
  const loaded=await page.evaluate(async()=>{
    const scene=new Image();
    scene.src="/art/sponsor-salah-panorama.avif";
    await scene.decode();
    return {width:scene.naturalWidth,height:scene.naturalHeight};
  });
  expect(loaded.width).toBeGreaterThanOrEqual(900);
  expect(loaded.height).toBeGreaterThanOrEqual(600);
  await expect.poll(async()=>loginArt.evaluate(el=>getComputedStyle(el).backgroundImage.includes("sponsor-salah-panorama.avif"))).toBe(true);
});

test("Admin profile menu closes with Escape and outside interaction",async ({page,isMobile})=>{
  await page.goto("/dashboard");
  if(isMobile)await page.getByRole("button",{name:"Open navigation"}).click();
  const button=page.getByRole("button",{name:"Admin account"});
  await button.click();
  await expect(page.getByRole("button",{name:"Sign out"})).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(button).toHaveAttribute("aria-expanded","false");
  await button.click();
  await page.getByRole("navigation",{name:"Modules"}).getByRole("link",{name:"Dashboard"}).click();
  if(isMobile)await page.getByRole("button",{name:"Open navigation"}).click();
  await expect(button).toHaveAttribute("aria-expanded","false");
  await expect(page.getByRole("button",{name:"Sign out"})).toHaveCount(0);
});

test("responsive layout has no horizontal overflow and drawer controls work",async ({page,isMobile})=>{
  await page.goto("/promoters");
  await expect.poll(async()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  if(isMobile){
    await page.getByRole("button",{name:"Open navigation"}).click();
    await expect(page.getByRole("navigation",{name:"Modules"})).toBeVisible();
    await page.getByRole("button",{name:"Close menu"}).click();
  }else{
    await expect(page.getByRole("button",{name:"Collapse sidebar"})).toHaveCount(0);
    await expect(page.getByRole("link",{name:"Emlen Foundation home"})).toBeVisible();
  }
});

test("WhatsApp cannot be enabled by a development Admin",async ({page})=>{
  await page.goto("/settings");
  await expect(page.getByText("WhatsApp automation",{exact:true})).toHaveCount(0);
  await expect(page.getByRole("button",{name:"Enable WhatsApp automation"})).toHaveCount(0);
});

test("settings are persisted, edited and can be reloaded",async ({page})=>{
  await page.goto("/settings");
  await expect(page.getByRole("heading",{name:"Organisation Settings"})).toBeVisible();
  const amount=page.getByRole("spinbutton",{name:"Default monthly contribution (₹)"});
  await expect(amount).not.toHaveValue("");
  const updated=(Number(await amount.inputValue())+250).toString();
  await amount.fill(updated);
  await page.getByRole("button",{name:"Save Changes"}).click();
  await expect(page.getByText(/Settings saved/)).toBeVisible();
  await page.reload();
  await expect(page.getByRole("spinbutton",{name:"Default monthly contribution (₹)"})).toHaveValue(updated);
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

test("sign out ends the authenticated browser session",async ({page,isMobile})=>{
  if(isMobile) await page.getByRole("button",{name:"Open navigation"}).click();
  const profile=page.getByRole("button",{name:"Admin account"});
  await expect(profile).toHaveAttribute("aria-expanded","false");
  await expect(page.getByRole("button",{name:"Sign out"})).toHaveCount(0);
  await profile.click();
  await expect(profile).toHaveAttribute("aria-expanded","true");
  await page.getByRole("button",{name:"Sign out"}).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.goto("/collections");
  await expect(page).toHaveURL(/\/login$/);
});

test("wrong password never yields an authenticated session",async ({page,context})=>{
  await context.clearCookies();
  await page.goto("/login");
  await page.getByRole("textbox",{name:"Email address"}).fill(ADMIN_EMAIL);
  await page.getByLabel("Password",{exact:true}).fill("incorrect-password");
  await page.getByRole("button",{name:"Sign In"}).click();
  await expect(page.locator(".form-error")).toContainText("Unable to sign in");
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login$/);
});

test("Admin registers and searches a new prospect without fake payment status",async ({page})=>{
  const label="Phase4 Browser Candidate "+(Date.now()%1000000);
  await page.goto("/prospects/add");
  await page.getByRole("textbox",{name:/First Name/}).fill(label);
  await page.getByRole("textbox",{name:/WhatsApp \/ Mobile/}).fill("9876543210");
  await page.getByRole("textbox",{name:/City/}).fill("Bengaluru");
  await page.getByRole("button",{name:"Add Prospect",exact:true}).click();
  await expect(page).toHaveURL(/\/prospects\/[0-9a-f-]{36}$/);
  await expect(page.getByText("Never paid")).toBeVisible();
  await page.getByRole("button",{name:/Edit details/}).click();
  await page.getByRole("textbox",{name:/Occupation/}).fill("Teacher");
  await page.getByRole("button",{name:"Save Changes"}).click();
  await expect(page.getByText("Teacher")).toBeVisible();
  await page.goto("/prospects");
  await page.getByRole("textbox",{name:"Search prospects"}).fill(label);
  const row=page.getByRole("row",{name:new RegExp(label)});
  await expect(row).toBeVisible();
  await expect(row.getByText("Active",{exact:true})).toBeVisible();
  await row.getByRole("link",{name:label}).click();
  await expect(page.getByText("Teacher")).toBeVisible();
});

test("Admin can archive and restore a prospect without deleting its record",async ({page})=>{
  const label="Archive Browser Candidate "+(Date.now()%1000000);
  await page.goto("/prospects/add");
  await page.getByRole("textbox",{name:/First Name/}).fill(label);
  await page.getByRole("textbox",{name:/WhatsApp \/ Mobile/}).fill("9876543201");
  await page.getByRole("button",{name:"Add Prospect",exact:true}).click();
  await expect(page).toHaveURL(/\/prospects\/[0-9a-f-]{36}$/);
  await page.getByRole("button",{name:/Delete prospect/}).click();
  await expect(page.getByRole("dialog",{name:"Confirm prospect archive"})).toBeVisible();
  await page.getByRole("button",{name:"Archive prospect",exact:true}).click();
  const detailsUrl=page.url();
  await expect(page.getByText("Archived",{exact:true})).toBeVisible();
  await page.goto("/prospects");
  await page.getByRole("textbox",{name:"Search prospects"}).fill(label);
  await expect(page.getByRole("row",{name:new RegExp(label)})).toHaveCount(0);
  await expect(page.getByRole("checkbox",{name:"Include archived"})).toHaveCount(0);
  await page.goto(detailsUrl);
  await page.getByRole("button",{name:/Restore prospect/}).click();
  await page.getByRole("dialog",{name:"Confirm prospect archive"}).getByRole("button",{name:"Restore prospect"}).click();
  await expect(page.getByText("Active",{exact:true}).first()).toBeVisible();
});

test("Prospect listing shows dedicated Stage, Status and sticky Action dropdown",async ({page})=>{
  await page.goto("/prospects");
  await expect(page.getByRole("checkbox",{name:"Include archived"})).toHaveCount(0);
  await expect(page.locator(".crm-list-tools-right")).toHaveCount(0);
  await expect(page.locator(".prospects-table th").allTextContents()).resolves.toEqual([
    "Created","Full Name","Mobile","City","Sponsorship","Start","Promoter",
    "Stage","Status","Action"
  ]);
  const style=await page.locator(".prospects-table th").last()
    .evaluate(el=>getComputedStyle(el).position);
  expect(style).toBe("sticky");
  const weight=await page.locator(".topbar-name")
    .evaluate(el=>getComputedStyle(el).fontWeight);
  expect(weight).toBe("800");
  const sidebar=page.locator(".brand-copy");
  await expect(sidebar.getByText("Emlen Foundation",{exact:true})).toHaveCount(1);
  await expect(sidebar.getByText("Sponsor a Salah",{exact:true})).toHaveCount(1);
});

test("Prospect CRM tabs, profile cards and reasoned inactivity work without changing payment status",async ({page})=>{
  const name="Stage Candidate "+(Date.now()%1000000);
  await page.goto("/prospects");
  const tabs=page.getByRole("navigation",{name:"Module views"});
  await expect(tabs.getByRole("link")).toHaveCount(5);
  await expect(tabs.getByRole("link").allTextContents()).resolves.toEqual([
    "All Prospects","Add Prospects","Active","Inactive","Stages"
  ]);
  const columns=await tabs.evaluate(el=>getComputedStyle(el).gridTemplateColumns.split(" ").length);
  expect(columns).toBe(5);
  await tabs.getByRole("link",{name:"Add Prospect"}).click();
  await page.getByRole("textbox",{name:/First Name/}).fill(name);
  await page.getByRole("textbox",{name:/WhatsApp \/ Mobile/}).fill("9765432100");
  await page.getByRole("combobox",{name:"Sponsorship Tokens"}).selectOption("2");
  await page.getByRole("textbox",{name:/City/}).fill("Mysuru");
  await page.getByRole("button",{name:"Add Prospect",exact:true}).click();
  await expect(page).toHaveURL(/\/prospects\/[0-9a-f-]{36}$/);
  await expect(page.getByRole("heading",{name:"Sponsorship"})).toBeVisible();
  await expect(page.getByText("Never paid")).toBeVisible();
  await page.getByRole("button",{name:/Mark inactive/}).click();
  const dialog=page.getByRole("dialog",{name:"Mark prospect inactive"});
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("button",{name:"Confirm Inactive"})).toBeDisabled();
  await dialog.getByRole("combobox",{name:/Reason for leaving/}).selectOption("budget");
  await dialog.getByRole("button",{name:"Confirm Inactive"}).click();
  await expect(page.getByText("Budget or affordability",{exact:true})).toBeVisible();
  await expect(page.getByText("0",{exact:true}).first()).toBeVisible();
  await expect(page.getByText("Never paid")).toBeVisible();
  await page.goto("/prospects/inactive");
  await page.getByRole("textbox",{name:"Search prospects"}).fill(name);
  const row=page.getByRole("row",{name:new RegExp(name)});
  await expect(row.getByText("Inactive",{exact:true})).toBeVisible();
  await row.getByRole("combobox",{name:"Actions for "+name}).selectOption("status");
  await page.getByRole("dialog",{name:"Reactivate prospect"}).getByRole("button",{name:"Mark Active"}).click();
  await expect(row).toHaveCount(0);
  await page.goto("/prospects/active");
  await page.getByRole("textbox",{name:"Search prospects"}).fill(name);
  await expect(page.getByRole("row",{name:new RegExp(name)})).toBeVisible();
});

test("Prospect pipeline stages can be added, edited, assigned and safely deleted",async ({page})=>{
  const stage="Pipeline Stage "+(Date.now()%1000000);
  const person="Pipeline Candidate "+(Date.now()%1000000);
  await page.goto("/prospects/stages");
  await expect(page.getByRole("region",{name:"Manage prospect stages"})).toBeVisible();
  await page.getByRole("textbox",{name:/Name/}).fill(stage);
  await page.getByRole("textbox",{name:/Description/}).fill("Initial contact completed");
  await page.getByRole("button",{name:"Choose color #0f766e"}).click();
  await page.getByRole("spinbutton",{name:"Order"}).fill("3");
  await page.getByRole("button",{name:"Add Stage"}).click();
  await expect(page.getByText(stage,{exact:true})).toBeVisible();
  await expect(page.getByText("0 prospects")).toBeVisible();
  await page.getByRole("button",{name:"Edit stage "+stage}).click();
  const renamed=stage+" edited";
  await page.getByRole("textbox",{name:/Name/}).fill(renamed);
  await page.getByRole("button",{name:"Save Stage"}).click();
  await expect(page.getByText(renamed,{exact:true})).toBeVisible();
  await page.goto("/prospects/add");
  await page.getByRole("textbox",{name:/First Name/}).fill(person);
  await page.getByRole("textbox",{name:/WhatsApp \/ Mobile/}).fill("9876432101");
  await page.getByRole("combobox",{name:"Prospect Stage"}).selectOption({label:renamed});
  await page.getByRole("button",{name:"Add Prospect",exact:true}).click();
  await expect(page).toHaveURL(/\/prospects\/[0-9a-f-]{36}$/);
  await expect(page.getByText(renamed,{exact:true})).toBeVisible();
  await page.goto("/prospects/stages");
  await expect(page.getByText("1 prospects")).toBeVisible();
  await page.getByRole("button",{name:"Delete stage "+renamed}).click();
  const dialog=page.getByRole("dialog",{name:"Confirm stage deletion"});
  await expect(dialog.getByRole("button",{name:"Delete stage"})).toBeDisabled();
  await dialog.getByRole("button",{name:"Cancel"}).click();
  await page.goto("/prospects");
  await page.getByRole("textbox",{name:"Search prospects"}).fill(person);
  await page.getByRole("row",{name:new RegExp(person)}).getByRole("link",{name:person}).click();
  await page.getByRole("button",{name:/Edit details/}).click();
  await page.getByRole("combobox",{name:"Prospect Stage"}).selectOption("");
  await page.getByRole("button",{name:"Save Changes"}).click();
  await page.goto("/prospects/stages");
  await page.getByRole("button",{name:"Delete stage "+renamed}).click();
  await page.getByRole("dialog",{name:"Confirm stage deletion"})
    .getByRole("button",{name:"Delete stage"}).click();
  await expect(page.getByText(renamed,{exact:true})).toHaveCount(0);
});

test("Admin creates and searches promoters with the requested CRM fields",async ({page})=>{
  const label="Phase5 Promoter "+(Date.now()%1000000);
  const number="9876"+String(Date.now()%1000000).padStart(6,"0");
  await page.goto("/promoters");
  const tabs=page.getByRole("navigation",{name:"Module views"});
  await expect(tabs.getByRole("link").allTextContents()).resolves.toEqual([
    "All Promoters","Add Promoters","Active","Inactive"
  ]);
  await tabs.getByRole("link",{name:"Add Promoters"}).click();
  await page.getByRole("textbox",{name:/First Name/}).fill(label);
  await page.getByRole("textbox",{name:/Mobile/}).fill(number);
  await page.getByRole("textbox",{name:/City/}).fill("Mysuru");
  await page.getByRole("textbox",{name:/Occupation/}).fill("Teacher");
  await page.getByRole("button",{name:"Add Promoter",exact:true}).click();
  await expect(page).toHaveURL(/\/promoters\/[0-9a-f-]{36}$/);
  await expect(page.getByText("Teacher")).toBeVisible();
  await page.goto("/promoters");
  const find=page.getByRole("textbox",{name:"Search promoters"});
  await find.fill(label);
  await expect(page.getByRole("row",{name:new RegExp(label)})).toBeVisible();
  const headers=await page.locator(".promoter-crm-table thead th").allTextContents();
  expect(headers).toEqual(["Created","Full Name","Mobile","City","Sponsors","Status"]);
  await tabs.getByRole("link",{name:"Active",exact:true}).click();
  await expect(page.getByRole("region",{name:"Active Promoters"})).toBeVisible();
  await page.getByRole("textbox",{name:"Search promoters"}).fill(label);
  await expect(page.getByRole("row",{name:new RegExp(label)})).toBeVisible();
});

test("Admin edits promoter cards and changes status with confirmation",async ({page})=>{
  const label="Toggle Promoter "+(Date.now()%1000000);
  const number="9786"+String(Date.now()%1000000).padStart(6,"0");
  await page.goto("/promoters/add");
  await page.getByRole("textbox",{name:/First Name/}).fill(label);
  await page.getByRole("textbox",{name:/Mobile/}).fill(number);
  await page.getByRole("button",{name:"Add Promoter",exact:true}).click();
  await expect(page).toHaveURL(/\/promoters\/[0-9a-f-]{36}$/);
  await page.getByRole("button",{name:/Edit details/}).click();
  await page.getByRole("textbox",{name:/Occupation/}).fill("Architect");
  await page.getByRole("button",{name:"Save Changes"}).click();
  await expect(page.getByText("Architect")).toBeVisible();
  await page.getByRole("button",{name:/^Deactivate/}).click();
  const confirm=page.getByRole("dialog",{name:"Confirm promoter status"});
  await expect(confirm).toBeVisible();
  await confirm.getByRole("button",{name:"Confirm"}).click();
  await expect(page.getByText("Inactive",{exact:true}).first()).toBeVisible();
  await page.goto("/promoters/inactive");
  await page.getByRole("textbox",{name:"Search promoters"}).fill(label);
  const row=page.getByRole("row",{name:new RegExp(label)});
  await expect(row).toBeVisible();
  await row.getByRole("button",{name:/Reactivate/}).click();
  await page.getByRole("dialog",{name:"Confirm promoter status"}).getByRole("button",{name:"Confirm"}).click();
  await expect(row).toHaveCount(0);
});

test("Promoter details safely assign and unassign a sponsor",async ({page})=>{
  const key=Date.now()%1000000;
  const sponsor="Phase5 Sponsor "+key;
  const promoter="Phase5 Liaison "+key;
  await page.goto("/prospects/add");
  await page.getByRole("textbox",{name:/First Name/}).fill(sponsor);
  await page.getByRole("textbox",{name:/WhatsApp \/ Mobile/}).fill("9676"+String(key).padStart(6,"0"));
  await page.getByRole("button",{name:"Add Prospect",exact:true}).click();
  await expect(page).toHaveURL(/\/prospects\/[0-9a-f-]{36}$/);
  await page.goto("/promoters/add");
  await page.getByRole("textbox",{name:/First Name/}).fill(promoter);
  await page.getByRole("textbox",{name:/Mobile/}).fill("9566"+String(key).padStart(6,"0"));
  await page.getByRole("button",{name:"Add Promoter",exact:true}).click();
  await expect(page).toHaveURL(/\/promoters\/[0-9a-f-]{36}$/);
  const section=page.getByRole("region",{name:"Sponsor assignments"});
  await section.getByRole("textbox",{name:"Find sponsor"}).fill(sponsor);
  await expect(section.getByText(sponsor,{exact:true})).toBeVisible();
  page.once("dialog",d=>d.accept());
  await section.getByRole("button",{name:"Assign",exact:true}).click();
  await expect(section.getByRole("button",{name:"Unassign"})).toBeVisible();
  await section.getByRole("button",{name:"Unassign"}).click();
  await expect(section.getByText("No sponsors assigned to this promoter.")).toBeVisible();
});

test("Collections All shows real monthly commitments, not imaginary deposits",async ({page})=>{
  const name="Ledger Candidate "+(Date.now()%1000000);
  await page.goto("/prospects/add");
  await page.getByRole("textbox",{name:/First Name/}).fill(name);
  const agreed=Number(await page.getByRole("combobox",{name:"Sponsorship Tokens"}).inputValue())*250;
  await page.getByRole("textbox",{name:/WhatsApp \/ Mobile/}).fill("9876543210");
  await page.getByRole("button",{name:"Add Prospect",exact:true}).click();
  await expect(page).toHaveURL(/\/prospects\/[0-9a-f-]{36}$/);
  await page.goto("/collections/all");
  await expect(page.getByRole("heading",{name:"Monthly sponsorship ledger"})).toBeVisible();
  await expect(page.getByText("Verified collections")).toBeVisible();
  const row=page.getByRole("row",{name:new RegExp(name)});
  await expect(row).toBeVisible();
  const amount=agreed.toLocaleString("en-IN",{minimumFractionDigits:2,maximumFractionDigits:2});
  await expect(row.getByRole("cell").nth(1)).toContainText(amount);
  await expect(row.getByRole("cell").nth(2)).toContainText("0.00");
  await expect(row.getByRole("cell").nth(3)).toContainText(amount);
  await expect(row.getByText("New",{exact:true})).toBeVisible();
  await expect(row.getByText("No",{exact:true})).toBeVisible();
  await page.getByRole("button",{name:"Refresh sponsor statuses"}).click();
  await expect(page.getByText(/Checked .* sponsors/)).toBeVisible();
});

test("Accounting rejects forged requests and never exposes payment write actions",async ({page})=>{
  const unauthenticated=await page.request.get("/api/admin/accounting/overview");
  expect(unauthenticated.status()).toBe(200);
  const noCsrf=await page.evaluate(()=>fetch("/api/admin/accounting/refresh-statuses",{
    method:"POST",
  }).then(response=>response.status));
  expect(noCsrf).toBe(403);
  const forged=await page.request.post("/api/admin/accounting/refresh-statuses",{
    headers:{"Origin":"https://invalid.example"},
  });
  expect(forged.status()).toBe(403);
  const unsupported=await page.request.post("/api/admin/accounting/credit",{
    headers:{"Origin":"http://127.0.0.1:3000"},
  });
  expect(unsupported.status()).toBe(404);
});

test("manual collection amount accepts only ₹250 denominations",async ({page})=>{
  await page.goto("/collections");
  const tiers=page.getByRole("combobox",{name:"Amount received (₹)"});
  for (const valid of ["250","500","750","1000"]) {
    await tiers.selectOption(valid);
    await expect(tiers).toHaveValue(valid);
  }
  await tiers.selectOption("other");
  const amount=page.getByRole("spinbutton",{name:"Custom collection amount (₹)"});
  await expect(amount).toHaveAttribute("min","250");
  await expect(amount).toHaveAttribute("step","250");
  for (const invalid of ["125","375","700"]) {
    await amount.fill(invalid);
    expect(await amount.evaluate(element=>element.checkValidity())).toBe(false);
  }
  await amount.fill("15000");
  expect(await amount.evaluate(element=>element.checkValidity())).toBe(true);
  // No sponsor is selected: this is input validation only, never a real receipt.
});

test("Sponsorship dropdown enforces ₹250 multiples and supports custom quantities",async ({page})=>{
  await page.goto("/prospects/add");
  const tokens=page.getByRole("combobox",{name:"Sponsorship Tokens"});
  await expect(tokens).toBeVisible();
  expect(Number(await tokens.inputValue())).toBeGreaterThan(0);
  await tokens.selectOption("3");
  await expect(page.getByText("₹750 / month")).toBeVisible();
  await tokens.selectOption("custom");
  const custom=page.getByRole("spinbutton",{name:"Custom sponsorship tokens"});
  await expect(custom).toBeVisible();
  await custom.fill("1.5");
  expect(await custom.evaluate(element=>element.checkValidity())).toBe(false);
  await custom.fill("60");
  expect(await custom.evaluate(element=>element.checkValidity())).toBe(true);
  await expect(page.getByText("₹15,000 / month")).toBeVisible();
  await expect(page.getByText(/Payment identifiers/)).toHaveCount(0);
  await expect(page.locator(".prospect-field-row .field-label").filter({hasText:"(optional)"})).toHaveCount(0);
});

test("Admin records a manual contribution without claiming WhatsApp delivery",async ({page})=>{
  const id=String(Date.now()%1000000).padStart(6,"0");
  const name="Manual Pay Sponsor "+id;
  await page.goto("/prospects/add");
  await page.getByRole("textbox",{name:/First Name/}).fill(name);
  const agreed=Number(await page.getByRole("combobox",{name:"Sponsorship Tokens"}).inputValue())*250;
  await page.getByRole("textbox",{name:/WhatsApp \/ Mobile/}).fill("9826"+id);
  await page.getByRole("checkbox",{name:/WhatsApp reminder consent/}).check();
  await page.getByRole("button",{name:"Add Prospect",exact:true}).click();
  await expect(page).toHaveURL(/\/prospects\/[0-9a-f-]{36}$/);
  await page.goto("/collections");
  await expect(page.getByRole("heading",{name:"Record Collection"})).toBeVisible();
  await page.getByRole("textbox",{name:"Search sponsor"}).fill(name);
  await page.getByRole("option",{name:new RegExp(name)}).click();
  const payment=page.getByRole("combobox",{name:"Amount received (₹)"});
  await expect(payment).toHaveValue("");
  await payment.selectOption(String(agreed));
  await page.getByRole("textbox",{name:"Transaction reference"}).fill("TESTREF"+id);
  const save=page.getByRole("button",{name:"Save Collection"});
  await expect(save).toBeDisabled();
  await page.getByRole("checkbox",{name:/Foundation's records/}).check();
  const amountBounds=await payment.boundingBox();
  const submitBounds=await save.boundingBox();
  expect(submitBounds.y).toBeGreaterThan(amountBounds.y+amountBounds.height);
  await save.scrollIntoViewIfNeeded();
  await save.click();
  await expect(page.getByRole("status").filter({hasText:"Recorded"})).toBeVisible();
  await expect(page.getByText(/has not been sent/)).toBeVisible();
  await expect(page.getByRole("region",{name:"Recent manual collections"}).getByText(name)).toBeVisible();
  await page.goto("/collections/all");
  await expect(page.getByRole("heading",{name:"Monthly sponsorship ledger"})).toBeVisible();
  const row=page.getByRole("region",{name:"Monthly sponsorship ledger"}).getByRole("row",{name:new RegExp(name)});
  await expect(row).toBeVisible();
  await expect(row.getByText("Active",{exact:true})).toBeVisible();
  await expect(row.getByText("Yes",{exact:true})).toBeVisible();
});

test("Duplicate manual reference cannot create a second contribution",async ({page})=>{
  const id=String(Date.now()%1000000).padStart(6,"0");
  const name="Receipt Retry Sponsor "+id;
  await page.goto("/prospects/add");
  await page.getByRole("textbox",{name:/First Name/}).fill(name);
  await page.getByRole("textbox",{name:/WhatsApp \/ Mobile/}).fill("9836"+id);
  await page.getByRole("button",{name:"Add Prospect",exact:true}).click();
  await expect(page).toHaveURL(/\/prospects\/[0-9a-f-]{36}$/);
  await page.goto("/collections");
  await expect(page.getByRole("heading",{name:"Record Collection"})).toBeVisible();
  await page.getByRole("textbox",{name:"Search sponsor"}).fill(name);
  await page.getByRole("option",{name:new RegExp(name)}).click();
  await page.getByRole("combobox",{name:"Amount received (₹)"}).selectOption("500");
  const receivedOn=await page.locator('input[type="date"]').inputValue();
  const month=await page.locator('input[type="month"]').inputValue();
  await page.getByRole("textbox",{name:"Transaction reference"}).fill("DUPEREF"+id);
  await page.getByRole("checkbox",{name:/Foundation's records/}).check();
  await page.getByRole("button",{name:"Save Collection"}).scrollIntoViewIfNeeded();
  await page.getByRole("button",{name:"Save Collection"}).click();
  await expect(page.getByRole("status").filter({hasText:"Recorded"})).toBeVisible();
  const outcome=await page.evaluate(async({receivedOn,month,reference})=>{
    const session=await fetch("/api/admin/session",{cache:"no-store"});
    const {csrf_token}=await session.json();
    const list=await fetch("/api/admin/collections?limit=1",{cache:"no-store"});
    const existing=(await list.json()).items[0];
    const response=await fetch("/api/admin/collections",{
      method:"POST",
      headers:{"X-CSRF-Token":csrf_token,"Content-Type":"application/json"},
      body:JSON.stringify({
        request_id:crypto.randomUUID(),prospect_id:existing.prospect_id,
        amount_paise:50000,period_month:month+"-01",received_on:receivedOn,
        payment_method:"upi",receipt_reference:reference,funds_confirmed:true,
      }),
    });
    return response.status;
  },{receivedOn,month,reference:"DUPEREF"+id});
  expect(outcome).toBe(409);
});


test("Admin reverses a mistaken collection and the net ledger returns to unpaid",async ({page})=>{
  const id=String(Date.now()%1000000).padStart(6,"0");
  const name="Reversal Browser Sponsor "+id;
  await page.goto("/prospects/add");
  await page.getByRole("textbox",{name:/First Name/}).fill(name);
  const agreed=Number(await page.getByRole("combobox",{name:"Sponsorship Tokens"}).inputValue())*250;
  await page.getByRole("textbox",{name:/WhatsApp \/ Mobile/}).fill("9847"+id);
  await page.getByRole("checkbox",{name:/WhatsApp reminder consent/}).check();
  await page.getByRole("button",{name:"Add Prospect",exact:true}).click();
  await expect(page).toHaveURL(/\/prospects\/[0-9a-f-]{36}$/);

  await page.goto("/collections");
  await page.getByRole("textbox",{name:"Search sponsor"}).fill(name);
  await page.getByRole("option",{name:new RegExp(name)}).click();
  await page.getByRole("combobox",{name:"Amount received (₹)"}).selectOption(String(agreed));
  await page.getByRole("textbox",{name:"Transaction reference"}).fill("REVERSAL"+id);
  await page.getByRole("checkbox",{name:/Foundation's records/}).check();
  await page.getByRole("button",{name:"Save Collection"}).scrollIntoViewIfNeeded();
  await page.getByRole("button",{name:"Save Collection"}).click();
  await expect(page.getByRole("status").filter({hasText:"Recorded"})).toBeVisible();
  await page.goto("/collections/all");
  const review=page.getByRole("region",{name:"Collection review"});
  const historyRow=review.getByRole("row",{name:new RegExp(name)});
  await expect(historyRow).toBeVisible();
  await expect(historyRow.getByText("Recorded",{exact:true})).toBeVisible();
  await historyRow.getByRole("button",{name:"Reverse entry"}).click();

  const dialog=page.getByRole("dialog",{name:"Reverse collection entry"});
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText(name,{exact:true})).toBeVisible();
  const submit=dialog.getByRole("button",{name:"Confirm reversal"});
  await expect(submit).toBeDisabled();
  await dialog.getByRole("combobox",{name:"Reason for reversal"}).selectOption("funds_not_received");
  await dialog.getByRole("textbox",{name:"Type REVERSE to confirm"}).fill("REVERSE");
  await submit.click();
  await expect(dialog).toHaveCount(0);
  await expect(review.getByRole("status")).toContainText(/Reversed the incorrect/);
  const reversed=review.getByRole("row",{name:new RegExp(name)});
  await expect(reversed.getByText("Reversed",{exact:true})).toBeVisible();
  await expect(reversed.getByText("Suppressed",{exact:true})).toBeVisible();
  await expect(reversed.getByRole("button",{name:"Reverse entry"})).toHaveCount(0);

  const ledger=page.getByRole("region",{name:"Monthly sponsorship ledger"});
  const dueRow=ledger.getByRole("row",{name:new RegExp(name)});
  await expect(dueRow.getByRole("cell").nth(2)).toContainText("0.00");
  await expect(dueRow.getByRole("cell").nth(3)).toContainText(agreed.toLocaleString("en-IN",{minimumFractionDigits:2,maximumFractionDigits:2}));
  await expect(dueRow.getByText("New",{exact:true})).toBeVisible();
});

test("Reversal gateway rejects unsigned, forged-origin and malformed operations",async ({page})=>{
  const id="00000000-0000-4000-8000-000000000001";
  await page.goto("/collections/all");
  const unverified=await page.evaluate(async(record)=>{
    const res=await fetch("/api/admin/collections/"+record+"/reverse",{
      method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({
        request_id:crypto.randomUUID(),reason_code:"wrong_amount",confirmation:"REVERSE"
      }),
    });
    return res.status;
  },id);
  expect(unverified).toBe(403);
  const forged=await page.request.post("/api/admin/collections/"+id+"/reverse",{
    headers:{"Origin":"https://untrusted.example","Content-Type":"application/json"},
    data:{
      request_id:"00000000-0000-4000-8000-000000000002",
      reason_code:"wrong_amount",confirmation:"REVERSE",
    },
  });
  expect(forged.status()).toBe(403);
  const invalid=await page.request.post("/api/admin/collections/not-a-uuid/reverse",{
    headers:{"Origin":"http://127.0.0.1:3000","Content-Type":"application/json"},
    data:{},
  });
  expect(invalid.status()).toBe(404);
});


test("Recurring payouts are planned before separate attested outgoing payment",async ({page})=>{
  const stamp=String(Date.now()%1000000).padStart(6,"0");
  const name="Phase9 Recurring Payee "+stamp;
  await page.goto("/payouts");
  await expect(page.getByRole("heading",{name:"Add payout"})).toBeVisible();
  await page.getByRole("textbox",{name:"Payee name"}).fill(name);
  await page.getByRole("textbox",{name:"Payout purpose"}).fill("Synthetic monthly facility upkeep");
  await page.getByRole("textbox",{name:"Payout amount (₹)"}).fill("742.35");
  await page.getByRole("button",{name:"Save payout plan"}).click();
  await expect(page.getByRole("status").filter({hasText:"Saved recurring"})).toBeVisible();
  await page.goto("/payouts/all");
  const section=page.getByRole("region",{name:"All payout plans"});
  const plan=section.getByRole("table").first().getByRole("row",{name:new RegExp(name)});
  await expect(plan).toBeVisible();
  await expect(plan.getByText("₹742.35")).toBeVisible();
  await expect(plan.getByText("₹0.00")).toBeVisible();
  await expect(plan.getByText("Active",{exact:true})).toBeVisible();
  await plan.getByRole("button",{name:"Record paid"}).click();
  const modal=page.getByRole("dialog",{name:"Record paid payout"});
  await expect(modal).toBeVisible();
  const submit=modal.getByRole("button",{name:"Record payment"});
  await expect(submit).toBeDisabled();
  await modal.getByRole("textbox",{name:"Outgoing payment reference"}).fill("PAYOUTREF"+stamp);
  await modal.getByRole("checkbox",{name:/funds were disbursed/}).check();
  await submit.click();
  await expect(modal).toHaveCount(0);
  await expect(section.getByRole("status")).toContainText(/Recorded the actual outgoing payment/);
  await expect(plan.getByRole("cell").nth(4)).toContainText("742.35");
  await expect(plan.getByRole("button",{name:"Record paid"})).toHaveCount(0);
  const history=page.getByRole("region",{name:"Recorded payout history"});
  await expect(history.getByRole("row",{name:new RegExp(name)})).toBeVisible();
  await expect(history.getByText("****"+stamp.slice(-4))).toBeVisible();
});

test("One-time payouts stay in All after payment; recurring Active excludes them",async ({page})=>{
  const stamp=String(Date.now()%1000000).padStart(6,"0");
  const name="Phase9 OneTime Payee "+stamp;
  await page.goto("/payouts");
  await page.getByRole("textbox",{name:"Payee name"}).fill(name);
  await page.getByRole("textbox",{name:"Payout purpose"}).fill("Synthetic one-time repair");
  await page.getByRole("combobox",{name:"Payout type"}).selectOption("one_time");
  await page.getByRole("textbox",{name:"Payout amount (₹)"}).fill("2895.00");
  await page.getByRole("button",{name:"Save payout plan"}).click();
  await expect(page.getByRole("status").filter({hasText:"Saved one-time"})).toBeVisible();
  await page.goto("/payouts/active");
  await expect(page.getByRole("region",{name:"Active payout plans"}).getByText(name)).toHaveCount(0);
  await page.goto("/payouts/all");
  const plans=page.getByRole("region",{name:"All payout plans"}).getByRole("table").first();
  const row=plans.getByRole("row",{name:new RegExp(name)});
  await expect(row).toBeVisible();
  await expect(row.getByRole("cell",{name:"One-time",exact:true})).toBeVisible();
  await row.getByRole("button",{name:"Record paid"}).click();
  const modal=page.getByRole("dialog",{name:"Record paid payout"});
  await modal.getByRole("textbox",{name:"Outgoing payment reference"}).fill("ONETIME"+stamp);
  await modal.getByRole("checkbox",{name:/funds were disbursed/}).check();
  await modal.getByRole("button",{name:"Record payment"}).click();
  await expect(row.getByText("Paid",{exact:true})).toBeVisible();
  await expect(row.getByRole("cell").nth(4)).toContainText("2,895.00");
});

test("Recurring pause schedules next month without changing current obligations",async ({page})=>{
  const stamp=String(Date.now()%1000000).padStart(6,"0");
  const name="Phase9 Pausable Payee "+stamp;
  await page.goto("/payouts");
  await page.getByRole("textbox",{name:"Payee name"}).fill(name);
  await page.getByRole("textbox",{name:"Payout purpose"}).fill("Monthly synthetic maintenance");
  await page.getByRole("textbox",{name:"Payout amount (₹)"}).fill("975.00");
  await page.getByRole("button",{name:"Save payout plan"}).click();
  await expect(page.getByRole("status").filter({hasText:"Saved recurring"})).toBeVisible();
  await page.goto("/payouts/active");
  const active=page.getByRole("region",{name:"Active payout plans"});
  const row=active.getByRole("row",{name:new RegExp(name)});
  await expect(row).toBeVisible();
  await row.getByRole("button",{name:"Pause",exact:true}).click();
  const dialog=page.getByRole("dialog",{name:"Schedule recurring status"});
  await expect(dialog).toContainText("next month");
  await dialog.getByRole("button",{name:"Confirm status change"}).click();
  await expect(dialog).toHaveCount(0);
  await expect(row.getByText("Active",{exact:true})).toBeVisible();
  await expect(row.getByText("Next: paused")).toBeVisible();
  await expect(row.getByRole("button",{name:"Pause",exact:true})).toHaveCount(0);
});

test("Payout write gateway rejects forged origins, missing CSRF and invalid routes",async ({page})=>{
  const malformed=await page.request.post(
    "/api/admin/payouts/plans/not-a-uuid/payments",{
      headers:{"Content-Type":"application/json","Origin":"http://127.0.0.1:3000"},
      data:{},
    }
  );
  expect(malformed.status()).toBe(404);
  const forged=await page.request.post("/api/admin/payouts/plans",{
    headers:{"Origin":"https://untrusted.example","Content-Type":"application/json"},
    data:{},
  });
  expect(forged.status()).toBe(403);
  const noCsrf=await page.evaluate(()=>fetch("/api/admin/payouts/plans",{
    method:"POST",headers:{"Content-Type":"application/json"},body:"{}"
  }).then(r=>r.status));
  expect(noCsrf).toBe(403);
});


test("Admin plans and confirms a recurring payout with separate payment evidence",async ({page})=>{
  const token=String(Date.now()%1000000).padStart(6,"0");
  const payee="Payout Caretaker "+token;
  await page.goto("/payouts");
  await expect(page.getByRole("region",{name:"Add payout plan"})).toBeVisible();
  await page.getByRole("textbox",{name:"Payee name"}).fill(payee);
  await page.getByRole("textbox",{name:"Payout purpose"}).fill("Synthetic building maintenance");
  await page.getByRole("textbox",{name:"Payout amount (₹)"}).fill("735.00");
  await page.getByRole("button",{name:"Save payout plan"}).click();
  await expect(page.getByRole("status")).toContainText("No money has been transferred.");

  await page.goto("/payouts/active");
  const active=page.getByRole("region",{name:"Active payout plans"});
  const row=active.getByRole("row",{name:new RegExp(payee)});
  await expect(row).toBeVisible();
  await expect(row.getByText("Active",{exact:true})).toBeVisible();
  await expect(row.getByRole("cell").nth(4)).toContainText("0.00");
  await row.getByRole("button",{name:"Record paid"}).click();
  const dialog=page.getByRole("dialog",{name:"Record paid payout"});
  await expect(dialog).toBeVisible();
  const save=dialog.getByRole("button",{name:"Record payment"});
  await expect(save).toBeDisabled();
  await dialog.getByRole("textbox",{name:"Outgoing payment reference"}).fill("SYNTHETICPAYOUT"+token);
  await dialog.getByRole("checkbox",{name:/confirm the funds were disbursed/}).check();
  await save.click();
  await expect(dialog).toHaveCount(0);
  await expect(active.getByRole("status")).toContainText("No transfer was initiated.");
  await expect(row.getByRole("cell").nth(4)).toContainText("735.00");

  await page.goto("/payouts/all");
  const all=page.getByRole("region",{name:"All payout plans"});
  await expect(all.getByRole("table").first().getByRole("row",{name:new RegExp(payee)})).toBeVisible();
  const payment=page.getByRole("region",{name:"Recorded payout history"});
  await expect(payment.getByRole("row",{name:new RegExp(payee)})).toBeVisible();
  await expect(payment.getByRole("row",{name:new RegExp(payee)})).toContainText("735.00");
});

test("One-time payouts remain in All and are not recurring Active obligations",async ({page})=>{
  const token=String(Date.now()%1000000).padStart(6,"0");
  const payee="One Time Payee "+token;
  await page.goto("/payouts");
  await page.getByRole("textbox",{name:"Payee name"}).fill(payee);
  await page.getByRole("combobox",{name:"Payout type"}).selectOption("one_time");
  await page.getByRole("textbox",{name:"Payout amount (₹)"}).fill("1240.00");
  await page.getByRole("textbox",{name:"Payout purpose"}).fill("Synthetic supplies purchase");
  await page.getByRole("button",{name:"Save payout plan"}).click();
  await expect(page.getByRole("status")).toContainText("one-time payout commitment");
  await page.goto("/payouts/active");
  await expect(page.getByRole("region",{name:"Active payout plans"})
    .getByRole("row",{name:new RegExp(payee)})).toHaveCount(0);
  await page.goto("/payouts/all");
  const row=page.getByRole("region",{name:"All payout plans"}).getByRole("table").first().getByRole("row",{name:new RegExp(payee)});
  await expect(row).toBeVisible();
  await expect(row.getByText("Scheduled",{exact:true})).toBeVisible();
  await row.getByRole("button",{name:"Record paid"}).click();
  const dialog=page.getByRole("dialog",{name:"Record paid payout"});
  await dialog.getByRole("textbox",{name:"Outgoing payment reference"}).fill("ONETIMEPAYOUT"+token);
  await dialog.getByRole("checkbox",{name:/confirm the funds were disbursed/}).check();
  await dialog.getByRole("button",{name:"Record payment"}).click();
  await expect(row.getByText("Paid",{exact:true})).toBeVisible();
  await expect(row.getByRole("button",{name:"Record paid"})).toHaveCount(0);
});

test("Recurring payout status change is scheduled without rewriting current month",async ({page})=>{
  const token=String(Date.now()%1000000).padStart(6,"0");
  const payee="Recurring Pause "+token;
  await page.goto("/payouts");
  await page.getByRole("textbox",{name:"Payee name"}).fill(payee);
  await page.getByRole("textbox",{name:"Payout purpose"}).fill("Synthetic monthly caretaker");
  await page.getByRole("textbox",{name:"Payout amount (₹)"}).fill("2100.00");
  await page.getByRole("button",{name:"Save payout plan"}).click();
  await expect(page.getByRole("status")).toContainText("No money has been transferred.");
  await page.goto("/payouts/active");
  const row=page.getByRole("region",{name:"Active payout plans"})
    .getByRole("row",{name:new RegExp(payee)});
  await row.getByRole("button",{name:"Pause"}).click();
  const dialog=page.getByRole("dialog",{name:"Schedule recurring status"});
  await expect(dialog.getByText(/next month/)).toBeVisible();
  await dialog.getByRole("button",{name:"Confirm status change"}).click();
  await expect(row.getByText("Active",{exact:true})).toBeVisible();
  await expect(row.getByText("Next: paused")).toBeVisible();
  await expect(row.getByRole("button",{name:"Pause"})).toHaveCount(0);
});

test("Protected payout gateway rejects forged actions or unsupported routes",async ({page})=>{
  await page.goto("/payouts");
  const bad=await page.evaluate(async()=>{
    const res=await fetch("/api/admin/payouts/plans",{
      method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({}),
    });
    return res.status;
  });
  expect(bad).toBe(403);
  const forged=await page.request.post("/api/admin/payouts/plans",{
    headers:{"Origin":"https://untrusted.example","Content-Type":"application/json"},
    data:{},
  });
  expect(forged.status()).toBe(403);
  const invalid=await page.request.post("/api/admin/payouts/plans/not-an-id/payments",{
    headers:{"Origin":"http://127.0.0.1:3000","Content-Type":"application/json"},
    data:{},
  });
  expect(invalid.status()).toBe(404);
});


test("Communication audience preview respects WhatsApp consent without dispatch",async ({page})=>{
  const suffix=String(Date.now()%1000000).padStart(6,"0");
  const name="Communication Candidate "+suffix;
  await page.goto("/prospects/add");
  await page.getByRole("textbox",{name:/First Name/}).fill(name);
  await page.getByRole("textbox",{name:/WhatsApp \/ Mobile/}).fill("9857"+suffix);
  await page.getByRole("checkbox",{name:/WhatsApp reminder consent/}).check();
  await page.getByRole("button",{name:"Add Prospect",exact:true}).click();
  await expect(page).toHaveURL(/\/prospects\/[0-9a-f-]{36}$/);
  await page.goto("/communication");
  const audience=page.getByRole("complementary",{name:"Message review"});
  await expect(audience.getByText(name,{exact:true})).toBeVisible();
  await expect(page.getByRole("button",{name:"Save draft"})).toBeVisible();
  await page.getByRole("button",{name:"Email"}).click();
  await expect(audience.getByText(/requires an email provider and recorded email consent/)).toBeVisible();
  await expect(page.getByRole("navigation",{name:"Communication views"})).toBeVisible();
});

test("Communication templates, campaign plans and rules persist across navigation",async ({page})=>{
  const key=Date.now()%1000000;
  const name="Foundation Message "+key;
  await page.goto("/communication/templates");
  await page.getByRole("textbox",{name:"Template name"}).fill(name);
  await page.getByRole("textbox",{name:"Message"}).fill("Assalamu Alaikum {{name}}, we have an update.");
  await page.getByRole("button",{name:"Save template"}).click();
  await expect(page.getByText(name,{exact:true})).toBeVisible();
  await page.goto("/communication");
  await page.getByRole("textbox",{name:"Campaign name"}).fill("Update "+key);
  await page.getByRole("combobox",{name:"Use template"}).selectOption({label:name});
  await expect(page.getByRole("textbox",{name:"Message body"})).toContainText("Assalamu Alaikum");
  await page.getByRole("button",{name:"Save draft"}).click();
  await expect(page.getByText(/No message has been sent or queued/)).toBeVisible();
  await page.goto("/communication/campaigns");
  const row=page.getByRole("row",{name:new RegExp("Update "+key)});
  await expect(row).toBeVisible();
  await expect(row.getByText("Draft")).toBeVisible();
  page.once("dialog",dialog=>dialog.accept());
  await row.getByRole("button",{name:"Cancel"}).click();
  await expect(row.getByText("Cancelled")).toBeVisible();
  await page.goto("/communication/automations");
  await page.getByRole("textbox",{name:"Workflow name"}).fill("Monthly demo "+key);
  await page.getByRole("combobox",{name:"Automation trigger"}).selectOption("monthly_sponsor");
  await page.getByRole("combobox",{name:"Automation template"}).selectOption({label:name+" · WhatsApp"});
  await page.getByRole("button",{name:"Save automation"}).click();
  await expect(page.getByText("Monthly demo "+key,{exact:true})).toBeVisible();
  await expect(page.getByText("Inactive · delivery not connected")).toBeVisible();
});

test("Communication proxy blocks forged-origin writes and has no unapproved send endpoint",async ({page})=>{
  await page.goto("/communication");
  const forged=await page.request.post("/api/admin/communication/templates",{
    headers:{"Origin":"https://untrusted.example","Content-Type":"application/json"},
    data:{name:"Evil",channel:"whatsapp",category:"update",body:"Message"},
  });
  expect(forged.status()).toBe(403);
  const missingCsrf=await page.evaluate(async()=>{
    const res=await fetch("/api/admin/communication/templates",{
      method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({name:"Attempt",channel:"whatsapp",category:"update",body:"Hello"}),
    });
    return res.status;
  });
  expect(missingCsrf).toBe(403);
  const wrongEndpoint=await page.request.post("/api/admin/communication/send",{
    headers:{"Origin":"http://127.0.0.1:3000","Content-Type":"application/json"},
    data:{},
  });
  expect(wrongEndpoint.status()).toBe(404);
  const prior=await page.request.post("/api/admin/reminders/send",{
    headers:{"Origin":"http://127.0.0.1:3000","Content-Type":"application/json"},data:{},
  });
  expect(prior.status()).toBe(404);
});

test("mobile collection form stays clickable with populated recent history",async ({page,isMobile})=>{
  test.skip(!isMobile,"mobile layout regression");
  await page.goto("/collections");
  const suffix=String(Date.now()%1000000).padStart(6,"0");
  const data=await page.evaluate(async suffix=>{
    const session=await (await fetch("/api/admin/session",{cache:"no-store"})).json();
    const csrf=session.csrf_token;
    const headers={"Content-Type":"application/json","X-CSRF-Token":csrf};
    const sponsorResponse=await fetch("/api/admin/prospects",{
      method:"POST",headers,
      body:JSON.stringify({
        full_name:"Seeded History Sponsor "+suffix,
        mobile_number:"+919114"+suffix,
        area_city:"Bengaluru",monthly_contribution_paise:50000,
        whatsapp_opt_in:false,
      }),
    });
    if(!sponsorResponse.ok)throw Error("Could not seed sponsor: "+sponsorResponse.status);
    const person=await sponsorResponse.json();
    const today=new Intl.DateTimeFormat("en-CA",{
      timeZone:"Asia/Kolkata",year:"numeric",month:"2-digit",day:"2-digit",
    }).format(new Date());
    for(let i=0;i<11;i++){
      const response=await fetch("/api/admin/collections",{
        method:"POST",headers,
        body:JSON.stringify({
          request_id:crypto.randomUUID(),prospect_id:person.id,
          period_month:today.slice(0,7)+"-01",received_on:today,
          amount_paise:25000,payment_method:"upi",
          receipt_reference:"HISTORY"+suffix+"-"+i,
          funds_confirmed:true,
        }),
      });
      if(!response.ok)throw Error("Could not seed history: "+response.status);
    }
    return {name:person.full_name,suffix};
  },suffix);
  await page.reload();
  await expect(page.getByRole("region",{name:"Recent manual collections"})).toBeVisible();
  await expect(page.getByRole("region",{name:"Recent manual collections"}).getByRole("row")).toHaveCount(11);
  const grid=page.locator(".manual-collections-workspace");
  await expect.poll(async()=>{
    const box=await grid.boundingBox();
    return box ? Math.round(box.width) : 0;
  }).toBeLessThanOrEqual(413);
  await page.getByRole("textbox",{name:"Search sponsor"}).fill(data.name);
  await page.getByRole("option",{name:new RegExp(data.name)}).click();
  await page.getByRole("combobox",{name:"Amount received (₹)"}).selectOption("250");
  await page.getByRole("textbox",{name:"Transaction reference"}).fill("FINALHISTORY"+suffix);
  await page.getByRole("checkbox",{name:/Foundation's records/}).check();
  const save=page.getByRole("button",{name:"Save Collection"});
  await save.scrollIntoViewIfNeeded();
  await expect.poll(async()=>await save.evaluate(el=>{
    const r=el.getBoundingClientRect();
    const hit=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);
    return hit===el || el.contains(hit);
  })).toBe(true);
  await save.click();
  await expect(page.getByRole("status").filter({hasText:"Recorded"})).toBeVisible();
});


test("Dashboard shows real six-month metrics and never initiates a payment",async ({page})=>{
  await page.goto("/dashboard");
  const container=page.locator(".dashboard-live");
  await expect(container).toBeVisible();
  await expect(page.getByRole("heading",{name:/Overview/})).toBeVisible();
  await expect(page.getByRole("region",{name:"Sponsorship finances"})).toBeVisible();
  await expect(page.getByRole("region",{name:"Outgoing payouts"})).toBeVisible();
  await expect(page.getByRole("region",{name:"Six-month financial trends"})).toBeVisible();
  await expect(page.locator(".dashboard-trend-row")).toHaveCount(6);
  await expect(page.getByText(/Creating a payout plan does not send funds/)).toHaveCount(0);
  await expect(page.getByText(/not independently reconciled bank balances/)).toHaveCount(0);
  await expect.poll(async()=>{
    return page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1);
  }).toBe(true);
  const endpoint=await page.request.get("/api/admin/dashboard");
  expect(endpoint.status()).toBe(200);
  const result=await endpoint.json();
  expect(result.months).toHaveLength(6);
  expect(result.recorded_contributions_paise).toBeGreaterThanOrEqual(0);
  expect(result.payout_disbursed_paise).toBeGreaterThanOrEqual(0);
  await page.getByRole("button",{name:"Refresh figures"}).click();
  await expect(page.getByRole("region",{name:"Foundation dashboard"})).toBeVisible();
});

test("Dashboard browser endpoint rejects unsupported query and cannot record money",async ({page})=>{
  const unknown=await page.request.get("/api/admin/dashboard?pretend_paid=true");
  expect(unknown.status()).toBe(400);
  const rejected=await page.request.post("/api/admin/dashboard",{
    data:{recorded_contributions_paise:99999999},
  });
  expect([404,405]).toContain(rejected.status());
});
