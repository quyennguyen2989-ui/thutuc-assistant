// Bot tra cứu thủ tục: nhận câu hỏi, cho Claude (Haiku 5.5) dùng công cụ tra dữ liệu, trả lời kèm nguồn.
// Chỉ lắng nghe trên 127.0.0.1. Caddy chuyển tiếp /tchc vào đây; bot tự kiểm tra đăng nhập và phục vụ tệp tĩnh.
import http from "node:http";
import Anthropic from "@anthropic-ai/sdk";
import {
  loadAll,
  loadKnowledge,
  searchProcedures,
  getProcedure,
  searchLegalDocuments,
  getLegalDocument,
  getLegalDocumentDetail,
  timTrongToanVan,
} from "./data.mjs";
import { serveSite } from "./site.mjs";
import { SYSTEM_PROMPT } from "./prompt.mjs";
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
const MODEL = "claude-haiku-5-5";
const MAX_TOOL_ROUNDS = 5;
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

const TOOLS = [
  {
    name: "search_procedures",
    description: "Tìm thủ tục hành chính theo từ khóa ngắn (ví dụ: 'đăng ký tạm trú', 'cấp lại thẻ căn cước'). Trả về danh sách ngắn kèm mã id, xếp theo mức khớp với tiêu đề.",
    input_schema: {
      type: "object",
      properties: { tu_khoa: { type: "string", description: "Từ khóa hoặc mô tả việc cần làm" } },
      required: ["tu_khoa"],
    },
  },
  {
    name: "get_procedure",
    description: "Lấy chi tiết một thủ tục theo id: hồ sơ, trình tự, thời hạn, lệ phí và căn cứ pháp lý kèm tình trạng hiệu lực.",
    input_schema: {
      type: "object",
      properties: { id: { type: "integer", description: "Mã id của thủ tục, lấy từ search_procedures" } },
      required: ["id"],
    },
  },
  {
    name: "search_legal_documents",
    description: "Tìm văn bản pháp luật theo số ký hiệu, trích yếu hoặc lĩnh vực. Trả về tình trạng hiệu lực.",
    input_schema: {
      type: "object",
      properties: { tu_khoa: { type: "string", description: "Số ký hiệu hoặc từ khóa trích yếu" } },
      required: ["tu_khoa"],
    },
  },
  {
    name: "get_legal_document",
    description: "Lấy thông tin và tình trạng hiệu lực của một văn bản theo số ký hiệu chính xác (ví dụ: '68/2020/QH14').",
    input_schema: {
      type: "object",
      properties: { so_ky_hieu: { type: "string", description: "Số ký hiệu văn bản" } },
      required: ["so_ky_hieu"],
    },
  },
  {
    name: "tra_van_ban",
    description: "Thông tin đầy đủ của một văn bản theo số ký hiệu chính xác: ngày ban hành, ngày hiệu lực, tình trạng (vbpl.vn hoặc chưa đối chiếu), ngày cập nhật, nguồn công bố và ghi chú đọc hiểu nếu có.",
    input_schema: {
      type: "object",
      properties: { so_ky_hieu: { type: "string", description: "Số ký hiệu văn bản, ví dụ '392/2026/NĐ-CP'" } },
      required: ["so_ky_hieu"],
    },
  },
  {
    name: "tim_trong_toan_van",
    description: "Tìm đoạn trong toàn văn các văn bản theo từ khóa (cụm từ ngắn, ví dụ 'không phụ thuộc nơi cư trú'). Trả về các đoạn kèm số điều, số ký hiệu và tình trạng. Tùy chọn giới hạn trong một văn bản.",
    input_schema: {
      type: "object",
      properties: {
        tu_khoa: { type: "string", description: "Cụm từ cần tìm trong nội dung văn bản" },
        so_ky_hieu: { type: "string", description: "Tùy chọn: chỉ tìm trong văn bản có số ký hiệu này" },
      },
      required: ["tu_khoa"],
    },
  },
];

// Định nghĩa công cụ được lưu đệm: lần sau không gửi lại toàn bộ, nhanh và rẻ hơn.
const TOOLS_CACHED = TOOLS.map((tool, index) =>
  index === TOOLS.length - 1 ? { ...tool, cache_control: { type: "ephemeral" } } : tool,
);

