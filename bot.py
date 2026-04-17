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

LOL_CHANNEL_NAME = "LOL"
LOL2_CHANNEL_NAME = "LOL2"
RAID_CHANNEL_NAME = "rajdy"

CLEAR_CHANNEL_NAMES = {LOL_CHANNEL_NAME, LOL2_CHANNEL_NAME, RAID_CHANNEL_NAME}
TRACKED_CHANNEL_NAMES = {LOL_CHANNEL_NAME, LOL2_CHANNEL_NAME, RAID_CHANNEL_NAME}


ALLOWED_ROLE_NAMES = [
    "lol",
    "lol2",
    "rajd",
]

TARGET_EMOJI = "✅"
STATE_FILE = Path("state.json")
MAX_VISIBLE_USERS = 5

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
def has_allowed_role(member: discord.Member) -> bool:
    user_role_names = {role.name for role in member.roles}
    return any(role_name in user_role_names for role_name in ALLOWED_ROLE_NAMES)


def get_tracked_entry(message_id: int) -> dict | None:
    tracked = state.setdefault("tracked_messages", {})
    entry = tracked.get(str(message_id))

    if entry is None:
        return None

    changed = False

    # migracja ze starego formatu:
    # "123456789": "LOL 19:00 ch1 dół ..."
    if isinstance(entry, str):
        entry = {
            "mode": "lol",
            "title": entry,
            "queue": [],
            "channel_name": LOL_CHANNEL_NAME,
        }
        tracked[str(message_id)] = entry
        changed = True

    if "mode" not in entry:
        entry["mode"] = "lol"
        changed = True

    if "title" not in entry:
        entry["title"] = ""
        changed = True

    if "queue" not in entry or not isinstance(entry["queue"], list):
        entry["queue"] = []
        changed = True

    if "channel_name" not in entry:
        if entry["mode"] == "rajd":
            entry["channel_name"] = RAID_CHANNEL_NAME
        else:
            entry["channel_name"] = LOL_CHANNEL_NAME
        changed = True

    if entry["mode"] == "rajd":
        if "capacity" not in entry or not isinstance(entry["capacity"], int):
            entry["capacity"] = 8
            changed = True

    if changed:
        save_state(state)

    return entry


def render_lol_message_content(title: str, user_ids: list[int]) -> str:
    lines = [title]
    for index, user_id in enumerate(user_ids, start=1):
        lines.append(f"{index}. <@{user_id}>")
    return "\n".join(lines)


def render_raid_message_content(title: str, capacity: int, user_ids: list[int]) -> str:
    squad = user_ids[:capacity]
    reserve = user_ids[capacity:]

    lines = [title, "", "Skład:"]

    for index in range(capacity):
        if index < len(squad):
            lines.append(f"{index + 1}. <@{squad[index]}>")
        else:
            lines.append(f"{index + 1}.")

    lines.append("")
    lines.append("Rezerwa:")

    reserve_visible_count = max(3, len(reserve))
    for index in range(reserve_visible_count):
        if index < len(reserve):
            lines.append(f"{index + 1}. <@{reserve[index]}>")
        else:
            lines.append(f"{index + 1}.")

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


def build_headers_lol2(hour: int, bottom_count: int, middle_count: int, top_count: int) -> list[str]:
    formatted_hour = f"{hour:02d}:00"
    headers: list[str] = []
    channel_number = 1

    for _ in range(bottom_count):
        headers.append(f"LOL2 {formatted_hour} ch{channel_number} dół (zalecany lvl 60-68)")
        channel_number += 1

    for _ in range(middle_count):
        headers.append(f"LOL2 {formatted_hour} ch{channel_number} środek (zalecany lvl 68-73)")
        channel_number += 1

    for _ in range(top_count):
        headers.append(f"LOL2 {formatted_hour} ch{channel_number} góra (zalecany lvl 73-80)")
        channel_number += 1

    return headers


