// Bot tra cứu thủ tục: nhận câu hỏi, cho Claude (Haiku 5.5) dùng công cụ tra dữ liệu, trả lời kèm nguồn.
// Chỉ lắng nghe trên 127.0.0.1. Caddy chuyển tiếp /tchc vào đây; bot tự kiểm tra đăng nhập và phục vụ tệp tĩnh.
import http from "node:http";
import Anthropic from "@anthropic-ai/sdk";
import { answer, MODEL } from "./agent.mjs";
import { loadAll, loadKnowledge } from "./data.mjs";
import { serveSite } from "./site.mjs";
import {
  DUMMY_RECORD,
  MAX_PASSWORD_LENGTH,
  MIN_PASSWORD_LENGTH,
  clearFailures,
  clearedCookie,
  createSession,
  endOtherSessions,
  endSession,
  findUser,
  getSession,
  lockedMinutes,
  passwordMatches,
  readSessionCookie,
  recordFailure,
  sessionCookie,
  setPassword,
} from "./auth.mjs";

const HOST = "127.0.0.1";
const PORT = Number(process.env.TCHC_BOT_PORT || 3100);
const MAX_MESSAGE_CHARS = 2000;
const MAX_BODY_BYTES = 20000;
const MAX_AUTH_BODY_BYTES = 2000;
const MAX_HISTORY_ITEMS = 8;
const SITE_DIR = process.env.TCHC_SITE_DIR || "C:\\tchc\\site";
const AUTH_FILE = process.env.TCHC_AUTH_FILE || "C:\\tchc\\auth\\users.json";
// Tiền tố công khai của trang: Caddy bỏ /tchc trước khi chuyển sang bot, nhưng trình duyệt cần đường dẫn đầy đủ.
const BASE = process.env.TCHC_BASE ?? "/tchc";
// Chỉ trang đăng nhập mở được khi chưa đăng nhập (CSS và JS nằm sẵn trong trang đó).
const PUBLIC_PAGES = new Set(["/login.html"]);

// Anthropic() đọc khóa từ biến môi trường ANTHROPIC_API_KEY.
const client = new Anthropic();

function sanitizeHistory(raw) {
  if (!Array.isArray(raw)) return [];
  const items = raw
    .filter((item) => item && (item.role === "user" || item.role === "assistant") && typeof item.content === "string")
    .map((item) => ({ role: item.role, content: item.content.slice(0, MAX_MESSAGE_CHARS) }))
    .slice(-MAX_HISTORY_ITEMS);
  // Lịch sử phải bắt đầu bằng lượt của người dùng.
  while (items.length && items[0].role !== "user") items.shift();
  return items;
}

class HttpError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

function send(res, status, payload, headers = {}) {
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    ...headers,
  });
  res.end(JSON.stringify(payload));
}

// Đọc thân yêu cầu JSON, giới hạn kích thước.
async function readJson(req, limit) {
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > limit) throw new HttpError(413, "yêu cầu quá lớn");
    chunks.push(chunk);
  }
  let parsed;
  try {
    parsed = JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    throw new HttpError(400, "dữ liệu không hợp lệ");
  }
  if (!parsed || typeof parsed !== "object") throw new HttpError(400, "dữ liệu không hợp lệ");
  return parsed;
}

// Tên đăng nhập đưa vào nhật ký: chỉ giữ ký tự an toàn, tránh làm sai lệch dòng log.
function logName(name) {
  return String(name).replace(/[^\w.@-]/g, "?").slice(0, 40);
}

function currentSession(req) {
  return getSession(readSessionCookie(req.headers.cookie));
}

async function login(req, res) {
  const body = await readJson(req, MAX_AUTH_BODY_BYTES);
  const username = typeof body.username === "string" ? body.username.trim() : "";
  const password = typeof body.password === "string" ? body.password : "";
  if (!username || !password || password.length > MAX_PASSWORD_LENGTH) {
    return send(res, 400, { loi: "Nhập tài khoản và mật khẩu." });
  }
  const locked = lockedMinutes(username);
  if (locked) return send(res, 429, { loi: `Nhập sai nhiều lần. Thử lại sau ${locked} phút.` });

  const user = await findUser(AUTH_FILE, username);
  const matched = await passwordMatches(password, user ?? DUMMY_RECORD);
  if (!user || !matched) {
    recordFailure(username);
    console.warn(`login failed: ${logName(username)}`);
    return send(res, 401, { loi: "Sai tài khoản hoặc mật khẩu." });
  }

  clearFailures(username);
  console.log(`login ok: ${logName(username)}`);
  const token = createSession(username);
  return send(
    res,
    200,
    { ok: true, phai_doi_mat_khau: Boolean(user.phai_doi_mat_khau) },
    { "Set-Cookie": sessionCookie(token) }
  );
}

async function me(res, session) {
  const user = await findUser(AUTH_FILE, session.username);
  if (!user) return send(res, 401, { loi: "Cần đăng nhập." });
  return send(res, 200, { ten: session.username, phai_doi_mat_khau: Boolean(user.phai_doi_mat_khau) });
}

