# Tích hợp nguồn văn bản chính thức

Đánh dấu những gì đã tích hợp vào dữ liệu và những gì còn chờ. Cập nhật file này mỗi khi thêm một nguồn hoặc một giai đoạn.

## Nguồn

| Nguồn | Đọc bằng | Trạng thái |
|---|---|---|
| Công báo điện tử Chính phủ (RSS văn bản mới ban hành) | `nguon_chinh_thuc.doc_chinh_phu` | Đã tích hợp, giai đoạn 1 |
| Công báo TP.HCM (bảng "Văn bản mới", các số Công báo gần nhất, dải tin công bố TTHC) | `nguon_chinh_thuc.doc_tphcm` | Đã tích hợp, giai đoạn 1 |
| Cổng Bộ Công an (thẻ văn bản trên trang chủ) | `nguon_chinh_thuc.doc_bo_cong_an` | Đã tích hợp, giai đoạn 1 |
| Toàn văn (PDF) của các văn bản trên | `nguon_text` | Đã tích hợp, giai đoạn 1 |
| vbpl.vn (tình trạng hiệu lực) | `vbpl_sync` | Có sẵn từ trước; văn bản mới được đưa vào danh sách theo dõi |
| Cổng Dịch vụ công Quốc gia (thủ tục do công an thực hiện hoặc có công an tham gia) | `cong_dvc` | Đã tích hợp: API công khai của trang tra cứu; chỉ lấy thủ tục có công an và thuộc lĩnh vực dân cư; bỏ thủ tục trùng tên với cổng TP.HCM |

## Giai đoạn 1 (đang thực hiện): thủ tục hành chính và cư trú

Từ khóa trong `nguon_chinh_thuc.GIAI_DOAN_1`, khớp theo tên văn bản không dấu:
`luat-cu-tru`, `dang-ky-cu-tru`, `tam-tru`, `tam-vang`, `thuong-tru`, `ho-khau`, `can-cuoc`, `thu-tuc-hanh-chinh`.

Không dùng riêng "cư trú": nhiều nghị quyết chỉ nhắc "cư trú trên địa bàn" trong nội dung (ví dụ nghị quyết hỗ trợ bảo hiểm y tế cho người hiến máu), nên bị lấy nhầm.

Phạm vi "thủ tục hành chính" (theo yêu cầu của cán bộ): từ khóa chung `thu-tuc-hanh-chinh` chỉ giữ khi văn bản thuộc cơ quan công an
(số hiệu có `BCA`, cơ quan ban hành hoặc tên có "công an"). Thủ tục của ngành khác (ngân hàng, hải quan, kho bạc, nông nghiệp,
khoa học, thủy sản...) bị bỏ. Các lĩnh vực cụ thể (cư trú, căn cước, con dấu, vũ khí, ANTT, khu phố...) giữ nguyên.
Quy tắc nằm trong `nguon_chinh_thuc.phu_hop_pham_vi` và `loc_pham_vi`; `export._trong_pham_vi` và bước toàn văn dùng cùng quy tắc.

## Giai đoạn 2: các lĩnh vực còn lại

Từ khóa trong `vbpl_config.json` (ANTT, vũ khí, con dấu, khu phố, hộ tịch, kinh doanh có điều kiện...).
Chạy với `python -m crawler.update --giai-doan=2`.

## Giai đoạn 3: đăng ký khác với cơ quan công an

Từ khóa trong `nguon_chinh_thuc.GIAI_DOAN_3`: mới sinh con (`moi-sinh`, `sinh-con`), khai sinh, đăng ký xe
(`dang-ky-xe`, `dang-ky-phuong-tien`, `giay-phep-lai-xe`), xuất nhập cảnh và hộ chiếu, phòng cháy chữa cháy.

Các từ khóa dễ lẫn sang ngành khác (`TU_KHOA_CAN_CONG_AN`: khai sinh của Tư pháp, đăng kiểm xe của Giao thông,
xuất khẩu lao động...) chỉ giữ khi văn bản thuộc cơ quan công an (số hiệu có BCA, cơ quan ban hành hoặc tên có "công an").
Phòng cháy chữa cháy giữ không cần dấu hiệu công an, nên có thể lẫn văn bản về xây dựng; cần rà lại khi có dữ liệu.

Thủ tục chi tiết (hồ sơ, trình tự) của các việc này chưa có trong danh mục cổng. Bot trả lời bằng toàn văn
và nói rõ đó là nội dung văn bản.

Chạy: `python -m crawler.update --giai-doan=3`. Mặc định hằng ngày chạy cả ba giai đoạn.

## Chưa tích hợp (làm sau khi giai đoạn 1 xong)

- Các lĩnh vực khác: an ninh trật tự, vũ khí và công cụ hỗ trợ, con dấu, phòng cháy, kinh doanh có điều kiện, khu phố/tổ dân phố (xem `vbpl_config.json`).
- Hộ tịch, lệ phí và thu phí không thuộc giai đoạn 1 (đang nằm trong `vbpl_config.json`, chưa dùng cho nguồn chính thức).
- Tệp đính kèm không phải PDF (biểu mẫu Word, bảng phụ lục) chưa được đọc.

## Cách vận hành

- Chạy hằng ngày qua `.github/workflows/cap-nhat-hang-ngay.yml` (cần `pypdf`).
- Chạy thủ công không cần vbpl: `python -m crawler.update --khong-vbpl`. Tắt từng nguồn: `--khong-chinh-thuc`, `--khong-vbpl`.
- Lần chạy đầu của mỗi nguồn chỉ ghi nền (không báo thay đổi). Các lần sau báo văn bản mới trong mục "Cập nhật".
- Toàn văn được lưu ở `docs/data/nguon_text/` (chỉ mục `index.json`), tối đa 300 văn bản mỗi lần chạy.
