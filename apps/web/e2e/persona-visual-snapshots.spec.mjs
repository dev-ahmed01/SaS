import {test,expect} from "@playwright/test";
// Synthetic-data visual review snapshots. Public CI log contains only
// fixed dummy admin session and renderings; never run against live data.
test("QA visual snapshots: desktop, mobile and narrow layouts",async ({page},info)=>{
  test.skip(info.project.name!=="desktop-chromium");
  test.setTimeout(180000);
  await page.goto("/login");
  await page.getByRole("textbox",{name:"Email address"}).fill("admin@foundation.org");
  await page.getByLabel("Password",{exact:true}).fill("integration-only-long-password-123");
  await page.getByRole("button",{name:"Sign In"}).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  const shots=[
    ["dashboard-desktop","/dashboard",1440,900],
    ["dashboard-mobile","/dashboard",390,844],
    ["prospects-mobile","/prospects/add",390,844],
    ["collections-mobile","/collections",390,844],
    ["payouts-mobile","/payouts",390,844],
    ["communication-320","/communication",320,700],
    ["communication-desktop","/communication",1440,900],
    ["promoters-desktop","/promoters",1440,900],
  ];
  for(const [id,path,width,height] of shots){
    await page.setViewportSize({width,height});
    await page.goto(path,{waitUntil:"domcontentloaded"});
    await page.locator(".topbar h1").waitFor();
    await page.waitForTimeout(220);
    const buf=await page.screenshot({type:"jpeg",quality:32,animations:"disabled",fullPage:false});
    const b64=buf.toString("base64");
    console.log("SAS_VISUAL_META",JSON.stringify({id,width,height,bytes:buf.length,chunks:Math.ceil(b64.length/18000)}));
    for(let i=0;i<b64.length;i+=18000){
      console.log("SAS_VISUAL_CHUNK",id,i/18000,b64.slice(i,i+18000));
    }
  }
});
