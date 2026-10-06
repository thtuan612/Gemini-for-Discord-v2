<div align="center">

# 🤖 Gemini for Discord v2

**Bot Discord tiếng Việt chạy bằng Google Gemini, kèm web dashboard phong cách iOS để quản lý.**

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![discord.py](https://img.shields.io/badge/discord.py-2.x-5865F2?logo=discord&logoColor=white)
![Gemini](https://img.shields.io/badge/Google-Gemini-4285F4?logo=google&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)

</div>

---

## ✨ Tính năng

- 💬 **Trò chuyện**: dùng `/chat`, mention bot, hoặc bật **Auto-Chat** để bot tự trả lời trong kênh (không cần mention).
- 🖼️ **Phân tích ảnh**: tối đa 4 ảnh/lần, mỗi ảnh ≤ 8 MB, định dạng png / jpg / webp / heic.
- 🧠 **Ghi nhớ hội thoại** riêng cho từng người **và từng server**, tự xóa sau 30 ngày.
- ⏰ **Reminder** một lần hoặc hàng ngày, theo giờ Việt Nam.
- 📊 **Giám sát**: lệnh `/botinfo` và web dashboard.
- 🔐 **An toàn**: khóa bot theo server (`ALLOWED_GUILD_IDS`), chặn ping `@everyone` / `@here` trong mọi tin nhắn của bot.

## 🚀 Cài đặt nhanh

**Yêu cầu:** Python 3.10+, Discord Bot Token, Gemini API Key.

```bash
git clone https://github.com/thtuan612/Gemini-for-Discord-v2.git
cd Gemini-for-Discord-v2
pip install -r requirements.txt
cp .env.example .env     # điền DISCORD_TOKEN và GEMINI_API_KEY
python bot.py
```

Trong [Discord Developer Portal](https://discord.com/developers/applications), bật **MESSAGE CONTENT INTENT**.
**SERVER MEMBERS INTENT** chỉ cần khi đặt `MEMBERS_INTENT=true`.

## ⚙️ Cấu hình

Mọi biến môi trường đều có chú thích trong [`.env.example`](.env.example). Các biến chính:

| Biến | Bắt buộc | Mô tả |
| --- | :---: | --- |
| `DISCORD_TOKEN` | ✅ | Token của bot Discord |
| `GEMINI_API_KEY` | ✅ | API key Google Gemini |
| `ALLOWED_GUILD_IDS` | | Chỉ cho bot chạy ở các server này |
| `ADMIN_ROLE_IDS` | | Các role được coi là Admin của bot |
| `MEMBERS_INTENT` | | `true` nếu bật Server Members Intent |
| `DASHBOARD_ENABLED` | | `true` để bật web dashboard |
| `DASHBOARD_PASSWORD` | | Mật khẩu đăng nhập dashboard (≥ 12 ký tự) |
| `DASHBOARD_SECURE_COOKIE` | | `true` khi chạy sau HTTPS |

System prompt của bot nằm trong [`prompt.txt`](prompt.txt), sửa file này để đổi tính cách bot.

## 📖 Lệnh

| Lệnh | Ai dùng | Mô tả |
| --- | --- | --- |
| `/chat message [image]` | Mọi người | Trò chuyện với Gemini |
| `/reset` | Mọi người | Xóa lịch sử của bạn ở server này |
| `/remind time message repeat [channel]` | Mọi người | Đặt nhắc (cần quyền gửi tin ở kênh đích) |
| `/remind_list` · `/remind_cancel id` | Mọi người | Xem / hủy reminder (chỉ người tạo hoặc Admin được hủy) |
| `/autochat_list` | Mọi người | Xem các kênh Auto-Chat |
| `/autochat_add` · `/autochat_remove` | Admin/Owner | Bật / tắt Auto-Chat |
| `/botinfo` | Admin/Owner | Xem thông số bot |

> **Admin/Owner** gồm: chủ server, người có quyền Administrator, hoặc thành viên có role nằm trong `ADMIN_ROLE_IDS`.

## 🖥️ Web dashboard

Giao diện phong cách iOS: tiêu đề lớn, thẻ kính mờ bo góc, tab bar nổi dạng viên thuốc ở đáy màn hình điện thoại (thanh điều hướng nổi ở trên cùng khi dùng máy tính), bảng tự chuyển thành danh sách thẻ trên điện thoại, tự chuyển sáng/tối theo hệ thống.
Thanh điều hướng dùng hiệu ứng [Liquid Glass](https://github.com/ybouane/liquidglass) (WebGL), tải từ CDN jsDelivr. Nếu trình duyệt không hỗ trợ WebGL, bật "giảm chuyển động", hoặc không tải được CDN, dashboard tự dùng kính mờ CSS thay thế. Thêm `?lg=0` vào URL để tắt hiệu ứng.

Bật trong `.env`:

```env
DASHBOARD_ENABLED=true
DASHBOARD_PASSWORD=mot-mat-khau-dai-it-nhat-12-ky-tu
```

Sau đó mở **http://127.0.0.1:8080** và đăng nhập.

| Trang | Chức năng |
| --- | --- |
| 📊 Tổng quan | Ping, uptime, RAM, disk, database, danh sách server |
| 💬 Auto-Chat | Bật / tắt Auto-Chat cho từng kênh |
| ⏰ Reminder | Xem và hủy reminder đang chạy |
| 🗂️ Lịch sử | Dọn lịch sử theo thời gian, theo người dùng, hoặc xóa toàn bộ |
| 📜 Log | Xem log gần nhất |
| ⚙️ Cấu hình | Xem cấu hình hiện tại (chỉ đọc, ẩn token và API key) |

### Truy cập từ xa

Mặc định dashboard chỉ lắng nghe `127.0.0.1`. Có hai cách an toàn để truy cập từ xa:

1. **SSH tunnel**: `ssh -L 8080:127.0.0.1:8080 user@server`, rồi mở `http://127.0.0.1:8080` trên máy bạn.
2. **Reverse proxy HTTPS** (Nginx, Caddy…) và đặt `DASHBOARD_SECURE_COOKIE=true`.

> ⚠️ Không mở `0.0.0.0` qua HTTP thường, vì mật khẩu sẽ đi không mã hóa.

Đăng nhập sai nhiều lần sẽ bị chặn tạm thời theo IP; phiên đăng nhập có CSRF token và tự hết hạn sau 12 giờ.

## 📁 Cấu trúc dự án

```text
├── bot.py               # Bot và các slash command
├── config.py            # Đọc cấu hình từ .env
├── db.py                # SQLite: lịch sử, reminder, auto-chat
├── utils.py             # Hàm tiện ích
├── dashboard.py         # Web server (aiohttp)
├── dashboard_views.py   # Giao diện HTML/CSS, phiên đăng nhập, rate limit
├── prompt.txt           # System prompt
├── requirements.txt
├── CHANGELOG.md
└── tests/               # Unit test
```

## 🧪 Kiểm thử

```bash
python -m unittest discover -s tests
```

## 🛡️ Bảo mật & quyền riêng tư

- Không commit `.env` hoặc `*.db` (đã có trong `.gitignore`). Nếu token / API key bị lộ, hãy thu hồi ngay.
- Tin nhắn người dùng được lưu dạng văn bản thường trong SQLite và được gửi tới Google Gemini. Hãy thông báo điều này với thành viên server.

## 👤 Tác giả

**ThTuan** · Discord: `@lmtuan612`

## 📜 License

MIT, xem file `LICENSE` (bản tiếng Việt: `LICENSE.vi`).
