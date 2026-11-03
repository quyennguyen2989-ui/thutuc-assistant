// Đọc dữ liệu đã xuất (docs/data) cho bot: thủ tục, văn bản, tình trạng, ghi chú đọc hiểu và toàn văn.
// Mọi tệp đọc qua bộ nhớ đệm, chỉ đọc lại khi tệp thay đổi, để trả lời nhanh.
import { readFile, stat } from "node:fs/promises";
import path from "node:path";

const DATA_DIR = process.env.TCHC_DATA_DIR || "C:\\tchc\\site\\data";
const NUMBER_IN_TEXT = /\d{1,4}\/\d{4}\/[\w\-]+/;
// Số ký hiệu trong tiêu đề như "Nghị định 122/2018/NĐ-CP của Chính phủ" (có chữ Đ, nên không dùng \w).
const SO_TRONG_TIEU_DE = /\d{1,4}\/\d{4}\/[^\s,;()]+/u;
const MAX_PASSAGES = 4;
const MAX_PASSAGES_PER_DOC = 2;
const PASSAGE_CHARS = 600;
const NOTE_CHARS = 2500;

// Từ không mang nghĩa tìm kiếm, bỏ qua khi chấm điểm.
const STOPWORDS = new Set([
  "toi", "can", "cho", "nguoi", "lam", "the", "nao", "gi", "bao", "nhieu", "khi",
  "thi", "va", "la", "co", "duoc", "phai", "cua", "cac", "mot", "trong", "tai",
  "ve", "voi", "hoi", "thu", "tuc", "xin", "muon", "biet", "nhung", "lau", "ban",
  "giay", "to", "can", "gi", "lam", "sao",
]);

const TEN_NGUON_TOAN_VAN = {
  "vbpl.vn": "vbpl.vn",
  chinh_phu: "Công báo Chính phủ",
  tphcm: "Công báo TP.HCM",
  bo_cong_an: "Cổng Bộ Công an",
};

// Bộ nhớ đệm theo đường dẫn: giá trị được đọc lại khi thời điểm sửa đổi thay đổi.
const cache = new Map();

async function cachedFile(relative) {
  const file = path.join(DATA_DIR, relative);
  const info = await stat(file);
  const hit = cache.get(file);
  if (hit && hit.mtime === info.mtimeMs) return hit.value;
  const raw = await readFile(file, "utf8");
  const value = relative.endsWith(".json") ? JSON.parse(raw) : raw;
  cache.set(file, { mtime: info.mtimeMs, value });
  return value;
}

export async function loadAll() {
  const [tthc, vanBan, meta] = await Promise.all(
    ["tthc.json", "van_ban.json", "meta.json"].map((name) => cachedFile(name)),
  );
  return { tthc, vanBan, meta };
}

export function normalize(text) {
  return (text || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/đ/g, "d")
    .replace(/Đ/g, "D")
    .toLowerCase();
}

// Tập từ của một đoạn: so khớp nguyên từ, để "sinh" không khớp "kinh" và "con" không khớp "công".
function tokensOf(norm) {
  return new Set(norm.split(/[^a-z0-9]+/).filter(Boolean));
}

// Khóa so khớp số ký hiệu: không dấu cách, không phân biệt hoa thường, Đ và D như nhau.
function numberKey(number) {
  return normalize(number || "").replace(/\s+/g, "").toUpperCase();
}

function queryTerms(query) {
  return normalize(query)
    .split(/\s+/)
    .filter((term) => term.length >= 2 && !STOPWORDS.has(term));
}

// Chấm điểm: từ khóa trong tiêu đề được tính gấp ba lần so với nội dung khác.
// Trả về các kết quả có điểm, cao nhất trước.
function scoreAll(items, query, { titleOf, textOf }, limit) {
  const terms = queryTerms(query);
  if (terms.length === 0) return [];
  return items
    .map((item) => {
      const title = normalize(titleOf(item));
      const body = normalize(textOf(item));
      const score = terms.reduce(
        (sum, term) => sum + (title.includes(term) ? 3 : 0) + (body.includes(term) ? 1 : 0),
        0,
      );
      return { item, score };
    })
    .filter((entry) => entry.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, limit)
    .map((entry) => entry.item);
}

