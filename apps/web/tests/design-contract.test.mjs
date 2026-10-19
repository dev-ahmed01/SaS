import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const css = read("../app/globals.css");
const shell = read("../components/app-shell.tsx");
const modules = read("../components/module-workspace.tsx");
const ui = read("../components/ui/primitives.tsx");
const routes = read("../app/[module]/[[...view]]/page.tsx");
const communication = read("../components/communication/workspace.tsx");
const composer = read("../components/communication/compose.tsx");
const clock = read("../components/communication/ist-clock.tsx");


test("locked brand colors and typography are centralized", () => {
  for (const token of ["--forest:", "--mint:", "--font-heading:", "--font-body:"]) assert.ok(css.includes(token),token);
  assert.match(css,/Bricolage Grotesque/);
  assert.match(css,/Poppins/);
  assert.match(css,/font-weight: 700/);
  assert.match(css,/font-weight: 600/);
});

test("navigation is consistent across exactly the approved seven destinations", () => {
  for (const name of ["Dashboard", "Prospects", "Promoters", "Collections", "Payouts", "Communication", "Settings"]) {
    assert.ok(shell.includes('name:"'+name+'"'),name);
  }
  assert.equal((shell.match(/name:"(?:Dashboard|Prospects|Promoters|Collections|Payouts|Communication|Settings)"/g)||[]).length,7);
  assert.match(shell,/aria-current/);
  assert.match(shell,/mobileOpen/);
  assert.match(shell,/drawer-scrim/);
  assert.doesNotMatch(shell,/bottom-nav|bottom-navigation/);
});

test("each module has the approved horizontal tab structure", () => {
  for (const label of ["Add Prospect","Inactive","All Prospects","Add Promoter","Active","All Promoters","Add Payout"]) assert.ok(modules.includes(label),label);
  assert.match(modules,/collections\/active/);
  assert.match(modules,/payouts\/all/);
  assert.match(ui,/aria-label="Module views"/);
  assert.match(ui,/aria-current/);
});

