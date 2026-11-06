import {test,expect} from "@playwright/test";
const sizes=[{width:320,height:700},{width:375,height:812},{width:390,height:844},{width:430,height:932}];
async function signIn(page) {
  await page.goto("/login");
  await page.getByRole("textbox",{name:"Email address"}).fill("admin@foundation.org");
  await page.getByLabel("Password",{exact:true}).fill("integration-only-long-password-123");
  await page.getByRole("button",{name:"Sign In"}).click();
  await expect(page).toHaveURL(/\/dashboard$/);
}
test("QA follow-up: overflow culprit, custom sponsorship and empty tables",async ({page},info)=>{
  test.skip(info.project.name!=="desktop-chromium");
  test.setTimeout(120000);
  await signIn(page);
  const records=[];
  for(const size of sizes){
    await page.setViewportSize(size);
    for(const route of ["/communication","/dashboard","/collections/all","/promoters"]){
      await page.goto(route);
      const data=await page.evaluate(()=>{
        const iw=innerWidth;
        const els=Array.from(document.querySelectorAll("*")).filter(e=>{
          const r=e.getBoundingClientRect();
          const cs=getComputedStyle(e);
          return r.width>1 && r.height>1 && cs.display!=="none" &&
            cs.visibility!=="hidden" && (e.scrollWidth>e.clientWidth+2||r.right>iw+2);
        });
        const biggest=els.sort((a,b)=>{
          const ar=a.getBoundingClientRect(),br=b.getBoundingClientRect();
          return Math.max(br.right-iw,b.scrollWidth-b.clientWidth)-
            Math.max(ar.right-iw,a.scrollWidth-a.clientWidth);
        }).slice(0,15).map(e=>{
          const r=e.getBoundingClientRect(),c=getComputedStyle(e);
          return {tag:e.tagName.toLowerCase(),classes:String(e.className?.baseVal||e.className||"").slice(0,90),
            text:(e.innerText||"").replace(/\s+/g," ").slice(0,65),
            right:Math.round(r.right),width:Math.round(r.width),
            client:e.clientWidth,scroll:e.scrollWidth,
            overflowX:c.overflowX,minWidth:c.minWidth,display:c.display};
        });
        const t=document.querySelector(".collection-review table");
        const heads=t?.querySelectorAll("thead th").length;
        const colspan=t?.querySelector("tbody tr td[colspan]")?.getAttribute("colspan");
        return {docWidth:document.documentElement.scrollWidth,screen:iw,
          culprits:biggest,table:{heads,colspan}};
      });
      records.push({route,width:size.width,...data});
    }
  }
  await page.setViewportSize({width:390,height:844});
  await page.goto("/prospects/add");
  await page.getByRole("combobox",{name:"Sponsorship Tokens"}).selectOption("custom");
  const tokens=await page.getByRole("spinbutton",{name:"Custom sponsorship tokens"}).inputValue();
  console.log("SAS_CUSTOM_TOKEN_SELECTION",JSON.stringify({tokens,rupees:Number(tokens)*250}));
  await page.goto("/dashboard");
  await page.getByRole("button",{name:"Open navigation"}).click();
  const before=await page.locator(".site-sidebar").evaluate(e=>e.classList.contains("mobile-open"));
  await page.keyboard.press("Escape");
  const after=await page.locator(".site-sidebar").evaluate(e=>e.classList.contains("mobile-open"));
  console.log("SAS_MOBILE_DRAWER_ESCAPE",JSON.stringify({before,after}));
  console.log("SAS_OVERFLOW_DIAGNOSTIC",JSON.stringify(records));
});
