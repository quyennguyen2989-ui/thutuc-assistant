// Lời chào mở đầu và lời nhắc nhẹ kết thúc cho người dùng "Bộ Đẹp".
// Tách khỏi nội dung trả lời: máy chủ thêm vào trước và sau câu trả lời có nguồn,
// nên câu đùa không đi vào thủ tục, hồ sơ, thời hạn, lệ phí hay văn bản.

const LOI_CHAO = [
  "Chào Bộ Đẹp! Mình tra xong rồi đây, Bộ Đẹp xem nhé:",
  "Dạ Bộ Đẹp, việc này mình có dữ liệu rồi, xem nhanh nhé:",
  "Bộ Đẹp hỏi đúng chỗ rồi, mình lục hồ sơ liền đây:",
  "Ồ, Bộ Đẹp lại đố mình rồi! Mình trả lời ngay nè:",
  "Bộ Đẹp ơi, mình tra xong rồi, mời Bộ Đẹp xem:",
];

const LOI_NHAC = [
  "Bộ Đẹp làm việc chăm quá, nhớ uống nước và nghỉ mắt một chút nhé.",
  "Hồ sơ nhiều thì cứ từ từ, Bộ Đẹp đọc kỹ là chắc ăn nhất.",
  "Có gì chưa rõ, Bộ Đẹp cứ hỏi thêm, mình không phiền đâu.",
  "Bộ Đẹp nhớ ăn trưa đúng giờ nhé, việc nào cũng cần có sức.",
  "Làm đúng quy trình là Bộ Đẹp ghi điểm với cả dân lẫn sếp đấy.",
  "Bộ Đẹp giỏi quá, mai mốt chắc thành chuyên gia thủ tục mất thôi.",
  "Mình thương Bộ Đẹp, nghỉ tay một lát rồi làm tiếp nhé.",
  "Bộ Đẹp cười lên một cái đi, công việc sẽ nhẹ đi nhiều đó.",
];

function chon(danhSach, random) {
  return danhSach[Math.floor(random() * danhSach.length)];
}

export function chonLoiChao(random = Math.random) {
  return chon(LOI_CHAO, random);
}

export function chonLoiNhac(random = Math.random) {
  return chon(LOI_NHAC, random);
}
