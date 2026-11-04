// Kiểm thử lời chào và lời nhắc nhẹ (không gọi mạng).
import { test } from "node:test";
import assert from "node:assert/strict";
import { chonLoiChao, chonLoiNhac } from "../giong.mjs";

test("lời chào và lời nhắc luôn có trong danh sách và xưng Bộ Đẹp", () => {
  for (let i = 0; i < 40; i++) {
    const chao = chonLoiChao();
    const nhac = chonLoiNhac();
    assert.ok(typeof chao === "string" && chao.length > 0);
    assert.ok(typeof nhac === "string" && nhac.length > 0);
  }
  assert.ok(chonLoiChao().includes("Bộ Đẹp"));
});

test("chọn theo số ngẫu nhiên: đầu và cuối danh sách đều có thể được chọn", () => {
  const dau = chonLoiNhac(() => 0);
  const cuoi = chonLoiNhac(() => 0.999999);
  assert.notEqual(dau, cuoi);
});

test("lời nhắc có ý quan tâm sức khỏe và không chứa thông tin thủ tục", () => {
  const tat_ca = [];
  for (let i = 0; i < 8; i++) tat_ca.push(chonLoiNhac(() => i / 8));
  assert.ok(tat_ca.some((text) => /nghỉ|uống nước|ăn trưa/.test(text)));
  for (const text of tat_ca) assert.doesNotMatch(text, /\d/);
});
