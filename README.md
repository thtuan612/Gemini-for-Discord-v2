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
- [Auto-Chat hoạt động thế nào](#-auto-chat-hoạt-động-thế-nào)
- [Web dashboard](#️-web-dashboard)
- [Triển khai trên server / Railway](#-triển-khai-trên-server--railway)
- [Cấu trúc dự án](#-cấu-trúc-dự-án)
- [Kiểm thử](#-kiểm-thử)
- [Bảo mật & quyền riêng tư](#️-bảo-mật--quyền-riêng-tư)
- [Hỗ trợ từ AI](#-hỗ-trợ-từ-ai)
- [License](#-license)
- [Tác giả](#-tác-giả)

## ✨ Tính năng

| | Tính năng | Chi tiết |
| --- | --- | --- |
| 💬 | **Trò chuyện với Gemini** | Dùng `/chat`, mention bot, hoặc bật **Auto-Chat** để kênh tự trả lời, không cần mention |
| 🖼️ | **Phân tích ảnh** | Tối đa 4 ảnh mỗi tin, 8 MB mỗi ảnh, định dạng png / jpg / webp / heic |
| 🧠 | **Lịch sử hội thoại riêng** | Tách theo từng người **và từng server**, giữ 10 lượt gần nhất, tự xóa sau 30 ngày không hoạt động |
| ⏰ | **Reminder** | Nhắc một lần hoặc hằng ngày, theo giờ Việt Nam |
| 📊 | **Giám sát** | Lệnh `/botinfo` và web dashboard |
| 🔐 | **An toàn** | Khóa bot theo server (`ALLOWED_GUILD_IDS`), phân quyền Admin/Owner, chặn ping `@everyone` / `@here` trong mọi tin nhắn của bot |
| ⚡ | **Ổn định** | Mỗi người xử lý 1 yêu cầu một lúc, giới hạn số request Gemini chạy song song, tự thử lại khi Gemini lỗi tạm thời hoặc bị giới hạn tốc độ (429), tự chia tin nhắn dài |

## 🚀 Cài đặt nhanh

### Yêu cầu

- Python **3.10+**
- Discord Bot Token
- Gemini API Key
- Bật **MESSAGE CONTENT INTENT** trong [Discord Developer Portal](https://discord.com/developers/applications)
  (**SERVER MEMBERS INTENT** chỉ cần khi đặt `MEMBERS_INTENT=true`)
- Khi mời bot vào server, chọn scope `bot` và `applications.commands`

### Các bước

```bash
git clone https://github.com/thtuan612/Gemini-for-Discord-v2.git
cd Gemini-for-Discord-v2
pip install -r requirements.txt
cp .env.example .env    # rồi điền DISCORD_TOKEN và GEMINI_API_KEY
python bot.py
```

Thư viện sử dụng (`requirements.txt`): `discord.py`, `python-dotenv`, `google-genai`, `psutil`, `aiohttp`.

## ⚙️ Cấu hình

Toàn bộ biến môi trường có chú thích trong [`.env.example`](.env.example). Biến nào để trống sẽ dùng giá trị mặc định.

### Bắt buộc

| Biến | Mô tả |
| --- | --- |
| `DISCORD_TOKEN` | Token của Discord bot |
| `GEMINI_API_KEY` | API key của Google Gemini |

### Gemini

| Biến | Mặc định | Mô tả |
| --- | --- | --- |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Model Gemini sử dụng |
| `MAX_OUTPUT_TOKENS` | `1024` | Giới hạn độ dài câu trả lời |
| `THINKING_LEVEL` | *(trống)* | `minimal` / `low` / `medium` / `high`. Để trống = mặc định của model |
| `THINKING_BUDGET` | *(trống)* | Cách cũ, chỉ dùng khi `THINKING_LEVEL` để trống (nếu đặt cả hai thì `THINKING_LEVEL` được ưu tiên) |
| `GEMINI_TEMPERATURE` | *(trống)* | Để trống = không gửi tham số (Google khuyến nghị không chỉnh với Gemini 3.x) |
| `GEMINI_TIMEOUT` | `30` | Timeout mỗi lần gọi Gemini (giây) |
| `GEMINI_CONCURRENCY` | `4` | Số request Gemini chạy song song tối đa |
| `GEMINI_429_RETRY_SECONDS` | `3` | Chờ bao lâu rồi thử lại 1 lần khi bị 429 (`0` = không thử lại) |

### Hội thoại & ảnh

| Biến | Mặc định | Mô tả |
| --- | --- | --- |
| `MAX_HISTORY_TURNS` | `10` | Số lượt hội thoại được nhớ cho mỗi người ở mỗi server |
| `HISTORY_RETENTION_DAYS` | `30` | Tự xóa lịch sử không hoạt động sau N ngày (`0` = không tự xóa) |
| `MAX_IMAGES` | `4` | Số ảnh tối đa mỗi tin nhắn |
| `MAX_IMAGE_MB` | `8` | Dung lượng tối đa mỗi ảnh (MB) |

### Discord & phân quyền

| Biến | Mặc định | Mô tả |
| --- | --- | --- |
| `ALLOWED_GUILD_IDS` | *(trống)* | Giới hạn bot chỉ hoạt động ở các server này (ID cách nhau bằng dấu phẩy). Server khác: lệnh bị từ chối và bot tự rời khi được mời |
| `AUTO_CHAT_CHANNEL_IDS` | *(trống)* | Kênh Auto-Chat có sẵn khi khởi động |
| `ADMIN_ROLE_IDS` | *(trống)* | ID các role được coi là Admin của bot (ngoài Owner và người có quyền Administrator) |
| `ADMIN_ROLE_NAMES` | *(trống)* | Khớp role theo tên, mặc định tắt vì dễ bị giả mạo. Chỉ bật khi thật sự cần |
| `MEMBERS_INTENT` | `false` | Đặt `true` nếu đã bật SERVER MEMBERS INTENT (để bot đếm được số bot / thành viên thật) |
| `SYNC_ON_START` | `true` | Đồng bộ slash commands mỗi lần khởi động |
| `STATUS_TYPE` / `STATUS_TEXT` | `playing` / `Where Winds Meet` | Trạng thái hiển thị của bot (`playing`, `listening`, `watching`, `competing`) |
| `AUTO_CHAT_COOLDOWN_SECONDS` | `3` | Mỗi người chỉ kích hoạt Auto-Chat 1 lần / N giây trong một kênh (`0` = tắt) |

### Reminder & database

| Biến | Mặc định | Mô tả |
| --- | --- | --- |
| `REMINDER_GRACE_MINUTES` | `10` | Trễ quá số phút này thì reminder hằng ngày bị bỏ lượt, reminder một lần được gửi kèm "(nhắc trễ)" |
| `MAX_REMINDERS_PER_USER` | `20` | Số reminder đang chạy tối đa của mỗi người ở mỗi server |
| `MAX_REMINDER_LENGTH` | `1500` | Độ dài tối đa nội dung nhắc |
| `REMINDER_RETENTION_DAYS` | `30` | Xóa reminder đã tắt sau N ngày (`0` = giữ mãi) |
| `DB_PATH` | `conversations.db` | Đường dẫn file SQLite |
| `SYSTEM_PROMPT` | *(trống)* | Nếu đặt, dùng thay cho nội dung `prompt.txt` |

### Web dashboard

| Biến | Mặc định | Mô tả |
| --- | --- | --- |
| `DASHBOARD_ENABLED` | `false` | Đặt `true` để bật web dashboard |
| `DASHBOARD_HOST` | `127.0.0.1` | Địa chỉ lắng nghe |
| `DASHBOARD_PORT` | `8080` | Cổng lắng nghe |
| `DASHBOARD_PASSWORD` | *(trống)* | Mật khẩu đăng nhập (nên dài ít nhất 12 ký tự) |
| `DASHBOARD_SECURE_COOKIE` | `false` | Đặt `true` khi truy cập qua HTTPS |

System prompt (tính cách) của bot nằm ở [`prompt.txt`](prompt.txt), có thể chỉnh để đổi cách trả lời.

## 📖 Lệnh

| Lệnh | Ai dùng | Mô tả |
| --- | --- | --- |
| `/chat message [image]` | Mọi người | Trò chuyện với Gemini (có thể kèm 1 ảnh) |
| `/reset` | Mọi người | Xóa lịch sử hội thoại của bạn ở server này |
| `/remind time message repeat [channel]` | Mọi người | Đặt nhắc theo giờ Việt Nam, định dạng `HH:MM` (24h), `repeat` là một lần hoặc hằng ngày. Cần quyền gửi tin ở kênh đích |
| `/remind_list` | Mọi người | Xem các reminder đang hoạt động trong server |
| `/remind_cancel id` | Người tạo hoặc Admin | Hủy reminder theo ID |
| `/autochat_list` | Mọi người | Xem các kênh Auto-Chat |
| `/autochat_add [channel]` | Admin/Owner | Bật Auto-Chat cho một kênh (mặc định: kênh hiện tại) |
| `/autochat_remove [channel]` | Admin/Owner | Tắt Auto-Chat |
| `/botinfo` | Admin/Owner | Xem ping, uptime, RAM, disk, dung lượng DB, model đang dùng... |

Ngoài slash commands, bạn có thể **mention bot** ở bất kỳ kênh nào để trò chuyện. Slash commands chỉ dùng được trong server (không dùng trong tin nhắn riêng).

> **Admin/Owner** gồm: chủ server, người có quyền Administrator, hoặc thành viên có role nằm trong `ADMIN_ROLE_IDS`.

## 📣 Auto-Chat hoạt động thế nào

Ở kênh được bật Auto-Chat, bot đọc tin nhắn và tự trả lời mà không cần mention. Để tránh trả lời bừa và tiết kiệm lượt gọi Gemini:

- Tin chỉ có emoji, link hoặc sticker (không có chữ/số, không kèm ảnh) sẽ bị bỏ qua.
- Mỗi người chỉ kích hoạt bot 1 lần mỗi vài giây trong một kênh (`AUTO_CHAT_COOLDOWN_SECONDS`).
- Tin nhắn trả lời (reply) tin của người khác, hoặc mention thành viên khác mà không mention bot, bị bỏ qua.
- Gemini được hướng dẫn chỉ im lặng khi có bằng chứng rõ ràng tin nhắn đang nói với người khác.

Nếu tin nhắn có mention bot thì bot luôn xử lý, kể cả trong kênh Auto-Chat.

## 🖥️ Web dashboard

Bật trong `.env`:

```env
DASHBOARD_ENABLED=true
DASHBOARD_PASSWORD=mot-mat-khau-dai-it-nhat-12-ky-tu
```

Sau đó mở <http://127.0.0.1:8080>. Giao diện kính mờ, tự chuyển sáng/tối theo thiết bị và dùng được trên cả điện thoại lẫn máy tính. Dashboard gồm các trang:

| Trang | Chức năng |
| --- | --- |
| **Tổng quan** | Ping, uptime, RAM, disk, dung lượng DB, số server / thành viên / reminder / kênh Auto-Chat |
| **Reminder** | Xem và hủy reminder đang hoạt động |
| **Auto-Chat** | Thêm / bỏ kênh Auto-Chat |
| **Lịch sử** | Dọn lịch sử cũ, xóa lịch sử của một người, xóa toàn bộ, xóa cache |
| **Log** | Xem log gần đây (tự che token, API key, mật khẩu) |
| **Cấu hình** | Xem cấu hình hiện tại (chỉ xem, không sửa được) |

**Đổi hình nền:** thay file `static/bg.jpg` bằng ảnh của bạn (giữ nguyên tên). Server tự nhận ảnh mới và trình duyệt sẽ tải lại ngay. Nếu xóa file, giao diện quay về nền gradient.

### Bảo mật của dashboard

- Đăng nhập bằng mật khẩu, so sánh an toàn thời gian (`hmac.compare_digest`).
- Giới hạn đăng nhập sai: 8 lần sai liên tiếp từ một IP thì bị chặn 10 phút.
- Phiên đăng nhập hết hạn sau 7 ngày; cookie `HttpOnly`, `SameSite=Strict`, và `Secure` khi bật `DASHBOARD_SECURE_COOKIE`.
- Mọi thao tác thay đổi dữ liệu sau khi đăng nhập (POST) đều yêu cầu **CSRF token**.
- Các header bảo mật: `Content-Security-Policy`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Permissions-Policy`, `Cache-Control: no-store`.
- Chỉ các đường dẫn `/login`, `/dashboard.css`, `/static/login.js`, `/bg.jpg` mở công khai; còn lại cần đăng nhập.

> [!WARNING]
> Mặc định dashboard chỉ lắng nghe trên `127.0.0.1`. Để truy cập từ xa, hãy dùng SSH tunnel:
>
> ```bash
> ssh -L 8080:127.0.0.1:8080 user@server
> ```
>
> hoặc đặt sau reverse proxy HTTPS và bật `DASHBOARD_SECURE_COOKIE=true`.
> **Không** mở thẳng `0.0.0.0` qua HTTP thường, vì mật khẩu sẽ đi không mã hóa.

## ☁️ Triển khai trên server / Railway

Khi chạy trên nền tảng như Railway, hãy lưu ý:

1. Nhập các biến môi trường ở mục **Variables** của nền tảng thay cho file `.env`. Nếu bạn từng đặt `GEMINI_MODEL`, biến này sẽ ghi đè giá trị mặc định trong code.
2. **Database:** đặt `DB_PATH` trỏ vào một **Volume** (ví dụ `/data/conversations.db`) để lịch sử, reminder và danh sách Auto-Chat không mất sau mỗi lần deploy.
3. **Dashboard:** đặt `DASHBOARD_HOST=0.0.0.0`, `DASHBOARD_PORT` khớp với cổng mà nền tảng định tuyến tới, và `DASHBOARD_SECURE_COOKIE=true` (nền tảng cung cấp HTTPS). Dùng mật khẩu dài và duy nhất.
4. Khởi chạy bằng lệnh `python bot.py`.

## 📁 Cấu trúc dự án

```text
.
├── bot.py                # Bot Discord, slash commands, gọi Gemini
├── config.py             # Đọc cấu hình từ .env / biến môi trường
├── db.py                 # Lưu trữ SQLite (lịch sử, reminder, Auto-Chat)
├── utils.py              # Hàm tiện ích
├── dashboard.py          # Web server (aiohttp), routes, bảo mật
├── dashboard_views.py    # Giao diện, phiên đăng nhập, giới hạn đăng nhập
├── prompt.txt            # System prompt (tính cách của bot)
├── requirements.txt
├── .env.example          # Mẫu biến môi trường
├── .gitignore
├── LICENSE.txt
├── static/
│   ├── dashboard.css     # Giao diện dashboard
│   ├── login.js          # Script trang đăng nhập
│   └── bg.jpg            # Hình nền dashboard
├── templates/
│   ├── dashboard.html    # Khung giao diện dashboard
│   └── login.html        # Trang đăng nhập
└── tests/                # Bộ kiểm thử
    ├── test_core.py
    ├── test_dashboard_views.py
    └── test_performance.py
```

## 🧪 Kiểm thử

```bash
python -m unittest discover -s tests
```

## 🛡️ Bảo mật & quyền riêng tư

- **Không commit** `.env` hoặc `*.db` (đã có trong `.gitignore`). Không đưa token, API key, mật khẩu vào code.
- Nếu token hoặc API key bị lộ, hãy **thu hồi ngay** trên Discord Developer Portal / Google AI Studio.
- Tin nhắn của người dùng được lưu dạng văn bản thường trong SQLite (chỉ lưu chữ, không lưu ảnh) và được gửi tới Google Gemini để xử lý. Hãy thông báo điều này với thành viên server của bạn.
- Người dùng có thể tự xóa lịch sử của mình bằng `/reset`; Admin có thể xóa qua dashboard.

## 🤖 Hỗ trợ từ AI

Dự án này được xây dựng và cải tiến **với sự hỗ trợ của AI**. **Claude AI (Anthropic)** đã hỗ trợ trong quá trình phát triển, gồm: rà soát và viết code, sửa lỗi, tối ưu hiệu suất, viết test và soạn tài liệu. Tác giả là người định hướng, kiểm tra và chịu trách nhiệm cho kết quả cuối cùng.

## 📜 License

Phát hành theo giấy phép **MIT**. Xem file [`LICENSE.txt`](LICENSE.txt).

## 👤 Tác giả

**ThTuan** · Discord: `@lmtuan612` · GitHub: [@thtuan612](https://github.com/thtuan612)