// Tình trạng hiệu lực: ưu tiên vbpl.vn, rồi đối chiếu thủ công, rồi công báo chính thức, rồi cổng.
export function statusOf(doc) {
  if (doc.vbpl && doc.vbpl.tinh_trang) {
    const hasEffectiveDate = Boolean(doc.vbpl.ngay_hieu_luc);
    return {
      tinh_trang: doc.vbpl.tinh_trang,
      nguon: "vbpl.vn",
      ngay_hieu_luc: doc.vbpl.ngay_hieu_luc || null,
      ngay_cap_nhat: doc.vbpl.ngay_cap_nhat || null,
      kiem_tra_luc: doc.vbpl.kiem_tra_luc || null,
      lich_su: doc.vbpl.lich_su || [],
      luu_y: hasEffectiveDate
        ? null
        : "Trang vbpl.vn chưa ghi ngày hiệu lực cho văn bản này. Không suy ra tình trạng chỉ từ việc thiếu ngày; xem lịch sử sửa đổi và văn bản sửa đổi để biết nội dung nào đã thay đổi.",
    };
  }
  if (doc.doi_chieu_thu_cong) {
    const outdated = doc.doi_chieu_thu_cong.tinh_trang === "het_hieu_luc";
    return {
      tinh_trang: outdated ? "Hết hiệu lực" : "Còn hiệu lực",
      nguon: "đối chiếu thủ công",
      ngay_cap_nhat: doc.doi_chieu_thu_cong.ngay_doi_chieu || null,
      kiem_tra_luc: null,
    };
  }
  if (doc.nguon === "thu_cong") {
    return { tinh_trang: "Còn hiệu lực", nguon: "bổ sung thủ công", ngay_cap_nhat: null, kiem_tra_luc: null };
  }
  if (doc.nguon === "chinh_thuc") {
    // Văn bản từ công báo chính thức, chưa đối chiếu với vbpl.vn: không kết luận còn hay hết hiệu lực.
    return { tinh_trang: "Chưa đối chiếu với vbpl.vn", nguon: "công báo chính thức", ngay_cap_nhat: null, kiem_tra_luc: null };
  }
  return {
    tinh_trang: doc.hieu_luc_theo_cong ? "Cổng đánh dấu còn hiệu lực (chưa đối chiếu)" : "Cổng đánh dấu hết hiệu lực",
    nguon: "cổng Phòng CSQLHC",
    ngay_cap_nhat: null,
    kiem_tra_luc: null,
  };
}

function findDocumentByNumber(data, number) {
  if (!number) return null;
  const target = numberKey(number);
  return data.vanBan.find((doc) => numberKey(doc.so_ky_hieu) === target) || null;
}

export function searchProcedures(data, query, limit = 8) {
  return scoreAll(
    data.tthc,
    query,
    {
      titleOf: (t) => t.ten,
      textOf: (t) => [t.linh_vuc, t.co_quan_thuc_hien, t.doi_tuong, t.thanh_phan_ho_so, t.trinh_tu, (t.can_cu || []).join(" ")].join(" "),
    },
    limit,
  ).map((t) => ({
    id: t.id,
    ten: t.ten,
    linh_vuc: t.linh_vuc,
    co_quan_thuc_hien: t.co_quan_thuc_hien,
    thoi_han: t.thoi_han,
  }));
}

