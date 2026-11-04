"use strict";

// Thông tin chính của một thủ tục, hiển thị ở cột tóm tắt.
const FACTS = [
  ["linh_vuc", "Lĩnh vực"],
  ["co_quan_thuc_hien", "Cơ quan thực hiện"],
  ["thoi_han", "Thời hạn giải quyết"],
  ["cach_thuc", "Cách thức thực hiện"],
  ["doi_tuong", "Đối tượng"],
];

// Nội dung dài, giữ nguyên xuống dòng, hiển thị trong bài đọc.
const TTHC_BODY = [
  ["thanh_phan_ho_so", "Thành phần hồ sơ"],
  ["trinh_tu", "Trình tự thực hiện"],
  ["ket_qua", "Kết quả"],
];

const CHANGE_LABELS = {
  moi: "Mới",
  thay_doi: "Thay đổi",
  khong_con_tren_cong: "Không còn trên cổng",
  quay_lai: "Xuất hiện lại trên cổng",
};

// Tên trường trong nhật ký thay đổi của vbpl.vn.
const FIELD_LABELS = {
  tinh_trang: "Tình trạng",
  ngay_hieu_luc: "Ngày hiệu lực",
  ngay_cap_nhat: "Ngày cập nhật",
  lich_su: "Lịch sử sửa đổi",
};

// Việc thường gặp, bấm để tìm nhanh.
const COMMON_TASKS = ["tạm trú", "thẻ căn cước", "hộ khẩu", "lệ phí", "con dấu", "vũ khí"];

// Lối vào nhanh ở trang chủ: mỗi lối là một việc cụ thể cán bộ hay cần.
const QUICK_LINKS = [
  { href: "#hoidap", ten: "Hỏi đáp theo tình huống", mo_ta: "Mô tả việc công dân cần làm. Bot nêu hồ sơ, nơi nộp và luồng duyệt." },
  { href: "#vanban", ten: "Tra cứu văn bản", mo_ta: "Nhập số ký hiệu để xem tình trạng hiệu lực và ghi chú đọc hiểu." },
  { href: "#capnhat", ten: "Thay đổi mới nhất", mo_ta: "Văn bản và thủ tục vừa được cập nhật, kèm ngày và nguồn." },
];

const MIN_PASSWORD_LENGTH = 6;

const state = {
  user: null,
  viewKey: null,
  data: null,
  latestChange: null,
  changes: new Map(),
  chat: [],
  chatBusy: false,
  filters: { tthc: { q: "", lv: "" }, vanban: { q: "", lv: "" } },
  tthcById: new Map(),
  vanBanBySo: new Map(),
};

const app = document.getElementById("app");

// CRC-32 khớp với zlib.crc32 mà crawler dùng làm record_id cho thay đổi của vbpl.vn.
const CRC_TABLE = Array.from({ length: 256 }, (_, n) => {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});

function crc32(text) {
  let crc = 0xffffffff;
  for (const byte of new TextEncoder().encode(text)) crc = CRC_TABLE[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

// Tạo phần tử bằng DOM API, không dùng innerHTML, để nội dung từ cổng không chèn được mã.
function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key.startsWith("on")) {
      node.addEventListener(key.slice(2), value);
    } else if (value === true) {
      node.setAttribute(key, "");
    } else if (value !== false && value !== null && value !== undefined) {
      node.setAttribute(key, value);
    }
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function norm(text) {
  return (text || "")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/đ/g, "d")
    .replace(/Đ/g, "d")
    .toLowerCase();
}

function fmtDate(iso) {
  if (!iso) return "";
  const [y, m, d] = iso.split("-");
  return d && m && y ? `${d}/${m}/${y}` : iso;
}

// Nhãn ngắn theo nguồn của ngày cập nhật, để người đọc biết ngày đó là gì.
const NHAN_NGAY_CAP_NHAT = {
  "vbpl.vn cập nhật trang văn bản": (ngay) => `vbpl.vn cập nhật ngày ${ngay}`,
  "đối chiếu thủ công": (ngay) => `Đối chiếu ngày ${ngay}`,
  "ngày ban hành trên công báo": (ngay) => `Ban hành ngày ${ngay}`,
  "hệ thống phát hiện thay đổi trên cổng": (ngay) => `Cập nhật mới ngày ${ngay}`,
  "ghi nhận lần đầu, cổng không ghi ngày cập nhật": (ngay) => `Ghi nhận ngày ${ngay}`,
};

// Ngày cập nhật mới nhất, ghi rõ là ngày nào và ngày đó là ngày gì.
function updateLabel(item) {
  if (!item.ngay_cap_nhat) return "Chưa có ngày cập nhật";
  const nhan = NHAN_NGAY_CAP_NHAT[item.nguon_ngay_cap_nhat] || ((ngay) => `Cập nhật ngày ${ngay}`);
  return nhan(fmtDate(item.ngay_cap_nhat));
}

function updateDetail(item) {
  if (!item.ngay_cap_nhat) return "Chưa có ngày cập nhật";
  return `${updateLabel(item)} · nguồn: ${item.nguon_ngay_cap_nhat || "không ghi"}`;
}

// Ghi nhận lần đầu chỉ là ngày hệ thống thấy thủ tục lần đầu, không phải ngày cổng cập nhật.
const NGUON_GHI_NHAN_LAN_DAU = "ghi nhận lần đầu, cổng không ghi ngày cập nhật";
const SO_NGAY_NHAN_NEW = 5;

// Có cập nhật thật từ cổng hoặc nguồn chính thức (không tính ngày ghi nhận lần đầu).
function isRealUpdate(item) {
  return Boolean(item.ngay_cap_nhat) && item.nguon_ngay_cap_nhat !== NGUON_GHI_NHAN_LAN_DAU;
}