async def get_target_channel(channel_name: str, guild: discord.Guild | None = None) -> discord.TextChannel | None:
    if guild is not None:
        return discord.utils.get(guild.text_channels, name=channel_name)

    for guild in bot.guilds:
        channel = discord.utils.get(guild.text_channels, name=channel_name)
        if channel is not None:
            return channel

    return None


async def clear_messages(
    channel: discord.TextChannel,
    amount: int,
    *,
    before: discord.Message | None = None
) -> list[discord.Message]:
    deleted_messages: list[discord.Message] = []
    remaining = amount

    while remaining > 0:
        batch_size = min(remaining, 100)
        deleted = await channel.purge(limit=batch_size, bulk=False, before=before)
        if not deleted:
            break

        deleted_messages.extend(deleted)
        remaining -= len(deleted)

    return deleted_messages


async def clear_entire_channel(
    channel: discord.TextChannel,
    *,
    before: discord.Message | None = None
) -> list[discord.Message]:
    deleted_messages: list[discord.Message] = []

    while True:
        deleted = await channel.purge(limit=100, bulk=False, before=before)
        if not deleted:
            break

        deleted_messages.extend(deleted)

    return deleted_messages


async def get_actual_reaction_users(message: discord.Message) -> list[int]:
    reaction_obj = discord.utils.get(message.reactions, emoji=TARGET_EMOJI)

    user_ids: list[int] = []
    if reaction_obj is not None:
        async for user in reaction_obj.users():
            if user.bot:
                continue
            user_ids.append(user.id)

    return user_ids


async def rebuild_one_message(channel: discord.TextChannel, message_id: int) -> None:
    entry = get_tracked_entry(message_id)
    if entry is None:
        return

    try:
        message = await channel.fetch_message(message_id)
    except discord.NotFound:
        state["tracked_messages"].pop(str(message_id), None)
        save_state(state)
        return
    except Exception:
        return

    actual_user_ids = await get_actual_reaction_users(message)

    queue = [user_id for user_id in entry["queue"] if user_id in actual_user_ids]

    for user_id in actual_user_ids:
        if user_id not in queue:
            queue.append(user_id)

    entry["queue"] = queue
    save_state(state)

    if entry["mode"] == "rajd":
        new_content = render_raid_message_content(
            entry["title"],
            entry["capacity"],
            queue
        )
    else:
        visible_user_ids = queue[:MAX_VISIBLE_USERS]
        new_content = render_lol_message_content(entry["title"], visible_user_ids)

    await message.edit(
        content=new_content,
        allowed_mentions=discord.AllowedMentions(users=False)
    )


async def rebuild_all_tracked_messages() -> None:
    tracked = state.get("tracked_messages", {})

    for message_id_str in list(tracked.keys()):
        entry = get_tracked_entry(int(message_id_str))
        if entry is None:
            continue

        channel_name = entry.get("channel_name", LOL_CHANNEL_NAME)
        channel = await get_target_channel(channel_name)

        if channel is None:
            continue

        await rebuild_one_message(channel, int(message_id_str))


async def create_board(channel: discord.TextChannel, headers: list[str], intro_message: str | None = None) -> None:
    if intro_message:
        await channel.send(intro_message)

    for title in headers:
        msg = await channel.send(title)
        await msg.add_reaction(TARGET_EMOJI)

        state["tracked_messages"][str(msg.id)] = {
            "mode": "lol",
            "title": title,
            "queue": [],
            "channel_name": channel.name,
        }

    save_state(state)


async def create_raid(channel: discord.TextChannel, capacity: int) -> None:
    title = f"RAJD ({capacity} osób)"
    content = render_raid_message_content(title, capacity, [])

    msg = await channel.send(content)
    await msg.add_reaction(TARGET_EMOJI)

    state["tracked_messages"][str(msg.id)] = {
        "mode": "rajd",
        "title": title,
        "capacity": capacity,
        "queue": [],
        "channel_name": channel.name,
    }
    save_state(state)


