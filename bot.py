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
# SPECIAL DM CONFIG
# =========================
SPECIAL_USER_ID = 326616606513954818 
DM_MESSAGE = "Zapisałeś się! 🔥"

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
# DM CONTROL
# =========================
notified_users = set()

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


async def resolve_payload_text_channel(payload: discord.RawReactionActionEvent):
    channel = bot.get_channel(payload.channel_id)
    if not isinstance(channel, discord.TextChannel):
        try:
            channel = await bot.fetch_channel(payload.channel_id)
        except Exception:
            return None
    return channel


# =========================
# REACTION HANDLERS
# =========================
async def handle_reaction_add(payload: discord.RawReactionActionEvent):
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

    if payload.user_id not in entry["queue"]:
        entry["queue"].append(payload.user_id)
        save_state(state)

        # ===== DM dla konkretnego usera =====
        if payload.user_id == SPECIAL_USER_ID and payload.user_id not in notified_users:
            try:
                user = await bot.fetch_user(payload.user_id)
                await user.send(DM_MESSAGE)
                notified_users.add(payload.user_id)
            except Exception as e:
                print("DM error:", e)


async def handle_reaction_remove(payload: discord.RawReactionActionEvent):
    entry = get_tracked_entry(payload.message_id)
    if entry:
        entry["queue"] = [u for u in entry["queue"] if u != payload.user_id]
        save_state(state)


# =========================
# EVENTS
# =========================
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")


@bot.event
async def on_raw_reaction_add(payload):
    await handle_reaction_add(payload)


@bot.event
async def on_raw_reaction_remove(payload):
    await handle_reaction_remove(payload)


# =========================
# START
# =========================
bot.run(TOKEN)
