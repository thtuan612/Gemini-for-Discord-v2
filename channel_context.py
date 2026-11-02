"""Quản lý cache tin nhắn và dựng ngữ cảnh Discord cho pipeline chat."""
from __future__ import annotations

from collections import OrderedDict, deque
from typing import Iterable

import discord

import config

REFERENCE_UNSET = object()


def _message_id(message: object) -> int | None:
    """ID dạng số của tin nhắn, hoặc None nếu không có (snowflake tăng dần theo thời gian)."""
    value = getattr(message, "id", None)
    return value if isinstance(value, int) else None


class ChannelContext:
    """Đóng gói cache theo channel và các thao tác đọc ngữ cảnh Discord."""

    MAX_CHANNELS = 200

    def __init__(self, bot: discord.Client, logger):
        self.bot = bot
        self.log = logger
        self._messages: OrderedDict[int, deque[discord.Message]] = OrderedDict()

    def record_message(self, message: discord.Message | None) -> None:
        """Ghi tin nhắn vào cache của đúng kênh.

        Cache luôn được giữ theo thứ tự id tăng dần (id snowflake tăng theo thời gian) và không
        trùng lặp: ghi lại cùng một tin sẽ thay bản cũ; tin cũ hơn (vd. nạp bù từ lịch sử Discord)
        được chèn đúng vị trí thay vì nối vào cuối.
        """
        if message is None or not getattr(message, "channel", None) or not hasattr(message.channel, "id"):
            return
        channel_id = message.channel.id
        queue = self._messages.get(channel_id)
        if queue is None:
            if len(self._messages) >= self.MAX_CHANNELS:
                self._messages.popitem(last=False)
            queue = deque(maxlen=max(20, config.CHANNEL_HISTORY_LIMIT * 2))
            self._messages[channel_id] = queue
        else:
            self._messages.move_to_end(channel_id)

        new_id = _message_id(message)
        items = list(queue)
        if new_id is not None:
            for index, existing in enumerate(items):
                if _message_id(existing) == new_id:
                    items[index] = message  # cùng một tin: giữ bản mới nhất, không nhân đôi
                    break
            else:
                items.append(message)
        else:
            if queue and queue[-1] is message:
                return
            items.append(message)

        # Tin có id xếp theo id; tin không có id giữ nguyên thứ tự đến, đứng sau cùng.
        known = sorted((m for m in items if _message_id(m) is not None), key=_message_id)
        unknown = [m for m in items if _message_id(m) is None]
        ordered = known + unknown
        queue.clear()
        queue.extend(ordered[-queue.maxlen:])

    def remove_messages(self, channel_id: int, message_ids: Iterable[int]) -> int:
        """Xóa tin nhắn khỏi cache (tin bị xóa/sửa không được tiếp tục đưa vào ngữ cảnh AI)."""
        queue = self._messages.get(channel_id)
        if not queue:
            return 0
        targets = set(message_ids)
        kept = [m for m in queue if _message_id(m) not in targets]
        removed = len(queue) - len(kept)
        if removed:
            queue.clear()
            queue.extend(kept)
        return removed

    def forget_channel(self, channel_id: int) -> None:
        self._messages.pop(channel_id, None)

    def forget_guild(self, guild_id: int) -> int:
        """Bỏ toàn bộ cache của các kênh thuộc một server. Trả về số kênh đã bỏ."""
        stale = [
            channel_id
            for channel_id, queue in self._messages.items()
            if any(getattr(getattr(m, "guild", None), "id", None) == guild_id for m in queue)
        ]
        for channel_id in stale:
            del self._messages[channel_id]
        return len(stale)

    async def get_reference(self, message: discord.Message) -> discord.Message | None:
        if message.reference is None:
            return None
        channel_id = getattr(message.channel, "id", None)
        # Chỉ chấp nhận tin tham chiếu nằm CÙNG kênh: tin được chuyển tiếp/crosspost từ kênh khác
        # không được kéo nội dung kênh đó vào ngữ cảnh.
        reference_channel_id = getattr(message.reference, "channel_id", None)
        if isinstance(reference_channel_id, int) and isinstance(channel_id, int) and reference_channel_id != channel_id:
            return None
        reference = message.reference.resolved
        if isinstance(reference, discord.Message):
            resolved_channel_id = getattr(getattr(reference, "channel", None), "id", None)
            if isinstance(resolved_channel_id, int) and isinstance(channel_id, int) and resolved_channel_id != channel_id:
                return None
            return reference
        reference_id = message.reference.message_id
        if not reference_id:
            return None

        if channel_id and channel_id in self._messages:
            for cached in self._messages[channel_id]:
                if getattr(cached, "id", None) == reference_id:
                    return cached

        if hasattr(message.channel, "fetch_message"):
            try:
                return await message.channel.fetch_message(reference_id)
            except Exception:
                return None
        return None

    def _format_message(
        self,
        message: discord.Message,
        *,
        max_chars: int,
        include_reply: bool = True,
    ) -> str:
        author = message.author
        if self.bot.user and author.id == self.bot.user.id:
            author_name = f"Bot ({self.bot.user.display_name} - chính bạn)"
        else:
            author_name = getattr(author, "display_name", str(author))

        content = (
            getattr(message, "clean_content", None)
            or getattr(message, "content", None)
            or ""
        ).strip()
        attachments = getattr(message, "attachments", None) or []
        if attachments:
            names = ", ".join(item.filename for item in attachments[:2])
            tag = f"[kèm {len(attachments)} file/ảnh: {names}]"
            content = f"{content} {tag}".strip() if content else tag
        if len(content) > max_chars:
            content = content[:max_chars] + "..."

        reply_tag = ""
        reference = getattr(message, "reference", None)
        if include_reply and reference and getattr(reference, "message_id", None):
            reply_tag = " (đang reply)"
        return f"- {author_name}{reply_tag}: {content or '[Nội dung trống]'}"

    async def build(
        self,
        channel: discord.abc.Messageable | None,
        *,
        current_message: discord.Message | None = None,
        ref_msg: discord.Message | None = None,
        limit: int = config.CHANNEL_HISTORY_LIMIT,
        before_id: int | None = None,
    ) -> str:
        """Dựng ngữ cảnh từ các tin nhắn gần nhất của ĐÚNG kênh `channel`.

        Chỉ lấy tin có id nhỏ hơn mốc thời điểm: id của `current_message`, hoặc `before_id`
        (vd. id của interaction với slash command, vốn không có tin nhắn). Nhờ vậy tin đến sau
        không lọt vào ngữ cảnh của yêu cầu đến trước.
        """
        if channel is None or limit <= 0:
            return ""

        messages: list[discord.Message] = []
        channel_id = getattr(channel, "id", None)
        cached = list(self._messages.get(channel_id, ())) if channel_id else []
        current_id = _message_id(current_message)
        if current_id is None and isinstance(before_id, int):
            current_id = before_id

        def is_before_current(message: discord.Message) -> bool:
            message_id = _message_id(message)
            if current_id is None or message_id is None:
                return message is not current_message
            # Discord snowflake IDs preserve chronological order.
            return message_id < current_id

        def has_content(message: discord.Message) -> bool:
            content = (
                getattr(message, "clean_content", None)
                or getattr(message, "content", None)
                or ""
            ).strip()
            return bool(content or getattr(message, "attachments", None))

        # Cache có thể đã chứa tin nhắn hiện tại (on_message ghi trước khi xử lý)
        # hoặc cả tin nhắn đến sau do các event được xử lý đồng thời.
        cached = [
            message for message in cached
            if is_before_current(message) and has_content(message)
        ]
        # Luôn xếp theo id: thứ tự đến của event không đảm bảo thứ tự thời gian
        # (vd. tin bot trả lời được ghi sau khi đã có tin mới của người khác).
        cached.sort(key=lambda item: _message_id(item) or 0)
        messages = cached[-limit:]

        # Khi bot vừa khởi động, cache thường chỉ có tin nhắn hiện tại hoặc vài tin.
        # Bù phần còn thiếu bằng lịch sử Discord, lấy các tin cũ hơn cache.
        missing = limit - len(messages)
        if missing > 0 and hasattr(channel, "history"):
            try:
                before = messages[0] if messages else current_message
                if before is None and current_id is not None:
                    before = discord.Object(id=current_id)  # slash command: lấy tin trước thời điểm gọi lệnh
                older: list[discord.Message] = []
                async for message in channel.history(limit=missing, before=before):
                    if not is_before_current(message) or not has_content(message):
                        continue
                    if any(_message_id(item) == _message_id(message) for item in messages):
                        continue
                    older.append(message)
                older.reverse()  # Discord trả lịch sử từ mới đến cũ.
                messages = (older + messages)[-limit:]
                for message in older:
                    self.record_message(message)
            except Exception as exc:
                self.log.warning(
                    "Không thể đọc lịch sử tin nhắn kênh %s: %s",
                    getattr(channel, "id", None),
                    type(exc).__name__,
                )

        lines: list[str] = []
        if messages:
            lines.append(
                "Lịch sử các tin nhắn gần nhất trong kênh chat "
                "(từ cũ đến mới để bạn nắm ngữ cảnh):"
            )
            lines.extend(self._format_message(message, max_chars=300) for message in messages)

        if ref_msg is not None:
            lines.append("\n[Tin nhắn đang được người dùng trực tiếp reply / trích dẫn]:")
            lines.append(self._format_message(ref_msg, max_chars=400, include_reply=False))

        if not lines:
            return ""

        lines.append(
            "\nLƯU Ý VỀ NGỮ CẢNH: Đoạn chat trên là các tin nhắn gần nhất trong kênh để bạn hiểu "
            "mọi người đang thảo luận vấn đề gì, ai đang hỏi ai, các đại từ 'nó', 'đó', 'họ', "
            "'quán đó'... ám chỉ điều gì. Nếu câu hỏi hiện tại tiếp nối cuộc trò chuyện trên, "
            "hãy trả lời đúng ngữ cảnh, tuyệt đối không trả lời lạc đề, bậy bạ hoặc vô nghĩa. "
            "Nếu người dùng hỏi một chủ đề hoàn toàn mới, hãy tập trung trả lời chủ đề mới đó."
        )
        return "\n".join(lines)

    async def is_message_for_bot(
        self,
        message: discord.Message,
        *,
        ref_msg: object = REFERENCE_UNSET,
    ) -> bool:
        if self.bot.user and self.bot.user in message.mentions:
            return True

        if message.reference is not None:
            if ref_msg is REFERENCE_UNSET:
                ref_msg = message.reference.resolved
                if ref_msg is None and message.reference.message_id:
                    try:
                        ref_msg = await message.channel.fetch_message(message.reference.message_id)
                    except discord.HTTPException:
                        ref_msg = None
            if isinstance(ref_msg, discord.Message) and (
                not self.bot.user or ref_msg.author.id != self.bot.user.id
            ):
                return False

        human_mentions = [member for member in message.mentions if not member.bot]
        if human_mentions and (not self.bot.user or self.bot.user not in message.mentions):
            return False
        return True
