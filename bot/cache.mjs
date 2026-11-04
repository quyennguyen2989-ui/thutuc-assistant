// Bộ nhớ đệm câu trả lời: chỉ cho câu hỏi đầu tiên (không có lịch sử hội thoại) và chỉ khi có nguồn.
// Khóa gồm câu hỏi đã chuẩn hóa và phiên bản dữ liệu, nên khi dữ liệu cập nhật thì câu trả lời cũ không còn dùng.

const MAX_ENTRIES = 200;

export function createAnswerCache(maxEntries = MAX_ENTRIES) {
  const entries = new Map();
  return {
    get size() {
      return entries.size;
    },
    get(key) {
      return entries.get(key);
    },
    set(key, value) {
      if (entries.has(key)) entries.delete(key);
      entries.set(key, value);
      // Bỏ mục cũ nhất khi vượt giới hạn (Map giữ thứ tự thêm vào).
      if (entries.size > maxEntries) entries.delete(entries.keys().next().value);
    },
  };
}

// Phiên bản dữ liệu: đổi khi cổng cập nhật (meta.cap_nhat_luc) hoặc số ghi chú đọc hiểu thay đổi.
export function versionOf(data) {
  return `${data.meta?.cap_nhat_luc ?? ""}|${data.knowledge?.length ?? 0}`;
}

export function cacheKey(question, data, normalize) {
  return `${versionOf(data)}|${normalize(question).replace(/\s+/g, " ").trim()}`;
}
