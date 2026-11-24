import os
import json
import re
from pathlib import Path

import discord
from discord.ext import commands

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("Missing DISCORD_TOKEN environment variable")

MAX_CHANNELS = 7
intents = discord.Intents.default()
intents.guilds = True
intents.messages = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# =========================
# INTERACTIVE LAND OF LIFE LOBBIES (v4.1)
# =========================
import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from discord.ext import tasks
import aiohttp

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
# Icons verified on NosApki item pages (image IDs, not item IDs).
# NosTale artwork: Gameforge / Entwell; source: https://nosapki.com/en/items?category=specialist
SP_ICON_IDS = {
    'Warrior':901, 'Ninja':902, 'Crusader':909, 'Berserker':910,
    'Gladiator':2544, 'Battlemonk':2588, 'Deathreaper':2654, 'Renegade':2706,
    'Waterfallberserker':4496, 'Dragonknight':4862, 'Stonebreaker':7138,
    'Ranger':903, 'Assassin':904, 'Destroyer':911, 'Wildkeeper':912,
    'Firecannoneer':2545, 'Scout':2589, 'Demonhunter':2655, 'Avengingangel':2707,
    'Sunchaser':4494, 'Blaster':4860, 'Foghunter':7139,
    'Redmage':905, 'Holymage':906, 'Bluemagician':913, 'Darkgunner':914,
    'Vulcano':2546, 'Tidelord':2590, 'Seer':2656, 'Archmage':2708,
    'Voodoo':4497, 'Gravity':4863, 'Firestorm':7140,
    'Draconicfist':4048, 'Mysticarts':4093, 'Masterwolf':4126, 'Demonwarrior':4151,
}
CLASS_ICON_IDS = {'Swordsman':1, 'Archer':2, 'Mage':3, 'MartialArtist':4}
ICON_URLS = {
    **{name: f'https://nosapki.com/images/icons/{number}.png' for name, number in SP_ICON_IDS.items()},
    **{name: f'https://nosapki.com/images/nt-images/class_{number}.png' for name, number in CLASS_ICON_IDS.items()},
}
CLASS_BASE = {'Martial Artist': 'MartialArtist'}
app_icons = {}
icon_lock = asyncio.Lock()

def icon_name(spec):
    return 'nt_' + spec.lower().replace(' ', '')

def character_icon(group, spec):
    return app_icons.get(icon_name(spec)) or app_icons.get(icon_name(CLASS_BASE.get(group, group))) or CLASSES[group][0]

async def load_app_icons():
    # Application emojis persist in Discord, independent of parties.json.
    emojis = await bot.fetch_application_emojis()
    app_icons.clear()
    app_icons.update({e.name: discord.PartialEmoji(name=e.name, id=e.id, animated=e.animated)
                      for e in emojis if e.name in {icon_name(s) for s in ICON_URLS}})

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
            lines.append(f'{i+1}. {crown}{character_icon(x["class"], x["spec"])} **{x["spec"]}** <@{x["id"]}>')
    e.add_field(name='Slots', value='\n'.join(lines), inline=False)
    if p['bench']:
        bench = []
        for i, x in enumerate(p['bench'][:12]):
            line = f'{i+1}. {character_icon(x["class"], x["spec"])} {x["spec"]} <@{x["id"]}>'
            # Custom emoji markup counts towards Discord's 1024-character field limit.
            if len('\n'.join(bench + [line])) > 990:
                break
            bench.append(line)
        if len(p['bench']) > len(bench):
            bench.append(f'+ {len(p["bench"])-len(bench)} more')
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
    await msg.edit(embed=party_embed(p), view=PartyView(), allowed_mentions=NO_MENTIONS)

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
    def __init__(self, placeholder, values, action, *, row=0, default=None,
                 label_for=None, emoji_for=None, description_for=None):
        options = [discord.SelectOption(
            label=label_for(v) if label_for else str(v), value=str(v),
            default=str(v)==str(default), emoji=emoji_for(v) if emoji_for else None,
            description=description_for(v) if description_for else None) for v in values]
        super().__init__(placeholder=placeholder, options=options, row=row, min_values=1, max_values=1)
        self.action = action
    async def callback(self, interaction):
        await self.action(interaction, self.values[0])

