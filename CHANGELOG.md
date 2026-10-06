# Thay đổi

## Web dashboard (mới)
- Bật bằng `DASHBOARD_ENABLED=true` + `DASHBOARD_PASSWORD` (≥ 12 ký tự). Mặc định chỉ lắng nghe `127.0.0.1`.
- Trang: Tổng quan (thông số như `/botinfo` + danh sách server), Auto-Chat (bật/tắt kênh), Reminder (xem/hủy),
  Lịch sử (dọn theo ngày / theo user / toàn bộ / cache), Log (300 dòng gần nhất, đã che token), Cấu hình (chỉ xem).
- Bảo mật: cookie `HttpOnly` + `SameSite=Strict`, CSRF token cho mọi POST, giới hạn 5 lần sai/10 phút/IP,
  CSP chặt, không dùng JavaScript, escape toàn bộ dữ liệu hiển thị.
- Không có thêm dependency ngoài `aiohttp` (vốn đã đi kèm discord.py).

## Bảo mật
- `AllowedMentions.none()` đặt làm mặc định cho bot + mọi reminder → không thể ping @everyone/@here/role.
- `/remind_cancel`: chỉ hủy được reminder của server mình; chỉ người tạo hoặc Admin/Owner mới hủy.
- `/remind`: kiểm tra quyền gửi tin của người dùng *và* của bot ở kênh đích; giới hạn số lượng và độ dài.
- Quyền admin: Owner / quyền Administrator / `ADMIN_ROLE_IDS`. So khớp theo tên role chỉ còn khi đặt `ADMIN_ROLE_NAMES`.
- Mọi slash command chỉ chạy trong server nằm trong `ALLOWED_GUILD_IDS` (trước đây DM bot vẫn dùng được `/chat`).

## Độ tin cậy
- Bỏ `pending_users` (kẹt vĩnh viễn khi lỗi) → khóa theo người dùng, luôn tự giải phóng; tin nhắn auto-chat xếp hàng thay vì bị bỏ.
- SQLite: 1 connection dùng chung, chạy trong thread, bật WAL → không còn block event loop.
- `RELEVANCE_INSTRUCTION` chuyển sang system instruction (không còn bị lưu vào lịch sử).
- Lịch sử khóa theo `(guild_id, user_id)`, cache LRU 500 mục. Bảng `conversations` cũ bị xóa (bảng mới: `chat_history`).
- Giới hạn ảnh: tối đa 4 ảnh, 8 MB, chỉ png/jpeg/webp/heic/heif.
- Bắt mọi exception khi gọi Gemini + timeout 60s + semaphore giới hạn song song.
- `MAX_OUTPUT_TOKENS` mặc định 1024, phát hiện bị cắt (`MAX_TOKENS`); `THINKING_BUDGET` tùy chọn.
- Reminder lỡ giờ: daily bị bỏ qua, once gửi kèm "(nhắc trễ)". Vòng lặp reminder không còn chết khi gặp lỗi.
- `tree.sync()` chạy 1 lần ở `setup_hook` (tắt bằng `SYNC_ON_START=false`).
- Sửa vòng lặp vô hạn của `split_message` khi chuỗi bắt đầu bằng xuống dòng; sửa lỗi với tin nhắn được reply đã bị xóa.

## Quyền riêng tư
- Tự xóa lịch sử cũ hơn `HISTORY_RETENTION_DAYS` (mặc định 30 ngày).
- `SERVER MEMBERS INTENT` mặc định tắt (`MEMBERS_INTENT=true` để bật lại và có số liệu đếm bot).

## Cấu trúc
- Tách `config.py`, `db.py`, `utils.py`, `prompt.txt`; thêm `tests/`, CI, `.gitignore`.

## Cần sửa tay trong README
- Mục License: repo đã có MIT (`LICENSE`, `LICENSE.vi`) — bỏ đoạn "chưa chỉ định License".
- Bỏ "Nếu repository có `requirements.txt`".
- Mục quyền Admin: bỏ phần role tên Owner/Admin; thêm `ADMIN_ROLE_IDS`.
- Mục Intents: `SERVER MEMBERS INTENT` chỉ cần khi `MEMBERS_INTENT=true`.
- `/reset`: chỉ xóa lịch sử ở server hiện tại.
- Cấu trúc project: thêm các file mới; thêm các biến môi trường mới (xem `.env.example`).
