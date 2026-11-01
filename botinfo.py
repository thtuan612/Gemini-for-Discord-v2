"""BotInfo dashboard and Auto-Chat interactive views."""
from __future__ import annotations

import asyncio
import os
import platform
import time
from datetime import datetime, timezone

import discord
import psutil

import config
from utils import format_bytes, format_uptime, get_dir_size, get_memory_limit_bytes

bot: discord.Client
db: object
auto_chat_channels: set[int]
is_privileged = None
describe_ai_providers = None
BOT_START_TIME: datetime
_PROCESS: psutil.Process


def setup(*, bot_instance, database, channels, privilege_check, provider_description, start_time):
    global bot, db, auto_chat_channels, is_privileged, describe_ai_providers
    global BOT_START_TIME, _PROCESS
    bot = bot_instance
    db = database
    auto_chat_channels = channels
    is_privileged = privilege_check
    describe_ai_providers = provider_description
    BOT_START_TIME = start_time
    _PROCESS = psutil.Process(os.getpid())


# ======================================================================
APP_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DISK_CACHE_TTL = 60
_PROCESS = psutil.Process(os.getpid())
_app_disk_size_cache: tuple[float, int] | None = None
_app_disk_size_lock = asyncio.Lock()


async def _get_app_disk_size() -> int:
    """Cache dung lượng thư mục bot 60 giây để tránh quét ổ đĩa mỗi lần refresh /botinfo."""
    global _app_disk_size_cache
    now = time.monotonic()
    cached = _app_disk_size_cache
    if cached is not None and now - cached[0] < APP_DISK_CACHE_TTL:
        return cached[1]

    async with _app_disk_size_lock:
        now = time.monotonic()
        cached = _app_disk_size_cache
        if cached is not None and now - cached[0] < APP_DISK_CACHE_TTL:
            return cached[1]
        size = await asyncio.to_thread(get_dir_size, APP_DIR)
        _app_disk_size_cache = (time.monotonic(), size)
        return size


async def build_botinfo_embed(guild: discord.Guild | None) -> discord.Embed:
    process = _PROCESS
    app_disk_used = await _get_app_disk_size()
    db_size = os.path.getsize(config.DB_PATH) if os.path.exists(config.DB_PATH) else 0
    uptime = datetime.now(timezone.utc) - BOT_START_TIME
    total_members = sum(g.member_count or 0 for g in bot.guilds)
    total_members_text = f"{total_members:,}".replace(",", ".")

    guild_autochat_count = 0
    if guild:
        guild_channel_ids = {c.id for c in guild.text_channels}
        guild_autochat_count = len(guild_channel_ids & auto_chat_channels)

    description = (
        f"🏓 **Ping:** {round(bot.latency * 1000)}ms\n"
        f"⏱️ **Uptime:** {format_uptime(uptime)}\n"
        f"🌐 **Số server:** {len(bot.guilds)}\n"
        f"👥 **Tổng thành viên:** {total_members_text}\n"
        f"💾 **RAM:** {format_bytes(process.memory_info().rss)} / {format_bytes(get_memory_limit_bytes())}\n"
        f"🗂️ **Disk (thư mục bot):** {format_bytes(app_disk_used)}\n"
        f"🧮 **Dung lượng DB:** {format_bytes(db_size)}\n"
        f"🐍 **Python:** {platform.python_version()}\n"
        f"📘 **discord.py:** {discord.__version__}\n"
        f"✨ **AI:** {describe_ai_providers()}\n"
        f"📣 **Kênh auto-chat:** {len(auto_chat_channels)} kênh (Server này: {guild_autochat_count})\n\n"
        "💡 *Dùng nút bên dưới để đổi cài đặt Auto-Chat.*"
    )
    embed = discord.Embed(
        title="📊 Bảng Điều Khiển & Thông Số Bot",
        description=description,
        color=discord.Color.blurple(),
    )
    if bot.user and bot.user.display_avatar:
        embed.set_thumbnail(url=bot.user.display_avatar.url)
    embed.set_footer(text="Được tạo bởi ThTuan (@lmtuan612)")
    return embed


def build_autochat_embed(guild: discord.Guild, notice: str = "") -> discord.Embed:
    guild_channel_ids = {c.id for c in guild.text_channels}
    active_in_guild = sorted(guild_channel_ids & auto_chat_channels)
    if active_in_guild:
        channels_text = "\n".join(f"• <#{cid}>" for cid in active_in_guild)
    else:
        channels_text = "*(Chưa có kênh nào bật auto-chat trong server này)*"

    desc_parts = []
    if notice:
        desc_parts.append(f"> 💬 **{notice}**\n")

    desc_parts.append(
        f"🏠 **Server:** {guild.name}\n"
        f"📣 **Các kênh đang bật Auto-Chat ở server này ({len(active_in_guild)}):**\n"
        f"{channels_text}\n\n"
        f"🌐 **Tổng kênh Auto-Chat toàn bot:** {len(auto_chat_channels)}\n\n"
        "📝 **Hướng dẫn:**\n"
        "• Chọn kênh trong menu bên dưới để **Bật** hoặc **Tắt** nhanh auto-chat.\n"
        "• Hoặc bấm **Bật/Tắt kênh hiện tại** để đổi trạng thái kênh bạn đang gửi lệnh.\n\n"
        "⚠️ **Quyền riêng tư:** Khi bật, nội dung tin nhắn trong kênh và ngữ cảnh cần thiết "
        "có thể được gửi tới AI provider đang cấu hình để tạo phản hồi. Hãy thông báo cho thành viên "
        "và chỉ bật ở kênh phù hợp."
    )
    embed = discord.Embed(
        title="📣 Quản Lý Auto-Chat",
        description="\n".join(desc_parts),
        color=discord.Color.blue(),
    )
    if bot.user and bot.user.display_avatar:
        embed.set_thumbnail(url=bot.user.display_avatar.url)
    embed.set_footer(text="Chọn kênh từ menu để bật/tắt")
    return embed


