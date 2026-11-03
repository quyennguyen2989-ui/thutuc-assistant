// Kiểm thử vòng lặp trả lời với Claude giả (không gọi mạng, không cần khóa API).
import { test } from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
process.env.TCHC_DATA_DIR = path.resolve(here, "..", "..", "docs", "data");
const { answer } = await import("../agent.mjs");
const data = await import("../data.mjs");

const KET_THUC = "Bạn nêu cụ thể hơn tên thủ tục hoặc số văn bản.";

// Claude giả: trả lần lượt các phản hồi đã cho và ghi lại tham số mỗi lần gọi.
function fakeClient(responses) {
  const calls = [];
  return {
    calls,
    messages: {
      create: async (params) => {
        calls.push(structuredClone(params));
        const next = responses.shift();
        if (!next) throw new Error("hết phản hồi giả");
        return next;
      },
    },
  };
}

const goiCongCu = (name, input) => ({
  stop_reason: "tool_use",
  content: [{ type: "tool_use", id: `id_${name}`, name, input }],
});
const traLoi = (text) => ({ stop_reason: "end_turn", content: [{ type: "text", text }] });

async function loadData() {
  return { ...(await data.loadAll()), knowledge: await data.loadKnowledge() };
}

test("câu trả lời thường: gọi công cụ rồi trả lời kèm nguồn", async () => {
  const client = fakeClient([goiCongCu("tra_van_ban", { so_ky_hieu: "301/2026/NĐ-CP" }), traLoi("Bước 1: nộp hồ sơ.")]);
  const result = await answer(client, "Mới sinh con cần làm gì", [], await loadData());
  assert.equal(result.answer, "Bước 1: nộp hồ sơ.");
  assert.ok(result.sources.some((item) => item.loai === "van_ban" && item.ten === "301/2026/NĐ-CP"));
  assert.equal(client.calls[0].tool_choice.type, "auto");
});

test("hết lượt tra cứu: lượt cuối không cho gọi công cụ và vẫn có câu trả lời", async () => {
  const hetLuot = Array.from({ length: 6 }, (_, i) => goiCongCu("tim_trong_toan_van", { tu_khoa: `khai sinh ${i}` }));
  const client = fakeClient([...hetLuot, traLoi("Theo Nghị định 301/2026, chưa có thẻ thủ tục khai sinh.")]);
  const result = await answer(client, "Mới sinh con cần đăng ký khai sinh", [], await loadData());

  assert.equal(client.calls.length, 7);
  assert.deepEqual(client.calls[6].tool_choice, { type: "none" });
  assert.match(result.answer, /chưa có thẻ thủ tục khai sinh/);
  assert.doesNotMatch(result.answer, /quá nhiều bước/);
});

test("không có văn bản trả lời: vẫn trả lời bằng câu hướng dẫn cụ thể hơn", async () => {
  const hetLuot = Array.from({ length: 6 }, () => goiCongCu("search_procedures", { tu_khoa: "abc" }));
  const client = fakeClient([...hetLuot, { stop_reason: "end_turn", content: [] }]);
  const result = await answer(client, "abc", [], await loadData());
  assert.ok(result.answer.includes(KET_THUC));
});

test("lượt cuối có thêm chỉ dẫn trả lời ngay trong tin nhắn của người dùng", async () => {
  const hetLuot = Array.from({ length: 6 }, () => goiCongCu("search_procedures", { tu_khoa: "đăng ký" }));
  const client = fakeClient([...hetLuot, traLoi("Đã trả lời.")]);
  await answer(client, "đăng ký", [], await loadData());
  const lastMessage = client.calls[6].messages.at(-1);
  assert.equal(lastMessage.role, "user");
  assert.ok(lastMessage.content.some((block) => block.type === "text" && block.text.includes("Đã hết lượt tra cứu")));
});