export function getProcedure(data, id) {
  const t = data.tthc.find((item) => item.id === id);
  if (!t) return null;
  return {
    id: t.id,
    ten: t.ten,
    linh_vuc: t.linh_vuc,
    co_quan_thuc_hien: t.co_quan_thuc_hien,
    doi_tuong: t.doi_tuong,
    thoi_han: t.thoi_han,
    cach_thuc: t.cach_thuc,
    thanh_phan_ho_so: t.thanh_phan_ho_so,
    trinh_tu: t.trinh_tu,
    ket_qua: t.ket_qua,
    le_phi: t.le_phi,
    yeu_cau: t.yeu_cau,
    mau_don: t.mau_don,
    can_cu: (t.can_cu || []).map((title) => {
      const doc = findDocumentByNumber(data, title.match(NUMBER_IN_TEXT)?.[0]);
      return {
        trich_dan: title,
        so_ky_hieu: doc ? doc.so_ky_hieu : null,
        tinh_trang: doc ? statusOf(doc) : null,
      };
    }),
  };
}

export function searchLegalDocuments(data, query, limit = 8) {
  return scoreAll(
    data.vanBan,
    query,
    {
      titleOf: (v) => [v.so_ky_hieu, v.trich_yeu].join(" "),
      textOf: (v) => [v.loai, v.linh_vuc, v.co_quan_ban_hanh].join(" "),
    },
    limit,
  ).map((v) => ({
    so_ky_hieu: v.so_ky_hieu,
    trich_yeu: v.trich_yeu || v.tieu_de || "",
    loai: v.loai,
    linh_vuc: v.linh_vuc,
    ngay_hieu_luc: v.ngay_hieu_luc || null,
    tinh_trang: statusOf(v),
  }));
}

export function getLegalDocument(data, soKyHieu) {
  const doc = findDocumentByNumber(data, soKyHieu);
  if (!doc) return null;
  return {
    so_ky_hieu: doc.so_ky_hieu,
    trich_yeu: doc.trich_yeu || doc.vbpl?.tieu_de || "",
    loai: doc.loai,
    linh_vuc: doc.linh_vuc,
    co_quan_ban_hanh: doc.co_quan_ban_hanh,
    ngay_ban_hanh: doc.ngay_ban_hanh || null,
    ngay_hieu_luc: doc.ngay_hieu_luc || null,
    tinh_trang: statusOf(doc),
    ghi_chu: doc.doi_chieu_thu_cong?.ghi_chu || doc.ghi_chu || null,
    luu_y: "Chỉ có thông tin tóm tắt và tình trạng. Muốn biết điều khoản cụ thể, dùng tìm trong toàn văn.",
  };
}

// ----- Ghi chú đọc hiểu (kien_thuc/tom_tat.json) -----

// Ghi chú theo số ký hiệu đã chuẩn hóa. Không có tệp thì trả về bản đồ rỗng.
export async function loadKnowledge() {
  try {
    const entries = await cachedFile("kien_thuc/tom_tat.json");
    const byNumber = new Map();
    for (const entry of entries) {
      const key = numberKey(entry.so_ky_hieu);
      if (!byNumber.has(key)) byNumber.set(key, []);
      byNumber.get(key).push(entry);
    }
    return byNumber;
  } catch {
    return new Map();
  }
}

// Thông tin đầy đủ của một văn bản: tình trạng, nguồn, ngày cập nhật và ghi chú đọc hiểu.
export function getLegalDocumentDetail(data, knowledge, soKyHieu) {
  const base = getLegalDocument(data, soKyHieu);
  const notes = knowledge.get(numberKey(soKyHieu)) || [];
  if (!base && notes.length === 0) return null;
  const doc = findDocumentByNumber(data, soKyHieu);
  return {
    ...(base || { so_ky_hieu: soKyHieu, luu_y: "Số ký hiệu này chưa có trong danh mục theo dõi." }),
    nguon_chinh_thuc: doc?.nguon_chinh_thuc || [],
    ngay_cap_nhat: doc?.ngay_cap_nhat || null,
    nguon_ngay_cap_nhat: doc?.nguon_ngay_cap_nhat || null,
    ghi_chu_doc_hieu: notes.map((note) => note.ghi_chu.slice(0, NOTE_CHARS)),
  };
}