class BotInfoMainView(discord.ui.View):
    def __init__(self, guild: discord.Guild | None):
        super().__init__(timeout=300)
        self.guild = guild

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not is_privileged(interaction.user):
            await interaction.response.send_message("Lệnh này chỉ Admin/Owner mới dùng được nhé.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="📣 Quản Lý Auto-Chat", style=discord.ButtonStyle.primary)
    async def go_autochat(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = build_autochat_embed(interaction.guild)
        view = AutoChatManageView(interaction.guild)
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="🔄 Làm mới", style=discord.ButtonStyle.success)
    async def refresh_info(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = await build_botinfo_embed(interaction.guild)
        await interaction.response.edit_message(embed=embed, view=self)


class AutoChatChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, current_guild: discord.Guild):
        super().__init__(
            placeholder="Chọn kênh text để Bật / Tắt Auto-Chat...",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
            row=0,
        )
        self.current_guild = current_guild

    async def callback(self, interaction: discord.Interaction):
        channel_obj = self.values[0]
        cid = channel_obj.id

        if cid in auto_chat_channels:
            await db.remove_auto_chat_channel(cid)
            auto_chat_channels.discard(cid)
            note = " (kênh nằm trong AUTO_CHAT_CHANNEL_IDS từ .env)" if cid in config.AUTO_CHAT_CHANNEL_IDS else ""
            notice = f"🔕 Đã tắt auto-chat tại <#{cid}>{note}."
        else:
            target_channel = interaction.guild.get_channel(cid)
            if isinstance(target_channel, discord.TextChannel):
                perms = target_channel.permissions_for(interaction.guild.me)
                if not (perms.view_channel and perms.send_messages):
                    embed = build_autochat_embed(
                        interaction.guild,
                        notice=f"❌ Bot không có quyền xem hoặc gửi tin tại <#{cid}>.",
                    )
                    await interaction.response.edit_message(embed=embed, view=AutoChatManageView(interaction.guild))
                    return

            await db.add_auto_chat_channel(cid, interaction.guild_id, interaction.user.id)
            auto_chat_channels.add(cid)
            notice = (
                f"✅ Đã bật auto-chat tại <#{cid}> — gõ là bot rep. "
                "Tin nhắn trong kênh có thể được gửi tới AI provider để xử lý."
            )

        embed = build_autochat_embed(interaction.guild, notice=notice)
        await interaction.response.edit_message(embed=embed, view=AutoChatManageView(interaction.guild))


class AutoChatManageView(discord.ui.View):
    def __init__(self, guild: discord.Guild):
        super().__init__(timeout=300)
        self.guild = guild
        self.add_item(AutoChatChannelSelect(guild))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not is_privileged(interaction.user):
            await interaction.response.send_message("Lệnh này chỉ Admin/Owner mới dùng được nhé.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="⚡ Bật/Tắt kênh hiện tại", style=discord.ButtonStyle.primary, row=1)
    async def toggle_current_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        cid = interaction.channel_id
        if cid in auto_chat_channels:
            await db.remove_auto_chat_channel(cid)
            auto_chat_channels.discard(cid)
            note = " (kênh nằm trong AUTO_CHAT_CHANNEL_IDS từ .env)" if cid in config.AUTO_CHAT_CHANNEL_IDS else ""
            notice = f"🔕 Đã tắt auto-chat tại <#{cid}>{note}."
        else:
            if isinstance(interaction.channel, discord.TextChannel):
                perms = interaction.channel.permissions_for(interaction.guild.me)
                if not (perms.view_channel and perms.send_messages):
                    embed = build_autochat_embed(
                        interaction.guild,
                        notice="❌ Bot không có quyền xem/gửi tin ở kênh này.",
                    )
                    await interaction.response.edit_message(embed=embed, view=self)
                    return
            await db.add_auto_chat_channel(cid, interaction.guild_id, interaction.user.id)
            auto_chat_channels.add(cid)
            notice = (
                f"✅ Đã bật auto-chat tại <#{cid}> — gõ là bot rep. "
                "Tin nhắn trong kênh có thể được gửi tới AI provider để xử lý."
            )

        embed = build_autochat_embed(interaction.guild, notice=notice)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="📋 Tất cả kênh (toàn bot)", style=discord.ButtonStyle.secondary, row=1)
    async def list_all_channels(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not auto_chat_channels:
            await interaction.response.send_message("Hiện chưa có kênh nào bật auto-chat trên toàn bộ bot.", ephemeral=True)
            return
        lines = []
        for cid in sorted(auto_chat_channels):
            ch = bot.get_channel(cid)
            if ch:
                lines.append(f"• <#{cid}> (Server: **{ch.guild.name}**)")
            else:
                lines.append(f"• Kênh ID `{cid}` *(không rõ server)*")
        msg = "📋 **Danh sách kênh Auto-Chat toàn bot:**\n" + "\n".join(lines)
        await interaction.response.send_message(msg, ephemeral=True)

    @discord.ui.button(label="⬅️ Quay lại", style=discord.ButtonStyle.secondary, row=2)
    async def back_to_main(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = await build_botinfo_embed(interaction.guild)
        view = BotInfoMainView(interaction.guild)
        await interaction.response.edit_message(embed=embed, view=view)