class SpecView(SafeView):
    def __init__(self, group, channel_id):
        super().__init__(timeout=180)
        self.group, self.channel_id = group, channel_id
        self.add_item(Choice('Select your subclass / character', CLASSES[group][1], self.choose,
                             emoji_for=lambda spec: character_icon(group, spec),
                             description_for=lambda spec: f'{group} · {spec}'))
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
                result = f'✅ Your character is now {character_icon(self.group, spec)} **{spec}**.'
            elif len(p['players']) < p['capacity']:
                p['players'].append(player(uid, self.group, spec))
                result = f'✅ You joined as {character_icon(self.group, spec)} **{spec}**!'
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
                await i.response.send_message(f'{character_icon(group, CLASS_BASE.get(group, group))} **{group}** Select your subclass / character:', view=SpecView(group, i.channel_id), ephemeral=True)
            self.add_item(ActionButton(group, f'lolv2:class:{index}', choose, row=0, style=discord.ButtonStyle.primary, emoji=character_icon(group, CLASS_BASE.get(group, group))))
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
                if uid != p['leader']:
                    return await private(i, '❌ Only the party leader can close the party.')
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
            if not p:
                return await private(i, 'This party is no longer available.')
            if i.user.id != p['leader']:
                return await private(i, '❌ Only the party leader can close the party.')
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

def lol_zone(level):
    # Normal LoL (C30-C59) and advanced LoL (C60+) use separate maps.
    return 'LOL60' if int(level.split('-')[0][1:]) >= 60 else 'LOL'


def find_party_conflict(existing, *, guild_id, start, game_channel, level, area):
    """Only Bottom + Top may share a channel in the same LoL map/time."""
    zone = lol_zone(level)
    for p in existing:
        if (p['guild_id'] != guild_id or p['start'] != start
                or p['game_channel'] != game_channel or lol_zone(p['level']) != zone):
            continue
        # Same area, Middle or Any are mutually exclusive with other parties.
        if {area, p['area']} != {'Bottom', 'Top'}:
            return p
    return None


class CreateView(SafeView):
    def __init__(self, hour, member):
        super().__init__(timeout=300)
        self.start = next_start(hour)
        self.game_channel = '1'
        self.level = next((r.name for r in member.roles if r.name in LEVELS), 'C60-69')
        self.capacity = '6'
        self.area = 'Any'
        for row,(attr,label,choices) in enumerate([
            ('game_channel','Select in-game channel (CH1)',range(1,MAX_CHANNELS+1)),
            ('level','Select level range',LEVELS.keys()),
            ('capacity','Select party size',range(3,7)),
            ('area','Select exping area',['Any','Bottom','Middle','Top'])]):
            async def choose(i, value, attr=attr):
                setattr(self, attr, value)
                await i.response.defer()
            self.add_item(Choice(label, choices, choose, row=row, default=getattr(self, attr),
                                 label_for=(lambda v: f'CH{v}') if attr == 'game_channel' else None))
        self.add_item(ActionButton('Create the final party','lolv2:create', self.create, row=4, style=discord.ButtonStyle.success, emoji='🚀'))
    async def create(self,i):
        await i.response.defer(ephemeral=True, thinking=True)
        async with party_lock:
            if self.start <= time.time():
                return await private(i, 'This time has passed. Please select the hour again.')
            # Check and reserve under the same lock to prevent simultaneous bookings.
            conflict = find_party_conflict(
                parties.values(), guild_id=i.guild_id, start=self.start,
                game_channel=int(self.game_channel), level=self.level, area=self.area)
            if conflict is not None:
                local = datetime.fromtimestamp(self.start, BERLIN)
                return await private(i,
                    f'❌ CH{self.game_channel} is already occupied by a **{conflict["area"]}** '
                    f'party at {local:%H:%M} ({lol_zone(self.level)}, Berlin time): '
                    f'<#{conflict["channel_id"]}>.\nPlease select another channel or compatible area.')
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

@bot.command(name='setup-icons')
@commands.guild_only()
@commands.has_guild_permissions(administrator=True)
async def setup_icons(ctx):
    # Explicit admin-only import. Safe to repeat: only missing emojis are created.
    if icon_lock.locked():
        return await ctx.reply('Icon import is already running.')
    async with icon_lock:
        await ctx.reply(f'Importing missing NosTale icons ({len(ICON_URLS)} total). Existing icons will be reused.')
        await load_app_icons()
        created = 0
        failures = []
        consecutive_network_errors = 0
        timeout = aiohttp.ClientTimeout(total=12)
        async with aiohttp.ClientSession(timeout=timeout, headers={'User-Agent':'NosTale-Discord-PartyBot/3.0'}) as session:
            for spec, url in ICON_URLS.items():
                name = icon_name(spec)
                if name in app_icons:
                    continue
                if consecutive_network_errors >= 3:
                    failures.append(f'{spec}: source unavailable')
                    continue
                try:
                    async with session.get(url, allow_redirects=False) as response:
                        response.raise_for_status()
                        # Limit downloads to Discord's emoji size limit.
                        data = await response.content.readexactly(8)
                        if data != b'\x89PNG\r\n\x1a\n':
                            raise ValueError('Source did not return a PNG')
                        async for chunk in response.content.iter_chunked(8192):
                            data += chunk
                            if len(data) > 256 * 1024:
                                raise ValueError('PNG exceeds 256 KiB')
                    consecutive_network_errors = 0
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, asyncio.IncompleteReadError) as error:
                    consecutive_network_errors += 1
                    failures.append(f'{spec}: {type(error).__name__}')
                    log.warning('Icon download failed %s: %s', url, error)
                    continue
                try:
                    emoji = await bot.create_application_emoji(name=name, image=data)
                    app_icons[name] = discord.PartialEmoji(name=emoji.name, id=emoji.id, animated=emoji.animated)
                    created += 1
                except discord.HTTPException as error:
                    failures.append(f'{spec}: Discord HTTP {error.status}')
                    log.warning('Emoji creation failed %s: %s', name, error)
        refreshed = 0
        async with party_lock:
            for p in list(parties.values()):
                if p['guild_id'] == ctx.guild.id and p['end'] > time.time():
                    try:
                        await refresh_party(p)
                        refreshed += 1
                    except Exception:
                        log.exception('Could not refresh lobby %s', p['channel_id'])
        result = (f'✅ Icons ready: **{len(app_icons)}/{len(ICON_URLS)}** (new: {created}). '
                  f'Updated lobbies: {refreshed}.')
        if failures:
            result += '\n⚠️ Missing icons use the standard class emoji. Retry `!setup-icons`.\n' + ', '.join(failures)
        await ctx.reply(result[:1900], allowed_mentions=NO_MENTIONS)

