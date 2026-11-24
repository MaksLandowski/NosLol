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
# INTERACTIVE LAND OF LIFE LOBBIES (v2)
# =========================
import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from discord.ext import tasks

LOBBY_CATEGORY = os.getenv('LOL_LOBBY_CATEGORY', 'Land of Life')
CREATE_CHANNEL = 'create-lol'
PARTY_FILE = Path('parties.json')
BERLIN = ZoneInfo('Europe/Berlin')
LEVELS = {f'C{n}-{n+9}': (emoji, colour) for n, emoji, colour in [
    (30,'🟢',0x78B159),(40,'🟣',0x9266CC),(50,'🟤',0xA66A46),
    (60,'🔵',0x3498DB),(70,'🔴',0xE74C3C),(80,'🟡',0xF1C40F),(90,'⚪',0xEEEEEE)]}
CLASSES = {
    'Swordsman': ('🗡️', ['Swordsman','Warrior','Ninja','Crusader','Berserker','Gladiator','Battlemonk','Deathreaper','Renegade','Waterfallberserker','Dragonknight','Stonebreaker']),
    'Archer': ('🏹', ['Archer','Ranger','Assassin','Destroyer','Wildkeeper','Firecannoneer','Scout','Demonhunter','Avengingangel','Sunchaser','Blaster','Foghunter']),
    'Mage': ('🪄', ['Mage','Redmage','Holymage','Bluemagician','Darkgunner','Vulcano','Tidelord','Seer','Archmage','Voodoo','Gravity','Firestorm']),
    'Martial Artist': ('🥊', ['MartialArtist','Draconicfist','Mysticarts','Masterwolf','Demonwarrior']),
    'Any / flexible': ('❓', ['Any / flexible']),
}
NO_MENTIONS = discord.AllowedMentions.none()
party_lock = asyncio.Lock()
log = logging.getLogger('lol_lobby')

