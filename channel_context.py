"""Quản lý cache tin nhắn và dựng ngữ cảnh Discord cho pipeline chat."""
from __future__ import annotations

from collections import OrderedDict, deque

import discord

import config

REFERENCE_UNSET = object()


class ChannelContext:
    """Đóng gói cache theo channel và các thao tác đọc ngữ cảnh Discord."""

    MAX_CHANNELS = 200

    def __init__(self, bot: discord.Client, logger):
        self.bot = bot
        self.log = logger
        self._messages: OrderedDict[int, deque[discord.Message]] = OrderedDict()

    def record_message(self, message: discord.Message | None) -> None:
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

        if queue and getattr(queue[-1], "id", None) == getattr(message, "id", None):
            return
        queue.append(message)

    async def get_reference(self, message: discord.Message) -> discord.Message | None:
        if message.reference is None:
            return None
        reference = message.reference.resolved
        if isinstance(reference, discord.Message):
            return reference
        reference_id = message.reference.message_id
        if not reference_id:
            return None

        channel_id = getattr(message.channel, "id", None)
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
    ) -> str:
        if channel is None or limit <= 0:
            return ""

        messages: list[discord.Message] = []
        channel_id = getattr(channel, "id", None)
        cached = self._messages.get(channel_id) if channel_id else None

        if cached:
            for message in reversed(cached):
                if current_message is not None and getattr(message, "id", None) == getattr(current_message, "id", None):
                    continue
                content = (
                    getattr(message, "clean_content", None)
                    or getattr(message, "content", None)
                    or ""
                ).strip()
                attachments = getattr(message, "attachments", None) or []
                if not content and not attachments:
                    continue
                messages.append(message)
                if len(messages) >= limit:
                    break
            messages.reverse()
        elif hasattr(channel, "history"):
            try:
                before = current_message if current_message is not None else None
                async for message in channel.history(limit=limit, before=before):
                    if current_message is not None and getattr(message, "id", None) == getattr(current_message, "id", None):
                        continue
                    content = (
                        getattr(message, "clean_content", None)
                        or getattr(message, "content", None)
                        or ""
                    ).strip()
                    attachments = getattr(message, "attachments", None) or []
                    if not content and not attachments:
                        continue
                    messages.append(message)
            except Exception as exc:
                self.log.warning(
                    "Không thể đọc lịch sử tin nhắn kênh %s: %s",
                    getattr(channel, "id", None),
                    exc,
                )
            messages.reverse()
            for message in messages:
                self.record_message(message)

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
