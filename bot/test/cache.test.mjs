// Kiểm thử bộ nhớ đệm câu trả lời (không gọi mạng).
import { test } from "node:test";
import assert from "node:assert/strict";
import { cacheKey, createAnswerCache, versionOf } from "../cache.mjs";

const normalize = (text) => text.toLowerCase();

test("lưu và lấy lại theo khóa", () => {
  const cache = createAnswerCache(10);
  cache.set("k1", { answer: "a", sources: [] });
  assert.deepEqual(cache.get("k1"), { answer: "a", sources: [] });
  assert.equal(cache.get("k2"), undefined);
});

test("vượt giới hạn thì bỏ mục cũ nhất", () => {
  const cache = createAnswerCache(2);
  cache.set("a", 1);
  cache.set("b", 2);
  cache.set("c", 3);
  assert.equal(cache.size, 2);
  assert.equal(cache.get("a"), undefined);
  assert.equal(cache.get("c"), 3);
});

test("khóa không phân biệt hoa thường và khoảng trắng thừa", () => {
  const data = { meta: { cap_nhat_luc: "2026-11-04T01:00:00+00:00" }, knowledge: [1, 2] };
  assert.equal(cacheKey("  Đăng ký  Tạm trú ", data, normalize), cacheKey("đăng ký tạm trú", data, normalize));
});

test("đổi dữ liệu thì khóa đổi, câu trả lời cũ không còn dùng", () => {
  const moi = { meta: { cap_nhat_luc: "2026-11-05T01:00:00+00:00" }, knowledge: [1, 2] };
  const cu = { meta: { cap_nhat_luc: "2026-11-04T01:00:00+00:00" }, knowledge: [1, 2] };
  assert.notEqual(cacheKey("q", moi, normalize), cacheKey("q", cu, normalize));
  assert.notEqual(versionOf(moi), versionOf(cu));
});