async def resolve_payload_text_channel(payload: discord.RawReactionActionEvent) -> discord.TextChannel | None:
    channel = bot.get_channel(payload.channel_id)

    if not isinstance(channel, discord.TextChannel):
        try:
            fetched = await bot.fetch_channel(payload.channel_id)
            if isinstance(fetched, discord.TextChannel):
                channel = fetched
            else:
                return None
        except Exception:
            return None

    return channel


async def handle_reaction_add(payload: discord.RawReactionActionEvent) -> None:
    if bot.user and payload.user_id == bot.user.id:
        return

    if str(payload.emoji) != TARGET_EMOJI:
        return

    channel = await resolve_payload_text_channel(payload)
    if channel is None or channel.name not in TRACKED_CHANNEL_NAMES:
        return

    entry = get_tracked_entry(payload.message_id)
    if entry is None:
        return

    if entry.get("channel_name") != channel.name:
        return

    if payload.user_id not in entry["queue"]:
        entry["queue"].append(payload.user_id)
        save_state(state)

    await rebuild_one_message(channel, payload.message_id)


async def handle_reaction_remove(payload: discord.RawReactionActionEvent) -> None:
    if bot.user and payload.user_id == bot.user.id:
        return

    if str(payload.emoji) != TARGET_EMOJI:
        return

    channel = await resolve_payload_text_channel(payload)
    if channel is None or channel.name not in TRACKED_CHANNEL_NAMES:
        return

    entry = get_tracked_entry(payload.message_id)
    if entry is None:
        return

    if entry.get("channel_name") != channel.name:
        return

    entry["queue"] = [user_id for user_id in entry["queue"] if user_id != payload.user_id]
    save_state(state)

    await rebuild_one_message(channel, payload.message_id)


# =========================
# EVENTY
# =========================
@bot.event
async def on_ready():
    print(f"Zalogowano jako: {bot.user} (ID: {bot.user.id})")
    await rebuild_all_tracked_messages()


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    await handle_reaction_add(payload)


@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    await handle_reaction_remove(payload)


# =========================
# KOMENDA !lol
# =========================
@bot.command(name="lol")
async def lol_command(ctx: commands.Context, hour: int, bottom_count: int, middle_count: int, top_count: int):
    if not has_allowed_role(ctx.author):
        await ctx.reply("Nie masz wymaganej roli do użycia tej komendy.")
        return

    if ctx.channel.name != LOL_CHANNEL_NAME:
        await ctx.reply(f"Ta komenda działa tylko na kanale #{LOL_CHANNEL_NAME}.")
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

    if total > 7:
        await ctx.reply("Maksymalna ilość kanałów to 7.")
        return

    headers = build_headers(hour, bottom_count, middle_count, top_count)
    await create_board(ctx.channel, headers, intro_message="Zapisy na LOL 30-64")

    try:
        await ctx.message.delete()
    except Exception:
        pass


# =========================
# KOMENDA !lol2
# =========================
@bot.command(name="lol2")
async def lol2_command(ctx: commands.Context, hour: int, bottom_count: int, middle_count: int, top_count: int):
    if not has_allowed_role(ctx.author):
        await ctx.reply("Nie masz wymaganej roli do użycia tej komendy.")
        return

    if ctx.channel.name != LOL2_CHANNEL_NAME:
        await ctx.reply(f"Ta komenda działa tylko na kanale #{LOL2_CHANNEL_NAME}.")
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

    if total > 7:
        await ctx.reply("Maksymalna ilość kanałów to 7.")
        return

    headers = build_headers_lol2(hour, bottom_count, middle_count, top_count)
    await create_board(ctx.channel, headers, intro_message="Zapisy na zaawansowany LOL2 60-82")

    try:
        await ctx.message.delete()
    except Exception:
        pass


