import { test, expect } from "@playwright/test";

// Temporary synthetic-only audit. It reads authenticated test pages but
// never writes Foundation data or triggers outbound communications.
const routes = [
  ["/dashboard","Foundation admin"],
  ["/prospects","Prospect operator"],["/prospects/add","Prospect operator"],
  ["/prospects/active","Prospect operator"],["/prospects/inactive","Prospect operator"],
  ["/prospects/stages","Pipeline manager"],
  ["/promoters","Promoter coordinator"],["/promoters/add","Promoter coordinator"],
  ["/promoters/active","Promoter coordinator"],["/promoters/inactive","Promoter coordinator"],
  ["/collections","Finance officer"],["/collections/active","Finance officer"],
  ["/collections/all","Finance officer"],
  ["/payouts","Finance officer"],["/payouts/active","Finance officer"],
  ["/payouts/all","Finance officer"],
  ["/communication","Messaging operator"],["/communication/campaigns","Messaging operator"],
  ["/communication/templates","Messaging operator"],["/settings","Foundation admin"],
];
const viewports = [
  {name:"desktop-1440",width:1440,height:900},
  {name:"laptop-1024",width:1024,height:768},
  {name:"tablet-768",width:768,height:1024},
  {name:"mobile-430",width:430,height:932},
  {name:"mobile-390",width:390,height:844},
  {name:"mobile-375",width:375,height:812},
  {name:"small-phone-320",width:320,height:700},
  {name:"landscape-640",width:640,height:360},
];

async function metrics(page) {
  return page.evaluate(() => {
    const isShown = e => {
      if (!e || !e.isConnected) return false;
      const rect=e.getBoundingClientRect();
      if(rect.width<1||rect.height<1)return false;
      const style=getComputedStyle(e);
      return style.visibility!=="hidden" && style.display!=="none" && Number(style.opacity)!==0;
    };
    const rectLabel=e=>{
      const name=(e.getAttribute("aria-label")||e.getAttribute("title")||
        e.innerText||e.textContent||e.getAttribute("placeholder")||e.tagName).trim();
      return name.replace(/\s+/g," ").slice(0,75);
    };
    const scrollParent=e=>{
      let p=e.parentElement;
      while(p && p!==document.body) {
        const css=getComputedStyle(p);
        if(["auto","scroll"].includes(css.overflowX) && p.scrollWidth>p.clientWidth+3)return true;
        p=p.parentElement;
      }
      return false;
    };
    const interactive=Array.from(document.querySelectorAll("button,a[href],input,select,textarea,[role='button']"))
      .filter(e=>isShown(e) && e.type!=="hidden");
    const offscreen=interactive.filter(e=>{
      const r=e.getBoundingClientRect();
      return (r.left< -4 || r.right>innerWidth+4) && !scrollParent(e);
    }).slice(0,12).map(e=>rectLabel(e));
    const unlabeled=Array.from(document.querySelectorAll("input,select,textarea")).filter(e=>{
      if(!isShown(e)||e.type==="hidden")return false;
      const described=Boolean(e.getAttribute("aria-label")||e.getAttribute("aria-labelledby")||
        e.labels?.length||e.closest("label")||e.getAttribute("title"));
      return !described;
    }).slice(0,12).map(e=>e.tagName.toLowerCase()+":"+rectLabel(e));
    const nameless=Array.from(document.querySelectorAll("button,[role='button']"))
      .filter(e=>isShown(e) && !e.hasAttribute("aria-label") && !e.hasAttribute("aria-labelledby") &&
        !e.getAttribute("title") && !(e.textContent||"").trim())
      .slice(0,12).map(e=>e.outerHTML.slice(0,130));
    const ids=new Set(), duplicateIds=[];
    for(const e of document.querySelectorAll("[id]")){
      if(ids.has(e.id))duplicateIds.push(e.id);
      ids.add(e.id);
    }
    const smallTargets=interactive.filter(e=>{
      if(innerWidth>640)return false;
      if(e.type==="checkbox"||e.type==="radio")return false;
      const r=e.getBoundingClientRect();
      return r.width<24 || r.height<24;
    }).slice(0,14).map(e=>{
      const r=e.getBoundingClientRect();
      return rectLabel(e)+" ("+Math.round(r.width)+"x"+Math.round(r.height)+")";
    });
    const narrowButtons=interactive.filter(e=>{
      if(e.tagName!=="BUTTON"||!isShown(e))return false;
      const r=e.getBoundingClientRect();
      return r.width<90 && (e.textContent||"").trim().length>18;
    }).slice(0,12).map(e=>rectLabel(e));
    const imageAlt=Array.from(document.querySelectorAll("img"))
      .filter(e=>!e.hasAttribute("alt")&&isShown(e))
      .slice(0,8).map(e=>e.getAttribute("src")?.slice(0,80));
    const docScroll=Math.max(document.documentElement.scrollWidth,document.body.scrollWidth||0);
    const overflow=Math.round(docScroll-innerWidth);
    const main=document.querySelector("main");
    const header=document.querySelector("h1");
    const counts={buttons:interactive.filter(e=>e.tagName==="BUTTON").length,
      inputs:interactive.filter(e=>["INPUT","SELECT","TEXTAREA"].includes(e.tagName)).length,
      dialogs:document.querySelectorAll('[role="dialog"]').length};
    return {overflow,offscreen,unlabeled,nameless,duplicateIds,smallTargets,
      narrowButtons,imageAlt,hasMain:Boolean(main),h1:header?.textContent?.trim()||"",
      pageTitle:document.title,counts};
  });
}

