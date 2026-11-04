// Vòng lặp trả lời của bot: Claude gọi công cụ tra dữ liệu rồi trả lời kèm nguồn.
// Tách khỏi máy chủ HTTP để kiểm thử được mà không mở cổng và không gọi Claude thật.
import {
  searchProcedures,
  getProcedure,
  searchLegalDocuments,
  getLegalDocument,
  getLegalDocumentDetail,
  timTrongToanVan,
} from "./data.mjs";
import { SYSTEM_PROMPT } from "./prompt.mjs";

export const MODEL = "claude-haiku-5-5";
// Số lượt gọi công cụ tối đa cho một câu hỏi. Hết lượt, bot vẫn trả lời từ dữ liệu đã tra được.
const MAX_TOOL_ROUNDS = 6;
const HET_LUOT_TRA_CUU = "Đã hết lượt tra cứu. Hãy trả lời ngay từ các kết quả đã có, nêu rõ phần nào chưa có dữ liệu. Không gọi thêm công cụ.";
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

// Lượt cuối không cho gọi công cụ nữa: buộc bot trả lời từ dữ liệu đã có, không báo "quá nhiều bước".
// Trả lời theo luồng: chữ của mô hình được chuyển cho onEvent ngay khi sinh ra ("delta").
// Nếu mô hình đã nói trước rồi mới gọi công cụ, gửi "reset" để bỏ phần đã nói; lượt sau viết lại.
export async function answerStream(client, message, history, data, onEvent = () => {}) {
  const messages = [...history, { role: "user", content: message }];
  const sources = [];
  let daPhatChu = false;

  for (let round = 1; round <= MAX_TOOL_ROUNDS + 1; round++) {
    const finalRound = round > MAX_TOOL_ROUNDS;
    if (finalRound) messages.at(-1).content.push({ type: "text", text: HET_LUOT_TRA_CUU });
    const luong = client.messages.stream({
      model: MODEL,
      max_tokens: 4000,
      system: [{ type: "text", text: SYSTEM_PROMPT, cache_control: { type: "ephemeral" } }],
      tools: TOOLS_CACHED,
      tool_choice: finalRound ? { type: "none" } : { type: "auto" },
      messages,
    });
    luong.on("text", (delta) => {
      daPhatChu = true;
      onEvent({ type: "delta", text: delta });
    });
    const response = await luong.finalMessage();

    if (response.stop_reason === "tool_use" && !finalRound) {
      if (daPhatChu) {
        onEvent({ type: "reset" });
        daPhatChu = false;
      }
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
      return { answer: "Mình không thể trả lời câu hỏi này. Bạn thử diễn đạt lại theo việc cần làm.", sources, co_noi_dung: false };
    }

    const text = response.content
      .filter((block) => block.type === "text")
      .map((block) => block.text)
      .join("\n")
      .trim();
    const note = response.stop_reason === "max_tokens" ? "\n\n(Câu trả lời bị cắt ngắn, hãy hỏi cụ thể hơn.)" : "";
    const fallback = "Mình chưa tìm đủ dữ liệu để trả lời. Bạn nêu cụ thể hơn tên thủ tục hoặc số văn bản.";
    return { answer: (text || fallback) + note, sources: dedupe(sources), co_noi_dung: Boolean(text) };
  }
}

// Bản không luồng, giữ cho các nơi gọi cũ.
export async function answer(client, message, history, data) {
  return answerStream(client, message, history, data);
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