async function changePassword(req, res, session) {
  const body = await readJson(req, MAX_AUTH_BODY_BYTES);
  const current = typeof body.current === "string" ? body.current : "";
  const next = typeof body.next === "string" ? body.next : "";
  const user = await findUser(AUTH_FILE, session.username);
  if (!user) return send(res, 401, { loi: "Cần đăng nhập." });

  const locked = lockedMinutes(session.username);
  if (locked) return send(res, 429, { loi: `Nhập sai nhiều lần. Thử lại sau ${locked} phút.` });
  if (!(await passwordMatches(current, user))) {
    recordFailure(session.username);
    return send(res, 400, { loi: "Mật khẩu hiện tại không đúng." });
  }
  if (next.length < MIN_PASSWORD_LENGTH) {
    return send(res, 400, { loi: `Mật khẩu mới cần ít nhất ${MIN_PASSWORD_LENGTH} ký tự.` });
  }
  if (next.length > MAX_PASSWORD_LENGTH) return send(res, 400, { loi: "Mật khẩu mới quá dài." });
  if (next === current) return send(res, 400, { loi: "Mật khẩu mới phải khác mật khẩu hiện tại." });

  await setPassword(AUTH_FILE, session.username, next, { mustChange: false });
  clearFailures(session.username);
  endOtherSessions(session.username, session.token);
  console.log(`password changed: ${logName(session.username)}`);
  return send(res, 200, { ok: true });
}

async function chat(req, res, session) {
  const user = await findUser(AUTH_FILE, session.username);
  if (user?.phai_doi_mat_khau) {
    return send(res, 403, { loi: "Cần đổi mật khẩu trước khi dùng Hỏi đáp.", phai_doi_mat_khau: true });
  }
  const parsed = await readJson(req, MAX_BODY_BYTES);
  const message = typeof parsed.message === "string" ? parsed.message.trim() : "";
  if (!message || message.length > MAX_MESSAGE_CHARS) {
    return send(res, 400, { loi: "câu hỏi trống hoặc quá dài" });
  }

  const started = Date.now();
  try {
    const data = { ...(await loadAll()), knowledge: await loadKnowledge() };
    const result = await answer(client, message, sanitizeHistory(parsed.history), data);
    // Không ghi nội dung câu hỏi vào nhật ký, chỉ ghi thời gian xử lý.
    console.log(`chat ok in ${Date.now() - started} ms`);
    return send(res, 200, result);
  } catch (error) {
    console.error(`chat failed: ${error.status ?? ""} ${error.name}`);
    return send(res, 500, { loi: "Hệ thống đang gặp lỗi, bạn thử lại sau." });
  }
}

async function handleApi(req, res, pathname) {
  if (req.method === "POST" && pathname === "/api/login") return login(req, res);
  if (req.method === "POST" && pathname === "/api/logout") {
    endSession(readSessionCookie(req.headers.cookie));
    return send(res, 200, { ok: true }, { "Set-Cookie": clearedCookie() });
  }

  const session = currentSession(req);
  if (!session) return send(res, 401, { loi: "Cần đăng nhập." });
  if (req.method === "GET" && pathname === "/api/me") return me(res, session);
  if (req.method === "POST" && pathname === "/api/change-password") return changePassword(req, res, session);
  if (req.method === "GET" && pathname === "/api/health") return send(res, 200, { ok: true, model: MODEL });
  if (req.method === "POST" && pathname === "/api/chat") return chat(req, res, session);
  return send(res, 404, { loi: "không tìm thấy" });
}

async function handlePage(req, res, pathname) {
  if (req.method !== "GET" && req.method !== "HEAD") return send(res, 405, { loi: "không hỗ trợ" });
  const headOnly = req.method === "HEAD";
  if (PUBLIC_PAGES.has(pathname)) return serveSite(res, SITE_DIR, pathname, headOnly);

  if (!currentSession(req)) {
    // Mở trang bằng trình duyệt thì chuyển sang màn đăng nhập; tải dữ liệu ngầm thì trả 401.
    if ((req.headers.accept || "").includes("text/html")) {
      res.writeHead(302, { Location: `${BASE}/login.html`, "Cache-Control": "no-store" });
      return res.end();
    }
    return send(res, 401, { loi: "Cần đăng nhập." });
  }
  return serveSite(res, SITE_DIR, pathname, headOnly);
}

const server = http.createServer(async (req, res) => {
  const { pathname } = new URL(req.url, "http://localhost");
  try {
    if (pathname.startsWith("/api/")) return await handleApi(req, res, pathname);
    return await handlePage(req, res, pathname);
  } catch (error) {
    if (error instanceof HttpError) return send(res, error.status, { loi: error.message });
    console.error(`request failed: ${error.name}`);
    return send(res, 500, { loi: "Hệ thống đang gặp lỗi, bạn thử lại sau." });
  }
});

server.listen(PORT, HOST, () => {
  console.log(`tchc bot listening on ${HOST}:${PORT}`);
});
