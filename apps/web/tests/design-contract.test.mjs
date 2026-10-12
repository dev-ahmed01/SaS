import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

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
  assert.match(modules,/Waiting for live data/);
  assert.doesNotMatch(modules,/\b(?:28,500|98 active sponsors|Payment succeeded)\b/);
});

test("responsive design, focus visibility, and reduced motion present", () => {
  assert.match(css,/:focus-visible/);
  assert.match(css,/max-width:780px/);
  assert.match(css,/prefers-reduced-motion/);
  assert.match(shell,/Skip to content/);
  assert.match(ui,/scope="col"/);
});