// Ngày của dữ liệu (lần kiểm tra gần nhất), để tính số ngày từ cập nhật; thiếu thì dùng ngày hôm nay.
function ngayCuaDuLieu(meta) {
  if (meta && meta.cap_nhat_luc) return meta.cap_nhat_luc.slice(0, 10);
  return new Date().toISOString().slice(0, 10);
}

function soNgayGiua(isoTruoc, isoSau) {
  const [y1, m1, d1] = isoTruoc.split("-").map(Number);
  const [y2, m2, d2] = isoSau.split("-").map(Number);
  return Math.round((Date.UTC(y2, m2 - 1, d2) - Date.UTC(y1, m1 - 1, d1)) / 86400000);
}

// NEW: có cập nhật thật trong vài ngày gần nhất so với ngày của dữ liệu.
function laThuTucMoi(item, today) {
  if (!isRealUpdate(item)) return false;
  const songay = soNgayGiua(item.ngay_cap_nhat, today);
  return songay >= 0 && songay <= SO_NGAY_NHAN_NEW;
}

// Thay đổi mới nhất lên trên; cùng ngày thì xếp theo tên. Thiếu ngày thì xuống cuối.
function sapXepMoiNhatLenTren(items) {
  return [...items].sort(
    (a, b) =>
      (b.ngay_cap_nhat || "").localeCompare(a.ngay_cap_nhat || "") ||
      (a.ten || "").localeCompare(b.ten || "", "vi")
  );
}

function fmtDateTime(iso) {
  if (!iso) return "chưa có";
  const date = new Date(iso);
  return isNaN(date) ? iso : date.toLocaleString("vi-VN", { hour12: false });
}

function shorten(text, max = 140) {
  const flat = String(text ?? "").replace(/\s+/g, " ").trim();
  return flat.length > max ? flat.slice(0, max - 1) + "…" : flat;
}

function uniqueSorted(values) {
  return [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b, "vi"));
}

function matchesQuery(haystack, query) {
  const terms = norm(query).split(/\s+/).filter(Boolean);
  return terms.every((term) => haystack.includes(term));
}

function decode(text) {
  try {
    return decodeURIComponent(text);
  } catch {
    return text;
  }
}

// Số ký hiệu trong tên căn cứ, ví dụ "Nghị định số 31/2014/NĐ-CP, ngày ..." -> "31/2014/NĐ-CP".
function citedSoKyHieu(title) {
  const match = String(title).match(/\d{1,4}\/\d{4}\/[^\s,;)]+/);
  return match ? match[0] : null;
}

function changesFor(kind, recordId) {
  return state.changes.get(`${kind}:${recordId}`) || [];
}

function vanBanChanges(v) {
  return v.vbpl ? changesFor("vbpl", crc32(v.vbpl.url)) : [];
}

// Tình trạng hiện hành: ưu tiên vbpl.vn, rồi đối chiếu thủ công, rồi cổng.
function vanBanStatus(v) {
  const vb = v.vbpl;
  if (vb && vb.tinh_trang) {
    const label = vb.tinh_trang;
    const tone = label.startsWith("Còn") ? "ok" : label.startsWith("Chưa") ? "muted" : "warn";
    return { text: label, tone };
  }
  if (v.doi_chieu_thu_cong) {
    const outdated = v.doi_chieu_thu_cong.tinh_trang === "het_hieu_luc";
    return { text: outdated ? "Hết hiệu lực" : "Còn hiệu lực", tone: outdated ? "warn" : "ok" };
  }
  // Văn bản từ công báo chính thức, chưa đối chiếu với vbpl.vn: không kết luận còn hay hết hiệu lực.
  if (v.nguon === "chinh_thuc") return { text: "Chưa đối chiếu với vbpl.vn", tone: "muted" };
  if (v.nguon === "thu_cong") return { text: "Bổ sung thủ công", tone: "ok" };
  return v.hieu_luc_theo_cong
    ? { text: "Cổng: còn hiệu lực, chưa đối chiếu", tone: "muted" }
    : { text: "Cổng: hết hiệu lực", tone: "warn" };
}

function documentForCitation(title) {
  const so = citedSoKyHieu(title);
  return so ? state.vanBanBySo.get(so) : undefined;
}

function citationStatus(title) {
  const doc = documentForCitation(title);
  return doc ? vanBanStatus(doc) : { text: "Chưa đối chiếu được", tone: "muted" };
}

// Chỉ đánh dấu "không dùng" khi vbpl.vn ghi hết hiệu lực toàn bộ, không phải một phần.
function isFullyExpired(title) {
  const doc = documentForCitation(title);
  if (!doc) return false;
  if (doc.vbpl && doc.vbpl.tinh_trang) return doc.vbpl.tinh_trang === "Hết hiệu lực";
  return Boolean(doc.doi_chieu_thu_cong && doc.doi_chieu_thu_cong.tinh_trang === "het_hieu_luc");
}

function statusChip(status) {
  return el("span", { class: `status status--${status.tone}` }, status.text);
}

function haystackTthc(t) {
  return norm(
    [
      t.ten,
      t.linh_vuc,
      t.co_quan_thuc_hien,
      t.doi_tuong,
      t.thanh_phan_ho_so,
      t.trinh_tu,
      t.can_cu.join(" "),
      t.le_phi.map((x) => `${x.ten} ${x.muc}`).join(" "),
    ].join(" ")
  );
}

function haystackVanBan(v) {
  return norm([v.so_ky_hieu, v.trich_yeu, v.loai, v.linh_vuc, v.co_quan_ban_hanh].join(" "));
}

// Các mục nhỏ đặt cạnh nhau, cách bằng khoảng trống, không dùng dấu ngăn.
function inlineParts(parts) {
  return parts.filter(Boolean).map((text) => el("span", {}, text));
}

