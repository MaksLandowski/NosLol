import os
import json
from pathlib import Path

import discord
from discord.ext import commands

# =========================
# CONFIGURATION
# =========================
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("Missing DISCORD_TOKEN environment variable")

LOL_CHANNEL_NAME = "lol"
LOL60_CHANNEL_NAME = "lol60"
RAID_CHANNEL_NAME = "rajdy"

CLEAR_CHANNEL_NAMES = {LOL_CHANNEL_NAME, LOL60_CHANNEL_NAME, RAID_CHANNEL_NAME}
TRACKED_CHANNEL_NAMES = {LOL_CHANNEL_NAME, LOL60_CHANNEL_NAME, RAID_CHANNEL_NAME}

ALLOWED_ROLE_NAMES = [
    "lol",
    "lol60",
    "rajd",
]

CLEAR_ALLOWED_ROLE_NAME = "smietnik"

TARGET_EMOJI = "✅"
STATE_FILE = Path("state.json")
MAX_VISIBLE_USERS = 5
MAX_CHANNELS = 7

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
# STATE FILE
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
# HELPERS
# =========================
def has_allowed_role(member: discord.Member) -> bool:
    user_role_names = {role.name for role in member.roles}
    return any(role_name in user_role_names for role_name in ALLOWED_ROLE_NAMES)


def has_clear_role(member: discord.Member) -> bool:
    user_role_names = {role.name for role in member.roles}
    return CLEAR_ALLOWED_ROLE_NAME in user_role_names


def get_tracked_entry(message_id: int) -> dict | None:
    tracked = state.setdefault("tracked_messages", {})
    entry = tracked.get(str(message_id))

    if entry is None:
        return None

    changed = False

    # migration from old format:
    # "123456789": "LOL 19:00 ch1 bottom ..."
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

    lines = [title, "", "Squad:"]

    for index in range(capacity):
        if index < len(squad):
            lines.append(f"{index + 1}. <@{squad[index]}>")
        else:
            lines.append(f"{index + 1}.")

    lines.append("")
    lines.append("Reserve:")

    reserve_visible_count = max(3, len(reserve))
    for index in range(reserve_visible_count):
        if index < len(reserve):
            lines.append(f"{index + 1}. <@{reserve[index]}>")
        else:
            lines.append(f"{index + 1}.")

    return "\n".join(lines)


def validate_lol_counts(bottom_count: int, middle_count: int, top_count: int) -> str | None:
    if bottom_count + middle_count > MAX_CHANNELS:
        return f"The total number of channels for bottom + middle cannot exceed {MAX_CHANNELS}."

    if middle_count + top_count > MAX_CHANNELS:
        return f"The total number of channels for middle + top cannot exceed {MAX_CHANNELS}."

    return None


def build_channel_numbers(
    bottom_count: int,
    middle_count: int,
    top_count: int
) -> tuple[list[int], list[int], list[int]]:
    bottom_channels = list(range(1, bottom_count + 1))

    middle_start = bottom_count + 1
    middle_channels = list(range(middle_start, middle_start + middle_count))

    top_channels: list[int] = []
    top_start = bottom_count + middle_count + 1

    for offset in range(top_count):
        channel_number = ((top_start + offset - 1) % MAX_CHANNELS) + 1
        top_channels.append(channel_number)

    return bottom_channels, middle_channels, top_channels


def build_headers(hour: int, bottom_count: int, middle_count: int, top_count: int) -> list[str]:
    formatted_hour = f"{hour:02d}:00"
    headers: list[str] = []

    bottom_channels, middle_channels, top_channels = build_channel_numbers(
        bottom_count, middle_count, top_count
    )

    for channel_number in bottom_channels:
        headers.append(f"LOL {formatted_hour} ch{channel_number} bottom (recommended lvl 30-40)")

    for channel_number in middle_channels:
        headers.append(f"LOL {formatted_hour} ch{channel_number} middle (recommended lvl 38-50)")

    for channel_number in top_channels:
        headers.append(f"LOL {formatted_hour} ch{channel_number} top (recommended lvl 48-60)")

    return headers


def build_headers_lol60(hour: int, bottom_count: int, middle_count: int, top_count: int) -> list[str]:
    formatted_hour = f"{hour:02d}:00"
    headers: list[str] = []

    bottom_channels, middle_channels, top_channels = build_channel_numbers(
        bottom_count, middle_count, top_count
    )

    for channel_number in bottom_channels:
        headers.append(f"LOL60 {formatted_hour} ch{channel_number} bottom (recommended lvl 60-68)")

    for channel_number in middle_channels:
        headers.append(f"LOL60 {formatted_hour} ch{channel_number} middle (recommended lvl 68-73)")

    for channel_number in top_channels:
        headers.append(f"LOL60 {formatted_hour} ch{channel_number} top (recommended lvl 73-80)")

    return headers


async def get_target_channel(
    channel_name: str,
    guild: discord.Guild | None = None
) -> discord.TextChannel | None:
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


async def create_board(
    channel: discord.TextChannel,
    headers: list[str],
    intro_message: str | None = None
) -> None:
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
    title = f"RAID ({capacity} people)"
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


async def resolve_payload_text_channel(
    payload: discord.RawReactionActionEvent
) -> discord.TextChannel | None:
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
# EVENTS
# =========================
@bot.event
async def on_ready():
    print(f"Logged in as: {bot.user} (ID: {bot.user.id})")
    await rebuild_all_tracked_messages()


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    await handle_reaction_add(payload)


@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    await handle_reaction_remove(payload)


