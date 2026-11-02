// Bot tra cứu thủ tục: nhận câu hỏi, cho Claude (Haiku 5.5) dùng công cụ tra dữ liệu, trả lời kèm nguồn.
// Chỉ lắng nghe trên 127.0.0.1; Caddy đứng trước để kiểm soát đăng nhập.
import http from "node:http";
import Anthropic from "@anthropic-ai/sdk";
import {
  loadAll,
  searchProcedures,
  getProcedure,
  searchLegalDocuments,
  getLegalDocument,
} from "./data.mjs";

const HOST = "127.0.0.1";
const PORT = Number(process.env.TCHC_BOT_PORT || 3100);
const MODEL = "claude-haiku-5-5";
const MAX_TOOL_ROUNDS = 6;
const MAX_MESSAGE_CHARS = 2000;
const MAX_BODY_BYTES = 20000;
const MAX_HISTORY_ITEMS = 8;

// Anthropic() đọc khóa từ biến môi trường ANTHROPIC_API_KEY.
const client = new Anthropic();

const SYSTEM_PROMPT = `Bạn là trợ lý tra cứu thủ tục hành chính cho cán bộ quản lý khu vực dân cư tại TP.HCM. Lĩnh vực: cư trú, căn cước, con dấu, vũ khí và công cụ hỗ trợ, an ninh trật tự, và các thủ tục liên quan.

Quy tắc bắt buộc:
- Chỉ trả lời dựa trên kết quả của các công cụ. Không dùng kiến thức bên ngoài để bổ sung. Nếu công cụ không có thông tin, nói rõ là không tìm thấy trong dữ liệu và gợi ý hỏi bộ phận tiếp nhận.
- Khi tra cứu thủ tục, trình bày đủ: cơ quan thực hiện, thành phần hồ sơ, trình tự, thời hạn giải quyết, lệ phí và căn cứ pháp lý.
- Với mỗi căn cứ pháp lý, nêu số ký hiệu và tình trạng hiệu lực mà công cụ trả về, kèm nguồn. Nếu tình trạng là hết hiệu lực hoặc chưa được đối chiếu, nói rõ điều đó.
- Dữ liệu chưa có toàn văn điều khoản. Đừng trích "Điều x, khoản y" trừ khi công cụ đã cung cấp nội dung đó.
- Không đưa ý kiến pháp lý cá nhân. Khi quyết định áp dụng, nhắc người dùng đối chiếu văn bản gốc.
- Nếu người dùng nhập số định danh, số điện thoại hoặc địa chỉ của công dân, nhắc không nhập thông tin cá nhân vào hệ thống.
- Khi gọi công cụ tìm kiếm, dùng từ khóa ngắn 2 đến 5 từ lấy từ việc cần làm (ví dụ: "cấp lại thẻ căn cước"), không đưa cả câu hỏi vào. Nếu kết quả đầu tiên chưa đúng, thử từ khóa khác trước khi kết luận là không có.
- Trả lời bằng tiếng Việt, ngắn gọn, dùng gạch đầu dòng khi liệt kê.`;

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
];

function runTool(name, input, data, sources) {
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
      tools: TOOLS,
      messages,
    });

    if (response.stop_reason === "tool_use") {
      messages.push({ role: "assistant", content: response.content });
      const results = response.content
        .filter((block) => block.type === "tool_use")
        .map((block) => ({
          type: "tool_result",
          tool_use_id: block.id,
          content: runTool(block.name, block.input, data, sources),
        }));
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

function send(res, status, payload) {
  res.writeHead(status, { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" });
  res.end(JSON.stringify(payload));
}

const server = http.createServer(async (req, res) => {
  if (req.method === "GET" && req.url === "/api/health") {
    return send(res, 200, { ok: true, model: MODEL });
  }
  if (req.method !== "POST" || req.url !== "/api/chat") {
    return send(res, 404, { loi: "không tìm thấy" });
  }

  let body = "";
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > MAX_BODY_BYTES) return send(res, 413, { loi: "yêu cầu quá lớn" });
    body += chunk;
  }

  let parsed;
  try {
    parsed = JSON.parse(body);
  } catch {
    return send(res, 400, { loi: "dữ liệu không hợp lệ" });
  }

  const message = typeof parsed.message === "string" ? parsed.message.trim() : "";
  if (!message || message.length > MAX_MESSAGE_CHARS) {
    return send(res, 400, { loi: "câu hỏi trống hoặc quá dài" });
  }

  const started = Date.now();
  try {
    const data = await loadAll();
    const result = await answer(message, sanitizeHistory(parsed.history), data);
    // Không ghi nội dung câu hỏi vào nhật ký, chỉ ghi thời gian xử lý.
    console.log(`chat ok in ${Date.now() - started} ms`);
    return send(res, 200, result);
  } catch (error) {
    console.error(`chat failed: ${error.status ?? ""} ${error.name}`);
    return send(res, 500, { loi: "Hệ thống đang gặp lỗi, bạn thử lại sau." });
  }
});

server.listen(PORT, HOST, () => {
  console.log(`tchc bot listening on ${HOST}:${PORT}`);
});
