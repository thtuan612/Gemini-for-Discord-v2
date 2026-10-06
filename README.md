# 🤖 Gemini for Discord v2

Bot Discord tiếng Việt tích hợp Google Gemini, xây dựng bằng Python + discord.py, kèm **web dashboard** để quản lý.

> Tác giả: **ThTuan** · Discord: `@lmtuan612`

## ✨ Tính năng

- 💬 `/chat`, mention bot, hoặc Auto-Chat (kênh tự trả lời, không cần mention)
- 🖼️ Phân tích ảnh đính kèm (tối đa 4 ảnh, 8 MB, png/jpg/webp/heic)
- 🧠 Lịch sử hội thoại riêng theo từng người **và từng server**, tự xóa sau 30 ngày
- ⏰ Reminder một lần / hàng ngày (giờ Việt Nam)
- 📊 `/botinfo` và **Web dashboard**
- 🔐 Khóa bot theo server (`ALLOWED_GUILD_IDS`), chặn ping `@everyone/@here` ở mọi tin nhắn của bot

## 📦 Cài đặt

```bash
git clone https://github.com/thtuan612/Gemini-for-Discord-v2.git
cd Gemini-for-Discord-v2
pip install -r requirements.txt
cp .env.example .env   # rồi điền DISCORD_TOKEN và GEMINI_API_KEY
python bot.py
```

Yêu cầu: Python 3.10+, Discord Bot Token, Gemini API Key. Bật **MESSAGE CONTENT INTENT** trong Discord Developer Portal
(**SERVER MEMBERS INTENT** chỉ cần khi đặt `MEMBERS_INTENT=true`).

Toàn bộ biến môi trường có chú thích trong [`.env.example`](.env.example). System prompt nằm ở [`prompt.txt`](prompt.txt).

## 📖 Lệnh

| Lệnh | Ai dùng | Mô tả |
| --- | --- | --- |
| `/chat message [image]` | Mọi người | Trò chuyện với Gemini |
| `/reset` | Mọi người | Xóa lịch sử của bạn ở server này |
| `/remind time message repeat [channel]` | Mọi người | Đặt nhắc (cần quyền gửi tin ở kênh đích) |
| `/remind_list` · `/remind_cancel id` | Mọi người | Xem / hủy (chỉ người tạo hoặc Admin được hủy) |
| `/autochat_list` | Mọi người | Xem kênh Auto-Chat |
| `/autochat_add` · `/autochat_remove` | Admin/Owner | Bật / tắt Auto-Chat |
| `/botinfo` | Admin/Owner | Thông số bot |

**Admin/Owner** = chủ server, người có quyền Administrator, hoặc role có ID trong `ADMIN_ROLE_IDS`.

## 🖥️ Web dashboard

Bật trong `.env`:

```env
DASHBOARD_ENABLED=true
DASHBOARD_PASSWORD=mot-mat-khau-dai-it-nhat-12-ky-tu
```

Mở `http://127.0.0.1:8080`. Gồm các trang: **Tổng quan**, **Auto-Chat**, **Reminder**, **Lịch sử**, **Log**, **Cấu hình** (chỉ xem).

> ⚠️ Mặc định dashboard chỉ lắng nghe `127.0.0.1`. Để truy cập từ xa, dùng SSH tunnel
> (`ssh -L 8080:127.0.0.1:8080 user@server`) hoặc đặt sau reverse proxy HTTPS và bật `DASHBOARD_SECURE_COOKIE=true`.
> Không mở thẳng `0.0.0.0` qua HTTP thường: mật khẩu sẽ đi không mã hóa.

## 📁 Cấu trúc

```
├── bot.py              # bot + slash commands
├── dashboard.py        # web server (aiohttp)
├── dashboard_views.py  # giao diện, phiên đăng nhập
├── config.py  db.py  utils.py
├── prompt.txt  .env.example  requirements.txt
└── tests/              # python -m unittest discover -s tests
```

## 🛡️ Bảo mật

Không commit `.env` hoặc `*.db` (đã có trong `.gitignore`). Nếu token / API key bị lộ, hãy thu hồi ngay.
Tin nhắn người dùng được lưu dạng văn bản thường trong SQLite và gửi tới Google Gemini; hãy thông báo điều này với thành viên server.

## 📜 License

MIT — xem `LICENSE` / `LICENSE.vi` (copy từ repo cũ).
