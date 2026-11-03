// Quản lý tài khoản trên máy chủ:
//   node auth-cli.mjs reset <tên đăng nhập>            mật khẩu tạm ngẫu nhiên, lần đầu bắt buộc đổi
//   node auth-cli.mjs dat <tên đăng nhập> <mật khẩu>   đặt mật khẩu cố định, không bắt buộc đổi
import { randomBytes } from "node:crypto";
import { setPassword } from "./auth.mjs";

const AUTH_FILE = process.env.TCHC_AUTH_FILE || "C:\\tchc\\auth\\users.json";
const [command, username, password] = process.argv.slice(2);
const USAGE = [
  "Cách dùng:",
  "  node auth-cli.mjs reset <tên đăng nhập>",
  "  node auth-cli.mjs dat <tên đăng nhập> <mật khẩu>",
].join("\n");

if (!/^[a-z0-9._-]{1,32}$/.test(username ?? "") || !["reset", "dat"].includes(command)) {
  console.error(USAGE);
  process.exit(2);
}

if (command === "reset") {
  const temporary = randomBytes(12).toString("base64url");
  await setPassword(AUTH_FILE, username, temporary, { mustChange: true });
  console.log(`Mật khẩu tạm cho ${username}: ${temporary}`);
  console.log("Đăng nhập bằng mật khẩu này. Hệ thống sẽ yêu cầu đặt mật khẩu mới ngay.");
} else {
  if (!password) {
    console.error(USAGE);
    process.exit(2);
  }
  await setPassword(AUTH_FILE, username, password, { mustChange: false });
  console.log(`Đã đặt mật khẩu cho ${username}. Không bắt buộc đổi khi đăng nhập.`);
}