function route() {
  const [head, ...rest] = location.hash.replace(/^#\/?/, "").split("/");
  const id = rest.length ? decode(rest.join("/")) : null;
  if (head === "vanban") return { tab: "vanban", id };
  if (head === "capnhat") return { tab: "capnhat", id: null };
  if (head === "hoidap") return { tab: "hoidap", id: null };
  if (head === "taikhoan") return { tab: "taikhoan", id: null };
  return { tab: "tthc", id: head === "tthc" ? id : null };
}

function render() {
  if (!state.data) return;
  const current = route();
  document.querySelectorAll(".tabs a").forEach((link) => {
    if (link.dataset.tab === current.tab) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });

  // Mật khẩu tạm: chỉ cho vào trang Tài khoản cho tới khi đổi xong.
  if (state.user.phai_doi_mat_khau && current.tab !== "taikhoan") {
    location.hash = "#taikhoan";
    return;
  }
  if (state.user.cong_khai && current.tab === "taikhoan") {
    location.hash = "#tthc";
    return;
  }
  if (current.tab === "taikhoan") return renderAccount();
  if (current.tab === "capnhat") return renderUpdates();
  if (current.tab === "hoidap") return renderChat();
  if (current.tab === "vanban") return current.id ? renderVanBanDetail(current.id) : renderVanBanList();
  return current.id ? renderTthcDetail(current.id) : renderTthcList();
}

// Dòng thông báo đầu trang: lần kiểm tra và thay đổi gần nhất.
function updateBanner() {
  const { meta } = state.data;
  const latest = state.latestChange;
  const lead = latest
    ? `Có ${latest.count} thay đổi được ghi nhận lúc ${fmtDateTime(latest.run_at)}. `
    : "Chưa có thay đổi mới. ";
  return el(
    "p",
    { class: "notice notice--info" },
    lead,
    `Kiểm tra dữ liệu lúc ${fmtDateTime(meta.cap_nhat_luc)}. `,
    el("a", { href: "#capnhat" }, "Xem lịch sử cập nhật")
  );
}

// Thứ tự các tab để đoán chiều chuyển trang: đi tới trượt từ phải, quay lại trượt từ trái.
const TAB_ORDER = { tthc: 0, vanban: 1, hoidap: 2, capnhat: 3, taikhoan: 4 };

function viewRank(key) {
  const tab = key.split("/")[0];
  return TAB_ORDER[tab] * 2 + (key.length > tab.length + 1 ? 1 : 0);
}

// Lớp hiệu ứng cho khung nội dung. Lần mở đầu chỉ hiện dần; cùng một trang thì không chạy lại.
function viewMotion(key) {
  if (state.viewKey === null) return "view--fade";
  if (state.viewKey === key) return "";
  return viewRank(key) > viewRank(state.viewKey) ? "view--forward" : "view--back";
}

function setView(...nodes) {
  const current = route();
  const key = `${current.tab}/${current.id ?? ""}`;
  const banner = !["capnhat", "taikhoan"].includes(current.tab) ? updateBanner() : null;
  const motion = viewMotion(key);
  state.viewKey = key;
  app.replaceChildren(el("div", { class: `view ${motion}` }, banner, nodes));
}

function factsList(pairs) {
  return el(
    "dl",
    { class: "facts" },
    pairs.map(([label, value]) => el("div", {}, el("dt", {}, label), el("dd", {}, value || "Chưa có")))
  );
}

function emptyState(message, onReset) {
  return el(
    "div",
    { class: "empty" },
    el("p", {}, message),
    el("button", { type: "button", class: "btn btn--ghost", onclick: onReset }, "Xóa bộ lọc")
  );
}

function listSection(title, items) {
  const filtered = items.filter(Boolean);
  if (!filtered.length) return null;
  return el(
    "section",
    { class: "section" },
    el("h2", {}, title),
    el("ul", { class: "bullets" }, filtered.map((item) => el("li", {}, item)))
  );
}

function feeItem(fee) {
  return el(
    "li",
    {},
    fee.ten || fee.muc,
    fee.muc && fee.ten ? el("span", { class: "fine" }, fee.muc) : null,
    fee.van_ban ? el("span", { class: "fine" }, fee.van_ban) : null
  );
}

// ----- Thủ tục -----

// Bắt đầu nhanh: ẩn khi người dùng đang lọc, để kết quả hiện lên ngay.
function quickStart(filters) {
  return el(
    "section",
    { class: "quick", id: "quick-start", "aria-labelledby": "quick-title", hidden: Boolean(filters.q || filters.lv) },
    el("h2", { class: "quick__title", id: "quick-title" }, "Bắt đầu nhanh"),
    el(
      "div",
      { class: "quick__grid" },
      QUICK_LINKS.map((item) =>
        el(
          "a",
          { class: "quick__card", href: item.href },
          el("span", { class: "quick__name" }, item.ten),
          el("span", { class: "quick__text" }, item.mo_ta)
        )
      )
    )
  );
}

function renderTthcList() {
  const filters = state.filters.tthc;
  const input = el("input", {
    class: "search",
    type: "search",
    id: "tthc-q",
    value: filters.q,
    placeholder: "Ví dụ: đăng ký tạm trú, cấp lại thẻ căn cước",
    "aria-label": "Tìm thủ tục",
    oninput: (event) => {
      filters.q = event.target.value;
      updateTthcResults();
    },
  });
  const select = el(
    "select",
    {
      class: "select",
      "aria-label": "Lọc theo lĩnh vực",
      onchange: (event) => {
        filters.lv = event.target.value;
        updateTthcResults();
      },
    },
    el("option", { value: "" }, "Mọi lĩnh vực"),
    uniqueSorted(state.data.tthc.map((t) => t.linh_vuc)).map((lv) => el("option", { value: lv }, lv))
  );
  select.value = filters.lv;

  setView(
    el(
      "section",
      { class: "hero" },
      el("h1", {}, "Bộ Đẹp cần mần rì today?"),
      el("p", { class: "lede" }, "Tìm thủ tục để xem hồ sơ, trình tự, thời hạn, lệ phí và căn cứ pháp lý đang có hiệu lực."),
      el("div", { class: "search-row" }, input, select),
      el(
        "div",
        { class: "chips", role: "group", "aria-label": "Việc thường gặp" },
        COMMON_TASKS.map((task) =>
          el(
            "button",
            {
              type: "button",
              class: "chip-btn",
              onclick: () => {
                filters.q = task;
                input.value = task;
                updateTthcResults();
              },
            },
            task
          )
        )
      )
    ),
    quickStart(filters),
    el("p", { class: "count", id: "results-count", "aria-live": "polite" }),
    el("div", { class: "rows", id: "results" })
  );
  updateTthcResults();
}

function updateTthcResults() {
  const { q, lv } = state.filters.tthc;
  const today = ngayCuaDuLieu(state.data.meta);
  const matched = sapXepMoiNhatLenTren(
    state.data.tthc.filter((t) => (!lv || t.linh_vuc === lv) && (!q || matchesQuery(haystackTthc(t), q)))
  );
  document.getElementById("results-count").textContent = `${matched.length} thủ tục`;
  document.getElementById("quick-start").hidden = Boolean(q || lv);
  const results = document.getElementById("results");

  if (!matched.length) {
    results.replaceChildren(
      emptyState("Không có thủ tục khớp. Thử từ khóa ngắn hơn, ví dụ \"tạm trú\".", () => {
        state.filters.tthc = { q: "", lv: "" };
        renderTthcList();
      })
    );
    return;
  }

  results.replaceChildren(
    ...matched.map((t) =>
      el(
        "a",
        { class: "row", href: `#tthc/${t.id}` },
        el(
          "span",
          { class: "row__main" },
          el(
            "span",
            { class: "row__title" },
            t.ten,
            laThuTucMoi(t, today) ? el("span", { class: "row__new" }, "NEW") : null
          ),
          el("span", { class: "row__sub" }, inlineParts([t.linh_vuc, t.co_quan_thuc_hien]))
        ),
        el(
          "span",
          { class: "row__meta" },
          el("span", {}, t.thoi_han ? `Thời hạn: ${shorten(t.thoi_han, 80)}` : "Chưa có thời hạn"),
          el("span", { class: "row__update" }, updateLabel(t))
        )
      )
    )
  );
}

function renderTthcDetail(id) {
  const t = state.tthcById.get(String(id));
  if (!t) return renderNotFound("#tthc", "Tất cả thủ tục");

  const incomplete = !t.thanh_phan_ho_so && !t.trinh_tu;
  const body = TTHC_BODY.filter(([key]) => t[key]).map(([key, title]) =>
    el("section", { class: "section" }, el("h2", {}, title), el("div", { class: "prewrap" }, t[key]))
  );
  const fees = t.le_phi.length
    ? el("section", { class: "section" }, el("h2", {}, "Lệ phí"), el("ul", { class: "bullets" }, t.le_phi.map(feeItem)))
    : null;

  const article = el(
    "article",
    { class: "doc" },
    el("p", { class: "crumb" }, el("a", { href: "#tthc" }, "Tất cả thủ tục")),
    el("h1", {}, t.ten),
    t.nguon === "cong_dvc_quoc_gia"
      ? el("p", { class: "fine" }, "Nguồn: ", el("a", { href: t.url, target: "_blank", rel: "noopener" }, t.nguon_ten || "Cổng Dịch vụ công Quốc gia"))
      : null,
    incomplete
      ? el("p", { class: "notice" }, "Cổng chưa có đủ hồ sơ và trình tự cho thủ tục này. Liên hệ bộ phận tiếp nhận để biết chi tiết.")
      : null,
    body,
    fees,
    listSection("Yêu cầu", t.yeu_cau.map((item) => item.NOI_DUNG)),
    listSection("Mẫu đơn", t.mau_don.map((item) => item.TEN_MAU_DON)),
    changesSection(changesFor("tthc", t.id))
  );

  const copyButton = el("button", { type: "button", class: "btn btn--seal" }, "Sao chép nội dung");
  copyButton.addEventListener("click", () => copyWithFeedback(copyButton, tthcToText(t)));

  const aside = el(
    "aside",
    { class: "summary", "aria-label": "Tóm tắt thủ tục" },
    el("h2", {}, "Tóm tắt"),
    factsList([...FACTS.map(([key, label]) => [label, t[key]]), ["Ngày cập nhật", updateDetail(t)]]),
    t.can_cu.length ? el("h3", {}, "Căn cứ pháp lý") : null,
    t.can_cu.length ? el("ul", { class: "citations" }, t.can_cu.map(citationItem)) : null,
    el(
      "div",
      { class: "actions" },
      copyButton,
      el("button", { type: "button", class: "btn btn--ghost", onclick: () => window.print() }, "In hoặc lưu PDF")
    )
  );

  setView(el("div", { class: "doc-layout" }, article, aside));
}

function citationItem(title) {
  return el(
    "li",
    {},
    el("span", {}, title),
    statusChip(citationStatus(title)),
    isFullyExpired(title) ? el("span", { class: "fine" }, "Không dùng làm căn cứ hiện hành.") : null
  );
}

function tthcToText(t) {
  const lines = [t.ten, `Cơ quan thực hiện: ${t.co_quan_thuc_hien}`];
  for (const [key, title] of TTHC_BODY) {
    if (t[key]) lines.push("", `${title}:`, t[key]);
  }
  if (t.le_phi.length) {
    lines.push("", "Lệ phí:", ...t.le_phi.map((fee) => `- ${[fee.muc, fee.ten].filter(Boolean).join(" ")}`));
  }
  if (t.can_cu.length) lines.push("", "Căn cứ pháp lý:", ...t.can_cu.map((title) => `- ${title}`));
  return lines.join("\n");
}

// Thông báo kết quả ngay trên nút vừa bấm, không dùng hộp thoại.
async function copyWithFeedback(button, text) {
  const original = button.textContent;
  try {
    await navigator.clipboard.writeText(text);
    button.textContent = "Đã sao chép";
  } catch {
    button.textContent = "Chưa sao chép được";
  }
  setTimeout(() => (button.textContent = original), 2000);
}

// ----- Văn bản -----

function renderVanBanList() {
  const filters = state.filters.vanban;
  const input = el("input", {
    class: "search",
    type: "search",
    id: "vb-q",
    value: filters.q,
    placeholder: "Số ký hiệu hoặc trích yếu, ví dụ: 68/2020, cư trú",
    "aria-label": "Tìm văn bản",
    oninput: (event) => {
      filters.q = event.target.value;
      updateVanBanResults();
    },
  });
  const select = el(
    "select",
    {
      class: "select",
      "aria-label": "Lọc theo lĩnh vực",
      onchange: (event) => {
        filters.lv = event.target.value;
        updateVanBanResults();
      },
    },
    el("option", { value: "" }, "Mọi lĩnh vực"),
    uniqueSorted(state.data.vanBan.map((v) => v.linh_vuc)).map((lv) => el("option", { value: lv }, lv))
  );
  select.value = filters.lv;

  setView(
    el(
      "section",
      { class: "hero" },
      el("h1", {}, "Văn bản pháp luật"),
      el(
        "p",
        { class: "lede" },
        "Tình trạng hiệu lực lấy từ vbpl.vn khi có. Thiếu ngày hiệu lực trên trang không có nghĩa là hết hiệu lực."
      ),
      el("div", { class: "search-row" }, input, select)
    ),
    el("p", { class: "count", id: "results-count", "aria-live": "polite" }),
    el("div", { class: "rows", id: "results" })
  );
  updateVanBanResults();
}

function updateVanBanResults() {
  const { q, lv } = state.filters.vanban;
  const matched = state.data.vanBan.filter(
    (v) => (!lv || v.linh_vuc === lv) && (!q || matchesQuery(haystackVanBan(v), q))
  );
  document.getElementById("results-count").textContent = `${matched.length} văn bản`;
  const results = document.getElementById("results");

  if (!matched.length) {
    results.replaceChildren(
      emptyState("Không có văn bản nào khớp. Thử số ký hiệu hoặc từ khóa khác.", () => {
        state.filters.vanban = { q: "", lv: "" };
        renderVanBanList();
      })
    );
    return;
  }

  results.replaceChildren(
    ...matched.map((v) =>
      el(
        "a",
        { class: "row", href: `#vanban/${encodeURIComponent(v.so_ky_hieu)}` },
        el(
          "span",
          { class: "row__main" },
          el("span", { class: "row__title" }, shorten(v.trich_yeu || v.so_ky_hieu, 180)),
          el("span", { class: "row__sub" }, inlineParts([v.so_ky_hieu, v.loai, v.co_quan_ban_hanh]))
        ),
        el(
          "span",
          { class: "row__meta" },
          statusChip(vanBanStatus(v)),
          el("span", { class: "row__update" }, updateLabel(v))
        )
      )
    )
  );
}

// Link nguồn; nhiều nguồn thì đánh số.
function sourceLinks(urls, label) {
  return urls.map((url, index) => [
    " ",
    el("a", { href: url, target: "_blank", rel: "noopener" }, urls.length > 1 ? `${label} ${index + 1}` : label),
  ]);
}

function vanBanNotes(v) {
  const notes = [];
  if (v.nguon_chinh_thuc && v.nguon_chinh_thuc.length) {
    notes.push(
      el(
        "p",
        { class: "notice notice--info" },
        "Công bố trên: ",
        ...v.nguon_chinh_thuc.flatMap((source, index) => [
          index ? "; " : "",
          el("a", { href: source.url, target: "_blank", rel: "noopener" }, source.ten),
        ])
      )
    );
  }
  if (v.vbpl && v.vbpl.tinh_trang) {
    if (!v.vbpl.ngay_hieu_luc) {
      notes.push(
        el(
          "p",
          { class: "notice" },
          "vbpl.vn chưa ghi ngày hiệu lực. Thiếu ngày trên trang không có nghĩa là hết hiệu lực. Đọc lịch sử sửa đổi để biết nội dung nào đã thay đổi."
        )
      );
    }
    notes.push(
      el(
        "p",
        { class: "notice notice--info" },
        `Tình trạng theo vbpl.vn, kiểm tra lúc ${fmtDateTime(v.vbpl.kiem_tra_luc)}. `,
        el("a", { href: v.vbpl.url, target: "_blank", rel: "noopener" }, "Mở trên vbpl.vn")
      )
    );
  }
  if (v.doi_chieu_thu_cong) {
    notes.push(
      el(
        "p",
        { class: "notice" },
        v.doi_chieu_thu_cong.ghi_chu,
        ` Đối chiếu ngày ${fmtDate(v.doi_chieu_thu_cong.ngay_doi_chieu)}.`,
        ...sourceLinks(v.doi_chieu_thu_cong.nguon, "Nguồn")
      )
    );
  } else if (v.nguon === "thu_cong") {
    notes.push(
      el(
        "p",
        { class: "notice notice--info" },
        v.ghi_chu || "Văn bản bổ sung thủ công.",
        ...sourceLinks(v.tham_khao || [], "Nguồn tham khảo")
      )
    );
  } else if (v.hieu_luc_theo_cong && !(v.vbpl && v.vbpl.tinh_trang)) {
    notes.push(el("p", { class: "notice notice--info" }, "Cổng đánh dấu còn hiệu lực, chưa đối chiếu với nguồn khác."));
  }
  return notes;
}

function renderVanBanDetail(soKyHieu) {
  const v = state.vanBanBySo.get(soKyHieu);
  if (!v) return renderNotFound("#vanban", "Tất cả văn bản");

  const effective = v.vbpl?.ngay_hieu_luc || v.ngay_hieu_luc;
  const history =
    v.vbpl && v.vbpl.lich_su && v.vbpl.lich_su.length
      ? el(
          "section",
          { class: "section" },
          el("h2", {}, "Lịch sử sửa đổi, bổ sung"),
          el(
            "ol",
            { class: "timeline" },
            v.vbpl.lich_su.map((item) =>
              el(
                "li",
                {},
                el("time", { datetime: item.ngay }, fmtDate(item.ngay)),
                el("span", { class: "tl__label" }, item.trang_thai),
                el("span", {}, item.van_ban_nguon)
              )
            )
          )
        )
      : null;

  const article = el(
    "article",
    { class: "doc" },
    el("p", { class: "crumb" }, el("a", { href: "#vanban" }, "Tất cả văn bản")),
    el("h1", {}, v.trich_yeu || v.so_ky_hieu),
    vanBanNotes(v),
    history,
    changesSection(vanBanChanges(v))
  );

  const aside = el(
    "aside",
    { class: "summary", "aria-label": "Tóm tắt văn bản" },
    el("h2", {}, "Tình trạng"),
    el("p", { class: "status-line" }, statusChip(vanBanStatus(v))),
    factsList([
      ["Số ký hiệu", v.so_ky_hieu],
      ["Loại văn bản", v.loai],
      ["Cơ quan ban hành", v.co_quan_ban_hanh],
      ["Người ký", v.nguoi_ky],
      ["Ngày ban hành", fmtDate(v.ngay_ban_hanh)],
      ["Ngày có hiệu lực", effective ? fmtDate(effective) : "Chưa có trên trang"],
      ["Lĩnh vực", v.linh_vuc],
      ["Ngày cập nhật", updateDetail(v)],
    ])
  );

  setView(el("div", { class: "doc-layout" }, article, aside));
}

// ----- Hỏi đáp -----

function renderChat() {
  const thread = el(
    "div",
    { class: "thread", role: "log", "aria-live": "polite", "aria-busy": state.chatBusy ? "true" : "false" },
    state.chat.length
      ? state.chat.map(chatMessage)
      : el(
          "p",
          { class: "empty" },
          "Hỏi bằng việc cần làm, ví dụ: đăng ký tạm trú cần giấy tờ gì? Bot trả lời theo dữ liệu thủ tục và văn bản, có ghi nguồn."
        )
  );
  const input = el("textarea", {
    id: "chat-input",
    rows: "3",
    placeholder: "Nhập câu hỏi…",
    "aria-label": "Câu hỏi",
    onkeydown: (event) => {
      if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) event.currentTarget.form.requestSubmit();
    },
  });
  const send = el(
    "button",
    { type: "submit", class: "btn btn--seal", disabled: state.chatBusy ? "disabled" : null },
    state.chatBusy ? "Đang tra cứu…" : "Gửi"
  );
  const form = el(
    "form",
    {
      class: "composer",
      onsubmit: (event) => {
        event.preventDefault();
        sendQuestion(input.value);
      },
    },
    input,
    el(
      "div",
      { class: "composer__actions" },
      el("p", { class: "fine" }, "Ctrl + Enter để gửi. Không nhập số CCCD, số điện thoại hay địa chỉ của công dân."),
      send
    )
  );

  setView(el("section", { class: "chat" }, el("h1", {}, "Hỏi đáp thủ tục"), thread, form));
  thread.scrollTop = thread.scrollHeight;
}

