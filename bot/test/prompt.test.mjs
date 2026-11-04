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

test("lời nhắc có giọng hài nhẹ gọi người dùng là Bộ Đẹp, và cấm đùa về nội dung pháp lý", () => {
  assert.ok(SYSTEM_PROMPT.includes('"Bộ Đẹp"'));
  assert.ok(SYSTEM_PROMPT.includes("Không đùa về công dân, thủ tục"));
});
