import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const css = read("../app/globals.css");
const shell = read("../components/app-shell.tsx");
const modules = read("../components/module-workspace.tsx");
const ui = read("../components/ui/primitives.tsx");
const routes = read("../app/[module]/[[...view]]/page.tsx");

test("locked brand colors and typography are centralized", () => {
  for (const token of ["--forest:", "--mint:", "--font-heading:", "--font-body:"]) assert.ok(css.includes(token),token);
  assert.match(css,/Bricolage Grotesque/);
  assert.match(css,/Poppins/);
  assert.match(css,/font-weight: 700/);
  assert.match(css,/font-weight: 600/);
});

test("navigation is consistent across exactly the approved seven destinations", () => {
  for (const name of ["Dashboard", "Prospects", "Promoters", "Collections", "Payouts", "Reminders", "Settings"]) {
    assert.ok(shell.includes('name:"'+name+'"'),name);
  }
  assert.equal((shell.match(/name:"(?:Dashboard|Prospects|Promoters|Collections|Payouts|Reminders|Settings)"/g)||[]).length,7);
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

test("reminders have only WhatsApp and Email entry cards", () => {
  assert.match(modules,/WhatsApp Reminders/);
  assert.match(modules,/Email Reminders/);
  assert.match(routes,/whatsapp","email/);
});

test("phase 2 never claims functional authentication, payment or reminder delivery", () => {
  assert.match(modules,/disabled/);
  assert.match(ui,/disabled/);
  assert.match(modules,/No messages are being sent/);
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