# =========================
# KOMENDA !rajd
# =========================
@bot.command(name="rajd")
async def rajd_command(ctx: commands.Context, capacity: int):
    if not has_allowed_role(ctx.author):
        await ctx.reply("Nie masz wymaganej roli do użycia tej komendy.")
        return

    if ctx.channel.name != RAID_CHANNEL_NAME:
        await ctx.reply(f"Ta komenda działa tylko na kanale #{RAID_CHANNEL_NAME}.")
        return

    if not (8 <= capacity <= 20):
        await ctx.reply("Liczba osób dla `!rajd` musi być z przedziału 8-20.")
        return

    await create_raid(ctx.channel, capacity)

    try:
        await ctx.message.delete()
    except Exception:
        pass


# =========================
# KOMENDA !clear
# =========================
@bot.command(name="clear")
async def clear_command(ctx: commands.Context, amount: int):
    if not has_allowed_role(ctx.author):
        await ctx.reply("Nie masz wymaganej roli do użycia tej komendy.")
        return

    if ctx.channel.name not in CLEAR_CHANNEL_NAMES:
        allowed = ", ".join(f"#{name}" for name in sorted(CLEAR_CHANNEL_NAMES))
        await ctx.reply(f"Ta komenda działa tylko na kanałach: {allowed}.")
        return

    if amount < 0:
        await ctx.reply("Podaj liczbę 0 lub większą.")
        return

    if amount == 0:
        deleted_messages = await clear_entire_channel(ctx.channel, before=ctx.message)

        deleted_ids = {msg.id for msg in deleted_messages}
        state["tracked_messages"] = {
            msg_id: entry
            for msg_id, entry in state.get("tracked_messages", {}).items()
            if int(msg_id) not in deleted_ids
        }
        save_state(state)

        try:
            await ctx.message.delete()
        except Exception:
            pass
        return

    deleted_messages = await clear_messages(ctx.channel, amount, before=ctx.message)

    for msg in deleted_messages:
        state["tracked_messages"].pop(str(msg.id), None)

    save_state(state)

    try:
        await ctx.message.delete()
    except Exception:
        pass


# =========================
# OBSŁUGA BŁĘDÓW
# =========================
@lol_command.error
async def lol_command_error(ctx: commands.Context, error: Exception):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.reply("Użycie: `!lol <godzina> <dół> <środek> <góra>`")
    elif isinstance(error, commands.BadArgument):
        await ctx.reply("Wszystkie parametry muszą być liczbami. Przykład: `!lol 19 3 2 1`")
    else:
        await ctx.reply(f"Wystąpił błąd: `{error}`")


@lol2_command.error
async def lol2_command_error(ctx: commands.Context, error: Exception):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.reply("Użycie: `!lol2 <godzina> <dół> <środek> <góra>`")
    elif isinstance(error, commands.BadArgument):
        await ctx.reply("Wszystkie parametry muszą być liczbami. Przykład: `!lol2 19 3 2 1`")
    else:
        await ctx.reply(f"Wystąpił błąd: `{error}`")


@rajd_command.error
async def rajd_command_error(ctx: commands.Context, error: Exception):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.reply("Użycie: `!rajd <liczba>`\nPrzykład: `!rajd 12`")
    elif isinstance(error, commands.BadArgument):
        await ctx.reply("Parametr musi być liczbą całkowitą. Przykład: `!rajd 12`")
    else:
        await ctx.reply(f"Wystąpił błąd: `{error}`")


@clear_command.error
async def clear_command_error(ctx: commands.Context, error: Exception):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.reply("Użycie: `!clear <liczba>`\nPrzykład: `!clear 10` albo `!clear 0`")
    elif isinstance(error, commands.BadArgument):
        await ctx.reply("Parametr musi być liczbą całkowitą. Przykład: `!clear 25`")
    else:
        await ctx.reply(f"Wystąpił błąd: `{error}`")


# =========================
# START
# =========================
bot.run(TOKEN)
