<div align="center">

# 🤖 Gemini for Discord v2

**Bot Discord tiếng Việt tích hợp Google Gemini, kèm web dashboard để quản lý.**

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![discord.py](https://img.shields.io/badge/discord.py-2.x-5865F2?logo=discord&logoColor=white)
![Gemini](https://img.shields.io/badge/Google-Gemini-4285F4?logo=google&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-003B57?logo=sqlite&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)

</div>

---

## 📑 Mục lục

- [Tính năng](#-tính-năng)
- [Cài đặt nhanh](#-cài-đặt-nhanh)
- [Cấu hình](#️-cấu-hình)
- [Lệnh](#-lệnh)
- [Web dashboard](#️-web-dashboard)
- [Cấu trúc dự án](#-cấu-trúc-dự-án)
- [Kiểm thử](#-kiểm-thử)
- [Bảo mật & quyền riêng tư](#️-bảo-mật--quyền-riêng-tư)
- [License](#-license)
- [Tác giả](#-tác-giả)

## ✨ Tính năng

| | Tính năng | Chi tiết |
| --- | --- | --- |
| 💬 | **Trò chuyện với Gemini** | Dùng `/chat`, mention bot, hoặc bật **Auto-Chat** để kênh tự trả lời, không cần mention |
| 🖼️ | **Phân tích ảnh** | Tối đa 4 ảnh mỗi tin, 8 MB mỗi ảnh, định dạng png / jpg / webp / heic |
| 🧠 | **Lịch sử hội thoại riêng** | Tách theo từng người **và từng server**, tự xóa sau 30 ngày |
| ⏰ | **Reminder** | Nhắc một lần hoặc hằng ngày, theo giờ Việt Nam |
| 📊 | **Giám sát** | Lệnh `/botinfo` và web dashboard |
| 🔐 | **An toàn** | Khóa bot theo server (`ALLOWED_GUILD_IDS`), chặn ping `@everyone` / `@here` trong mọi tin nhắn của bot |

## 🚀 Cài đặt nhanh

### Yêu cầu

- Python **3.10+**
- Discord Bot Token
- Gemini API Key
- Bật **MESSAGE CONTENT INTENT** trong [Discord Developer Portal](https://discord.com/developers/applications)
  (**SERVER MEMBERS INTENT** chỉ cần khi đặt `MEMBERS_INTENT=true`)

### Các bước

```bash
git clone https://github.com/thtuan612/Gemini-for-Discord-v2.git
cd Gemini-for-Discord-v2
pip install -r requirements.txt
cp .env.example .env    # rồi điền DISCORD_TOKEN và GEMINI_API_KEY
python bot.py
```

## ⚙️ Cấu hình

Toàn bộ biến môi trường có chú thích trong [`.env.example`](.env.example). Một số biến thường dùng:

| Biến | Bắt buộc | Mô tả |
| --- | :---: | --- |
| `DISCORD_TOKEN` | ✅ | Token của Discord bot |
| `GEMINI_API_KEY` | ✅ | API key của Google Gemini |
| `ALLOWED_GUILD_IDS` | | Giới hạn bot chỉ hoạt động ở các server được liệt kê |
| `ADMIN_ROLE_IDS` | | ID các role được coi là Admin của bot |
| `MEMBERS_INTENT` | | Đặt `true` nếu đã bật SERVER MEMBERS INTENT |
| `DASHBOARD_ENABLED` | | Đặt `true` để bật web dashboard |
| `DASHBOARD_PASSWORD` | | Mật khẩu đăng nhập dashboard (nên dài ít nhất 12 ký tự) |
| `DASHBOARD_SECURE_COOKIE` | | Đặt `true` khi chạy sau reverse proxy HTTPS |

System prompt của bot nằm ở [`prompt.txt`](prompt.txt), có thể chỉnh để đổi tính cách và cách trả lời.

## 📖 Lệnh

| Lệnh | Ai dùng | Mô tả |
| --- | --- | --- |
| `/chat message [image]` | Mọi người | Trò chuyện với Gemini |
| `/reset` | Mọi người | Xóa lịch sử của bạn ở server này |
| `/remind time message repeat [channel]` | Mọi người | Đặt nhắc (cần quyền gửi tin ở kênh đích) |
| `/remind_list` | Mọi người | Xem danh sách reminder |
| `/remind_cancel id` | Mọi người | Hủy reminder (chỉ người tạo hoặc Admin được hủy) |
| `/autochat_list` | Mọi người | Xem các kênh Auto-Chat |
| `/autochat_add` | Admin/Owner | Bật Auto-Chat cho một kênh |
| `/autochat_remove` | Admin/Owner | Tắt Auto-Chat |
| `/botinfo` | Admin/Owner | Xem thông số bot |

> **Admin/Owner** gồm: chủ server, người có quyền Administrator, hoặc thành viên có role nằm trong `ADMIN_ROLE_IDS`.

## 🖥️ Web dashboard

Bật trong `.env`:

```env
DASHBOARD_ENABLED=true
DASHBOARD_PASSWORD=mot-mat-khau-dai-it-nhat-12-ky-tu
```

Sau đó mở <http://127.0.0.1:8080>. Dashboard gồm các trang:

**Tổng quan** · **Auto-Chat** · **Reminder** · **Lịch sử** · **Log** · **Cấu hình** (chỉ xem)

> [!WARNING]
> Mặc định dashboard chỉ lắng nghe trên `127.0.0.1`. Để truy cập từ xa, hãy dùng SSH tunnel:
>
> ```bash
> ssh -L 8080:127.0.0.1:8080 user@server
> ```
>
> hoặc đặt sau reverse proxy HTTPS và bật `DASHBOARD_SECURE_COOKIE=true`.
> **Không** mở thẳng `0.0.0.0` qua HTTP thường, vì mật khẩu sẽ đi không mã hóa.

## 📁 Cấu trúc dự án

```text
.
├── bot.py               # Bot + slash commands
├── dashboard.py         # Web server (aiohttp)
├── dashboard_views.py   # Giao diện, phiên đăng nhập
├── config.py            # Đọc cấu hình từ .env
├── db.py                # Lưu trữ SQLite
├── utils.py             # Hàm tiện ích
├── prompt.txt           # System prompt
├── .env.example         # Mẫu biến môi trường
├── requirements.txt
├── CHANGELOG.md
└── tests/               # Bộ kiểm thử
```

## 🧪 Kiểm thử

```bash
python -m unittest discover -s tests
```

## 🛡️ Bảo mật & quyền riêng tư

- Không commit `.env` hoặc `*.db` (đã có trong `.gitignore`).
- Nếu token hoặc API key bị lộ, hãy **thu hồi ngay** trên Discord Developer Portal / Google AI Studio.
- Tin nhắn của người dùng được lưu dạng văn bản thường trong SQLite và được gửi tới Google Gemini để xử lý. Hãy thông báo điều này với thành viên server của bạn.

## 📜 License

Phát hành theo giấy phép **MIT**. Xem file [`LICENSE`](LICENSE).

## 👤 Tác giả

**ThTuan** · Discord: `@lmtuan612` · GitHub: [@thtuan612](https://github.com/thtuan612)
