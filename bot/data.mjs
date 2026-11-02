// Đọc dữ liệu đã xuất (docs/data) và tìm kiếm, tính trạng thái hiệu lực cho bot.
import { readFile } from "node:fs/promises";
import path from "node:path";

const DATA_DIR = process.env.TCHC_DATA_DIR || "C:\\tchc\\site\\data";
const NUMBER_IN_TEXT = /\d{1,4}\/\d{4}\/[\w\-]+/;

// Từ không mang nghĩa tìm kiếm, bỏ qua khi chấm điểm.
const STOPWORDS = new Set([
  "toi", "can", "cho", "nguoi", "lam", "the", "nao", "gi", "bao", "nhieu", "khi",
  "thi", "va", "la", "co", "duoc", "phai", "cua", "cac", "mot", "trong", "tai",
  "ve", "voi", "hoi", "thu", "tuc", "xin", "muon", "biet", "nhung", "lau", "ban",
  "giay", "to", "can", "gi", "lam", "sao",
]);

async function readJson(name) {
  return JSON.parse(await readFile(path.join(DATA_DIR, name), "utf8"));
}

export async function loadAll() {
  const [tthc, vanBan, meta] = await Promise.all(
    ["tthc.json", "van_ban.json", "meta.json"].map(readJson),
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

// Tình trạng hiệu lực: ưu tiên vbpl.vn, rồi đối chiếu thủ công, rồi cổng.
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
  return {
    tinh_trang: doc.hieu_luc_theo_cong ? "Cổng đánh dấu còn hiệu lực (chưa đối chiếu)" : "Cổng đánh dấu hết hiệu lực",
    nguon: "cổng Phòng CSQLHC",
    ngay_cap_nhat: null,
    kiem_tra_luc: null,
  };
}

function findDocumentByNumber(data, number) {
  if (!number) return null;
  const target = normalize(number);
  return data.vanBan.find((doc) => normalize(doc.so_ky_hieu) === target) || null;
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
    luu_y: "Chỉ có thông tin tóm tắt và tình trạng. Chưa có toàn văn điều khoản trong dữ liệu.",
  };
}
