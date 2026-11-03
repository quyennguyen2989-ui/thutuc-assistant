// Đăng nhập cho trang tra cứu: tài khoản, mật khẩu băm bằng scrypt, phiên lưu trong bộ nhớ,
// khóa tạm sau nhiều lần nhập sai. Chỉ dùng thư viện có sẵn của Node.
import { randomBytes, scrypt as scryptCallback, timingSafeEqual } from "node:crypto";
import { promisify } from "node:util";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";

const scrypt = promisify(scryptCallback);

export const MIN_PASSWORD_LENGTH = 6;
export const MAX_PASSWORD_LENGTH = 200;
export const SESSION_MS = 12 * 60 * 60 * 1000;
export const COOKIE_NAME = "tchc_sid";
// Cookie chỉ gửi cho /tchc, không lẫn với ứng dụng khác trên cùng tên miền.
export const COOKIE_PATH = process.env.TCHC_COOKIE_PATH || "/tchc";

const MAX_FAILURES = 5;
const LOCK_MS = 15 * 60 * 1000;
const MAX_TRACKED = 1000;
const SCRYPT_PARAMS = { N: 16384, r: 8, p: 1 };
const KEY_BYTES = 64;

export async function hashPassword(password) {
  const salt = randomBytes(16);
  const key = await scrypt(password, salt, KEY_BYTES, SCRYPT_PARAMS);
  return { salt: salt.toString("hex"), hash: key.toString("hex"), params: SCRYPT_PARAMS };
}

export async function passwordMatches(password, record) {
  const key = await scrypt(password, Buffer.from(record.salt, "hex"), KEY_BYTES, record.params);
  return timingSafeEqual(key, Buffer.from(record.hash, "hex"));
}

// Tệp tài khoản: JSON { "tên đăng nhập": { salt, hash, params, phai_doi_mat_khau, cap_nhat } }.
export async function readUsers(file) {
  try {
    return JSON.parse(await readFile(file, "utf8"));
  } catch (error) {
    if (error.code === "ENOENT") return {};
    throw error;
  }
}

async function writeUsers(file, users) {
  await mkdir(path.dirname(file), { recursive: true });
  const temp = `${file}.tmp`;
  await writeFile(temp, JSON.stringify(users, null, 2), "utf8");
  await rename(temp, file);
}

export async function findUser(file, username) {
  const users = await readUsers(file);
  return Object.hasOwn(users, username) ? users[username] : null;
}

export async function setPassword(file, username, password, { mustChange }) {
  const users = await readUsers(file);
  users[username] = {
    ...(await hashPassword(password)),
    phai_doi_mat_khau: mustChange,
    cap_nhat: new Date().toISOString(),
  };
  await writeUsers(file, users);
}

// Lần nhập sai gần đây theo tên đăng nhập. Nằm trong bộ nhớ nên mất khi bot khởi động lại.
const failures = new Map();

// Số phút còn bị khóa, 0 nếu không bị khóa.
export function lockedMinutes(username, now = Date.now()) {
  const entry = failures.get(username);
  if (!entry || entry.lockedUntil <= now) return 0;
  return Math.ceil((entry.lockedUntil - now) / 60000);
}

export function recordFailure(username, now = Date.now()) {
  if (failures.size >= MAX_TRACKED) failures.clear();
  const entry = failures.get(username) ?? { count: 0, lockedUntil: 0 };
  entry.count += 1;
  if (entry.count >= MAX_FAILURES) {
    entry.count = 0;
    entry.lockedUntil = now + LOCK_MS;
  }
  failures.set(username, entry);
}

export function clearFailures(username) {
  failures.delete(username);
}

// Phiên đăng nhập lưu trong bộ nhớ: token ngẫu nhiên, hết hạn sau SESSION_MS.
const sessions = new Map();

export function createSession(username, now = Date.now()) {
  const token = randomBytes(32).toString("base64url");
  sessions.set(token, { username, expiresAt: now + SESSION_MS });
  return token;
}

export function getSession(token, now = Date.now()) {
  const session = token ? sessions.get(token) : undefined;
  if (!session) return null;
  if (session.expiresAt <= now) {
    sessions.delete(token);
    return null;
  }
  return { token, username: session.username };
}

export function endSession(token) {
  if (token) sessions.delete(token);
}

// Đổi mật khẩu thì đăng xuất các máy khác, giữ phiên hiện tại.
export function endOtherSessions(username, keepToken) {
  for (const [token, session] of sessions) {
    if (session.username === username && token !== keepToken) sessions.delete(token);
  }
}

export function readSessionCookie(header = "") {
  for (const part of header.split(";")) {
    const index = part.indexOf("=");
    if (index > 0 && part.slice(0, index).trim() === COOKIE_NAME) return part.slice(index + 1).trim();
  }
  return null;
}

export function sessionCookie(token) {
  return `${COOKIE_NAME}=${token}; Path=${COOKIE_PATH}; HttpOnly; Secure; SameSite=Strict; Max-Age=${SESSION_MS / 1000}`;
}

export function clearedCookie() {
  return `${COOKIE_NAME}=; Path=${COOKIE_PATH}; HttpOnly; Secure; SameSite=Strict; Max-Age=0`;
}

// Bản ghi giả để so sánh khi tài khoản không tồn tại, tránh lộ tài khoản qua thời gian phản hồi.
export const DUMMY_RECORD = await hashPassword(randomBytes(16).toString("hex"));