@setup_icons.error
async def setup_icons_error(ctx, error):
    if isinstance(error, (commands.MissingPermissions, commands.NoPrivateMessage)):
        await ctx.reply('Only a server administrator can run !setup-icons on a server.')
    else:
        log.error('Icon setup failed: %s', error)
        await ctx.reply('Icon setup failed. Check the server logs. Existing lobbies remain usable.')

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

def command_party(ctx):
    # Commands operate only on an active lobby in the invoking guild.
    p = parties.get(str(ctx.channel.id))
    if p and ctx.guild and p['guild_id'] == ctx.guild.id and p['end'] > time.time():
        return p
    return None


@bot.command(name='kick', ignore_extra=False)
@commands.guild_only()
async def kick_command(ctx, target: str = ''):
    """Remove a player from this party (party leader only). Usage: !kick @player"""
    async with party_lock:
        p = command_party(ctx)
        if not p:
            return await ctx.reply('Use !kick inside an active party lobby.')
        if ctx.author.id != p['leader']:
            return await ctx.reply('❌ Only the party leader can kick players.')
        # Accept a Discord user mention or ID; no member lookup is necessary.
        match = re.fullmatch(r'<@!?(\d{15,20})>|(\d{15,20})', target)
        if not match:
            return await ctx.reply('Usage: !kick @player (or !kick user_id)')
        uid = int(match.group(1) or match.group(2))
        if uid == p['leader']:
            return await ctx.reply('You cannot kick yourself. Use Leave or !close instead.')
        if not find_player(p, uid):
            return await ctx.reply('That player is not in this party or on the bench.')
        # Verify that this is the tracked lobby before mutating its state.
        await get_lobby_channel(p)
        p['players'] = [x for x in p['players'] if x['id'] != uid]
        p['bench'] = [x for x in p['bench'] if x['id'] != uid]
        promote(p)
        save_parties()
        await refresh_party(p)
        await ctx.reply(f'✅ <@{uid}> was removed from the party.', allowed_mentions=NO_MENTIONS)


@bot.command(name='close', ignore_extra=False)
@commands.guild_only()
async def close_command(ctx):
    """Close this lobby immediately (party leader or server administrator)."""
    async with party_lock:
        p = command_party(ctx)
        if not p:
            return await ctx.reply('Use !close inside an active party lobby.')
        if ctx.author.id != p['leader'] and not ctx.author.guild_permissions.administrator:
            return await ctx.reply('❌ Only the party leader or a server administrator can close the party.')
        await close_party(p)


@kick_command.error
@close_command.error
async def lobby_command_error(ctx, error):
    if isinstance(error, commands.NoPrivateMessage):
        return await ctx.reply('Use this command inside a party lobby on the server.')
    if isinstance(error, commands.UserInputError):
        return await ctx.reply('Usage: !kick @player or !close')
    log.error('Lobby command failed: %s', error, exc_info=(type(error), error, error.__traceback__))
    await ctx.reply('Operation failed. Check the bot permissions and server logs.')


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
    print(f"Logged in as: {bot.user} (ID: {bot.user.id})")
    if not getattr(bot,'_lobby_views_registered',False):
        bot.add_view(ScheduleView())
        bot.add_view(LevelView())
        bot.add_view(PartyView())
        bot._lobby_views_registered = True
    if not lobby_cleanup.is_running():
        lobby_cleanup.start()
    try:
        async with icon_lock:
            await load_app_icons()
        print(f'NosTale icons loaded: {len(app_icons)}/{len(ICON_URLS)}')
    except Exception:
        log.exception('Could not load application emojis; standard class icons remain available')

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