function chatMessage(message) {
  // Tin mới trượt lên một lần; tin cũ không chạy lại khi vẽ lại khung hỏi đáp.
  const enter = message.shown ? "" : " msg--enter";
  message.shown = true;
  if (message.role === "user") return el("div", { class: `msg msg--user${enter}` }, message.text);
  const base = message.error ? "msg msg--bot msg--error" : "msg msg--bot";
  return el(
    "div",
    { class: `${base}${enter}` },
    formatAnswer(message.text),
    message.sources && message.sources.length
      ? el("p", { class: "msg__src" }, `Nguồn: ${message.sources.map((source) => source.ten).join("; ")}`)
      : null
  );
}

// Đoạn văn và danh sách gạch đầu dòng trong câu trả lời của bot.
function formatAnswer(text) {
  const nodes = [];
  let list = null;
  for (const raw of String(text || "").split("\n")) {
    const line = raw.trim();
    if (!line) {
      list = null;
      continue;
    }
    if (line.startsWith("- ")) {
      if (!list) {
        list = el("ul", {});
        nodes.push(list);
      }
      list.append(el("li", {}, renderInline(line.slice(2))));
    } else {
      list = null;
      nodes.push(el("p", {}, renderInline(line)));
    }
  }
  return nodes;
}

// Chữ đậm **...** trong câu trả lời.
function renderInline(line) {
  return line
    .split(/(\*\*[^*]+\*\*)/)
    .filter(Boolean)
    .map((part) => (part.startsWith("**") && part.endsWith("**") ? el("strong", {}, part.slice(2, -2)) : part));
}

