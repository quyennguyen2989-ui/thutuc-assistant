"""Lưu toàn văn các văn bản từ nguồn chính thức (PDF), để bot và skill đọc được nội dung.

Với mỗi văn bản chưa có toàn văn:
- Lấy đường dẫn PDF từ trang chi tiết (Công báo Chính phủ, Bộ Công an) hoặc từ "Tải về" (Công báo TP.HCM).
- Trích chữ bằng pypdf, chuẩn hóa Unicode về dạng NFC, lưu thành docs/data/nguon_text/<tên>.txt.
- Ghi chỉ mục index.json; văn bản đã có trong chỉ mục không tải lại.

Giới hạn số văn bản mỗi lần chạy để không gây tải lớn cho cổng. Văn bản không đọc được chữ
(PDF quét ảnh) được ghi vào chỉ mục với lý do, để không tải lại mỗi ngày.
"""

import io
import json
import re
import unicodedata
from datetime import datetime

from .client import BlockedError
from .nguon_chinh_thuc import slug

MAX_MOI_LAN = 300  # đủ cho lần nạp đầu; các lần sau chỉ có vài văn bản mới mỗi ngày
MIN_KY_TU = 200

PDF_CHINH_PHU = re.compile(r'href="(https://congbaocdn\.chinhphu\.vn/[^"]+\.pdf)"')
PDF_BO_CONG_AN = re.compile(r'href="(https://bocongan\.gov\.vn/media/[^"]+\.pdf)"')


def duong_dan_pdf(nguon, url, fetcher):
    """Đường dẫn PDF của văn bản, hoặc None nếu nguồn không có PDF cho trang này."""
    if nguon == "tphcm":
        # Trang "Tải về" của Công báo TP.HCM trả về trực tiếp tệp PDF.
        return url.replace("/noi-dung/", "/tai-ve/") if "/noi-dung/" in url else None
    if nguon == "chinh_phu":
        match = PDF_CHINH_PHU.search(fetcher.get_text(url))
    elif nguon == "bo_cong_an":
        match = PDF_BO_CONG_AN.search(fetcher.get_text(url + "?tab=attributes"))
    else:
        return None
    return match.group(1) if match else None


def trich_chu(pdf_bytes):
    """Chữ trong PDF. Trả về chuỗi rỗng nếu tệp không có lớp chữ (quét ảnh)."""
    try:
        import pypdf
    except ImportError as error:
        raise RuntimeError("thiếu thư viện pypdf (pip install pypdf)") from error
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    pages = [page.extract_text() or "" for page in reader.pages]
    text = unicodedata.normalize("NFC", "\n".join(pages))
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def _tep_cua(nguon, so_ky_hieu):
    return f"{slug(so_ky_hieu)}-{nguon.replace('_', '-')}.txt"


def doc_chi_muc(out_dir):
    path = out_dir / "index.json"
    if not path.exists():
        return {}
    return {entry["url"]: entry for entry in json.loads(path.read_text(encoding="utf-8"))}


def ghi_chi_muc(out_dir, index):
    entries = sorted(index.values(), key=lambda entry: (entry["nguon"], entry["so_ky_hieu"]))
    (out_dir / "index.json").write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")


def sync_nguon_text(conn, fetcher, out_dir, rows, limit=MAX_MOI_LAN):
    """Tải toàn văn cho các văn bản chưa có. Trả về (số văn bản mới có chữ, số văn bản không đọc được)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    index = doc_chi_muc(out_dir)
    pending = [row for row in rows if row["url"] not in index]
    done = failed = 0
    for row in pending[:limit]:
        entry = {
            "nguon": row["nguon"],
            "so_ky_hieu": row["so_ky_hieu"],
            "url": row["url"],
            "tep": None,
            "pdf": None,
            "ky_tu": 0,
            "lay_luc": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        try:
            pdf = duong_dan_pdf(row["nguon"], row["url"], fetcher)
            entry["pdf"] = pdf
            if not pdf:
                entry["ly_do"] = "không tìm thấy tệp PDF trên trang"
            else:
                text = trich_chu(fetcher.get_bytes(pdf, accept="application/pdf, */*;q=0.8"))
                if len(text) < MIN_KY_TU:
                    entry["ly_do"] = "PDF không có lớp chữ (có thể là bản quét ảnh)"
                else:
                    tep = _tep_cua(row["nguon"], row["so_ky_hieu"])
                    (out_dir / tep).write_text(text, encoding="utf-8")
                    entry["tep"] = tep
                    entry["ky_tu"] = len(text)
                    done += 1
                    print(f"toàn văn: {row['so_ky_hieu']} ({len(text)} ký tự)")
        except BlockedError:
            raise
        except RuntimeError as error:
            entry["ly_do"] = str(error)
        if not entry["tep"]:
            failed += 1
        index[row["url"]] = entry
    ghi_chi_muc(out_dir, index)
    return done, failed
