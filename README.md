<div align="center">

# 🤖 Gemini for Discord v2

**Bot Discord tiếng Việt mạnh mẽ tích hợp Google Gemini AI, hỗ trợ ngữ cảnh hội thoại đa phương thức và bảng điều khiển quản trị tương tác trực tiếp trên Discord.**

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![discord.py](https://img.shields.io/badge/discord.py-2.4%2B-5865F2?logo=discord&logoColor=white)
![Google Gemini](https://img.shields.io/badge/Google-Gemini_SDK-4285F4?logo=google&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-WAL_Mode-003B57?logo=sqlite&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)

</div>

---

## 📑 Mục lục

- [✨ Tính năng nổi bật](#-tính-năng-nổi-bật)
- [🚀 Hướng dẫn cài đặt](#-hướng-dẫn-cài-đặt)
- [⚙️ Cấu hình biến môi trường](#️-cấu-hình-biến-môi-trường)
- [📖 Danh sách lệnh Slash](#-danh-sách-lệnh-slash)
- [📊 Bảng điều khiển tương tác (/botinfo)](#-bảng-điều-khiển-tương-tác-botinfo)
- [📁 Cấu trúc thư mục](#-cấu-trúc-thư-mục)
- [🧪 Kiểm thử (Testing)](#-kiểm-thử-testing)
- [🛡️ Bảo mật & Tối ưu](#️-bảo-mật--tối-ưu)
- [📜 Giấy phép](#-giấy-phép)
- [👤 Tác giả](#-tác-giả)

---

## ✨ Tính năng nổi bật

| Biểu tượng | Tính năng | Chi tiết |
| :---: | :--- | :--- |
| 💬 | **Trò chuyện thông minh** | Dùng slash command `/chat`, mention bot `@Bot`, hoặc bật chế độ **Auto-Chat** để bot tự tham gia trò chuyện mà không cần ping. |
| 🧠 | **Hiểu ngữ cảnh kênh chat** | Tự động đọc các tin nhắn gần nhất trong kênh và tin nhắn trích dẫn (reply/quote) để hiểu đại từ ("nó", "đó", "họ") và trả lời đúng mạch đàm thoại. |
| 🖼️ | **Phân tích hình ảnh (Vision)** | Hỗ trợ tải song song tối đa 4 ảnh (`png`, `jpg`, `webp`, `heic`), kích thước lên tới 8 MB mỗi ảnh. |
| ⚡ | **Hỗ trợ Gemini 3.x & Thinking** | Tương thích SDK `google-genai` mới nhất, cấu hình được mức độ suy nghĩ (`THINKING_LEVEL`), tự động retry khi gặp lỗi 429 hoặc quá tải tạm thời. |
| 🎛️ | **Bảng điều khiển tương tác** | Giao diện nút bấm và menu chọn (Discord UI Components) tích hợp ngay trong `/botinfo` để quản lý Auto-Chat và danh sách server cho phép. |
| 🔒 | **Phân tách dữ liệu & Chặn spam** | Lưu lịch sử hội thoại riêng biệt theo từng cặp `(guild_id, user_id)`, kiểm soát hàng đợi tối đa 3 tác vụ/user để tránh nghẽn. |
| 🛡️ | **An toàn & Anti-mention** | Mặc định cấu hình `allowed_mentions=NO_MENTIONS` triệt tiêu nguy cơ AI bị lợi dụng để tag `@everyone`, `@here` hoặc role spam. |

---

## 🚀 Hướng dẫn cài đặt

### Yêu cầu tiên quyết

1. **Python 3.10+**
2. **Discord Bot Token** từ [Discord Developer Portal](https://discord.com/developers/applications):
   - Bật **MESSAGE CONTENT INTENT** trong mục **Bot** -> **Privileged Gateway Intents**.
   - *(Tùy chọn)* Bật **SERVER MEMBERS INTENT** nếu muốn bot thống kê chính xác số lượng bot/người thật trong server (`MEMBERS_INTENT=true`).
3. **Gemini API Key** từ [Google AI Studio](https://aistudio.google.com/).

### Các bước triển khai

```bash
# 1. Clone repository
git clone https://github.com/thtuan612/Gemini-for-Discord-v2.git
cd Gemini-for-Discord-v2

# 2. Tạo môi trường ảo (khuyến nghị)
python3 -m venv .venv
source .venv/bin/activate  # Trên Linux/macOS
# .venv\Scripts\activate   # Trên Windows

# 3. Cài đặt các gói phụ thuộc
pip install -r requirements.txt

# 4. Thiết lập biến môi trường
cp .env.example .env
# Mở file .env và điền DISCORD_TOKEN cùng GEMINI_API_KEY

# 5. Chạy bot
python bot.py
```

---

## ⚙️ Cấu hình biến môi trường

Chi tiết đầy đủ các tùy chọn cấu hình trong [`.env.example`](.env.example):

### Bắt buộc
- `DISCORD_TOKEN`: Token bí mật của Discord Bot.
- `GEMINI_API_KEY`: Khóa API Google Gemini (bắt buộc khi `GEMINI_ENABLED=true`).

### Gemini AI
- `GEMINI_ENABLED`: Bật/tắt provider Gemini (mặc định: `true`).
- `GEMINI_MODEL`: Model Gemini chính (mặc định: `gemini-3.5-flash-lite`).
- `GEMINI_FALLBACK_MODELS`: Các model dự phòng, cách nhau bằng dấu phẩy. Bot thử lần lượt khi model trước gặp quota, 429 hoặc lỗi tạm thời (5xx, timeout).
- `MAX_OUTPUT_TOKENS`: Giới hạn token đầu ra (mặc định: `1024`).
- `THINKING_LEVEL`: Mức suy nghĩ của mô hình (`minimal`, `low`, `medium`, `high`, hoặc để trống).
- `GEMINI_TIMEOUT`: Thời gian chờ tối đa cho mỗi request (giây, mặc định: `30`).
- `GEMINI_CONCURRENCY`: Số lượng yêu cầu Gemini được xử lý đồng thời (mặc định: `4`).
- `GEMINI_429_RETRY_SECONDS`: Thời gian chờ tự động thử lại khi chạm giới hạn tần suất (giây, mặc định: `3`).

### Literouter (OpenAI-compatible)
- `LITEROUTER_ENABLED`: Bật/tắt provider Literouter (mặc định: `false`).
- `LITEROUTER_API_KEY`: API Key Literouter (chỉ đặt trong `.env`, không ghi vào source).
- `LITEROUTER_BASE_URL`: Mặc định `https://literouter.fun/api/v1`.
- `LITEROUTER_MODEL`: Model mặc định. Để trống = dùng model đầu tiên trong danh sách `/models`.
- `LITEROUTER_MODELS_REFRESH_HOURS`: Chu kỳ làm mới danh sách model (mặc định: `6`). Danh sách được cache ra file (`LITEROUTER_CACHE_PATH`, mặc định cạnh file DB) và dùng lại khi API tạm ngừng.
- `LITEROUTER_TIMEOUT`: Timeout mỗi request (giây, mặc định: `30`).
- `AI_PROVIDER_ORDER`: Thứ tự thử provider (mặc định: `gemini,literouter`).

### Discord & Quản trị
- `ALLOWED_GUILD_IDS`: Danh sách ID server được phép hoạt động (cách nhau bởi dấu phẩy, để trống = mở tất cả).
- `AUTO_CHAT_CHANNEL_IDS`: Danh sách ID kênh bật sẵn chế độ tự động trò chuyện.
- `ADMIN_ROLE_IDS`: ID các role có quyền Admin điều khiển bot (bên cạnh Owner và quyền Administrator).
- `AUTO_CHAT_COOLDOWN_SECONDS`: Giãn cách tối thiểu giữa các lần kích hoạt auto-chat của 1 người dùng (mặc định: `3` giây).
- `CHANNEL_HISTORY_LIMIT`: Số tin nhắn gần nhất Auto-Chat/mention và `/chat` đọc để tạo ngữ cảnh (mặc định: `5`, đặt `0` để tắt).
- `CHAT_INCLUDE_CHANNEL_CONTEXT`: Cho phép `/chat` gửi lịch sử kênh (có thể chứa tin nhắn của thành viên khác) tới AI provider; mặc định `true`. Đặt `false` nếu muốn `/chat` chỉ dùng lịch sử riêng của người gọi.
- `STATUS_TYPE` & `STATUS_TEXT`: Trạng thái hoạt động hiển thị của bot (ví dụ: `playing`, `Where Winds Meet`).

### Cơ sở dữ liệu
- `DB_PATH`: Đường dẫn file SQLite (mặc định: `conversations.db`).
- `HISTORY_RETENTION_DAYS`: Tự động xóa lịch sử hội thoại sau N ngày (mặc định: `30`, `0` = giữ mãi).

> [!TIP]
> Bạn có thể tùy chỉnh tính cách, phong cách xưng hô và chỉ dẫn hệ thống của bot bằng cách chỉnh sửa trực tiếp nội dung file [`prompt.txt`](prompt.txt).

---

## 📖 Danh sách lệnh Slash

| Lệnh | Quyền hạn | Mô tả |
| :--- | :---: | :--- |
| `/chat <message> [image]` | Mọi người | Gửi câu hỏi kèm hình ảnh (tùy chọn) để trò chuyện cùng AI. |
| `/reset` | Mọi người | Xóa sạch ngữ cảnh lịch sử trò chuyện của chính bạn tại server hiện tại. |
| `/autochat_list` | Mọi người | Liệt kê các kênh text đang bật tính năng Auto-Chat trong server. |
| `/autochat_add [channel]` | Admin / Owner | Kích hoạt Auto-Chat cho kênh chỉ định (hoặc kênh hiện tại). |
| `/autochat_remove [channel]` | Admin / Owner | Tắt tính năng Auto-Chat tại kênh chỉ định. |
| `/botinfo` | Admin / Owner | Mở **Bảng điều khiển tương tác** xem tài nguyên hệ thống và quản trị bot. |

---

## 📊 Bảng điều khiển tương tác (`/botinfo`)

Lệnh `/botinfo` cung cấp giao diện quản trị trực quan với các thành phần Discord UI Components:

1. **Thông số thời gian thực:** Ping, Uptime, RAM/Disk usage, phiên bản Python & discord.py, provider AI và kênh auto-chat.
2. **Quản lý Auto-Chat:**
   - Chọn nhanh bất kỳ kênh text nào qua menu chọn kênh (`ChannelSelect`) để bật/tắt.
   - Nút bật/tắt nhanh ngay tại kênh đang mở bảng điều khiển.
   - Danh sách kênh được lưu trong SQLite (`DB_PATH`) và tự nạp lại khi khởi động; `AUTO_CHAT_CHANNEL_IDS` chỉ là danh sách bật sẵn bổ sung.

---

## 📁 Cấu trúc thư mục

```text
.
├── bot.py               # Xử lý sự kiện Discord, slash commands, quản lý state và gọi Gemini API
├── config.py            # Nạp và chuẩn hóa cấu hình từ biến môi trường (.env)
├── literouter.py        # Client Literouter (OpenAI-compatible) + danh sách model tự cập nhật/cache
├── db.py                # Wrapper SQLite async (WAL mode, migrations, CRUD lịch sử)
├── utils.py             # Các hàm tiện ích: cắt tin nhắn, lọc tin trivial, tính dung lượng, parse giờ
├── prompt.txt           # System prompt mặc định định hình phong cách phản hồi của AI
├── .env.example         # File mẫu cấu hình các biến môi trường
├── requirements.txt     # Danh sách thư viện Python cần thiết
├── LICENSE.txt          # Giấy phép mã nguồn mở MIT
└── tests/               # Bộ unit test toàn diện
    ├── __init__.py
    ├── test_core.py     # Test suite: utils, database, channel context và retry logic Gemini
    └── test_providers.py # Test fallback Gemini, client Literouter, cache danh sách model
```

---

## 🧪 Kiểm thử (Testing)

Dự án đi kèm bộ kiểm thử toàn diện kiểm tra tính đúng đắn của logic xử lý chuỗi, cơ sở dữ liệu SQLite đa luồng và các trường hợp lỗi API (mock):

```bash
# Chạy toàn bộ test suite
python -m unittest tests/test_core.py -v
```

**Các nhóm kiểm thử chính:**
- `UtilsTests`: Kiểm tra giới hạn và cách chia đoạn văn bản (`split_message`).
- `DatabaseTests`: Kiểm tra phân tách dữ liệu theo Guild/User, transaction an toàn, tự động dọn dẹp (purge), migration và bảo toàn dữ liệu hiện có.
- `ChannelContextTests`: Kiểm tra định dạng ngữ cảnh các tin nhắn gần nhất và tin nhắn trích dẫn.
- `AskGeminiRetryTests`: Giả lập các phản hồi lỗi từ Google Gemini (429 Rate Limit, 5xx Server Error, Timeout, Client Error) để đảm bảo bot retry và phản hồi chính xác.

---

## 🛡️ Bảo mật & Tối ưu

- **Bảo mật bí mật:** File `.env` và các tệp dữ liệu SQLite (`*.db`, `*.db-wal`) đã được cấu hình trong `.gitignore` để không bao giờ bị lộ lên Git repository.
- **Tối ưu bộ nhớ cache:** Áp dụng LRU có TTL 5 phút cho lịch sử chat; dữ liệu cũ được nạp lại từ SQLite thay vì giữ vô thời hạn trong RAM.
- **Quyền riêng tư dữ liệu:** `/chat` đọc tối đa 5 tin nhắn gần nhất trong kênh theo mặc định (có thể tắt bằng `CHAT_INCLUDE_CHANNEL_CONTEXT=false`); retention tự động xóa lịch sử sau 30 ngày, SQLite bật `secure_delete`, giới hạn quyền file DB ở `0600` trên hệ thống POSIX và checkpoint WAL sau thao tác xóa.
- **Xử lý bất đồng bộ chuẩn mực:** Mọi thao tác I/O với database và filesystem đều được đưa vào thread pool (`asyncio.to_thread`), tránh block event loop chính của Discord.

---

## 📜 Giấy phép

Dự án được phân phối dưới giấy phép **MIT License**. Chi tiết xem tại file [`LICENSE.txt`](LICENSE.txt).

---

## 👤 Tác giả

- **ThTuan**
  - Discord: `@lmtuan612`
  - GitHub: [@thtuan612](https://github.com/thtuan612)
