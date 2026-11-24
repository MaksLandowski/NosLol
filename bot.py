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
