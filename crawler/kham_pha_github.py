"""Đẩy tệp kết quả tìm văn bản vbpl lên GitHub bằng API nội dung. Chỉ dùng thư viện chuẩn của Python.

Dùng trên server-chat, nơi có token GitHub giới hạn một repo (quyền Contents: đọc và ghi).
Token đọc từ một tệp trên máy chủ, không bao giờ ghi vào repo hay log.
Chỉ đẩy khi nội dung đổi, để không tạo commit trùng mỗi ngày.
"""

import base64
import hashlib
import json
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.github.com"
REPO = "quyennguyen2989-ui/thutuc-assistant"
NHANH = "main"
DUONG_DAN_KET_QUA = "data/vbpl_kham_pha.json"
USER_AGENT = "thutuc-assistant/0.1 (open-source, cong cu tra cuu van ban cho can bo dan cu)"


class LoiGitHub(RuntimeError):
    pass


def doc_token(duong_dan):
    token = Path(duong_dan).read_text(encoding="utf-8").strip()
    if not token:
        raise LoiGitHub(f"tệp token trống: {duong_dan}")
    return token


def _yeu_cau(method, url, token, body=None):
    """Gọi API. Trả về (mã HTTP, dữ liệu JSON). 404 không ném lỗi để người gọi tự xử lý."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": USER_AGENT,
    }
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read().decode("utf-8")
            return response.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return 404, None
        raise LoiGitHub(f"GitHub trả HTTP {error.code} khi {method} {duong_dan_api(url)}") from error


def duong_dan_api(url):
    """Đường dẫn trong URL API để ghi log (không kèm tham số truy vấn)."""
    return url.split("?", 1)[0].replace(API, "")


def blob_sha(noi_dung):
    """Mã băm git (SHA-1 của blob) của nội dung, cùng giá trị GitHub trả về cho tệp."""
    return hashlib.sha1(b"blob %d\0" % len(noi_dung) + noi_dung).hexdigest()


def day_nhieu_tep(token, tep, thong_diep, sha_cu=None, repo=REPO, nhanh=NHANH):
    """Ghi nhiều tệp trong một commit. tep là {đường dẫn: nội dung bytes}. Trả về số tệp đã đổi.

    sha_cu là {đường dẫn: mã blob đã biết}. Nếu nhánh đã đổi một tệp như vậy (ví dụ CI vừa ghi cơ sở dữ liệu)
    thì ném LoiGitHub và không ghi gì, để không đè lên thay đổi của người khác.
    """
    base = f"{API}/repos/{repo}"
    _, ref = _yeu_cau("GET", f"{base}/git/ref/heads/{nhanh}", token)
    dau = ref["object"]["sha"]
    _, commit = _yeu_cau("GET", f"{base}/git/commits/{dau}", token)
    cay_cu = commit["tree"]["sha"]
    _, cay = _yeu_cau("GET", f"{base}/git/trees/{cay_cu}?recursive=1", token)
    if cay.get("truncated"):
        raise LoiGitHub("cây thư mục của repo quá lớn, không đọc đủ")
    hien_tai = {entry["path"]: entry["sha"] for entry in cay["tree"] if entry["type"] == "blob"}

    thay_doi = {}
    for duong_dan, noi_dung in tep.items():
        moi = blob_sha(noi_dung)
        if hien_tai.get(duong_dan) == moi:
            continue
        if sha_cu and duong_dan in sha_cu and hien_tai.get(duong_dan) != sha_cu[duong_dan]:
            raise LoiGitHub(f"xung đột: {duong_dan} đã đổi trên GitHub, không ghi đè")
        thay_doi[duong_dan] = noi_dung
    if not thay_doi:
        return 0

    nut = []
    for duong_dan, noi_dung in thay_doi.items():
        _, blob = _yeu_cau("POST", f"{base}/git/blobs", token, {
            "content": base64.b64encode(noi_dung).decode("ascii"),
            "encoding": "base64",
        })
        nut.append({"path": duong_dan, "mode": "100644", "type": "blob", "sha": blob["sha"]})
    _, cay_moi = _yeu_cau("POST", f"{base}/git/trees", token, {"base_tree": cay_cu, "tree": nut})
    _, commit_moi = _yeu_cau("POST", f"{base}/git/commits", token, {
        "message": thong_diep,
        "tree": cay_moi["sha"],
        "parents": [dau],
    })
    _yeu_cau("PATCH", f"{base}/git/refs/heads/{nhanh}", token, {"sha": commit_moi["sha"]})
    return len(thay_doi)


def day_tep(token, noi_dung, thong_diep, duong_dan=DUONG_DAN_KET_QUA, repo=REPO, nhanh=NHANH):
    """Ghi tệp lên nhánh. Trả về True nếu đã đẩy commit, False nếu nội dung không đổi."""
    url = f"{API}/repos/{repo}/contents/{duong_dan}?ref={nhanh}"
    status, hien_tai = _yeu_cau("GET", url, token)
    sha = None
    if status == 200:
        if base64.b64decode(hien_tai["content"]) == noi_dung:
            return False
        sha = hien_tai["sha"]
    body = {
        "message": thong_diep,
        "content": base64.b64encode(noi_dung).decode("ascii"),
        "branch": nhanh,
    }
    if sha:
        body["sha"] = sha
    _yeu_cau("PUT", f"{API}/repos/{repo}/contents/{duong_dan}", token, body)
    return True