# =========================
# COMMAND !lol
# =========================
@bot.command(name="lol")
async def lol_command(ctx: commands.Context, hour: int, bottom_count: int, middle_count: int, top_count: int):
    if not has_allowed_role(ctx.author):
        await ctx.reply("You do not have the required role to use this command.")
        return

    if ctx.channel.name != LOL_CHANNEL_NAME:
        await ctx.reply(f"This command only works in the #{LOL_CHANNEL_NAME} channel.")
        return

    if not (0 <= hour <= 23):
        await ctx.reply("Hour must be between 0 and 23.")
        return

    if bottom_count < 0 or middle_count < 0 or top_count < 0:
        await ctx.reply("The values for bottom / middle / top cannot be negative.")
        return

    total = bottom_count + middle_count + top_count
    if total == 0:
        await ctx.reply("All values are 0, so there is nothing to create.")
        return

    validation_error = validate_lol_counts(bottom_count, middle_count, top_count)
    if validation_error is not None:
        await ctx.reply(validation_error)
        return

    headers = build_headers(hour, bottom_count, middle_count, top_count)
    await create_board(ctx.channel, headers, intro_message="Sign-ups for LOL 30-64")

    try:
        await ctx.message.delete()
    except Exception:
        pass


# =========================
# COMMAND !lol60
# =========================
@bot.command(name="lol60")
async def lol60_command(ctx: commands.Context, hour: int, bottom_count: int, middle_count: int, top_count: int):
    if not has_allowed_role(ctx.author):
        await ctx.reply("You do not have the required role to use this command.")
        return

    if ctx.channel.name != LOL60_CHANNEL_NAME:
        await ctx.reply(f"This command only works in the #{LOL60_CHANNEL_NAME} channel.")
        return

    if not (0 <= hour <= 23):
        await ctx.reply("Hour must be between 0 and 23.")
        return

    if bottom_count < 0 or middle_count < 0 or top_count < 0:
        await ctx.reply("The values for bottom / middle / top cannot be negative.")
        return

    total = bottom_count + middle_count + top_count
    if total == 0:
        await ctx.reply("All values are 0, so there is nothing to create.")
        return

    validation_error = validate_lol_counts(bottom_count, middle_count, top_count)
    if validation_error is not None:
        await ctx.reply(validation_error)
        return

    headers = build_headers_lol60(hour, bottom_count, middle_count, top_count)
    await create_board(ctx.channel, headers, intro_message="Sign-ups for advanced LOL 60-82")

    try:
        await ctx.message.delete()
    except Exception:
        pass


# =========================
# COMMAND !rajd
# =========================
@bot.command(name="rajd")
async def rajd_command(ctx: commands.Context, capacity: int):
    if not has_allowed_role(ctx.author):
        await ctx.reply("You do not have the required role to use this command.")
        return

    if ctx.channel.name != RAID_CHANNEL_NAME:
        await ctx.reply(f"This command only works in the #{RAID_CHANNEL_NAME} channel.")
        return

    if not (8 <= capacity <= 20):
        await ctx.reply("The number of players for `!rajd` must be between 8 and 20.")
        return

    await create_raid(ctx.channel, capacity)

    try:
        await ctx.message.delete()
    except Exception:
        pass


# =========================
# COMMAND !clear
# =========================
@bot.command(name="clear")
async def clear_command(ctx: commands.Context, amount: int):
    if not has_clear_role(ctx.author):
        await ctx.reply(f"Only users with the `{CLEAR_ALLOWED_ROLE_NAME}` role can use this command.")
        return

    if ctx.channel.name not in CLEAR_CHANNEL_NAMES:
        allowed = ", ".join(f"#{name}" for name in sorted(CLEAR_CHANNEL_NAMES))
        await ctx.reply(f"This command only works in these channels: {allowed}.")
        return

    if amount < 0:
        await ctx.reply("Please provide a number equal to or greater than 0.")
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
# ERROR HANDLING
# =========================
@lol_command.error
async def lol_command_error(ctx: commands.Context, error: Exception):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.reply("Usage: `!lol <hour> <bottom> <middle> <top>`")
    elif isinstance(error, commands.BadArgument):
        await ctx.reply("All parameters must be numbers. Example: `!lol 19 3 2 1`")
    else:
        await ctx.reply(f"An error occurred: `{error}`")


@lol60_command.error
async def lol60_command_error(ctx: commands.Context, error: Exception):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.reply("Usage: `!lol60 <hour> <bottom> <middle> <top>`")
    elif isinstance(error, commands.BadArgument):
        await ctx.reply("All parameters must be numbers. Example: `!lol60 19 3 2 1`")
    else:
        await ctx.reply(f"An error occurred: `{error}`")


@rajd_command.error
async def rajd_command_error(ctx: commands.Context, error: Exception):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.reply("Usage: `!rajd <number>`\nExample: `!rajd 12`")
    elif isinstance(error, commands.BadArgument):
        await ctx.reply("The parameter must be an integer. Example: `!rajd 12`")
    else:
        await ctx.reply(f"An error occurred: `{error}`")


@clear_command.error
async def clear_command_error(ctx: commands.Context, error: Exception):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.reply("Usage: `!clear <number>`\nExample: `!clear 10` or `!clear 0`")
    elif isinstance(error, commands.BadArgument):
        await ctx.reply("The parameter must be an integer. Example: `!clear 25`")
    else:
        await ctx.reply(f"An error occurred: `{error}`")


# =========================
# START
# =========================
bot.run(TOKEN)
