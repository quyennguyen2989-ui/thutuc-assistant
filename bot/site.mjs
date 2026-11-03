// Phục vụ tệp tĩnh của trang tra cứu từ thư mục site. Chỉ các đuôi trong TYPES, không đi ra ngoài thư mục.
import { readFile } from "node:fs/promises";
import path from "node:path";

const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".txt": "text/plain; charset=utf-8",
};

// Trả về đường dẫn tệp trong siteDir, hoặc null nếu đường dẫn không hợp lệ hoặc đuôi không được phép.
export function resolveSitePath(siteDir, urlPath) {
  let decoded;
  try {
    decoded = decodeURIComponent(urlPath);
  } catch {
    return null;
  }
  if (decoded.includes("\0")) return null;

  const relative = path.posix.normalize(decoded);
  const target = path.resolve(siteDir, `.${relative.endsWith("/") ? `${relative}index.html` : relative}`);
  const root = path.resolve(siteDir);
  if (!target.startsWith(root + path.sep)) return null;
  return TYPES[path.extname(target).toLowerCase()] ? target : null;
}

export async function serveSite(res, siteDir, urlPath, headOnly) {
  const file = resolveSitePath(siteDir, urlPath);
  let body = null;
  if (file) {
    try {
      body = await readFile(file);
    } catch {
      body = null;
    }
  }
  if (!body) {
    res.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
    return res.end("không tìm thấy");
  }
  res.writeHead(200, {
    "Content-Type": TYPES[path.extname(file).toLowerCase()],
    "Content-Length": body.length,
    "Cache-Control": "no-cache",
    "X-Content-Type-Options": "nosniff",
  });
  return res.end(headOnly ? undefined : body);
}
