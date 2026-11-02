"use strict";

// Các mục hiển thị trong chi tiết thủ tục, theo thứ tự trên trang. Mục thứ ba: giữ nguyên xuống dòng.
const TTHC_SECTIONS = [
  ["doi_tuong", "Đối tượng thực hiện"],
  ["thoi_han", "Thời hạn giải quyết"],
  ["cach_thuc", "Cách thức thực hiện"],
  ["thanh_phan_ho_so", "Thành phần hồ sơ", true],
  ["trinh_tu", "Trình tự thực hiện", true],
  ["ket_qua", "Kết quả"],
];

const CHANGE_LABELS = {
  moi: "Mới",
  thay_doi: "Thay đổi",
  khong_con_tren_cong: "Không còn trên cổng",
  quay_lai: "Xuất hiện lại trên cổng",
};

const FIELD_LABELS = {
  ten: "Tên",
  linh_vuc: "Lĩnh vực",
  co_quan_thuc_hien: "Cơ quan thực hiện",
  doi_tuong: "Đối tượng",
  thoi_han: "Thời hạn",
  cach_thuc: "Cách thức",
  thanh_phan_ho_so: "Thành phần hồ sơ",
  trinh_tu: "Trình tự",
  ket_qua: "Kết quả",
  le_phi: "Lệ phí",
  can_cu: "Căn cứ pháp lý",
  yeu_cau: "Yêu cầu",
  mau_don: "Mẫu đơn",
  trich_yeu: "Trích yếu",
  ngay_ban_hanh: "Ngày ban hành",
  ngay_hieu_luc: "Ngày hiệu lực",
  hieu_luc_theo_cong: "Trạng thái trên cổng",
};

const state = {
  data: null,
  filters: { tthc: { q: "", lv: "" }, vanban: { q: "", lv: "" } },
  tthcById: new Map(),
  vanBanBySo: new Map(),
  names: new Map(),
  latestChange: null,
  chat: [],
  chatBusy: false,
};

const app = document.getElementById("app");

// Tạo phần tử bằng DOM API (không dùng innerHTML) để nội dung từ cổng không chèn được mã.
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
  if (!iso) return "—";
  const [y, m, d] = iso.split("-");
  return d && m && y ? `${d}/${m}/${y}` : iso;
}

function fmtDateTime(iso) {
  if (!iso) return "—";
  const date = new Date(iso);
  return isNaN(date) ? iso : date.toLocaleString("vi-VN", { hour12: false });
}

function shorten(text, max = 140) {
  const flat = String(text ?? "").replace(/\s+/g, " ").trim();
  return flat.length > max ? flat.slice(0, max - 1) + "…" : flat;
}

function flattenValues(item) {
  return Object.values(item).filter((value) => typeof value === "string" && value.trim()).join(" — ");
}

function uniqueSorted(values) {
  return [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b, "vi"));
}

// Nếu tên căn cứ có số ký hiệu (ví dụ "Luật 81/2006/QH11: ..."), trả về số ký hiệu để đối chiếu.
function citedSoKyHieu(title) {
  const match = String(title).match(/\d{1,4}\/\d{4}\/[^\s:;,)]+/);
  return match ? match[0] : null;
}

function vanBanStatus(v) {
  if (v.vbpl && v.vbpl.tinh_trang) {
    const outdated = v.vbpl.tinh_trang.startsWith("Hết hiệu lực");
    return { text: `vbpl.vn: ${v.vbpl.tinh_trang.toLowerCase()}`, cls: outdated ? "badge-warn" : "badge-ok" };
  }
  if (v.doi_chieu_thu_cong) {
    const outdated = v.doi_chieu_thu_cong.tinh_trang === "het_hieu_luc";
    return {
      text: outdated ? "Đã đối chiếu: hết hiệu lực" : "Đã đối chiếu: còn hiệu lực",
      cls: outdated ? "badge-warn" : "badge-ok",
    };
  }
  if (v.nguon === "thu_cong") return { text: "Bổ sung thủ công", cls: "badge-ok" };
  return v.hieu_luc_theo_cong
    ? { text: "Cổng: còn hiệu lực (chưa đối chiếu)", cls: "" }
    : { text: "Cổng: hết hiệu lực", cls: "badge-warn" };
}

