# Tra cứu thủ tục và văn bản

Công cụ mã nguồn mở giúp cán bộ và người dân tra cứu nhanh:

- **Thủ tục hành chính**: hồ sơ, trình tự, thời hạn, lệ phí, căn cứ pháp lý, lấy từ cổng của Phòng Cảnh sát quản lý hành chính về trật tự xã hội (Công an TP.HCM).
- **Văn bản pháp quy** về cư trú, căn cước, vũ khí, ANTT, kèm tình trạng hiệu lực đã đối chiếu.
- **Theo dõi thay đổi**: mỗi ngày tự kiểm tra cổng, so với lần trước và ghi lại mọi thay đổi (mới, sửa đổi, không còn trên cổng).

> Công cụ chỉ hỗ trợ tra cứu, không thay thế văn bản pháp luật chính thức và không phải ý kiến pháp lý. Trước khi áp dụng, đối chiếu với văn bản gốc.

## Cấu trúc

```
crawler/      Mã thu thập và phát hiện thay đổi (Python, không cần thư viện ngoài)
  client.py       gọi cổng chậm, dừng ngay khi bị chặn
  sources.py      các điểm truy cập JSON của cổng
  normalize.py    chuẩn hóa bản ghi, băm nội dung, so sánh
  store.py        lưu SQLite, ghi nhận thay đổi
  export.py       xuất JSON cho trang web
  update.py       điểm vào chính
  tinh_trang_thu_cong.json   ghi chú đối chiếu thủ công (có nguồn)
  van_ban_bo_sung.json       văn bản cổng chưa có (có nguồn)
docs/         Trang web tĩnh (GitHub Pages)
  data/           dữ liệu JSON do crawler sinh ra
data/         SQLite và ảnh chụp dữ liệu thô (raw/ không đưa lên git)
tests/        kiểm thử logic (không gọi mạng)
```

## Chạy thử trên máy

Yêu cầu Python 3.10 trở lên, không cần cài thêm thư viện.

```bash
python -m crawler.update
python -m unittest discover -s tests
```

Mở `docs/index.html` bằng một máy chủ tĩnh, ví dụ:

```bash
python -m http.server 8000 --directory docs
```

Rồi vào http://localhost:8000.

## Tự động cập nhật

**Cách 1: GitHub Actions (khuyến nghị).** Đưa dự án lên GitHub, bật GitHub Pages từ thư mục `/docs` của nhánh chính. Workflow `.github/workflows/cap-nhat-hang-ngay.yml` chạy mỗi ngày lúc 08:00, cập nhật `docs/data` và `data/thutuc.db`, rồi commit nếu có thay đổi.

**Cách 2: Windows Task Scheduler** trên máy cá nhân:

```bash
schtasks /Create /SC DAILY /ST 08:00 /TN "ThuTucAssistant" /TR "cmd /c cd /d D:\Claude-Work\thutuc-assistant && python -m crawler.update"
```

## Cách hoạt động của phát hiện thay đổi

- Mỗi bản ghi (văn bản hoặc thủ tục) được băm SHA-256 trên nội dung đã chuẩn hóa.
- Lần chạy đầu tiên chỉ ghi nhận nền, không báo thay đổi.
- Từ lần sau, bản ghi có băm khác sẽ được ghi kèm các trường đã đổi (cũ → mới).
- Bản ghi biến mất khỏi cổng được đánh dấu, không xóa.
- Nếu số bản ghi giảm quá nửa, hoặc cổng trả về rỗng, lần chạy bị coi là lỗi và không ghi gì (tránh xóa nhầm dữ liệu khi cổng sự cố).

## Văn bản từ vbpl.vn (CSDL quốc gia về pháp luật)

Công cụ đọc thêm tình trạng hiệu lực và ngày cập nhật từ vbpl.vn, gồm cả văn bản trung ương và văn bản địa phương TP.HCM. Mô-đun này làm đúng theo `robots.txt` của trang: chỉ đọc sitemap và trang chi tiết, không gọi `/api/`.

- **Mỗi tuần một lần**: đọc toàn bộ sitemap để tìm văn bản theo số ký hiệu và văn bản mới theo từ khóa (`crawler/vbpl_config.json`). Văn bản địa phương chỉ giữ những văn bản có "thành phố Hồ Chí Minh" trong tên.
- **Mỗi ngày**: mở từng trang chi tiết bằng trình duyệt tự động (Playwright) để lấy tình trạng, ngày có hiệu lực và ngày cập nhật.
- Khi không có Playwright, bước này được bỏ qua và phần cổng Phòng CSQLHC vẫn chạy bình thường.

Cài đặt để bật bước này trên máy:

```bash
pip install playwright
python -m playwright install chromium
```

Thứ tự ưu tiên khi hiển thị tình trạng: vbpl.vn trước, rồi đối chiếu thủ công, rồi cổng Phòng CSQLHC.

## Hạn chế đã biết

- **Cổng chưa được cập nhật đầy đủ.** Ngày ban hành mới nhất của văn bản trên cổng là 01/10/2019. Cổng vẫn đánh dấu "còn hiệu lực" cho Luật Cư trú 2006 và Luật Căn cước công dân 2014, dù đã bị thay thế. Vì vậy công cụ dùng `crawler/tinh_trang_thu_cong.json` để ghi chú đối chiếu, kèm nguồn và ngày đối chiếu, và `crawler/van_ban_bo_sung.json` cho Luật Căn cước 2023 và Luật Cư trú 2020.
- **Tệp đính kèm (.doc/.pdf) của cổng trả về 403** khi truy cập tự động, nên chưa đưa toàn văn văn bản vào công cụ. Thông tin của văn bản (số ký hiệu, ngày, trích yếu) vẫn đầy đủ.
- Mục đối chiếu thủ công cần người bảo trì cập nhật khi có văn bản mới. Đây là phần không tự động hóa được hoàn toàn.

## Đóng góp

Mỗi thay đổi về dữ liệu đối chiếu thủ công cần kèm nguồn chính thức hoặc tham khảo đáng tin cậy và ngày đối chiếu.
