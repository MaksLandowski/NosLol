import os
import json
import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks

# =========================
# KONFIGURACJA
# =========================
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("Brak zmiennej środowiskowej DISCORD_TOKEN")

CHANNEL_ID = 1491695833119199232
TARGET_EMOJI = "✅"
HEADERS = [f"Ch{i}" for i in range(1, 8)]

DAILY_HOUR = 18
DAILY_MINUTE = 0
TIMEZONE = ZoneInfo("Europe/Warsaw")

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

started_once = False


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


async def create_board(channel: discord.TextChannel) -> None:
    state["tracked_messages"] = {}

    for title in HEADERS:
        msg = await channel.send(title)
        await msg.add_reaction(TARGET_EMOJI)
        state["tracked_messages"][str(msg.id)] = title

    save_state(state)


async def reset_board(channel: discord.TextChannel) -> None:
    await clear_entire_channel(channel)
    await create_board(channel)


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
    global started_once

    print(f"Zalogowano jako: {bot.user} (ID: {bot.user.id})")

    if not daily_reset.is_running():
        daily_reset.start()

    if not started_once:
        started_once = True
        await rebuild_all_tracked_messages()


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    await handle_reaction_change(payload)


@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    await handle_reaction_change(payload)


# =========================
# KOMENDA RĘCZNA
# =========================
@bot.command(name="odswiez")
@commands.has_permissions(manage_messages=True)
async def odswiez(ctx: commands.Context):
    if ctx.channel.id != CHANNEL_ID:
        await ctx.reply(f"Ta komenda działa tylko na kanale <#{CHANNEL_ID}>.")
        return

    await reset_board(ctx.channel)


@odswiez.error
async def odswiez_error(ctx: commands.Context, error: Exception):
    if isinstance(error, commands.MissingPermissions):
        await ctx.reply("Nie masz uprawnień do użycia tej komendy.")
    else:
        await ctx.reply(f"Wystąpił błąd: `{error}`")


# =========================
# AUTOMATYCZNY RESET
# =========================
@tasks.loop(
    time=datetime.time(
        hour=DAILY_HOUR,
        minute=DAILY_MINUTE,
        tzinfo=TIMEZONE
    )
)
async def daily_reset():
    channel = await get_target_channel()
    if channel is None:
        return

    await reset_board(channel)


@daily_reset.before_loop
async def before_daily_reset():
    await bot.wait_until_ready()


# =========================
# START
# =========================
bot.run(TOKEN)