def load_parties():
    if not PARTY_FILE.exists():
        return {}
    data = json.loads(PARTY_FILE.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise RuntimeError('Invalid parties.json; restore it from backup.')
    return data

parties = load_parties()

def save_parties():
    tmp = PARTY_FILE.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(parties, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, PARTY_FILE)

def next_start(hour):
    now = datetime.now(timezone.utc)
    today = now.astimezone(BERLIN).date()
    candidates = set()
    for day in (today, today + timedelta(days=1)):
        for fold in (0, 1):
            local = datetime(day.year, day.month, day.day, hour, tzinfo=BERLIN, fold=fold)
            utc = local.astimezone(timezone.utc)
            if utc.astimezone(BERLIN).replace(tzinfo=None) == local.replace(tzinfo=None) and utc > now:
                candidates.add(utc)
    return int(min(candidates).timestamp())

def player(uid, group='Any / flexible', spec='Any / flexible'):
    return {'id': uid, 'class': group, 'spec': spec}

def find_player(p, uid):
    return next((x for x in p['players'] + p['bench'] if x['id'] == uid), None)

def party_embed(p):
    emoji, colour = LEVELS[p['level']]
    start = datetime.fromtimestamp(p['start'], BERLIN)
    end = datetime.fromtimestamp(p['end'], BERLIN)
    e = discord.Embed(title=f'🏰 Land of Life · LEVEL {p["level"]} {emoji}', colour=colour)
    e.add_field(name='🕒 Server Time', value=f'{start:%d.%m.%Y} · {start:%H:%M} – {end:%H:%M} (Berlin)', inline=False)
    e.add_field(name='🌍 Local Time', value=f'<t:{p["start"]}:f> – <t:{p["end"]}:t>\n(<t:{p["start"]}:R>)', inline=False)
    e.add_field(name='🔹 Channel / Area', value=f'CH {p["game_channel"]} · {p["area"]}', inline=True)
    e.add_field(name='👑 Leader', value=f'<@{p["leader"]}>', inline=True)
    n, cap = len(p['players']), p['capacity']
    e.add_field(name='👥 Party', value=f'{"▰"*n}{"▱"*(cap-n)} {n}/{cap}', inline=True)
    lines = []
    for i in range(cap):
        if i >= n:
            lines.append(f'{i+1}. 🔓 **open**')
        else:
            x = p['players'][i]
            crown = '👑 ' if x['id'] == p['leader'] else ''
            lines.append(f'{i+1}. {crown}{CLASSES[x["class"]][0]} **{x["spec"]}** <@{x["id"]}>')
    e.add_field(name='Slots', value='\n'.join(lines), inline=False)
    if p['bench']:
        bench = [f'{i+1}. {CLASSES[x["class"]][0]} {x["spec"]} <@{x["id"]}>' for i,x in enumerate(p['bench'][:12])]
        if len(p['bench']) > 12:
            bench.append(f'+ {len(p["bench"])-12} more')
        e.add_field(name='🪑 Bench', value='\n'.join(bench), inline=False)
    e.add_field(name='📝 Notes', value=p['notes'] or 'None', inline=False)
    e.set_footer(text=f'Party ID {p["channel_id"]} · automatically closes after the run')
    return e

async def get_lobby_channel(p):
    ch = bot.get_channel(p['channel_id'])
    if ch is None:
        ch = await bot.fetch_channel(p['channel_id'])
    if not isinstance(ch, discord.TextChannel) or ch.guild.id != p['guild_id'] or ch.topic != p['topic']:
        raise RuntimeError('Lobby channel marker mismatch; refusing to modify/delete it.')
    return ch

async def refresh_party(p):
    ch = await get_lobby_channel(p)
    msg = await ch.fetch_message(p['message_id'])
    await msg.edit(embed=party_embed(p), allowed_mentions=NO_MENTIONS)

async def close_party(p):
    try:
        ch = await get_lobby_channel(p)
        await ch.delete(reason='Land of Life party closed')
    except discord.NotFound:
        pass
    parties.pop(str(p['channel_id']), None)
    save_parties()

def promote(p):
    while p['bench'] and len(p['players']) < p['capacity']:
        p['players'].append(p['bench'].pop(0))
    if p['players'] and not any(x['id'] == p['leader'] for x in p['players']):
        p['leader'] = p['players'][0]['id']

async def private(i, message):
    if i.response.is_done():
        await i.followup.send(message, ephemeral=True, allowed_mentions=NO_MENTIONS)
    else:
        await i.response.send_message(message, ephemeral=True, allowed_mentions=NO_MENTIONS)

def active_party(i, channel_id=None):
    p = parties.get(str(channel_id or i.channel_id))
    if p and p['guild_id'] == i.guild_id and p['end'] > time.time():
        return p
    return None

class SafeView(discord.ui.View):
    async def on_error(self, interaction, error, item):
        log.error('Lobby interaction failed', exc_info=(type(error), error, error.__traceback__))
        await private(interaction, 'Operation failed. Please contact a server administrator.')

class ActionButton(discord.ui.Button):
    def __init__(self, label, custom_id, action, *, row=0, style=discord.ButtonStyle.secondary, emoji=None):
        super().__init__(label=label, custom_id=custom_id, row=row, style=style, emoji=emoji)
        self.action = action
    async def callback(self, interaction):
        await self.action(interaction)

class Choice(discord.ui.Select):
    def __init__(self, placeholder, values, action, *, row=0, default=None):
        options = [discord.SelectOption(label=str(v), value=str(v), default=str(v)==str(default)) for v in values]
        super().__init__(placeholder=placeholder, options=options, row=row, min_values=1, max_values=1)
        self.action = action
    async def callback(self, interaction):
        await self.action(interaction, self.values[0])

class SpecView(SafeView):
    def __init__(self, group, channel_id):
        super().__init__(timeout=180)
        self.group, self.channel_id = group, channel_id
        self.add_item(Choice('Select your subclass / character', CLASSES[group][1], self.choose))
    async def choose(self, i, spec):
        await i.response.defer(ephemeral=True, thinking=True)
        async with party_lock:
            p = active_party(i, self.channel_id)
            if not p:
                return await private(i, 'This party is no longer available.')
            uid = i.user.id
            x = find_player(p, uid)
            if x:
                x.update(player(uid, self.group, spec))
                result = f'✅ Your character is now **{spec}**.'
            elif len(p['players']) < p['capacity']:
                p['players'].append(player(uid, self.group, spec))
                result = f'✅ You joined as **{spec}**!'
            else:
                return await private(i, 'Party is full. Use **Bench**, then choose your class.')
            save_parties()
            await refresh_party(p)
            await private(i, result)

class NoteModal(discord.ui.Modal, title='Party notes'):
    note = discord.ui.TextInput(label='Notes', style=discord.TextStyle.paragraph, max_length=500, required=False)
    def __init__(self, p):
        super().__init__(timeout=180)
        self.channel_id = p['channel_id']
        self.note.default = p['notes']
    async def on_submit(self, i):
        await i.response.defer(ephemeral=True, thinking=True)
        async with party_lock:
            p = active_party(i, self.channel_id)
            if not p or i.user.id != p['leader']:
                return await private(i, '❌ Only the party leader can edit the notes.')
            p['notes'] = str(self.note.value)
            save_parties()
            await refresh_party(p)
            await private(i, '✅ Notes updated.')

class PartyView(SafeView):
    def __init__(self):
        super().__init__(timeout=None)
        for index,(group,(emoji,_)) in enumerate(CLASSES.items()):
            async def choose(i, group=group):
                if not active_party(i):
                    return await private(i, 'This party is no longer available.')
                if group == 'Any / flexible':
                    return await SpecView(group, i.channel_id).choose(i, group)
                await i.response.send_message(f'{CLASSES[group][0]} **{group}** Select your subclass / character:', view=SpecView(group, i.channel_id), ephemeral=True)
            self.add_item(ActionButton(group, f'lolv2:class:{index}', choose, row=0, style=discord.ButtonStyle.primary, emoji=emoji))
        for label, key, emoji in [('Leave','leave','🚪'),('Bench','bench','🪑'),('Leave Bench','unbench','❌'),('Ping party','ping','🔔'),('Note','note','📝')]:
            async def action(i, key=key):
                await self.handle(i, key)
            self.add_item(ActionButton(label, f'lolv2:{key}', action, row=1, emoji=emoji,
                style=discord.ButtonStyle.primary if key in ('ping','note') else discord.ButtonStyle.secondary))
        self.add_item(ActionButton('Close party','lolv2:close', self.close, row=2, emoji='🗑️', style=discord.ButtonStyle.danger))
    async def close(self, i):
        await self.handle(i, 'close')
    async def handle(self, i, key):
        if key == 'note':
            p = active_party(i)
            if not p or i.user.id != p['leader']:
                return await private(i, '❌ Only the party/raid leader can edit the notes.')
            return await i.response.send_modal(NoteModal(p))
        await i.response.defer(ephemeral=True, thinking=True)
        async with party_lock:
            p = active_party(i)
            if not p:
                return await private(i, 'This party is no longer available.')
            uid = i.user.id
            if key == 'close':
                if uid != p['leader'] and not i.user.guild_permissions.manage_channels:
                    return await private(i, '❌ Only the party leader or a channel administrator can close the party.')
                return await i.followup.send('Close and delete this lobby?', view=CloseConfirm(p['channel_id']), ephemeral=True)
            if key == 'ping':
                if uid != p['leader']:
                    return await private(i, '❌ Only the party leader can ping the party.')
                if time.time() - p.get('last_ping',0) < 600:
                    return await private(i, 'Please wait 10 minutes between party pings.')
                ids = [x['id'] for x in p['players']]
                ch = await get_lobby_channel(p)
                await ch.send('🔔 Party reminder: ' + ' '.join(f'<@{x}>' for x in ids), allowed_mentions=discord.AllowedMentions(users=[discord.Object(id=x) for x in ids], roles=False, everyone=False))
                p['last_ping'] = int(time.time())
                save_parties()
                return await private(i, '✅ Party notified.')
            if key == 'leave':
                if not any(x['id']==uid for x in p['players']):
                    return await private(i, 'You are not in the party. Use Leave Bench if applicable.')
                p['players'] = [x for x in p['players'] if x['id'] != uid]
                promote(p)
                if not p['players']:
                    await private(i, 'You left. Empty party will be closed.')
                    return await close_party(p)
                result = '🚪 You left the party.'
            elif key == 'bench':
                if find_player(p, uid):
                    return await private(i, 'You are already in the party or on the bench.')
                if len(p['players']) < p['capacity']:
                    return await private(i, f'The party is not full yet ({len(p["players"])}/{p["capacity"]}). You can join directly using a class button.')
                if len(p['bench']) >= 30:
                    return await private(i, 'Bench is full.')
                p['bench'].append(player(uid))
                result = '🪑 You joined the bench. Choose your class to update it.'
            elif key == 'unbench':
                if not any(x['id']==uid for x in p['bench']):
                    return await private(i, 'You are not on the bench.')
                p['bench'] = [x for x in p['bench'] if x['id'] != uid]
                result = 'You left the bench.'
            else:
                return
            save_parties()
            await refresh_party(p)
            await private(i, result)

class CloseConfirm(SafeView):
    def __init__(self, channel_id):
        super().__init__(timeout=60)
        self.channel_id = channel_id
        self.add_item(ActionButton('Delete lobby','lolv2:confirm', self.confirm, style=discord.ButtonStyle.danger))
    async def confirm(self,i):
        await i.response.defer(ephemeral=True, thinking=True)
        async with party_lock:
            p = active_party(i, self.channel_id)
            if not p or (i.user.id != p['leader'] and not i.user.guild_permissions.manage_channels):
                return await private(i, 'No permission or party already closed.')
            await close_party(p)

async def category_for(guild):
    category_id = os.getenv('LOL_LOBBY_CATEGORY_ID')
    if category_id:
        category = guild.get_channel(int(category_id))
        if not isinstance(category, discord.CategoryChannel):
            raise RuntimeError('LOL_LOBBY_CATEGORY_ID is invalid for this server.')
        return category
    matches = [x for x in guild.categories if x.name == LOBBY_CATEGORY]
    if len(matches) > 1:
        raise RuntimeError('Multiple categories found. Set LOL_LOBBY_CATEGORY_ID.')
    if matches:
        return matches[0]
    return await guild.create_category(LOBBY_CATEGORY, reason='Land of Life setup')

class CreateView(SafeView):
    def __init__(self, hour, member):
        super().__init__(timeout=300)
        self.start = next_start(hour)
        self.game_channel = '1'
        self.level = next((r.name for r in member.roles if r.name in LEVELS), 'C60-69')
        self.capacity = '6'
        self.area = 'Any'
        for row,(attr,label,choices) in enumerate([
            ('game_channel','Select in-game channel (CH 1)',range(1,MAX_CHANNELS+1)),
            ('level','Select level range',LEVELS.keys()),
            ('capacity','Select party size',range(3,7)),
            ('area','Select exping area',['Any','Bottom','Middle','Top'])]):
            async def choose(i, value, attr=attr):
                setattr(self, attr, value)
                await i.response.defer()
            self.add_item(Choice(label, choices, choose, row=row, default=getattr(self, attr)))
        self.add_item(ActionButton('Create the final party','lolv2:create', self.create, row=4, style=discord.ButtonStyle.success, emoji='🚀'))
    async def create(self,i):
        await i.response.defer(ephemeral=True, thinking=True)
        async with party_lock:
            if self.start <= time.time():
                return await private(i, 'This time has passed. Please select the hour again.')
            for p in parties.values():
                if p['guild_id']==i.guild_id and p['start']==self.start and p['game_channel']==int(self.game_channel) and p['level']==self.level and p['area']==self.area:
                    return await private(i, f'A matching party already exists: <#{p["channel_id"]}>')
            cat = await category_for(i.guild)
            local = datetime.fromtimestamp(self.start, BERLIN)
            name = f'party-{local:%H-%M}-ch{self.game_channel}-{self.level.lower()}'
            if self.area != 'Any':
                name += '-' + self.area.lower()
            topic = f'Land of Life | Start {local:%d.%m.%Y %H:%M} | CH {self.game_channel} | LEVEL {self.level} | {self.area} | lobby-v2:{i.id}'
            ch = await i.guild.create_text_channel(name, category=cat, topic=topic, reason='Land of Life party')
            p = dict(guild_id=i.guild_id, channel_id=ch.id, topic=topic, start=self.start, end=self.start+3600,
                     game_channel=int(self.game_channel), level=self.level, capacity=int(self.capacity), area=self.area,
                     leader=i.user.id, players=[player(i.user.id)], bench=[], notes='', last_ping=0)
            try:
                msg = await ch.send(embed=party_embed(p), view=PartyView(), allowed_mentions=NO_MENTIONS)
                p['message_id'] = msg.id
                parties[str(ch.id)] = p
                save_parties()
            except Exception:
                parties.pop(str(ch.id), None)
                try:
                    await ch.delete(reason='Incomplete lobby creation')
                except discord.HTTPException:
                    log.exception('Could not delete incomplete lobby')
                raise
            for item in self.children:
                item.disabled = True
            try:
                if i.message:
                    await i.message.edit(view=self)
            except discord.HTTPException:
                pass
            await private(i, f'🏰 **Land of Life party successfully created!**\n{ch.mention}\n🕒 <t:{p["start"]}:f> | 🔹 CH {p["game_channel"]}\n🏅 {p["level"]} | 👥 {p["capacity"]} players')

class ScheduleView(SafeView):
    def __init__(self):
        super().__init__(timeout=None)
        for index,hour in enumerate(range(1,24,2)):
            async def select(i, hour=hour):
                v = CreateView(hour, i.user)
                await i.response.send_message(f'🕒 **Time {hour:02d}:00 selected.**\nStart: <t:{v.start}:F>\nPlease select the in-game channel, level range, party size and area:', view=v, ephemeral=True)
            self.add_item(ActionButton(f'{hour:02d}:00', f'lolv2:hour:{hour}', select, row=index//5))

class LevelView(SafeView):
    def __init__(self):
        super().__init__(timeout=None)
        for index,(level,(emoji,_)) in enumerate(LEVELS.items()):
            async def select(i, level=level):
                await i.response.defer(ephemeral=True, thinking=True)
                async with party_lock:
                    matches = [r for r in i.guild.roles if r.name == level]
                    if len(matches) != 1:
                        return await private(i, 'Level role missing or ambiguous. Ask an administrator to run !setup-lol.')
                    role = matches[0]
                    if role.managed or role >= i.guild.me.top_role or role.permissions.value != 0:
                        return await private(i, 'This level role is not safe to self-assign. Contact an administrator.')
                    # Add/remove only level roles, leaving all other roles intact.
                    previous = [r for r in i.user.roles if r.name in LEVELS and r.id != role.id
                                and not r.managed and r < i.guild.me.top_role and r.permissions.value == 0]
                    if role not in i.user.roles:
                        await i.user.add_roles(role, reason='LOL level selection')
                    if previous:
                        await i.user.remove_roles(*previous, reason='LOL level selection')
                    await private(i, f'✅ Your level range is now **{level}**.')
            self.add_item(ActionButton(level, f'lolv2:level:{level}', select, row=index//4, emoji=emoji, style=discord.ButtonStyle.primary))

@bot.command(name='setup-lol')
@commands.guild_only()
@commands.has_guild_permissions(administrator=True)
async def setup_lol(ctx):
    async with party_lock:
        cat = await category_for(ctx.guild)
        for level,(_,colour) in LEVELS.items():
            matches = [r for r in ctx.guild.roles if r.name == level]
            if len(matches) > 1:
                return await ctx.reply(f'Duplicate roles named {level}. Setup stopped.')
            role = matches[0] if matches else None
            if role is None:
                await ctx.guild.create_role(name=level, colour=discord.Colour(colour), reason='LOL level roles')
            elif role.managed or role >= ctx.guild.me.top_role or role.permissions.value != 0:
                return await ctx.reply(f'Role {level} must be below the bot and have no server permissions. Setup stopped.')
        ch = discord.utils.get(cat.text_channels, name=CREATE_CHANNEL)
        if ch is None:
            ch = await ctx.guild.create_text_channel(CREATE_CHANNEL, category=cat, reason='LOL schedule panel')
            # Prevent normal members from typing in the panel; buttons still work.
            everyone_overwrite = ch.overwrites_for(ctx.guild.default_role)
            everyone_overwrite.send_messages = False
            await ch.set_permissions(ctx.guild.default_role, overwrite=everyone_overwrite)
            bot_overwrite = ch.overwrites_for(ctx.guild.me)
            bot_overwrite.update(view_channel=True, send_messages=True, read_message_history=True)
            await ch.set_permissions(ctx.guild.me, overwrite=bot_overwrite)
        markers = set()
        async for message in ch.history(limit=100):
            if message.author.id == bot.user.id and message.embeds:
                markers.add(message.embeds[0].footer.text)
        if 'LOL v2 · schedule' not in markers:
            e = discord.Embed(title='🏰 Land of Life', description='Choose a time, in-game channel, level range and party size. The bot opens a party channel for you.\n\n🕒 **Schedule**\n🇪🇺 Europe/Berlin game time (local time shown in each lobby).', colour=0x2ECC71)
            e.set_footer(text='LOL v2 · schedule')
            await ch.send(embed=e, view=ScheduleView())
        if 'LOL v2 · levels' not in markers:
            e = discord.Embed(title='🎮 Select Your Level Range', description='Select your current level range to receive its role. Selecting a different level replaces your previous level role.\nYou can change it at any time.', colour=0x2ECC71)
            e.set_footer(text='LOL v2 · levels')
            await ch.send(embed=e, view=LevelView())
        await ctx.reply(f'✅ Panel ready: {ch.mention}. New lobbies appear in **{cat.name}**.', allowed_mentions=NO_MENTIONS)

@setup_lol.error
async def setup_lol_error(ctx,error):
    if isinstance(error, (commands.MissingPermissions,commands.NoPrivateMessage)):
        await ctx.reply('Only a server administrator can run !setup-lol on a server.')
    else:
        log.error('Setup failed: %s', error)
        await ctx.reply('Setup failed. Check bot permissions, role hierarchy and server logs.')

@tasks.loop(minutes=1)
async def lobby_cleanup():
    async with party_lock:
        for p in list(parties.values()):
            if p['end'] <= time.time():
                try:
                    await close_party(p)
                except Exception:
                    log.exception('Could not clean up lobby %s', p['channel_id'])

@bot.listen('on_ready')
async def lobby_on_ready():
    if not getattr(bot,'_lobby_views_registered',False):
        bot.add_view(ScheduleView())
        bot.add_view(LevelView())
        bot.add_view(PartyView())
        bot._lobby_views_registered = True
    if not lobby_cleanup.is_running():
        lobby_cleanup.start()

@bot.listen('on_guild_channel_delete')
async def lobby_deleted(channel):
    async with party_lock:
        if str(channel.id) in parties:
            parties.pop(str(channel.id),None)
            save_parties()

# =========================
# START
# =========================
bot.run(TOKEN)