async function sendQuestion(text) {
  const question = text.trim();
  if (!question || state.chatBusy) return;

  const history = state.chat
    .filter((message) => !message.pending)
    .slice(-8)
    .map((message) => ({ role: message.role === "user" ? "user" : "assistant", content: message.text }));

  state.chatBusy = true;
  state.chat.push({ role: "user", text: question });
  state.chat.push({ role: "bot", text: "Đang tra cứu…", pending: true });
  renderChat();

  try {
    const response = await fetch("api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: question, history }),
    });
    const payload = await response.json().catch(() => ({}));
    if (response.status === 401) {
      location.replace("login.html");
      return;
    }
    if (response.status === 403 && payload.phai_doi_mat_khau) {
      state.chat.pop();
      state.user.phai_doi_mat_khau = true;
      location.hash = "#taikhoan";
      return;
    }
    if (response.status === 404) throw new Error("trang này chưa kết nối bot");
    if (!response.ok) throw new Error(payload.loi || `lỗi ${response.status}`);
    state.chat.pop();
    state.chat.push({ role: "bot", text: payload.answer, sources: payload.sources || [] });
  } catch (error) {
    state.chat.pop();
    state.chat.push({
      role: "bot",
      text: `Chưa trả lời được: ${error.message.replace(/\.$/, "")}. Thử lại sau, hoặc tra cứu trực tiếp ở mục Thủ tục.`,
      error: true,
    });
  } finally {
    state.chatBusy = false;
  }
  // Người dùng có thể đã chuyển tab khi đang chờ; chỉ vẽ lại nếu vẫn ở Hỏi đáp.
  if (route().tab === "hoidap") renderChat();
}