test("Collections ledger displays received only with aligned controls and a legible clock", () => {
  const ledger=read("../components/accounting/accounting-overview.tsx");
  assert.match(ledger,/\["Received",data\?money\(data\.verified_paise\)/);
  assert.match(ledger,/<th scope="col">Received<\/th>/);
  assert.doesNotMatch(ledger,/Received \/ Outstanding|finance-paired-values/);
  assert.match(css,/grid-template-columns:repeat\(3,minmax\(0,1fr\)\)/);
  assert.match(css,/\.accounting-heading \{/);
  assert.match(css,/\.account-month-picker \{/);
  assert.match(css,/\.topbar-ist-clock \{/);
  assert.match(css,/font:600 14px\/1\.3 var\(--font-body\)/);
});

test("Communication is compose-first and combines templates with automation", () => {
  for(const label of ["Compose","Campaigns","Templates & Automations"]){
    assert.ok(communication.includes(label),label);
  }
  assert.match(routes,/communication:\["compose","campaigns","templates","automations"\]/);
  assert.match(modules,/CommunicationWorkspace/);
  assert.doesNotMatch(composer,/Message review|Audience preview|Message preview/);
  assert.match(composer,/Saving does not send messages/);
  assert.doesNotMatch(communication,/Preparation history/);
  assert.doesNotMatch(communication,/New campaigns require channel activation/);
  assert.match(shell,/IstClock/);
  assert.match(clock,/Asia\/Kolkata/);
  assert.match(clock,/setInterval/);
});

test("Consent and Campaign review keep the no-send CRM boundary", () => {
  const consent=read("../components/communication/contact-consent.tsx");
  const campaigns=read("../components/communication/campaigns.tsx");
  const proxy=read("../app/api/admin/communication/[[...segments]]/route.ts");
  const prospect=read("../components/prospects/prospect-details.tsx");
  const promoter=read("../components/promoters/promoter-details.tsx");
  assert.match(consent,/Communication consent/);
  assert.match(consent,/Record opt-out/);
  assert.match(consent,/checked the recipient/);
  assert.match(campaigns,/simulation_only:true/);
  assert.match(campaigns,/Simulation only/);
  assert.match(campaigns,/Check recipients/);
  assert.match(proxy,/name==="consent-events"/);
  assert.match(prospect,/ContactConsent/);
  assert.match(promoter,/ContactConsent/);
  assert.doesNotMatch(campaigns,/\/send|\/dispatch/);
});

test("phase 2 never claims functional authentication, payment or reminder delivery", () => {
  assert.match(modules,/disabled/);
  assert.match(ui,/disabled/);
  assert.match(composer,/No message has been sent or queued/);
  assert.match(modules,/DashboardLive/);
  assert.doesNotMatch(modules,/Waiting for live data/);
  const dashboard = read("../components/dashboard/dashboard-live.tsx");
  assert.match(dashboard,/\/api\/admin\/dashboard/);
  assert.doesNotMatch(dashboard,/not independently reconciled bank balances/);
  assert.doesNotMatch(dashboard,/Figures are calculated from recorded Foundation activity/);
  assert.doesNotMatch(shell,/Admin workspace/);
  assert.doesNotMatch(shell,/desktop-collapse/);
  assert.doesNotMatch(modules,/\b(?:28,500|98 active sponsors|Payment succeeded)\b/);
});

test("responsive design, focus visibility, and reduced motion present", () => {
  assert.match(css,/:focus-visible/);
  assert.match(css,/max-width:780px/);
  assert.match(css,/prefers-reduced-motion/);
  assert.match(shell,/Skip to content/);
  assert.match(ui,/scope="col"/);
});

test("premium mosque illustrations remain scalable, unobstructed, and softly integrated", () => {
  for (const name of ["masjid-sidebar-premium.svg","masjid-landscape-premium.svg"]) {
    assert.ok(css.includes(name), name);
    assert.ok(existsSync(new URL("../public/art/"+name,import.meta.url)));
    const drawing=read("../public/art/"+name);
    assert.match(drawing,/<svg[^>]*viewBox=/);
    assert.match(drawing,/linearGradient/);
    assert.doesNotMatch(drawing,/<image/);
  }
  const scene=new URL("../public/art/sponsor-salah-panorama.avif",import.meta.url);
  assert.ok(existsSync(scene),"optimized landscape must be committed");
  const bytes=readFileSync(scene);
  assert.equal(bytes.subarray(4,12).toString("ascii"),"ftypavif","artwork must be AVIF encoded");
  assert.ok(bytes.length>12000 && bytes.length<150000,"keep high fidelity artwork reasonably small");
  assert.ok(css.includes('url("/art/sponsor-salah-panorama.avif")'));
  assert.ok(css.includes("background-image:image-set("));
  assert.ok(css.includes("background-size:cover"),"sidebar artwork should fill its frame without stretching");
  assert.ok(css.includes("width:auto;"),"sidebar illustration must span the entire padded sidebar");
  assert.ok(css.includes("background-position:center bottom"),"center the landscape crop");
  assert.ok(css.includes("mask-image:linear-gradient"));
  assert.ok(shell.includes('className="sidebar-art"'));
  assert.ok(shell.includes('aria-label="Admin account"'));
  assert.ok(shell.includes('aria-expanded={profileOpen}'));
  assert.ok(shell.includes('aria-label="Sign out"'));
});

test("Foundation branding and single active module header replace duplicate page titles", () => {
  assert.match(shell, /<strong>Emlen Foundation<\/strong><small>Sponsor a Salah<\/small>/);
  assert.match(shell, /aria-label="Emlen Foundation home"/);
  assert.match(shell, /<h1 className="topbar-name">/);
  assert.match(shell, /navigation\.find\(link=>pathname===link\.href/);
  assert.doesNotMatch(shell, /top-avatar|topbar-spacer/);
  assert.doesNotMatch(shell, /<span className="topbar-name">Sponsor a Salah<\/span>/);
  assert.match(css, /\.page-content > \.module-tabs \{ margin-top:0; \}/);
  assert.doesNotMatch(modules, /<PageHeading/);
  assert.doesNotMatch(read("../components/prospects/prospects-workspace.tsx"), /<PageHeading/);
  assert.doesNotMatch(read("../components/promoters/promoters-workspace.tsx"), /<PageHeading/);
});

test("password eye toggle remains keyboard accessible and never submits the form", () => {
  const login=read("../app/login/page.tsx");
  const icons=read("../components/ui/icon.tsx");
  assert.match(login, /type="button" aria-label=\{showPassword\?"Hide password":"Show password"\}/);
  assert.match(login, /<Icon name=\{showPassword\?"eye-off":"eye"\} size=\{19\}\/>/);
  assert.match(login, /aria-pressed=\{showPassword\}/);
  assert.match(icons, /eye: <>/);
  assert.match(icons, /"eye-off": <>/);
  assert.match(css, /\.login-password-toggle:focus-visible/);
});