function isOutdatedCitation(title) {
  const so = citedSoKyHieu(title);
  const doc = so && state.vanBanBySo.get(so);
  if (!doc) return false;
  if (doc.vbpl && doc.vbpl.tinh_trang) return doc.vbpl.tinh_trang.startsWith("Hết hiệu lực");
  return Boolean(doc.doi_chieu_thu_cong && doc.doi_chieu_thu_cong.tinh_trang === "het_hieu_luc");
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

function matchesQuery(haystack, query) {
  const terms = norm(query).split(/\s+/).filter(Boolean);
  return terms.every((term) => haystack.includes(term));
}

function route() {
  const [head, ...rest] = location.hash.replace(/^#\/?/, "").split("/");
  const id = rest.length ? decodeURIComponent(rest.join("/")) : null;
  if (head === "vanban") return { tab: "vanban", id };
  if (head === "capnhat") return { tab: "capnhat", id: null };
  if (head === "hoidap") return { tab: "hoidap", id: null };
  return { tab: "tthc", id: head === "tthc" ? id : null };
}

function render() {
  if (!state.data) return;
  const current = route();
  document.querySelectorAll(".tabs a").forEach((link) => {
    link.classList.toggle("active", link.dataset.tab === current.tab);
  });

  if (current.tab === "capnhat") return renderUpdates();
  if (current.tab === "hoidap") return renderChat();
  if (current.tab === "vanban") return current.id ? renderVanBanDetail(current.id) : renderVanBanList();
  return current.id ? renderTthcDetail(current.id) : renderTthcList();
}

function setView(...nodes) {
  const banner = state.data && route().tab !== "capnhat" ? updateBanner() : null;
  app.replaceChildren(...(banner ? [banner] : []), ...nodes);
  window.scrollTo({ top: 0 });
}

// Thông báo ở đầu mỗi trang: lần kiểm tra gần nhất và thay đổi gần nhất được ghi nhận.
function updateBanner() {
  const { meta } = state.data;
  const latest = state.latestChange;
  if (!latest) {
    return el("div", { class: "meta" }, `Đã kiểm tra dữ liệu lúc ${fmtDateTime(meta.cap_nhat_luc)}, chưa có thay đổi nào được ghi nhận.`);
  }
  return el(
    "div",
    { class: "warning-box" },
    el("strong", {}, `Thay đổi gần nhất (${fmtDateTime(latest.run_at)}): ${latest.count} mục. `),
    `Kiểm tra dữ liệu lúc ${fmtDateTime(meta.cap_nhat_luc)}. `,
    el("a", { href: "#capnhat" }, "Xem chi tiết")
  );
}

// ----- Danh sách thủ tục -----

function renderTthcList() {
  const filters = state.filters.tthc;
  const search = el("input", {
    type: "search",
    placeholder: "Gõ việc cần làm, ví dụ: cấp thẻ căn cước, đăng ký tạm trú, vũ khí…",
    value: filters.q,
    "aria-label": "Tìm thủ tục",
    oninput: (event) => {
      filters.q = event.target.value;
      updateTthcResults();
    },
  });
  const select = el(
    "select",
    {
      "aria-label": "Lọc theo lĩnh vực",
      onchange: (event) => {
        filters.lv = event.target.value;
        updateTthcResults();
      },
    },
    el("option", { value: "" }, "Tất cả lĩnh vực"),
    uniqueSorted(state.data.tthc.map((t) => t.linh_vuc)).map((lv) => el("option", { value: lv }, lv))
  );
  select.value = filters.lv;

  setView(
    el("div", { class: "toolbar" }, search, select),
    el("div", { class: "count", id: "results-count" }),
    el("div", { id: "results" })
  );
  updateTthcResults();
}

function updateTthcResults() {
  const { q, lv } = state.filters.tthc;
  const matched = state.data.tthc.filter(
    (t) => (!lv || t.linh_vuc === lv) && (!q || matchesQuery(haystackTthc(t), q))
  );
  document.getElementById("results-count").textContent = `${matched.length} thủ tục`;
  const results = document.getElementById("results");
  results.replaceChildren(
    ...(matched.length
      ? matched.map((t) =>
          el(
            "a",
            { class: "card", href: `#tthc/${t.id}` },
            el("span", { class: "chip" }, t.linh_vuc || "Khác"),
            el("h3", {}, t.ten),
            el(
              "div",
              { class: "meta" },
              `Cơ quan: ${t.co_quan_thuc_hien || "chưa có thông tin"} · Thời hạn: ${shorten(t.thoi_han, 90) || "chưa có thông tin"}`
            )
          )
        )
      : [el("p", { class: "empty" }, "Không có thủ tục phù hợp. Thử từ khóa khác hoặc bỏ bộ lọc lĩnh vực.")])
  );
}

// ----- Chi tiết thủ tục -----

function renderTthcDetail(id) {
  const t = state.tthcById.get(String(id));
  if (!t) return renderNotFound();

  const sections = TTHC_SECTIONS.map(([key, title, keepLines]) => {
    const text = t[key];
    if (!text) return null;
    return el("div", { class: "section" }, el("h4", {}, title), el("div", { class: keepLines ? "prewrap" : "" }, text));
  });

  const incomplete = !t.thanh_phan_ho_so && !t.trinh_tu;
  const feeList = t.le_phi.length
    ? el(
        "div",
        { class: "section" },
        el("h4", {}, "Lệ phí"),
        el(
          "ul",
          {},
          t.le_phi.map((fee) =>
            el("li", {}, [fee.muc, fee.ten && ` — ${fee.ten}`, fee.van_ban && ` (${fee.van_ban})`])
          )
        )
      )
    : null;

  const citations = t.can_cu.length
    ? el(
        "div",
        { class: "section" },
        el("h4", {}, "Căn cứ pháp lý"),
        el(
          "ul",
          {},
          t.can_cu.map((title) =>
            el(
              "li",
              {},
              title,
              isOutdatedCitation(title) && el("span", { class: "chip badge-warn" }, "Đã hết hiệu lực theo đối chiếu")
            )
          )
        )
      )
    : null;

  const extraList = (label, items) =>
    items.length
      ? el(
          "div",
          { class: "section" },
          el("h4", {}, label),
          el("ul", {}, items.map((item) => el("li", {}, flattenValues(item))))
        )
      : null;

  setView(
    el("a", { class: "back", href: "#tthc" }, "← Danh sách thủ tục"),
    el(
      "article",
      { class: "detail" },
      el("span", { class: "chip" }, t.linh_vuc || "Khác"),
      el("h2", {}, t.ten),
      el("div", { class: "meta" }, `Cơ quan thực hiện: ${t.co_quan_thuc_hien || "chưa có thông tin"}`),
      incomplete &&
        el(
          "div",
          { class: "warning-box" },
          "Cổng chưa có đủ thông tin về hồ sơ và trình tự cho thủ tục này. Liên hệ bộ phận tiếp nhận để biết chi tiết."
        ),
      sections,
      feeList,
      citations,
      extraList("Yêu cầu", t.yeu_cau),
      extraList("Mẫu đơn", t.mau_don),
      changesSection("tthc", t.id),
      el(
        "div",
        { class: "actions" },
        el("button", { onclick: () => copyText(tthcToText(t)) }, "Sao chép nội dung"),
        el("button", { class: "secondary", onclick: () => window.print() }, "In / lưu PDF")
      ),
      el("p", { class: "meta" }, `Ghi nhận lần cuối: ${fmtDateTime(t._last_seen)}`)
    )
  );
}

function tthcToText(t) {
  const lines = [t.ten, `Cơ quan thực hiện: ${t.co_quan_thuc_hien}`];
  for (const [key, title] of TTHC_SECTIONS) {
    if (t[key]) lines.push("", `${title}:`, t[key]);
  }
  if (t.le_phi.length) {
    lines.push("", "Lệ phí:", ...t.le_phi.map((fee) => `- ${fee.muc} ${fee.ten}`.trim()));
  }
  if (t.can_cu.length) lines.push("", "Căn cứ pháp lý:", ...t.can_cu.map((title) => `- ${title}`));
  return lines.join("\n");
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    alert("Đã sao chép nội dung.");
  } catch {
    alert("Không sao chép được. Hãy chọn nội dung và sao chép thủ công.");
  }
}

// ----- Văn bản pháp quy -----

function renderVanBanList() {
  const filters = state.filters.vanban;
  const search = el("input", {
    type: "search",
    placeholder: "Tìm theo số ký hiệu, trích yếu, ví dụ: 68/2020, cư trú",
    value: filters.q,
    "aria-label": "Tìm văn bản",
    oninput: (event) => {
      filters.q = event.target.value;
      updateVanBanResults();
    },
  });
  const select = el(
    "select",
    {
      "aria-label": "Lọc theo lĩnh vực",
      onchange: (event) => {
        filters.lv = event.target.value;
        updateVanBanResults();
      },
    },
    el("option", { value: "" }, "Tất cả lĩnh vực"),
    uniqueSorted(state.data.vanBan.map((v) => v.linh_vuc)).map((lv) => el("option", { value: lv }, lv))
  );
  select.value = filters.lv;

  setView(
    el("div", { class: "toolbar" }, search, select),
    el("div", { class: "count", id: "results-count" }),
    el("div", { id: "results" })
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
  results.replaceChildren(
    ...(matched.length
      ? matched.map((v) => {
          const status = vanBanStatus(v);
          return el(
            "a",
            { class: "card", href: `#vanban/${encodeURIComponent(v.so_ky_hieu)}` },
            el("span", { class: "chip" }, v.so_ky_hieu),
            el("span", { class: `chip ${status.cls}` }, status.text),
            el("h3", {}, shorten(v.trich_yeu, 200)),
            el(
              "div",
              { class: "meta" },
              `${v.loai || "Văn bản"} · ${v.co_quan_ban_hanh || ""} · Ban hành ${fmtDate(v.ngay_ban_hanh)} · Hiệu lực ${fmtDate(v.ngay_hieu_luc)}`
            )
          );
        })
      : [el("p", { class: "empty" }, "Không có văn bản phù hợp.")])
  );
}

function renderVanBanDetail(soKyHieu) {
  const v = state.vanBanBySo.get(soKyHieu);
  if (!v) return renderNotFound();
  const status = vanBanStatus(v);

  const notes = [];
  if (v.vbpl && v.vbpl.tinh_trang) {
    notes.push(
      el(
        "div",
        { class: "warning-box" },
        el("strong", {}, `Theo vbpl.vn: ${v.vbpl.tinh_trang}. `),
        `${v.vbpl.ngay_hieu_luc ? `Có hiệu lực từ ${fmtDate(v.vbpl.ngay_hieu_luc)}. ` : "Trang vbpl.vn chưa ghi ngày hiệu lực, xem lịch sử sửa đổi bên dưới. "}Trang vbpl.vn cập nhật ${fmtDate(v.vbpl.ngay_cap_nhat)}, kiểm tra lúc ${fmtDateTime(v.vbpl.kiem_tra_luc)}. `,
        el("a", { href: v.vbpl.url, target: "_blank", rel: "noopener" }, "Mở trên vbpl.vn")
      )
    );
  }
  if (v.doi_chieu_thu_cong) {
    notes.push(
      el(
        "div",
        { class: "warning-box" },
        el("strong", {}, `${status.text}. `),
        v.doi_chieu_thu_cong.ghi_chu,
        el("div", { class: "meta" }, `Đối chiếu ngày ${fmtDate(v.doi_chieu_thu_cong.ngay_doi_chieu)}. Nguồn: `),
        ...v.doi_chieu_thu_cong.nguon.map((url) => [el("a", { href: url, target: "_blank", rel: "noopener" }, url), " "])
      )
    );
  } else if (v.nguon === "thu_cong") {
    notes.push(
      el(
        "div",
        { class: "warning-box" },
        v.ghi_chu,
        el("div", { class: "meta" }, "Tham khảo: "),
        (v.tham_khao || []).map((url) => [el("a", { href: url, target: "_blank", rel: "noopener" }, url), " "])
      )
    );
  } else if (v.hieu_luc_theo_cong && !(v.vbpl && v.vbpl.tinh_trang)) {
    notes.push(
      el(
        "div",
        { class: "warning-box" },
        "Cổng đánh dấu văn bản này còn hiệu lực nhưng chưa đối chiếu với nguồn khác. Kiểm tra trên Cơ sở dữ liệu quốc gia về văn bản pháp luật trước khi dùng."
      )
    );
  }

  const row = (label, value) => el("div", { class: "section" }, el("h4", {}, label), el("div", {}, value || "—"));

  setView(
    el("a", { class: "back", href: "#vanban" }, "← Danh sách văn bản"),
    el(
      "article",
      { class: "detail" },
      el("span", { class: "chip" }, v.so_ky_hieu),
      el("span", { class: `chip ${status.cls}` }, status.text),
      el("h2", {}, v.trich_yeu),
      notes,
      row("Loại văn bản", v.loai),
      row("Lĩnh vực", v.linh_vuc),
      row("Cơ quan ban hành", v.co_quan_ban_hanh),
      row("Người ký", v.nguoi_ky),
      row("Ngày ban hành", fmtDate(v.ngay_ban_hanh)),
      row("Ngày có hiệu lực", v.vbpl?.ngay_hieu_luc || v.ngay_hieu_luc ? fmtDate(v.vbpl?.ngay_hieu_luc || v.ngay_hieu_luc) : "Chưa có trên trang, xem lịch sử sửa đổi"),
      v.vbpl && v.vbpl.lich_su && v.vbpl.lich_su.length
        ? el(
            "div",
            { class: "section" },
            el("h4", {}, "Lịch sử sửa đổi, bổ sung (vbpl.vn)"),
            el(
              "ul",
              {},
              v.vbpl.lich_su.map((item) => el("li", {}, `${fmtDate(item.ngay)} — ${item.trang_thai}: ${item.van_ban_nguon}`))
            )
          )
        : null,
      v.id !== null && changesSection("van_ban", v.id)
    )
  );
}

// ----- Cập nhật -----

function changesSection(kind, recordId) {
  const items = state.data.changes.filter((c) => c.kind === kind && c.record_id === recordId);
  if (!items.length) return null;
  return el(
    "div",
    { class: "section" },
    el("h4", {}, "Thay đổi đã ghi nhận"),
    items.map((change) => el("div", { class: "change-line" }, describeChange(change)))
  );
}

function describeChange(change) {
  const time = fmtDateTime(change.run_at);
  const label = CHANGE_LABELS[change.change_type] || change.change_type;
  const name = change.diff?._ten || state.names.get(`${change.kind}:${change.record_id}`) || `#${change.record_id}`;
  const diffs = Object.entries(change.diff || {})
    .filter(([field]) => !field.startsWith("_"))
    .map(([field, value]) => `${FIELD_LABELS[field] || field}: "${shorten(value.cu, 100)}" → "${shorten(value.moi, 100)}"`);
  return `${time} · ${label}: ${name}${diffs.length ? " — " + diffs.join("; ") : ""}`;
}

function renderUpdates() {
  const meta = state.data.meta;
  const changes = state.data.changes;
  setView(
    el("article", { class: "detail" },
      el("h2", {}, "Lịch sử cập nhật"),
      el("p", {}, "Công cụ tự kiểm tra cổng mỗi ngày và so với lần trước. Các thay đổi được liệt kê dưới đây."),
      el("div", { class: "section" },
        el("h4", {}, "Trạng thái"),
        el("div", {}, `Lần kiểm tra gần nhất: ${fmtDateTime(meta.cap_nhat_luc)}`),
        el("div", {}, `Lần thành công gần nhất: ${fmtDateTime(meta.lan_chay_thanh_cong_gan_nhat)}`),
        el("div", {}, `Số văn bản: ${meta.so_van_ban} · Số thủ tục: ${meta.so_thu_tuc}`)
      ),
      el("div", { class: "section" },
        el("h4", {}, "Thay đổi"),
        changes.length
          ? changes.slice(0, 200).map((change) => el("div", { class: "change-line" }, describeChange(change)))
          : el("p", { class: "empty" }, "Chưa có thay đổi nào được ghi nhận sau lần chạy đầu tiên.")
      ),
      el("div", { class: "section" },
        el("h4", {}, "Lưu ý"),
        el("p", {}, "Mục đánh dấu \"Đã đối chiếu\" hoặc \"Bổ sung thủ công\" được cập nhật bằng tay, không do cổng cung cấp, kèm nguồn và ngày đối chiếu.")
      )
    )
  );
}

function renderNotFound() {
  setView(
    el("a", { class: "back", href: "#tthc" }, "← Quay lại"),
    el("p", { class: "empty" }, "Không tìm thấy mục này. Có thể mục đã bị gỡ khỏi cổng.")
  );
}

// ----- Hỏi đáp (bot) -----

function renderChat() {
  const input = el("textarea", {
    id: "chat-input",
    rows: "3",
    placeholder: "Ví dụ: đăng ký tạm trú cần giấy tờ gì? Cấp lại thẻ căn cước mất bao lâu?",
    "aria-label": "Câu hỏi",
  });
  const form = el(
    "form",
    {
      class: "chat-form",
      onsubmit: (event) => {
        event.preventDefault();
        sendQuestion(input.value);
      },
    },
    input,
    el("div", { class: "actions" }, el("button", { type: "submit", disabled: state.chatBusy ? "disabled" : null }, "Gửi"))
  );

  setView(
    el("h2", {}, "Hỏi đáp thủ tục"),
    el("p", { class: "meta" }, "Trả lời dựa trên dữ liệu thủ tục và văn bản của trang. Luôn đối chiếu văn bản gốc trước khi áp dụng."),
    el("div", { class: "chat-log" }, state.chat.length ? state.chat.map(chatBubble) : el("p", { class: "empty" }, "Chưa có câu hỏi nào.")),
    form
  );
}

function chatBubble(message) {
  const classes = `bubble ${message.role}${message.error ? " error" : ""}`;
  return el(
    "div",
    { class: classes },
    String(message.text || "")
      .split("\n")
      .map((line) => el("div", {}, renderInline(line))),
    message.sources && message.sources.length
      ? el("div", { class: "meta" }, `Nguồn: ${message.sources.map((source) => source.ten).join("; ")}`)
      : null
  );
}

// Hiển thị **chữ đậm** trong câu trả lời của bot, các phần còn lại giữ nguyên.
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
    if (response.status === 404) throw new Error("trang này chưa kết nối bot");
    if (!response.ok) throw new Error(payload.loi || `lỗi ${response.status}`);
    state.chat.pop();
    state.chat.push({ role: "bot", text: payload.answer, sources: payload.sources || [] });
  } catch (error) {
    state.chat.pop();
    state.chat.push({
      role: "bot",
      text: `Chưa trả lời được: ${error.message}. Thử lại sau, hoặc tra cứu trực tiếp ở mục Thủ tục.`,
      error: true,
    });
  } finally {
    state.chatBusy = false;
  }
  renderChat();
}