// ----- Tài khoản -----

function accountField(name, label, autocomplete) {
  const id = `account-${name}`;
  return el(
    "div",
    { class: "field" },
    el("label", { for: id }, label),
    el("input", {
      id,
      name,
      type: "password",
      autocomplete,
      minlength: name === "next" ? MIN_PASSWORD_LENGTH : null,
      required: true,
    })
  );
}

function renderAccount() {
  const message = el("p", { class: "form-message", role: "alert", hidden: true });
  const form = el(
    "form",
    {
      class: "account-form",
      novalidate: true,
      onsubmit: (event) => {
        event.preventDefault();
        changePassword(event.currentTarget, message);
      },
    },
    accountField("current", "Mật khẩu hiện tại", "current-password"),
    accountField("next", `Mật khẩu mới (ít nhất ${MIN_PASSWORD_LENGTH} ký tự)`, "new-password"),
    accountField("confirm", "Nhập lại mật khẩu mới", "new-password"),
    message,
    el("button", { type: "submit", class: "btn" }, "Đổi mật khẩu")
  );

  setView(
    el(
      "article",
      { class: "doc" },
      el("h1", {}, "Tài khoản"),
      state.user.phai_doi_mat_khau
        ? el("p", { class: "notice" }, "Bạn đang dùng mật khẩu tạm. Đặt mật khẩu mới để tiếp tục dùng trang.")
        : null,
      el("section", { class: "section" }, el("h2", {}, "Đổi mật khẩu"), form),
      el(
        "section",
        { class: "section" },
        el("h2", {}, "Đăng xuất"),
        el("p", {}, `Đang đăng nhập bằng tài khoản ${state.user.ten}.`),
        el("button", { type: "button", class: "btn btn--ghost", onclick: logout }, "Đăng xuất")
      )
    )
  );
}

