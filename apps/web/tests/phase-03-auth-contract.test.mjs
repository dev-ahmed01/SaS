import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
const read=path=>readFileSync(new URL(path,import.meta.url),"utf8");

test("server guard verifies opaque session against backend",()=>{
  const text=read("../lib/admin-guard.ts");
  assert.match(text,/cookies\(\)/);
  assert.match(text,/\/v1\/auth\/session/);
  assert.match(text,/if \(!authenticated\) redirect\("\/login"\)/);
});
test("same-origin gateway whitelists methods and verifies origin",()=>{
  const text=read("../app/api/admin/[action]/route.ts");
  assert.match(text,/Origin verification failed/);
  assert.match(text,/Request too large/);
  assert.match(text,/NextResponse\.json/);
  assert.match(text,/set-cookie/);
});
test("settings uses CSRF and never exposes auth tokens through browser persistence",()=>{
  const text=read("../components/admin-settings-form.tsx");
  assert.match(text,/X-CSRF-Token/);
  assert.match(text,/default_contribution_paise/);
  assert.doesNotMatch(text,/localStorage|sessionStorage/);
});
test("login is no longer a disabled preview",()=>{
  const text=read("../app/login/page.tsx");
  assert.match(text,/\/api\/admin\/login/);
  assert.match(text,/autoComplete="current-password"/);
  assert.doesNotMatch(text,/Sign-in becomes available/);
});
