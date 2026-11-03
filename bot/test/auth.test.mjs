import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import {
  hashPassword,
  passwordMatches,
  setPassword,
  findUser,
  recordFailure,
  lockedMinutes,
  clearFailures,
  createSession,
  getSession,
  endOtherSessions,
  readSessionCookie,
  sessionCookie,
  SESSION_MS,
} from "../auth.mjs";
import { resolveSitePath } from "../site.mjs";

test("mật khẩu băm đúng thì khớp, sai thì không", async () => {
  const record = await hashPassword("mat-khau-dung-123");
  assert.equal(await passwordMatches("mat-khau-dung-123", record), true);
  assert.equal(await passwordMatches("mat-khau-sai-456", record), false);
});

test("đặt mật khẩu ghi cờ phải đổi và không lưu mật khẩu gốc", async () => {
  const dir = await mkdtemp(path.join(tmpdir(), "tchc-auth-"));
  try {
    const file = path.join(dir, "users.json");
    await setPassword(file, "tchc", "mat-khau-tam-abc", { mustChange: true });
    const user = await findUser(file, "tchc");
    assert.equal(user.phai_doi_mat_khau, true);
    assert.equal(await passwordMatches("mat-khau-tam-abc", user), true);
    assert.equal(JSON.stringify(user).includes("mat-khau-tam-abc"), false);
    assert.equal(await findUser(file, "khong-co"), null);
    assert.equal(await findUser(file, "__proto__"), null);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("nhập sai 5 lần thì bị khóa 15 phút, xóa lần sai thì mở lại", () => {
  const name = "khoa-thu-nghiem";
  const t0 = 1_000_000;
  for (let i = 0; i < 4; i++) recordFailure(name, t0);
  assert.equal(lockedMinutes(name, t0), 0);
  recordFailure(name, t0);
  assert.equal(lockedMinutes(name, t0), 15);
  assert.equal(lockedMinutes(name, t0 + 15 * 60 * 1000), 0);
  clearFailures(name);
  recordFailure(name, t0);
  assert.equal(lockedMinutes(name, t0), 0);
});

test("phiên hết hạn sau 12 giờ", () => {
  const token = createSession("nguoi-a", 0);
  assert.equal(getSession(token, 1)?.username, "nguoi-a");
  assert.equal(getSession(token, SESSION_MS), null);
  assert.equal(getSession(null), null);
});

test("đổi mật khẩu đăng xuất máy khác, giữ phiên hiện tại", () => {
  const keep = createSession("nguoi-b");
  const other = createSession("nguoi-b");
  endOtherSessions("nguoi-b", keep);
  assert.ok(getSession(keep));
  assert.equal(getSession(other), null);
});

test("đọc đúng cookie phiên và đặt thuộc tính an toàn", () => {
  assert.equal(readSessionCookie("a=1; tchc_sid=abc123; x=y"), "abc123");
  assert.equal(readSessionCookie("tchc_sid_khac=1"), null);
  assert.equal(readSessionCookie(undefined), null);
  const cookie = sessionCookie("abc");
  assert.match(cookie, /^tchc_sid=abc; /);
  assert.match(cookie, /HttpOnly; Secure; SameSite=Strict/);
});

test("đường dẫn tĩnh không thoát khỏi thư mục site", () => {
  const site = path.join(tmpdir(), "tchc-site-test");
  const root = path.resolve(site) + path.sep;
  assert.match(resolveSitePath(site, "/"), /index\.html$/);
  assert.match(resolveSitePath(site, "/app.js"), /app\.js$/);
  assert.match(resolveSitePath(site, "/data/tthc.json"), /tthc\.json$/);
  assert.equal(resolveSitePath(site, "/run-bot.cmd"), null);
  assert.equal(resolveSitePath(site, "/a%00.js"), null);
  for (const attack of ["/../server.mjs", "/..%2F..%2Fserver.mjs", "/..%5C..%5Cserver.js"]) {
    const result = resolveSitePath(site, attack);
    assert.ok(result === null || result.startsWith(root), `thoát thư mục: ${attack}`);
  }
});
