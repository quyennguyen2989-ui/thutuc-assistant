// Kiểm thử lớp dữ liệu của bot trên dữ liệu thật trong docs/data (không gọi mạng, không gọi Claude).
import { test } from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
process.env.TCHC_DATA_DIR = path.resolve(here, "..", "..", "docs", "data");
const data = await import("../data.mjs");

test("tìm đoạn toàn văn trả về số điều đúng với nội dung đã đọc", async () => {
  const hits = await data.timTrongToanVan("định danh mức độ 02 không phụ thuộc nơi cư trú");
  const hit = hits.find((item) => item.so_ky_hieu === "392/2026/NĐ-CP");
  assert.ok(hit, "phải tìm thấy Nghị định 392/2026");
  assert.equal(hit.dieu, "Điều 31");
  assert.match(hit.trich, /không phụ thuộc vào nơi cư trú/);
});

test("tìm toàn văn khớp nguyên từ: 'sinh' không khớp 'kinh', 'con' không khớp 'công'", async () => {
  const hits = await data.timTrongToanVan("khai sinh");
  assert.ok(hits.length > 0);
  for (const hit of hits) assert.match(hit.trich, /(^|[^\p{L}])(khai|sinh)([^\p{L}]|$)/iu);
});

test("văn bản toàn văn không có trường số ký hiệu thì lấy số từ tiêu đề", async () => {
  const hits = await data.timTrongToanVan("trong thời hạn 60 ngày kể từ ngày sinh con");
  const hit = hits.find((item) => item.so_ky_hieu === "60/2014/QH13");
  assert.ok(hit, "phải nhận ra Luật Hộ tịch 60/2014/QH13 từ tiêu đề");
  assert.equal(hit.dieu, "Điều 15");
});

test("mỗi văn bản góp tối đa hai đoạn", async () => {
  const hits = await data.timTrongToanVan("thẻ căn cước", { limit: 10 });
  const counts = new Map();
  for (const hit of hits) counts.set(hit.ten, (counts.get(hit.ten) || 0) + 1);
  for (const count of counts.values()) assert.ok(count <= 2);
});

test("văn bản còn hiệu lực được xếp trước văn bản hết hiệu lực", async () => {
  const hits = await data.timTrongToanVan("cấp lại thẻ căn cước", { limit: 4 });
  assert.ok(hits.length > 0);
  assert.notEqual(hits[0].tinh_trang?.startsWith("Hết hiệu lực"), true);
});

test("chi tiết văn bản có tình trạng, ngày hiệu lực, nguồn và ghi chú đọc hiểu", async () => {
  const loaded = await data.loadAll();
  const knowledge = await data.loadKnowledge();
  const detail = data.getLegalDocumentDetail(loaded, knowledge, "392/2026/NĐ-CP");
  assert.equal(detail.tinh_trang.tinh_trang, "Chưa đối chiếu với vbpl.vn");
  assert.equal(detail.ngay_hieu_luc, "2026-11-15");
  assert.ok(detail.ghi_chu_doc_hieu.length >= 1);
  assert.ok(detail.nguon_chinh_thuc.length >= 1);
});

test("số ký hiệu không có trong danh mục trả về null", async () => {
  const loaded = await data.loadAll();
  const knowledge = await data.loadKnowledge();
  assert.equal(data.getLegalDocumentDetail(loaded, knowledge, "999/1900/XX-YY"), null);
});