async function runTool(name, input, data, sources) {
  try {
    if (name === "search_procedures") {
      const tu_khoa = String(input?.tu_khoa ?? "").slice(0, 200);
      return JSON.stringify({ ket_qua: searchProcedures(data, tu_khoa) });
    }
    if (name === "get_procedure") {
      const id = Number(input?.id);
      if (!Number.isInteger(id)) return JSON.stringify({ loi: "id không hợp lệ" });
      const detail = getProcedure(data, id);
      if (!detail) return JSON.stringify({ loi: "không tìm thấy thủ tục" });
      sources.push({ loai: "thu_tuc", ten: detail.ten });
      return JSON.stringify(detail);
    }
    if (name === "search_legal_documents") {
      const tu_khoa = String(input?.tu_khoa ?? "").slice(0, 200);
      return JSON.stringify({ ket_qua: searchLegalDocuments(data, tu_khoa) });
    }
    if (name === "get_legal_document") {
      const so = String(input?.so_ky_hieu ?? "").slice(0, 60);
      const doc = getLegalDocument(data, so);
      if (!doc) return JSON.stringify({ loi: "không tìm thấy văn bản" });
      sources.push({ loai: "van_ban", ten: doc.so_ky_hieu });
      return JSON.stringify(doc);
    }
    if (name === "tra_van_ban") {
      const so = String(input?.so_ky_hieu ?? "").slice(0, 60);
      const detail = getLegalDocumentDetail(data, data.knowledge, so);
      if (!detail) return JSON.stringify({ loi: "không tìm thấy văn bản trong danh mục theo dõi" });
      sources.push({ loai: "van_ban", ten: detail.so_ky_hieu });
      return JSON.stringify(detail);
    }
    if (name === "tim_trong_toan_van") {
      const tuKhoa = String(input?.tu_khoa ?? "").slice(0, 200);
      const so = input?.so_ky_hieu ? String(input.so_ky_hieu).slice(0, 60) : null;
      const passages = await timTrongToanVan(tuKhoa, { soKyHieu: so });
      for (const passage of passages) {
        sources.push({ loai: "toan_van", ten: `${passage.ten}${passage.dieu ? ` — ${passage.dieu}` : ""}` });
      }
      return JSON.stringify(passages.length ? { doan_trich: passages } : { loi: "không tìm thấy đoạn phù hợp trong toàn văn" });
    }
    return JSON.stringify({ loi: "công cụ không tồn tại" });
  } catch (error) {
    console.error(`tool ${name} failed: ${error.name}`);
    return JSON.stringify({ loi: "lỗi khi tra cứu" });
  }
}

async function answer(message, history, data) {
  const messages = [...history, { role: "user", content: message }];
  const sources = [];

  for (let round = 0; round < MAX_TOOL_ROUNDS; round++) {
    const response = await client.messages.create({
      model: MODEL,
      max_tokens: 4000,
      system: [{ type: "text", text: SYSTEM_PROMPT, cache_control: { type: "ephemeral" } }],
      tools: TOOLS_CACHED,
      messages,
    });

    if (response.stop_reason === "tool_use") {
      messages.push({ role: "assistant", content: response.content });
      const results = [];
      for (const block of response.content.filter((item) => item.type === "tool_use")) {
        results.push({
          type: "tool_result",
          tool_use_id: block.id,
          content: await runTool(block.name, block.input, data, sources),
        });
      }
      messages.push({ role: "user", content: results });
      continue;
    }

    if (response.stop_reason === "refusal") {
      return { answer: "Mình không thể trả lời câu hỏi này. Bạn thử diễn đạt lại theo việc cần làm.", sources };
    }

    const text = response.content
      .filter((block) => block.type === "text")
      .map((block) => block.text)
      .join("\n")
      .trim();
    const note = response.stop_reason === "max_tokens" ? "\n\n(Câu trả lời bị cắt ngắn, hãy hỏi cụ thể hơn.)" : "";
    return { answer: (text || "Mình chưa có câu trả lời phù hợp.") + note, sources: dedupe(sources) };
  }

  return { answer: "Câu hỏi cần tra cứu quá nhiều bước. Bạn thử hỏi ngắn hơn hoặc cụ thể hơn.", sources: dedupe(sources) };
}

function dedupe(sources) {
  const seen = new Set();
  return sources.filter((item) => {
    const key = `${item.loai}:${item.ten}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

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
    const result = await answer(message, sanitizeHistory(parsed.history), data);
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