function showFormMessage(node, text, tone = "error") {
  node.textContent = text;
  node.className = `form-message form-message--${tone}`;
  node.hidden = false;
}

async function changePassword(form, message) {
  const data = new FormData(form);
  const current = String(data.get("current") ?? "");
  const next = String(data.get("next") ?? "");
  const confirm = String(data.get("confirm") ?? "");
  if (next.length < MIN_PASSWORD_LENGTH) {
    return showFormMessage(message, `Mật khẩu mới cần ít nhất ${MIN_PASSWORD_LENGTH} ký tự.`);
  }
  if (next !== confirm) return showFormMessage(message, "Hai lần nhập mật khẩu mới chưa khớp.");

  try {
    const response = await fetch("api/change-password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ current, next }),
      cache: "no-store",
    });
    const payload = await response.json().catch(() => ({}));
    if (response.status === 401) return location.replace("login.html");
    if (!response.ok) return showFormMessage(message, payload.loi || "Chưa đổi được mật khẩu. Thử lại sau.");
  } catch {
    return showFormMessage(message, "Không kết nối được máy chủ. Thử lại sau.");
  }

  // Đổi xong mật khẩu tạm thì vào trang tra cứu; đổi thường thì báo ngay trên form.
  if (state.user.phai_doi_mat_khau) {
    state.user.phai_doi_mat_khau = false;
    location.hash = "#tthc";
    return;
  }
  form.reset();
  showFormMessage(message, "Đã đổi mật khẩu. Các máy khác đã bị đăng xuất.", "ok");
}

async function logout() {
  await fetch("api/logout", { method: "POST", cache: "no-store" }).catch(() => {});
  location.replace("login.html");
}

// ----- Cập nhật -----

function changeText(field, value) {
  if (field === "lich_su") return `${FIELD_LABELS.lich_su}: ${value.cu ?? 0} → ${value.moi} mục`;
  const label = FIELD_LABELS[field] || field;
  return `${label}: ${shorten(value.cu, 90) || "chưa có"} → ${shorten(value.moi, 90) || "chưa có"}`;
}