test("UX scan across operator roles, modules, breakpoints and accessible controls",async ({page},info)=>{
  test.skip(info.project.name!=="desktop-chromium","single synthetic viewport matrix");
  test.setTimeout(540000);
  const rows=[],runtimeErrors=[];
  page.on("pageerror",e=>runtimeErrors.push({url:page.url(),message:String(e.message).slice(0,180)}));
  page.on("response",r=>{
    if(r.status()>=500 && r.url().includes("/api/"))
      runtimeErrors.push({url:page.url(),message:"HTTP "+r.status()+" "+r.url().slice(-80)});
  });
  // Unauthenticated first impression and login usability.
  await page.setViewportSize({width:320,height:700});
  await page.goto("/login");
  rows.push({persona:"New admin",viewport:"small-phone-320",path:"/login",...(await metrics(page))});
  await page.getByRole("textbox",{name:"Email address"}).fill("admin@foundation.org");
  await page.getByLabel("Password",{exact:true}).fill("integration-only-long-password-123");
  await page.getByRole("button",{name:"Sign In"}).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  for(const v of viewports){
    await page.setViewportSize({width:v.width,height:v.height});
    for(const [path,persona] of routes){
      try {
        const resp=await page.goto(path,{waitUntil:"domcontentloaded",timeout:20000});
        await expect(page.locator(".topbar h1")).toBeVisible({timeout:10000});
        await page.waitForTimeout(110);
        const m=await metrics(page);
        rows.push({persona,viewport:v.name,path,httpStatus:resp?.status(),...m});
      } catch(e){
        rows.push({persona,viewport:v.name,path,exception:String(e).slice(0,250)});
      }
    }
  }
  const issues=rows.filter(r=>r.exception || r.httpStatus>=400 || r.overflow>1 ||
    r.offscreen?.length || r.unlabeled?.length || r.nameless?.length ||
    r.duplicateIds?.length || r.smallTargets?.length || r.imageAlt?.length);
  const grouped={};
  for(const row of issues){
    const key=row.path+" / "+row.viewport;
    grouped[key]={overflow:row.overflow,offscreen:row.offscreen,
      unlabeled:row.unlabeled,nameless:row.nameless,duplicateIds:row.duplicateIds,
      smallTargets:row.smallTargets,imageAlt:row.imageAlt,
      exception:row.exception,httpStatus:row.httpStatus};
  }
  const issueTypes={};
  for(const r of rows)for(const key of ["overflow","offscreen","unlabeled","nameless","duplicateIds","smallTargets","imageAlt","exception"]){
    const hit=key==="overflow"?r.overflow>1:Array.isArray(r[key])?r[key].length>0:Boolean(r[key]);
    if(hit)issueTypes[key]=(issueTypes[key]||0)+1;
  }
  console.log("SAS_UX_MATRIX",JSON.stringify({scanned:rows.length,issueViews:issues.length,
    issueTypes,routeFindings:grouped,runtimeErrors:runtimeErrors.slice(0,30)}));
  // Explicit failure only for crashes or access loss, not for known/documented
  // usability defects: keep CI able to report a complete matrix.
  expect(rows.filter(r=>r.exception||r.httpStatus>=500)).toEqual([]);
});