// ----- Khởi động -----

async function loadJson(name) {
  const response = await fetch(`data/${name}.json`, { cache: "no-cache" });
  if (!response.ok) throw new Error(`${name}: HTTP ${response.status}`);
  return response.json();
}

async function init() {
  try {
    const [vanBan, tthc, changes, meta] = await Promise.all(
      ["van_ban", "tthc", "thay_doi", "meta"].map(loadJson)
    );
    state.data = { vanBan, tthc, changes, meta };
  } catch {
    app.replaceChildren(el("p", { class: "empty" }, "Không tải được dữ liệu. Thử tải lại trang sau."));
    return;
  }

  const { data } = state;
  data.tthc.forEach((t) => {
    state.tthcById.set(String(t.id), t);
    state.names.set(`tthc:${t.id}`, t.ten);
  });
  data.vanBan.forEach((v) => {
    state.vanBanBySo.set(v.so_ky_hieu, v);
    if (v.id !== null) state.names.set(`van_ban:${v.id}`, v.so_ky_hieu);
  });

  const latestRun = data.changes.reduce((max, change) => (change.run_at > max ? change.run_at : max), "");
  state.latestChange = latestRun
    ? { run_at: latestRun, count: data.changes.filter((change) => change.run_at === latestRun).length }
    : null;

  document.getElementById("disclaimer").textContent = data.meta.luu_y;
  const sourceLink = document.getElementById("source-link");
  sourceLink.href = data.meta.nguon.url;

  window.addEventListener("hashchange", render);
  render();
}

init();