function changeItem(change) {
  const label = CHANGE_LABELS[change.change_type] || change.change_type;
  const name = change.diff?._ten || `Mục ${change.record_id}`;
  const details = Object.entries(change.diff || {})
    .filter(([field]) => !field.startsWith("_"))
    .map(([field, value]) => changeText(field, value));
  return el(
    "li",
    {},
    el("time", { datetime: change.run_at }, fmtDateTime(change.run_at)),
    el("span", { class: "tl__label" }, `${label}: ${name}`),
    details.length ? el("span", { class: "tl__detail" }, details.join("; ")) : null
  );
}

function changesSection(items) {
  if (!items.length) return null;
  return el(
    "section",
    { class: "section" },
    el("h2", {}, "Thay đổi đã ghi nhận"),
    el("ol", { class: "timeline" }, items.map(changeItem))
  );
}

function renderUpdates() {
  const { meta, changes } = state.data;
  setView(
    el(
      "article",
      { class: "doc" },
      el("h1", {}, "Lịch sử cập nhật"),
      el(
        "p",
        { class: "lede" },
        "Công cụ kiểm tra cổng Phòng CSQLHC, vbpl.vn và các công báo chính thức (Chính phủ, TP.HCM, Bộ Công an) mỗi ngày, rồi ghi lại mọi thay đổi so với lần trước."
      ),
      el(
        "section",
        { class: "section" },
        el("h2", {}, "Trạng thái"),
        factsList([
          ["Lần kiểm tra gần nhất", fmtDateTime(meta.cap_nhat_luc)],
          ["Lần thành công gần nhất", fmtDateTime(meta.lan_chay_thanh_cong_gan_nhat)],
          ["Văn bản theo dõi", String(meta.so_van_ban)],
          ["Thủ tục", String(meta.so_thu_tuc)],
        ])
      ),
      el(
        "section",
        { class: "section" },
        el("h2", {}, "Thay đổi"),
        changes.length
          ? el("ol", { class: "timeline" }, changes.slice(0, 200).map(changeItem))
          : el("p", { class: "empty" }, "Chưa có thay đổi nào được ghi nhận sau lần chạy đầu tiên.")
      ),
      el(
        "section",
        { class: "section" },
        el("h2", {}, "Lưu ý"),
        el(
          "p",
          {},
          "Tình trạng đối chiếu thủ công được ghi rõ nguồn và ngày. Văn bản chưa có toàn văn trong dữ liệu được đánh dấu rõ khi trả lời."
        )
      )
    )
  );
}

function renderNotFound(backHref, backLabel) {
  setView(
    el("p", { class: "crumb" }, el("a", { href: backHref }, backLabel)),
    el("p", { class: "empty" }, "Không tìm thấy mục này. Có thể mục đã được gỡ khỏi cổng.")
  );
}

// ----- Khởi động -----

// Kiểm tra phiên trước khi tải dữ liệu. Hết phiên thì sang màn đăng nhập.
async function loadMe() {
  let response;
  try {
    response = await fetch("api/me", { cache: "no-store" });
  } catch {
    app.replaceChildren(el("p", { class: "notice" }, "Không kết nối được máy chủ. Tải lại trang sau ít phút."));
    return false;
  }
  if (response.status === 404) {
    // Trang công khai (GitHub Pages, không có máy chủ đăng nhập): xem dữ liệu, không có mục Tài khoản.
    state.user = { ten: "", phai_doi_mat_khau: false, cong_khai: true };
    document.querySelector('[data-tab="taikhoan"]').hidden = true;
    return true;
  }
  if (response.status === 401) {
    location.replace("login.html");
    return false;
  }
  if (!response.ok) {
    app.replaceChildren(el("p", { class: "notice" }, "Không kiểm tra được tài khoản. Tải lại trang sau ít phút."));
    return false;
  }
  state.user = await response.json();
  return true;
}

async function loadJson(name) {
  const response = await fetch(`data/${name}.json`, { cache: "no-cache" });
  if (response.status === 401) {
    location.replace("login.html");
    throw new Error("cần đăng nhập");
  }
  if (!response.ok) throw new Error(`${name}: HTTP ${response.status}`);
  return response.json();
}

async function init() {
  if (!(await loadMe())) return;
  app.replaceChildren(
    el("p", { class: "state", role: "status" }, "Đang tải dữ liệu…"),
    el("div", { class: "skeleton", "aria-hidden": "true" })
  );
  try {
    const [vanBan, tthc, changes, meta] = await Promise.all(["van_ban", "tthc", "thay_doi", "meta"].map(loadJson));
    state.data = { vanBan, tthc, changes, meta };
  } catch {
    app.replaceChildren(el("p", { class: "notice" }, "Không tải được dữ liệu. Tải lại trang sau ít phút."));
    return;
  }

  const { data } = state;
  data.tthc.forEach((t) => state.tthcById.set(String(t.id), t));
  data.vanBan.forEach((v) => state.vanBanBySo.set(v.so_ky_hieu, v));
  for (const change of data.changes) {
    const key = `${change.kind}:${change.record_id}`;
    if (!state.changes.has(key)) state.changes.set(key, []);
    state.changes.get(key).push(change);
  }

  const latestRun = data.changes.reduce((max, change) => (change.run_at > max ? change.run_at : max), "");
  state.latestChange = latestRun
    ? { run_at: latestRun, count: data.changes.filter((change) => change.run_at === latestRun).length }
    : null;

  document.getElementById("disclaimer").textContent = data.meta.luu_y;
  document.getElementById("source-link").href = data.meta.nguon.url;
  document.getElementById("vbpl-link").href = data.meta.nguon_van_ban.url;

  // Đổi tab thì đưa lên đầu trang và chuyển focus vào nội dung; gửi câu hỏi thì giữ nguyên vị trí.
  window.addEventListener("hashchange", () => {
    render();
    app.focus({ preventScroll: true });
    window.scrollTo({ top: 0 });
  });
  render();
}

init();