// ----- Toàn văn (vbpl_text, nguon_text) -----

// Số ký hiệu: lấy trường đã có, hoặc từ tiêu đề khi trường trống (phần lớn mục vbpl không có trường này).
function soKyHieuCuaMuc(entry) {
  if (entry.so_ky_hieu && entry.so_ky_hieu !== "None") return entry.so_ky_hieu;
  return entry.tieu_de?.match(SO_TRONG_TIEU_DE)?.[0] ?? null;
}

// Danh mục toàn văn: mỗi mục có tệp .txt, nguồn và (nếu có) số ký hiệu.
async function textCatalog() {
  const items = [];
  try {
    const vbpl = await cachedFile("vbpl_text/index.json");
    for (const [slug, entry] of Object.entries(vbpl)) {
      if (!entry.tep) continue;
      const file = entry.tep.endsWith(".txt") ? entry.tep : `${entry.tep}.txt`;
      items.push({
        so_ky_hieu: soKyHieuCuaMuc(entry),
        ten: entry.tieu_de || slug,
        nguon: TEN_NGUON_TOAN_VAN["vbpl.vn"],
        url: entry.url || null,
        tinh_trang: entry.tinh_trang || null,
        tep: `vbpl_text/${file}`,
      });
    }
  } catch {
    // Chưa có toàn văn vbpl.vn: bỏ qua.
  }
  try {
    const nguon = await cachedFile("nguon_text/index.json");
    for (const entry of nguon) {
      if (!entry.tep) continue;
      items.push({
        so_ky_hieu: entry.so_ky_hieu || null,
        ten: entry.so_ky_hieu || "",
        nguon: TEN_NGUON_TOAN_VAN[entry.nguon] || entry.nguon,
        url: entry.url || null,
        tinh_trang: null,
        tep: `nguon_text/${entry.tep}`,
      });
    }
  } catch {
    // Chưa có toàn văn công báo: bỏ qua.
  }
  return items;
}

// Tách toàn văn thành đoạn, gắn số điều gần nhất phía trên mỗi đoạn (nếu có).
const paragraphCache = new Map();

function splitLong(text) {
  if (text.length <= PASSAGE_CHARS) return [text];
  const pieces = [];
  let current = "";
  for (const sentence of text.split(/(?<=[.;])\s+/)) {
    if ((current + " " + sentence).length > PASSAGE_CHARS && current) {
      pieces.push(current.trim());
      current = sentence;
    } else {
      current = current ? `${current} ${sentence}` : sentence;
    }
  }
  if (current.trim()) pieces.push(current.trim());
  return pieces;
}

async function paragraphsOf(tep) {
  const raw = await cachedFile(tep);
  const hit = paragraphCache.get(tep);
  if (hit && hit.raw === raw) return hit.paragraphs;

  const full = raw.replace(/\r/g, "");
  // Tiêu đề điều: đầu dòng, hoặc sau dấu kết câu (văn bản công báo thường nối tiêu đề vào cuối đoạn trước).
  // Chữ hoa sau số điều bắt buộc, nên các câu dẫn như "Điều 33 Luật Cư trú" không bị nhận nhầm.
  const headings = [...full.matchAll(/(?<=^|\n|[.;:]\s)[ \t]*Điều\s+(\d+[a-z]?)\.\s+(?=\p{Lu})/gmu)]
    .map((match) => ({ at: match.index + match[0].search(/Điều/), dieu: `Điều ${match[1]}` }));
  const dieuTai = (position) => {
    let found = null;
    for (const heading of headings) {
      if (heading.at > position) break;
      found = heading.dieu;
    }
    return found;
  };
  const paragraphs = [];
  let pointer = 0;
  for (const block of full.split(/\n\s*\n/)) {
    if (!block.trim()) continue;
    const start = full.indexOf(block, pointer);
    const end = start + block.length;
    pointer = end;
    // Cắt khối tại mọi tiêu đề điều nằm trong nó, để mỗi đoạn gắn đúng điều.
    const cuts = [start, ...headings.filter((h) => h.at > start && h.at < end).map((h) => h.at), end];
    for (let i = 0; i < cuts.length - 1; i += 1) {
      const text = full.slice(cuts[i], cuts[i + 1]).trim();
      if (!text) continue;
      const dieu = dieuTai(cuts[i]);
      for (const piece of splitLong(text)) {
        const norm = normalize(piece);
        paragraphs.push({ text: piece, norm, tokens: tokensOf(norm), dieu });
      }
    }
  }
  paragraphCache.set(tep, { raw, paragraphs });
  return paragraphs;
}

