import os
import json
from pathlib import Path

import discord
from discord.ext import commands

# =========================
# KONFIGURACJA
# =========================
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("Brak zmiennej środowiskowej DISCORD_TOKEN")

CHANNEL_ID = 1491695833119199232
ALLOWED_ROLE_ID = 717702962851479602
TARGET_EMOJI = "✅"
STATE_FILE = Path("state.json")

# =========================
# INTENTS
# =========================
intents = discord.Intents.default()
intents.guilds = True
intents.messages = True
intents.reactions = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# =========================
# PLIK STANU
# =========================
def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"tracked_messages": {}}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


state = load_state()

# =========================
# POMOCNICZE
# =========================
def render_message_content(title: str, user_ids: list[int]) -> str:
    lines = [title]
    for index, user_id in enumerate(user_ids, start=1):
        lines.append(f"{index}. <@{user_id}>")
    return "\n".join(lines)


def build_headers(hour: int, bottom_count: int, middle_count: int, top_count: int) -> list[str]:
    formatted_hour = f"{hour:02d}:00"
    headers: list[str] = []
    channel_number = 1

    for _ in range(bottom_count):
        headers.append(f"LOL {formatted_hour} ch{channel_number} dół (zalecany lvl 30-40)")
        channel_number += 1

    for _ in range(middle_count):
        headers.append(f"LOL {formatted_hour} ch{channel_number} środek (zalecany lvl 38-50)")
        channel_number += 1

    for _ in range(top_count):
        headers.append(f"LOL {formatted_hour} ch{channel_number} góra (zalecany lvl 48-60)")
        channel_number += 1

    return headers


async def get_target_channel() -> discord.TextChannel | None:
    channel = bot.get_channel(CHANNEL_ID)
    if channel is None:
        try:
            channel = await bot.fetch_channel(CHANNEL_ID)
        except Exception:
            return None

    if isinstance(channel, discord.TextChannel):
        return channel

    return None


async def clear_entire_channel(channel: discord.TextChannel) -> None:
    while True:
        deleted = await channel.purge(limit=100, bulk=False)
        if not deleted:
            break


async def rebuild_one_message(channel: discord.TextChannel, message_id: int, title: str) -> None:
    try:
        message = await channel.fetch_message(message_id)
    except discord.NotFound:
        state["tracked_messages"].pop(str(message_id), None)
        save_state(state)
        return
    except Exception:
        return

    reaction_obj = discord.utils.get(message.reactions, emoji=TARGET_EMOJI)

    user_ids: list[int] = []
    if reaction_obj is not None:
        async for user in reaction_obj.users():
            if user.bot:
                continue
            user_ids.append(user.id)

    new_content = render_message_content(title, user_ids)

    await message.edit(
        content=new_content,
        allowed_mentions=discord.AllowedMentions(users=False)
    )


async def rebuild_all_tracked_messages() -> None:
    channel = await get_target_channel()
    if channel is None:
        return

    tracked = list(state.get("tracked_messages", {}).items())
    for message_id_str, title in tracked:
        await rebuild_one_message(channel, int(message_id_str), title)


async def create_board(channel: discord.TextChannel, headers: list[str]) -> None:
    for title in headers:
        msg = await channel.send(title)
        await msg.add_reaction(TARGET_EMOJI)
        state["tracked_messages"][str(msg.id)] = title

    save_state(state)


async def handle_reaction_change(payload: discord.RawReactionActionEvent) -> None:
    if payload.channel_id != CHANNEL_ID:
        return

    if bot.user and payload.user_id == bot.user.id:
        return

    if str(payload.emoji) != TARGET_EMOJI:
        return

    tracked = state.get("tracked_messages", {})
    title = tracked.get(str(payload.message_id))
    if not title:
        return

    channel = await get_target_channel()
    if channel is None:
        return

    await rebuild_one_message(channel, payload.message_id, title)


# =========================
# EVENTY
# =========================
@bot.event
async def on_ready():
    print(f"Zalogowano jako: {bot.user} (ID: {bot.user.id})")
    await rebuild_all_tracked_messages()


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    await handle_reaction_change(payload)


@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    await handle_reaction_change(payload)


# =========================
# KOMENDA !lol
# =========================
@bot.command(name="lol")
@commands.has_role(ALLOWED_ROLE_ID)
async def lol_command(ctx: commands.Context, hour: int, bottom_count: int, middle_count: int, top_count: int):
    if ctx.channel.id != CHANNEL_ID:
        await ctx.reply(f"Ta komenda działa tylko na kanale <#{CHANNEL_ID}>.")
        return

    if not (0 <= hour <= 23):
        await ctx.reply("Godzina musi być z przedziału 0-23.")
        return

    if bottom_count < 0 or middle_count < 0 or top_count < 0:
        await ctx.reply("Liczby dla dół / środek / góra nie mogą być ujemne.")
        return

    total = bottom_count + middle_count + top_count
    if total == 0:
        await ctx.reply("Wszystkie wartości są 0, więc nic nie robię.")
        return
        
    if total == 7:
        await ctx.reply("Maksymalna ilość kanałów to 7.")
        return

    headers = build_headers(hour, bottom_count, middle_count, top_count)
    await create_board(ctx.channel, headers)


# =========================
# KOMENDA !clear
# =========================
@bot.command(name="clear")
@commands.has_role(ALLOWED_ROLE_ID)
async def clear_command(ctx: commands.Context):
    if ctx.channel.id != CHANNEL_ID:
        await ctx.reply(f"Ta komenda działa tylko na kanale <#{CHANNEL_ID}>.")
        return

    await clear_entire_channel(ctx.channel)
    state["tracked_messages"] = {}
    save_state(state)


# =========================
# OBSŁUGA BŁĘDÓW
# =========================
@lol_command.error
async def lol_command_error(ctx: commands.Context, error: Exception):
    if isinstance(error, commands.MissingRole):
        await ctx.reply("Nie masz wymaganej roli do użycia tej komendy.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.reply("Użycie: `!lol <godzina> <dół> <środek> <góra>`")
    elif isinstance(error, commands.BadArgument):
        await ctx.reply("Wszystkie parametry muszą być liczbami. Przykład: `!lol 19 3 2 1`")
    else:
        await ctx.reply(f"Wystąpił błąd: `{error}`")


@clear_command.error
async def clear_command_error(ctx: commands.Context, error: Exception):
    if isinstance(error, commands.MissingRole):
        await ctx.reply("Nie masz wymaganej roli do użycia tej komendy.")
    else:
        await ctx.reply(f"Wystąpił błąd: `{error}`")


# =========================
# START
# =========================
bot.run(TOKEN)
