// Kiểm thử nội dung lời nhắc hệ thống (không gọi Claude).
import { test } from "node:test";
import assert from "node:assert/strict";
import { SYSTEM_PROMPT } from "../prompt.mjs";

test("lời nhắc hướng dẫn cán bộ: đủ các mục hướng dẫn và luồng duyệt", () => {
  for (const muc of ["Công dân chuẩn bị", "Nộp và nhận ở đâu", "Cán bộ làm gì", "Duyệt và gửi", "Căn cứ"]) {
    assert.ok(SYSTEM_PROMPT.includes(muc), `thiếu mục: ${muc}`);
  }
});

test("lời nhắc không cho bot kết luận thay cán bộ", () => {
  assert.ok(SYSTEM_PROMPT.includes("Không kết luận thay cán bộ"));
});

test("lời nhắc buộc lấy trình tự trước khi hướng dẫn thủ tục", () => {
  assert.ok(SYSTEM_PROMPT.includes("get_procedure"));
});

test("lời nhắc để máy chủ thêm lời chào và lời nhắc, nội dung không có câu đùa", () => {
  assert.ok(SYSTEM_PROMPT.includes("Hệ thống tự thêm lời chào và lời nhắc nhẹ"));
  assert.ok(SYSTEM_PROMPT.includes("không thêm câu đùa vào nội dung"));
});