// Văn bản còn hiệu lực được ưu tiên; văn bản hết hiệu lực vẫn có thể hiện nhưng xếp sau.
function trongSoTinhTrang(tinhTrang) {
  if (!tinhTrang) return 1;
  if (tinhTrang.startsWith("Còn hiệu lực") || tinhTrang.startsWith("Chưa có hiệu lực")) return 1.5;
  if (tinhTrang.startsWith("Hết hiệu lực một phần")) return 1.2;
  if (tinhTrang.startsWith("Chưa đối chiếu")) return 1.2;
  if (tinhTrang.startsWith("Hết hiệu lực")) return 0.6;
  return 1;
}

// Cụm hai từ liền nhau trong câu hỏi (ví dụ "khai sinh"): đoạn có cả cụm được ưu tiên.
function bigrams(terms) {
  const phrases = [];
  for (let i = 0; i + 1 < terms.length; i += 1) phrases.push(`${terms[i]} ${terms[i + 1]}`);
  return [...new Set(phrases)];
}

// Tìm đoạn trong toàn văn theo từ khóa. Mỗi văn bản góp tối đa vài đoạn để kết quả đa dạng.
export async function timTrongToanVan(query, { soKyHieu = null, limit = MAX_PASSAGES } = {}) {
  const terms = queryTerms(query);
  if (terms.length === 0) return [];
  const unique = [...new Set(terms)];
  const phrases = bigrams(terms);
  const wanted = soKyHieu ? numberKey(soKyHieu) : null;
  const hits = [];
  for (const item of await textCatalog()) {
    if (wanted && numberKey(item.so_ky_hieu) !== wanted) continue;
    const paragraphs = await paragraphsOf(item.tep);
    const weight = trongSoTinhTrang(item.tinh_trang);
    paragraphs.forEach((para, index) => {
      let score = 0;
      let matched = 0;
      for (const term of unique) {
        if (para.tokens.has(term)) {
          score += 1 + Math.min(term.length, 12) / 12;
          matched += 1;
        }
      }
      if (score === 0) return;
      score += phrases.filter((phrase) => para.norm.includes(phrase)).length * 2;
      // Đoạn chứa đủ mọi từ khóa được ưu tiên hơn đoạn chỉ chứa một phần.
      const complete = matched === unique.length ? 2 : 1;
      hits.push({ item, para, score: score * weight * complete, index });
    });
  }
  hits.sort((a, b) => b.score - a.score || a.index - b.index);

  const perDoc = new Map();
  const chosen = [];
  for (const hit of hits) {
    const count = perDoc.get(hit.item.tep) || 0;
    if (count >= MAX_PASSAGES_PER_DOC) continue;
    perDoc.set(hit.item.tep, count + 1);
    chosen.push({
      so_ky_hieu: hit.item.so_ky_hieu,
      ten: hit.item.ten,
      nguon: hit.item.nguon,
      url: hit.item.url,
      tinh_trang: hit.item.tinh_trang,
      dieu: hit.para.dieu,
      trich: hit.para.text.slice(0, PASSAGE_CHARS),
    });
    if (chosen.length >= limit) break;
  }
  return chosen;
}
