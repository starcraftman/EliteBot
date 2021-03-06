"""
To facilitate complex actions based on commands create a
hierarchy of actions that can be recombined in any order.
All actions have async execute methods.
"""
from __future__ import absolute_import, print_function
import asyncio
import datetime
import logging
import re
import string
from functools import partial

import decorator
import discord
import googleapiclient.errors

import cogdb
import cogdb.eddb
import cogdb.query
import cogdb.side
import cog.inara
import cog.jobs
import cog.tbl
import cog.util


async def bot_shutdown(bot, delay=60):  # pragma: no cover
    """
    Shutdown the bot. Gives background jobs grace window to finish  unless empty.
    """
    try:
        cog.jobs.POOL.close()
        await bot.loop.run_in_executor(None, cog.jobs.POOL.join, delay)
    except TimeoutError:
        logging.getLogger('cog.actions').error("Pool failed to close in time. Terminating.")
        cog.jobs.POOL.stop()

    await bot.logout()


def user_info(user):  # pragma: no cover
    """
    Trivial message formatter based on user information.
    """
    lines = [
        ['Username', '{}#{}'.format(user.name, user.discriminator)],
        ['ID', user.id],
        ['Status', str(user.status)],
        ['Join Date', str(user.joined_at)],
        ['All Roles:', str([str(role) for role in user.roles[1:]])],
        ['Top Role:', str(user.top_role).replace('@', '@ ')],
    ]
    return '**' + user.display_name + '**\n' + cog.tbl.wrap_markdown(cog.tbl.format_table(lines))


@decorator.decorator
async def check_mentions(coro, *args, **kwargs):
    """ If a single member mentioned, resubmit message on their behalf. """
    self = args[0]

    if self.msg.mentions:
        if len(self.msg.mentions) != 1:
            raise cog.exc.InvalidCommandArgs('Mention only 1 member per command.')

        self.log.info('DROP %s - Substituting author -> %s.',
                      self.msg.author, self.msg.mentions[0])
        self.msg.author = self.msg.mentions[0]
        self.msg.mentions = []
        await self.bot.on_message(self.msg)

    else:
        await coro(*args, **kwargs)


def check_sheet(scanner_name, stype):
    """ Check if user present in sheet. """
    @decorator.decorator
    async def inner(coro, *args, **kwargs):
        """ The actual decorator. """
        self = args[0]
        sheet = getattr(self, stype)
        if not sheet:
            self.log.info('DROP %s - Adding to %s as %s.',
                          self.duser.display_name, stype, self.duser.pref_name)
            sheet = cogdb.query.add_sheet(self.session, self.duser.pref_name,
                                          cry=self.duser.pref_cry,
                                          type=getattr(cogdb.schema.ESheetType, stype),
                                          start_row=get_scanner(scanner_name).user_row)

            job = cog.jobs.Job(
                partial(get_scanner(scanner_name).update_sheet_user,
                        sheet.row, sheet.cry, sheet.name))
            job.set_ident_from_msg(self.msg, 'Adding user to sheet')
            job.add_fail_callback([self.bot, self.msg])
            await cog.jobs.background_start(job)

            notice = 'Automatically added {} to {} sheet. See !user command to change.'.format(
                self.duser.pref_name, stype)
            asyncio.ensure_future(self.bot.send_message(self.msg.channel, notice))

        await coro(*args, **kwargs)

    return inner


class Action(object):
    """
    Top level action, contains shared logic.
    """
    def __init__(self, **kwargs):
        self.args = kwargs['args']
        self.bot = kwargs['bot']
        self.msg = kwargs['msg']
        self.log = logging.getLogger('cog.actions')
        self.session = cogdb.Session()
        self.__duser = None

    @property
    def duser(self):
        """ DUser associated with message author. """
        if not self.__duser:
            self.__duser = cogdb.query.ensure_duser(self.session, self.msg.author)
            self.log.info('DUSER - %s', str(self.__duser))

        return self.__duser

    @property
    def cattle(self):
        """ User's current cattle sheet. """
        return self.duser.cattle(self.session)

    @property
    def undermine(self):
        """ User's current undermining sheet. """
        return self.duser.undermine(self.session)

    async def execute(self):
        """
        Take steps to accomplish requested action, including possibly
        invoking and scheduling other actions.
        """
        raise NotImplementedError


class Admin(Action):
    """
    Admin command console. For knowledgeable users only.
    """
    def check_role(self, role):
        """ Sanity check that role exists. """
        if role not in [role.name for role in self.msg.channel.server.roles]:
            raise cog.exc.InvalidCommandArgs("Role does not exist!")

    def check_cmd(self):
        """ Sanity check that cmd exists. """
        cmd_set = sorted([cls.__name__ for cls in cog.actions.Action.__subclasses__()])
        cmd_set.remove('Admin')  # Admin cannot be restricted even by admins
        if not self.args.rule_cmd or self.args.rule_cmd not in cmd_set:
            raise cog.exc.InvalidCommandArgs("Rules require a command in following set: \n\n" +
                                             str(cmd_set))

    async def add(self):
        """
        Takes one of the following actions:
            1) Add 1 or more admins
            2) Add a single channel rule
            3) Add a single role rule
        """
        if not self.args.rule_cmd and self.msg.mentions:
            for member in self.msg.mentions:
                cogdb.query.add_admin(self.session, member)
            response = "Admins added:\n\n" + '\n'.join([member.name for member in self.msg.mentions])

        else:
            self.check_cmd()

            if self.msg.channel_mentions:
                cogdb.query.add_channel_perm(self.session, self.args.rule_cmd,
                                             self.msg.channel.server.name,
                                             self.msg.channel_mentions[0].name)
                response = "Channel permission added."

            elif self.args.role:
                role = ' '.join(self.args.role)
                self.check_role(role)
                cogdb.query.add_role_perm(self.session, self.args.rule_cmd,
                                          self.msg.channel.server.name,
                                          ' '.join(self.args.role))
                response = "Role permission added."

        return response

    async def remove(self, admin):
        """
        Takes one of the following actions:
            1) Remove 1 or more admins
            2) Remove a single channel rule
            3) Remove a single role rule
        """
        if not self.args.rule_cmd and self.msg.mentions:
            for member in self.msg.mentions:
                admin.remove(self.session, cogdb.query.get_admin(self.session, member))
            response = "Admins removed:\n\n" + '\n'.join([member.name for member in self.msg.mentions])

        else:
            self.check_cmd()

            if self.msg.channel_mentions:
                cogdb.query.remove_channel_perm(self.session, self.args.rule_cmd,
                                                self.msg.channel.server.name,
                                                self.msg.channel_mentions[0].name)
                response = "Channel permission removed."

            elif self.args.role:
                role = ' '.join(self.args.role)
                self.check_role(role)
                cogdb.query.remove_role_perm(self.session, self.args.rule_cmd,
                                             self.msg.channel.server.name, role)
                response = "Role permission removed."

        return response

    # No tests due to data being connected to discord and variable.
    async def active(self):  # pragma: no cover
        """
        Analyze the activity of users going back months for the mentioned channels.

        No storage, just requests info on demand.
        """
        all_members = []
        for member in self.msg.server.members:
            for channel in self.msg.channel_mentions:
                if channel.permissions_for(member).read_messages and member.id not in all_members:
                    all_members += [member.id]

        after = datetime.datetime.utcnow() - datetime.timedelta(days=30 * self.args.months)
        report = {}
        for channel in self.msg.channel_mentions:
            report[channel.name] = {}
            try:
                async for msg in self.bot.logs_from(channel, after=after, limit=100000):
                    try:
                        report[channel.name][msg.author.id]
                    except KeyError:
                        report[channel.name][msg.author.id] = msg.timestamp
            except discord.errors.Forbidden:
                raise cog.exc.InvalidCommandArgs("Bot has no permissions for channel: " + channel.name)

        flat = {}
        for chan in report:
            for cmdr in report[chan]:
                try:
                    flat[cmdr]
                except KeyError:
                    flat[cmdr] = {}
                flat[cmdr][chan] = report[chan][cmdr]

                try:
                    if flat[cmdr]['last'] < flat[cmdr][chan]:
                        flat[cmdr]['last'] = flat[cmdr][chan]
                except KeyError:
                    flat[cmdr]['last'] = flat[cmdr][chan]

                try:
                    all_members.remove(cmdr)
                except ValueError:
                    pass

        server = self.msg.server
        header = "ID,Name,Top Role,Created At,Joined At\n"
        inactive_recruits = "**Inactive Recruits**\n" + header
        inactive_members = "**Inactive Members or Above**\n" + header
        for member_id in all_members:
            member = server.get_member(member_id)
            if not member:
                continue

            line = "{},{},{},{},{}\n".format(member.id, member.name, member.top_role.name,
                                             member.created_at, member.joined_at)
            if member.top_role.name in ["FRC Recruit", "FLC Recruit"]:
                inactive_recruits += line
            else:
                inactive_members += line

        actives = "**Active Membership (last 90 days)**\n" + header[:-1] + ",Last Message\n"
        for member_id in flat:
            member = server.get_member(member_id)
            if not member:
                continue
            line = "{},{},{},{},{},{}\n".format(member.id, member.name, member.top_role.name,
                                                member.created_at, member.joined_at,
                                                str(flat[member_id]['last']))
            actives += line

        response = "\n".join([inactive_recruits, inactive_members, actives])
        return await cog.util.pastebin_new_paste("Activity Summary", response)

    async def cast(self):
        """ Broacast a message accross a server. """
        await self.bot.broadcast(' '.join(self.args.content))
        return 'Broadcast completed.'

    async def deny(self):
        """ Toggle bot's acceptance of commands. """
        self.bot.deny_commands = not self.bot.deny_commands
        return 'Commands: **{}abled**'.format('Dis' if self.bot.deny_commands else 'En')

    async def dump(self):
        """ Dump the entire database to a file on server. """
        cogdb.query.dump_db()
        return 'Db has been dumped to server file.'

    async def halt(self):
        """ Schedule the bot for safe shutdown. """
        self.bot.deny_commands = True
        asyncio.ensure_future(bot_shutdown(self.bot))
        return 'Shutdown scheduled. Will wait for jobs to finish or max 60s.'

    async def info(self):
        """ Information on user, deprecated? """
        if self.msg.mentions:
            response = ''
            for user in self.msg.mentions:
                response += user_info(user) + '\n'
        else:
            response = user_info(self.msg.author)
        self.msg.channel = self.msg.author  # Not for public

        return response

    async def scan(self):
        """ Schedule all sheets for update. """
        self.bot.sched.schedule_all()
        return 'All sheets scheduled for update.'

    # Should test eventually but mainly just recombines code
    async def cycle(self):  # pragma: no cover
        """
        Rollover scanners to new sheets post cycle tick.

        Configs will be modified and scanners re-initialized.

        Raises:
            InternalException - No parseable numeric component found in tab.
            RemoteError - The sheet/tab combination could not be resolved. Tab needs creating.
        """
        self.bot.deny_commands = True
        scanners = cog.util.get_config('scanners')
        ignore = scanners.copy()

        # Only cattle or um sheets should move.
        for key in list(scanners.keys()):
            if 'cattle' in key or 'undermine' in key:
                del ignore[key]
            else:
                del scanners[key]

        try:
            for name in scanners:
                scanners[name]['page'] = cog.util.number_increment(scanners[name]['page'])

                # Check the sheet actually exists before committing
                cls = getattr(cogdb.query, scanners[name]["cls"])
                scanner = cls(scanners[name])
                assert scanner.gsheet.get('!A1:A1')

            for name in scanners:
                init_scanner(name)
                # FIXME: Feels icky reaching into code like so
                self.bot.sched.wraps[name].scanner = cog.actions.get_scanner(name)

            scanners.update(ignore)
            cog.util.update_config(scanners, 'scanners')

            self.bot.sched.schedule_all()

            return "Cycle has been incremented, bot has scheduled sheets for update."
        except ValueError:
            raise cog.exc.InternalException("Impossible to increment scanner: {}".format(name))
        except (AssertionError, googleapiclient.errors.HttpError):
            raise cog.exc.RemoteError("The sheet {} with tab {} does not exist!".format(
                name, scanners[name]['page']))
        finally:
            self.bot.deny_commands = False

    async def execute(self):
        try:
            admin = cogdb.query.get_admin(self.session, self.duser)
        except cog.exc.NoMatch:
            raise cog.exc.InvalidPerms("{} You are not an admin!".format(self.msg.author.mention))

        try:
            func = getattr(self, self.args.subcmd)
            if self.args.subcmd == "remove":
                response = await func(admin)
            else:
                response = await func()
            await self.bot.send_long_message(self.msg.channel, response)
        except AttributeError:
            raise cog.exc.InvalidCommandArgs("Bad subcommand of `!admin`, see `!admin -h` for help.")


class BGS(Action):
    """
    Provide bgs related commands.
    """
    async def age(self, system_name):
        """ Handle age subcmd. """
        control_name = cogdb.query.complete_control_name(system_name, True)
        self.log.info('BGS - Looking for age around: %s', control_name)

        systems = cogdb.side.exploited_systems_by_age(cogdb.SideSession(), control_name)
        systems = await self.bot.loop.run_in_executor(None, cogdb.side.exploited_systems_by_age,
                                                      cogdb.SideSession(), control_name)
        lines = [['Control', 'System', 'Age']]
        lines += [[system.control, system.system, system.age] for system in systems]
        return cog.tbl.wrap_markdown(cog.tbl.format_table(lines, header=True))

    async def dash(self, control_name):
        """ Handle dash subcmd. """
        control_name = cogdb.query.complete_control_name(control_name, True)
        control, systems, net_inf, facts_count = await self.bot.loop.run_in_executor(
            None, cogdb.side.dash_overview, cogdb.SideSession(), control_name)

        lines = [['Age', 'System', 'Control Faction', 'Gov', 'Inf', 'Net', 'N', 'Pop']]
        cnt = {
            "anarchy": 0,
            "strong": 0,
            "weak": 0,
        }

        strong, weak = cogdb.side.bgs_funcs(control_name)
        for system, faction, gov, inf, age in systems:
            lines += [[
                age if age else 0, system.name[-12:], faction.name[:20], gov.text[:3],
                '{:.1f}'.format(inf.influence), net_inf[system.name],
                facts_count[system.name], system.log_pop
            ]]

            if gov.text == 'Anarchy':
                cnt["anarchy"] += 1
            elif weak(gov.text):
                cnt["weak"] += 1
            elif strong(gov.text):
                cnt["strong"] += 1

        table = cog.tbl.wrap_markdown(cog.tbl.format_table(lines, sep=' | ', center=False,
                                                           header=True))

        header = "**{}**".format(control.name)
        hlines = [
            ["Strong", "{}/{}".format(cnt["strong"], len(systems))],
            ["Weak", "{}/{}".format(cnt["weak"], len(systems))],
            ["Anarchy", "{}/{}".format(cnt["anarchy"], len(systems))],
        ]
        header += cog.tbl.wrap_markdown(cog.tbl.format_table(hlines))

        explain = """
**Net**: Net change in influence over last 5 days. There may not be 5 days of data.
         If Net == Inf, they just took control.
**N**: The number of factions present in a system.
**Pop**: log10(population), i.e. log10(10000) = 4.0
         This is the exponent that would carry 10 to the population of the system.
         Example: Pop = 4.0 then actual population is: 10 ^ 4.0 = 10000
        """

        return header + table + explain

    async def edmc(self, system_name):
        """ Handle edmc subcmd. """
        if not system_name:
            controls = cogdb.side.WATCH_BUBBLES
        else:
            controls = process_system_args(system_name.split(' '))
        eddb_session = cogdb.EDDBSession()
        side_session = cogdb.SideSession()

        resp = "__**EDMC Route**__\nIf no systems listed under control, up to date."
        resp += "\n\n__Bubbles By Proximity__\n"
        if len(controls) > 2:
            _, route = await self.bot.loop.run_in_executor(None, cogdb.eddb.find_best_route,
                                                           eddb_session, controls)
            controls = [sys.name for sys in route]
        resp += "\n".join([sys for sys in controls])

        for control in controls:
            resp += "\n\n__{}__\n".format(string.capwords(control))
            systems = await self.bot.loop.run_in_executor(None, cogdb.side.get_edmc_systems,
                                                          side_session, [control])
            if len(systems) > 2:
                _, systems = await self.bot.loop.run_in_executor(None, cogdb.eddb.find_best_route,
                                                                 eddb_session,
                                                                 [system.name for system in systems])
            resp += "\n".join([sys.name for sys in systems])

        return resp

    async def exp(self, system_name):
        """ Handle exp subcmd. """
        side_session = cogdb.SideSession()
        centre = await self.bot.loop.run_in_executor(None, cogdb.side.get_systems,
                                                     side_session, [system_name])
        centre = centre[0]

        factions = await self.bot.loop.run_in_executor(None, cogdb.side.get_factions_in_system,
                                                       side_session, centre.name)
        prompt = "Please select a faction to expand with:\n"
        for ind, name in enumerate([fact.name for fact in factions]):
            prompt += "\n({}) {}".format(ind, name)
        sent = await self.bot.send_message(self.msg.channel, prompt)
        select = await self.bot.wait_for_message(timeout=30, author=self.msg.author,
                                                 channel=self.msg.channel)

        try:
            ind = int(select.content)
            if ind not in range(len(factions)):
                raise ValueError

            cands = await self.bot.loop.run_in_executor(None, cogdb.side.expansion_candidates,
                                                        side_session, centre, factions[ind])
            resp = "**Would Expand To**\n\n{}, {}\n\n".format(centre.name, factions[ind].name)
            return resp + cog.tbl.wrap_markdown(cog.tbl.format_table(cands, header=True))
        except ValueError:
            raise cog.exc.InvalidCommandArgs("Selection was invalid, try command again.")
        finally:
            try:
                await self.bot.delete_message(sent)
                await self.bot.delete_message(select)
            except discord.errors.DiscordException:
                pass

    async def expto(self, system_name):
        """ Handle expto subcmd. """
        matches = await self.bot.loop.run_in_executor(None, cogdb.side.expand_to_candidates,
                                                      cogdb.SideSession(), system_name)
        header = "**Nearby Expansion Candidates**\n\n"
        return header + cog.tbl.wrap_markdown(cog.tbl.format_table(matches, header=True))

    async def faction(self, _):
        """ Handle faction subcmd. """
        names = []
        if self.args.faction:
            names = process_system_args(self.args.faction)
        return await self.bot.loop.run_in_executor(None, cogdb.side.monitor_factions,
                                                   cogdb.SideSession(), names)

    async def find(self, system_name):
        """ Handle find subcmd. """
        matches = await self.bot.loop.run_in_executor(None, cogdb.side.find_favorable,
                                                      cogdb.SideSession(), system_name,
                                                      self.args.max)
        header = "**Favorable Factions**\n\n"
        return header + cog.tbl.wrap_markdown(cog.tbl.format_table(matches, header=True))

    async def inf(self, system_name):
        """ Handle influence subcmd. """
        self.log.info('BGS - Looking for influence like: %s', system_name)
        infs = await self.bot.loop.run_in_executor(None, cogdb.side.influence_in_system,
                                                   cogdb.SideSession(), system_name)

        if not infs:
            raise cog.exc.InvalidCommandArgs("Invalid system name or system is not tracked in db.")

        header = "**{}**\n{} (UTC)\n\n".format(system_name, infs[0][-1])
        lines = [['Faction Name', 'Inf', 'Gov', 'PMF?']] + [inf[:-1] for inf in infs]
        return header + cog.tbl.wrap_markdown(cog.tbl.format_table(lines, header=True))

    async def report(self, system_name):
        """ Handle influence subcmd. """
        session = cogdb.SideSession()
        system_ids = await self.bot.loop.run_in_executor(None, cogdb.side.get_monitor_systems,
                                                         session, cogdb.side.WATCH_BUBBLES)
        report = await asyncio.gather(
            self.bot.loop.run_in_executor(None, cogdb.side.control_dictators,
                                          cogdb.SideSession(), system_ids),
            self.bot.loop.run_in_executor(None, cogdb.side.moving_dictators,
                                          cogdb.SideSession(), system_ids),
            self.bot.loop.run_in_executor(None, cogdb.side.monitor_events,
                                          cogdb.SideSession(), system_ids))
        report = "\n".join(report)

        title = "BGS Report {}".format(datetime.datetime.utcnow())
        paste_url = await cog.util.pastebin_new_paste(title, report)

        return "Report Generated: <{}>".format(paste_url)

    async def sys(self, system_name):
        """ Handle sys subcmd. """
        self.log.info('BGS - Looking for overview like: %s', system_name)
        system, factions = await self.bot.loop.run_in_executor(None, cogdb.side.system_overview,
                                                               cogdb.SideSession(), system_name)

        if not system:
            raise cog.exc.InvalidCommandArgs("System **{}** not found. Spelling?".format(system_name))
        if not factions:
            msg = """We aren't tracking influence in: **{}**

If we should contact Gears or Sidewinder""".format(system_name)
            raise cog.exc.InvalidCommandArgs(msg)

        lines = []
        for faction in factions:
            lines += [
                '{}{}: {} -> {}'.format(faction['name'], ' (PMF)' if faction['player'] else '',
                                        faction['state'], faction['pending']),
            ]
            if faction['stations']:
                lines += ['    Owns: ' + ', '.join(faction['stations'])]
            lines += [
                '    ' + ' | '.join(['{:^5}'.format(inf.short_date) for inf in faction['inf_history']]),
                '    ' + ' | '.join(['{:^5.1f}'.format(inf.influence) for inf in faction['inf_history']]),
            ]

        header = "**{}**: {:,}\n\n".format(system.name, system.population)
        return header + '```autohotkey\n' + '\n'.join(lines) + '```\n'

    async def execute(self):
        try:
            func = getattr(self, self.args.subcmd)
            response = await func(' '.join(self.args.system))
            await self.bot.send_long_message(self.msg.channel, response)
        except AttributeError:
            raise cog.exc.InvalidCommandArgs("Bad subcommand of `!bgs`, see `!bgs -h` for help.")
        except (cog.exc.NoMoreTargets, cog.exc.RemoteError) as exc:
            response = exc.reply()


class Dist(Action):
    """
    Handle logic related to finding the distance between a start system and any following systems.
    """
    async def execute(self):
        system_names = process_system_args(self.args.system)
        if len(system_names) < 2:
            raise cog.exc.InvalidCommandArgs("At least **2** systems required.")

        dists = await self.bot.loop.run_in_executor(None, cogdb.side.compute_dists,
                                                    cogdb.SideSession(), system_names)

        response = 'Distances From: **{}**\n\n'.format(system_names[0].capitalize())
        lines = [[key, '{:.2f}ly'.format(dists[key])] for key in sorted(dists)]
        response += cog.tbl.wrap_markdown(cog.tbl.format_table(lines))

        await self.bot.send_message(self.msg.channel, response)


class Drop(Action):
    """
    Handle the logic of dropping a fort at a target.
    """
    def finished(self, system):
        """
        Additional reply when a system is finished (i.e. deferred or 100%).
        """
        try:
            new_target = cogdb.query.fort_get_targets(self.session)[0]
            response = '\n\n__Next Fort Target__:\n' + new_target.display()
        except cog.exc.NoMoreTargets:
            response = '\n\n Could not determine next fort target.'

        lines = [
            '**{}** Have a :cookie: for completing {}'.format(self.duser.display_name, system.name),
        ]

        try:
            merits = list(reversed(sorted(system.merits)))
            top = merits[0]
            lines += ['Bonus for highest contribution:']
            for merit in merits:
                if merit.amount != top.amount:
                    break
                lines.append('    :cookie: for **{}** with {} supplies'.format(
                    merit.user.name, merit.amount))
        except IndexError:
            lines += ["No found contributions. Heres a :cookie: for the unknown commanders."]

        response += '\n\n' + '\n'.join(lines)

        return response

    @check_mentions
    @check_sheet('hudson_cattle', 'cattle')
    async def execute(self):
        """
        Drop forts at the fortification target.
        """
        self.log.info('DROP %s - Matched duser with id %s and sheet name %s.',
                      self.duser.display_name, self.duser.id[:6], self.cattle)

        system = cogdb.query.fort_find_system(self.session, ' '.join(self.args.system))
        self.log.info('DROP %s - Matched system %s from: \n%s.',
                      self.duser.display_name, system.name, system)

        drop = cogdb.query.fort_add_drop(self.session, system=system,
                                         user=self.cattle, amount=self.args.amount)
        if self.args.set:
            system.set_status(self.args.set)
        self.log.info('DROP %s - After drop, Drop: %s\nSystem: %s.',
                      self.duser.display_name, drop, system)
        self.session.commit()

        job = cog.jobs.Job(
            partial(sync_drop,
                    [drop.system.sheet_col, drop.user.row, drop.amount],
                    [drop.system.sheet_col, drop.system.fort_status, drop.system.um_status]))
        job.set_ident_from_msg(self.msg, 'Adding drop to fort sheet')
        job.add_fail_callback([self.bot, self.msg])
        await cog.jobs.background_start(job)

        self.log.info('DROP %s - Sucessfully dropped %d at %s.',
                      self.duser.display_name, self.args.amount, system.name)

        response = system.display()
        if system.is_fortified:
            response += self.finished(system)
        await self.bot.send_message(self.msg.channel,
                                    self.bot.emoji.fix(response, self.msg.server))


class Fort(Action):
    """
    Provide information on and manage the fort sheet.
    """
    def find_missing(self, left):
        """ Show systems with 'left' remaining. """
        lines = ['__Systems Missing {} Supplies__'.format(left)]

        for system in cogdb.query.fort_get_systems(self.session):
            if not system.is_fortified and not system.skip and system.missing <= left:
                lines.append(system.display(miss=True))

        return '\n'.join(lines)

    def system_summary(self):
        """ Provide a quick summary of systems. """
        states = cogdb.query.fort_get_systems_by_state(self.session)

        total = len(cogdb.query.fort_get_systems(self.session))
        keys = ['cancelled', 'fortified', 'undermined', 'skipped', 'left']
        lines = [
            [key.capitalize() for key in keys],
            ['{}/{}'.format(len(states[key]), total) for key in keys],
        ]

        return cog.tbl.wrap_markdown(cog.tbl.format_table(lines, sep='|', header=True))

    def system_details(self):
        """
        Provide a detailed system overview.
        """
        system_names = process_system_args(self.args.system)
        if len(system_names) != 1 or system_names[0] == '':
            raise cog.exc.InvalidCommandArgs('Exactly one system required.')

        system = cogdb.query.fort_find_system(self.session, system_names[0])

        merits = [['CMDR Name', 'Merits']]
        merits += [[merit.user.name, merit.amount] for merit in reversed(sorted(system.merits))]
        merit_table = '\n' + cog.tbl.wrap_markdown(cog.tbl.format_table(merits, header=True))
        return system.display_details() + merit_table

    async def execute(self):
        manual = ' (Manual Order)' if cogdb.query.fort_order_get(self.session) else ''
        if self.args.summary:
            response = self.system_summary()

        elif self.args.set:
            system_name = ' '.join(self.args.system)
            if ',' in system_name:
                raise cog.exc.InvalidCommandArgs('One system at a time with --set flag')

            system = cogdb.query.fort_find_system(self.session, system_name)
            system.set_status(self.args.set)
            self.session.commit()

            job = cog.jobs.Job(
                partial(get_scanner("hudson_cattle").update_system,
                        system.sheet_col, system.fort_status, system.um_status))
            job.set_ident_from_msg(self.msg, 'Updating fort system')
            job.add_fail_callback([self.bot, self.msg])
            await cog.jobs.background_start(job)
            response = system.display()

        elif self.args.miss:
            response = self.find_missing(self.args.miss)

        elif self.args.details:
            response = self.system_details()

        elif self.args.order:
            cogdb.query.fort_order_drop(self.session,
                                        cogdb.query.fort_order_get(self.session))
            if self.args.system:
                system_names = process_system_args(self.args.system)
                cogdb.query.fort_order_set(self.session, system_names)
                response = """Fort order has been manually set.
When all systems completed order will return to default.
To unset override, simply set an empty list of systems.
"""
            else:
                response = "Manual fort order unset. Resuming normal order."

        elif self.args.system:
            lines = ['__Search Results__']
            for name in process_system_args(self.args.system):
                lines.append(cogdb.query.fort_find_system(self.session, name).display())
            response = '\n'.join(lines)

        elif self.args.next:
            lines = ['__Next Targets{}__'.format(manual)]
            lines += [system.display() for system in
                      cogdb.query.fort_get_next_targets(self.session, count=self.args.next)]
            response = '\n'.join(lines)

        else:
            lines = ['__Active Targets{}__'.format(manual)]
            lines += [system.display() for system in cogdb.query.fort_get_targets(self.session)]

            lines += ['\n__Next Targets__']
            next_count = self.args.next if self.args.next else 3
            lines += [system.display() for system in
                      cogdb.query.fort_get_next_targets(self.session, count=next_count)]

            defers = cogdb.query.fort_get_deferred_targets(self.session)
            if defers:
                lines += ['\n__Almost Done__'] + [system.display() for system in defers]
            response = '\n'.join(lines)

        await self.bot.send_message(self.msg.channel,
                                    self.bot.emoji.fix(response, self.msg.server))


class Feedback(Action):
    """
    Send bug reports to Gears' Hideout reporting channel.
    """
    async def execute(self):
        lines = [
            ['Server', self.msg.server.name],
            ['Channel', self.msg.channel.name],
            ['Author', self.msg.author.name],
            ['Date (UTC)', datetime.datetime.utcnow()],
        ]
        response = cog.tbl.wrap_markdown(cog.tbl.format_table(lines)) + '\n\n'
        response += '__Bug Report Follows__\n\n' + ' '.join(self.args.content)

        self.log.info('FEEDBACK %s - Left a bug report.', self.msg.author.name)
        await self.bot.send_message(self.bot.get_channel_by_name('feedback'), response)


class Help(Action):
    """
    Provide an overview of help.
    """
    async def execute(self):
        prefix = self.bot.prefix
        over = [
            'Here is an overview of my commands.',
            '',
            'For more information do: `{}Command -h`'.format(prefix),
            '       Example: `{}drop -h`'.format(prefix),
            '',
        ]
        lines = [
            ['Command', 'Effect'],
            ['{prefix}admin', 'Admin commands'],
            ['{prefix}bgs', 'Display information related to BGS work'],
            ['{prefix}dist', 'Determine the distance from the first system to all others'],
            ['{prefix}drop', 'Drop forts into the fort sheet'],
            ['{prefix}feedback', 'Give feedback or report a bug'],
            ['{prefix}fort', 'Get information about our fort systems'],
            ['{prefix}hold', 'Declare held merits or redeem them'],
            ['{prefix}kos', 'Manage or search kos list'],
            ['{prefix}repair', 'Show the nearest orbitals with shipyards'],
            ['{prefix}route', 'Plot the shortest route between these systems'],
            ['{prefix}scout', 'Generate a list of systems to scout'],
            ['{prefix}status', 'Info about this bot'],
            ['{prefix}time', 'Show game time and time to ticks'],
            ['{prefix}trigger', 'Calculate fort and um triggers for systems'],
            ['{prefix}um', 'Get information about undermining targets'],
            ['{prefix}user', 'Manage your user, set sheet name and tag'],
            ['{prefix}whois', 'Search for commander on inara.cz'],
            ['{prefix}help', 'This help message'],
        ]
        lines = [[line[0].format(prefix=prefix), line[1]] for line in lines]

        response = '\n'.join(over) + cog.tbl.wrap_markdown(cog.tbl.format_table(lines, header=True))
        await self.bot.send_ttl_message(self.msg.channel, response)
        await self.bot.delete_message(self.msg)


class Hold(Action):
    """
    Update a user's held merits.
    """
    async def set_hold(self):
        """ Set the hold on a system. """
        if not self.args.system:
            raise cog.exc.InvalidCommandArgs("You forgot to specify a system to update.")

        system = cogdb.query.um_find_system(self.session, ' '.join(self.args.system))
        self.log.info('HOLD %s - Matched system name %s: \n%s.',
                      self.duser.display_name, self.args.system, system)
        hold = cogdb.query.um_add_hold(self.session, system=system,
                                       user=self.undermine, held=self.args.amount)

        if self.args.set:
            system.set_status(self.args.set)

            job = cog.jobs.Job(
                partial(get_scanner("hudson_undermine").update_system,
                        system.sheet_col, system.progress_us,
                        system.progress_them, system.map_offset))
            job.set_ident_from_msg(self.msg, 'Updating undermining system')
            job.add_fail_callback([self.bot, self.msg])
            await cog.jobs.background_start(job)

        self.log.info('Hold %s - After update, hold: %s\nSystem: %s.',
                      self.duser.display_name, hold, system)

        response = hold.system.display()
        if hold.system.is_undermined:
            response += '\n\nSystem is finished with held merits. Type `!um` for more targets.'

        return ([hold], response)

    @check_mentions
    @check_sheet('hudson_undermine', 'undermine')
    async def execute(self):
        self.log.info('HOLD %s - Matched self.duser with id %s and sheet name %s.',
                      self.duser.display_name, self.duser.id[:6], self.undermine)

        if self.args.died:
            holds = cogdb.query.um_reset_held(self.session, self.undermine)
            self.log.info('HOLD %s - User reset merits.', self.duser.display_name)
            response = 'Sorry you died :(. Held merits reset.'

        elif self.args.redeem:
            holds, redeemed = cogdb.query.um_redeem_merits(self.session, self.undermine)
            self.log.info('HOLD %s - Redeemed %d merits.', self.duser.display_name, redeemed)

            response = '**Redeemed Now** {}\n\n__Cycle Summary__\n'.format(redeemed)
            lines = [['System', 'Hold', 'Redeemed']]
            lines += [[merit.system.name, merit.held, merit.redeemed] for merit
                      in self.undermine.merits if merit.held + merit.redeemed > 0]
            response += cog.tbl.wrap_markdown(cog.tbl.format_table(lines, header=True))

        else:  # Default case, update the hold for a system
            holds, response = await self.set_hold()

        self.session.commit()

        holds = [[hold.system.sheet_col, hold.user.row, hold.held, hold.redeemed] for hold in holds]
        job = cog.jobs.Job(partial(sync_holds, holds), timeout=30)
        job.set_ident_from_msg(self.msg, 'Updating undermining holds')
        job.add_fail_callback([self.bot, self.msg])
        await cog.jobs.background_start(job)

        await self.bot.send_message(self.msg.channel, response)


class KOS(Action):
    """
    Handle the KOS command.
    """
    async def execute(self):
        msg = 'KOS: Invalid subcommand'

        if self.args.subcmd == 'report':
            get_scanner('hudson_kos').add_report(self.msg.author.name, self.args.cmdr,
                                                 ' '.join(self.args.reason))
            msg = 'CMDR {} has been reported for moderation.'.format(self.args.cmdr)

        elif self.args.subcmd == 'pull':
            get_scanner('hudson_kos').scan()
            msg = 'KOS list refreshed from sheet.'

        elif self.args.subcmd == 'search':
            session = cogdb.Session()
            msg = 'Searching for "{}" against known CMDRs\n\n'.format(self.args.term)
            cmdrs = cogdb.query.kos_search_cmdr(session, self.args.term)
            if cmdrs:
                cmdrs = [[x.cmdr, x.faction, x.danger, x.friendly]
                         for x in cmdrs]
                cmdrs = [['CMDR Name', 'Faction', 'Danger', 'Is Friendly?']] + cmdrs
                msg += cog.tbl.wrap_markdown(cog.tbl.format_table(cmdrs, header=True))
            else:
                msg += "No matches!"

        await self.bot.send_message(self.msg.channel, msg)


class Pin(Action):
    """
    Create an objetives pin.
    """
    # TODO: Incomplete, expect bot to manage pin entirely. Left undocumented.
    async def execute(self):
        systems = cogdb.query.fort_get_targets(self.session)
        systems.reverse()
        systems += cogdb.query.fort_get_next_targets(self.session, count=5)
        for defer in cogdb.query.fort_get_deferred_targets(self.session):
            if defer.name != "Othime":
                systems += [defer]

        lines = [":Fortifying: {} {}".format(
            sys.name, "**{}**".format(sys.notes) if sys.notes else "") for sys in systems]
        lines += [":Fortifying: The things in the list after that"]

        await self.bot.send_message(self.msg.channel, cog.tbl.wrap_markdown('\n'.join(lines)))

        # TODO: Use later in proper pin manager
        # to_delete = [msg]
        # async for message in self.bot.logs_from(msg.channel, 10):
            # if not message.content or message.content == "!pin":
                # to_delete += [message]
        # await self.bot.delete_messages(to_delete)


class Repair(Action):
    """
    Find a nearby station with a shipyard.
    """
    async def execute(self):
        if self.args.distance > 30:
            raise cog.exc.InvalidCommandArgs("Searching beyond **30**ly would produce too long a list.")

        stations = cogdb.eddb.get_shipyard_stations(cogdb.EDDBSession(), ' '.join(self.args.system),
                                                    self.args.distance, self.args.arrival)

        if stations:
            stations = [["System", "Distance", "Station", "Arrival"]] + stations[:25]
            response = "Nearby orbitals __with shipyards__\n\n"
            response += cog.tbl.wrap_markdown(cog.tbl.format_table(stations, header=True))
        else:
            response = "No results. Please check system name. Otherwise not near populations."

        await self.bot.send_long_message(self.msg.channel, response)


class Route(Action):
    """
    Find a nearby station with a shipyard.
    """
    async def execute(self):
        # TODO: Add ability to fix endpoint. That is solve route but then add distance to jump back.
        # TODO: Probably allow dupes.
        session = cogdb.EDDBSession()
        self.args.system = [arg.lower() for arg in self.args.system]
        system_names = process_system_args(self.args.system)

        if len(system_names) < 2:
            raise cog.exc.InvalidCommandArgs("Need at least __two unique__ systems to plot a course.")

        if len(system_names) != len(set(system_names)):
            raise cog.exc.InvalidCommandArgs("Don't duplicate system names.")

        if self.args.optimum:
            result = await self.bot.loop.run_in_executor(
                None, cogdb.eddb.find_best_route, session, system_names)
        else:
            result = await self.bot.loop.run_in_executor(
                None, cogdb.eddb.find_route, session, system_names[0], system_names[1:])

        lines = ["__Route Plotted__", "Total Distance: **{}**ly".format(round(result[0])), ""]
        lines += [sys.name for sys in result[1]]

        await self.bot.send_message(self.msg.channel, "\n".join(lines))


class Scout(Action):
    """
    Generate scout route.
    """
    async def interact_revise(self, systems):
        """
        Interactively edit the list of systems to scout.

        Returns:
            The list of systems after changes.
        """
        while True:
            l_systems = [sys.lower() for sys in systems]
            try:
                prompt = SCOUT_INTERACT.format('    ' + '\n    '.join(systems))
                responses = [await cog.util.BOT.send_message(self.msg.channel, prompt)]
                user_msg = await cog.util.BOT.wait_for_message(timeout=30, author=self.msg.author,
                                                               channel=self.msg.channel)
                if user_msg:
                    responses += [user_msg]
                if not user_msg:
                    break

                system = user_msg.content.strip()
                if system.lower() == 'stop':
                    break
                elif system.lower() in l_systems:
                    systems = [sys for sys in systems if sys.lower() != system.lower()]
                elif system:
                    systems.append(system)
                    l_systems.append(system.lower())
            finally:
                asyncio.ensure_future(asyncio.gather(
                    *[cog.util.BOT.delete_message(response) for response in responses]))

        return systems

    async def execute(self):
        session = cogdb.EDDBSession()

        if not self.args.round and not self.args.custom:
            raise cog.exc.InvalidCommandArgs("Select a --round or provide a --custom list.")

        if self.args.custom:
            systems = process_system_args(self.args.custom)
        else:
            systems = SCOUT_RND[self.args.round]
            systems = await self.interact_revise(systems)

        result = await self.bot.loop.run_in_executor(
            None, cogdb.eddb.find_best_route, session, systems)
        system_list = "\n".join([":Exploration: " + sys.name for sys in result[1]])

        now = datetime.datetime.utcnow()
        lines = SCOUT_TEMPLATE.format(
            round(result[0], 2), now.strftime("%B"),
            now.day, now.year + 1286, system_list)

        await self.bot.send_message(self.msg.channel, lines)


class Status(Action):
    """
    Display the status of this bot.
    """
    async def execute(self):
        lines = [
            ['Created By', 'GearsandCogs'],
            ['Uptime', self.bot.uptime],
            ['Version', '{}'.format(cog.__version__)],
            ['Contributors:', ''],
            ['    Shotwn', 'Inara search'],
        ]

        await self.bot.send_message(self.msg.channel,
                                    cog.tbl.wrap_markdown(cog.tbl.format_table(lines)))


class Time(Action):
    """
    Provide in game time and time to import in game ticks.

    Shows the time ...
    - In game
    - To daily BGS tick
    - To weekly tick
    """
    async def execute(self):
        now = datetime.datetime.utcnow().replace(microsecond=0)
        today = now.replace(hour=0, minute=0, second=0)  # pylint: disable=unexpected-keyword-arg

        weekly_tick = today + datetime.timedelta(hours=7)
        while weekly_tick < now or weekly_tick.strftime('%A') != 'Thursday':
            weekly_tick += datetime.timedelta(days=1)

        try:
            tick = await self.bot.loop.run_in_executor(
                None, cogdb.side.next_bgs_tick, cogdb.SideSession(), now)
        except (cog.exc.NoMoreTargets, cog.exc.RemoteError) as exc:
            tick = exc.reply()
        lines = [
            'Game Time: **{}**'.format(now.strftime('%H:%M:%S')),
            tick,
            'Cycle Ends in **{}**'.format(weekly_tick - now),
            'All Times UTC',
        ]

        await self.bot.send_message(self.msg.channel, '\n'.join(lines))


class Trigger(Action):
    """
    Calculate the estimated triggers relative Hudson.
    """
    async def execute(self):
        side_session = cogdb.SideSession()
        self.args.power = " ".join(self.args.power).lower()
        power = cogdb.side.get_power_hq(self.args.power)
        pow_hq = cogdb.side.get_systems(side_session, [power[1]])[0]
        lines = [
            "__Predicted Triggers__",
            "Power: {}".format(power[0]),
            "Power HQ: {}\n".format(power[1])
        ]

        systems = await self.bot.loop.run_in_executor(
            None, cogdb.side.get_systems, side_session,
            process_system_args(self.args.system))
        for system in systems:
            lines += [
                cog.tbl.wrap_markdown(cog.tbl.format_table([
                    ["System", system.name],
                    ["Distance", round(system.dist_to(pow_hq), 1)],
                    ["Upkeep", system.calc_upkeep(pow_hq)],
                    ["Fort Trigger", system.calc_fort_trigger(pow_hq)],
                    ["UM Trigger", system.calc_um_trigger(pow_hq)],
                ]))
            ]

        await self.bot.send_message(self.msg.channel, '\n'.join(lines))


class UM(Action):
    """
    Command to show um systems and update status.
    """
    async def execute(self):
        # Sanity check
        if (self.args.set or self.args.offset) and not self.args.system:
            raise cog.exc.InvalidCommandArgs("You forgot to specify a system to update.")

        elif self.args.list:
            now = datetime.datetime.utcnow().replace(microsecond=0)
            today = now.replace(hour=0, minute=0, second=0)  # pylint: disable=unexpected-keyword-arg
            weekly_tick = today + datetime.timedelta(hours=7)
            while weekly_tick < now or weekly_tick.strftime('%A') != 'Thursday':
                weekly_tick += datetime.timedelta(days=1)

            response = "**Held Merits**\n\n{}\n".format('DEADLINE **{}**'.format(weekly_tick - now))
            response += cog.tbl.wrap_markdown(cog.tbl.format_table(
                cogdb.query.um_all_held_merits(self.session), header=True))

        elif self.args.system:
            system = cogdb.query.um_find_system(self.session, ' '.join(self.args.system))

            if self.args.offset:
                system.map_offset = self.args.offset
            if self.args.set:
                system.set_status(self.args.set)
            if self.args.set or self.args.offset:
                self.session.commit()

                job = cog.jobs.Job(
                    partial(get_scanner("hudson_undermine").update_system,
                            system.sheet_col, system.progress_us,
                            system.progress_them, system.map_offset))
                job.set_ident_from_msg(self.msg, 'Updating undermining system status')
                job.add_fail_callback([self.bot, self.msg])
                await cog.jobs.background_start(job)

            response = system.display()

        else:
            systems = cogdb.query.um_get_systems(self.session)
            response = '__Current UM Targets__\n\n' + '\n'.join(
                [system.display() for system in systems])

        await self.bot.send_message(self.msg.channel, response)


class User(Action):
    """
    Manage your user settings.
    """
    async def execute(self):
        args = self.args
        if args.name:
            self.update_name()

        if args.cry:
            self.update_cry()

        self.session.commit()
        if args.name or args.cry:
            if self.cattle:
                sheet = self.cattle
                job = cog.jobs.Job(
                    partial(get_scanner("hudson_cattle").update_sheet_user,
                            sheet.row, sheet.cry, sheet.name))
                job.set_ident_from_msg(self.msg, 'Updating cattle name/cry')
                job.add_fail_callback([self.bot, self.msg])
                await cog.jobs.background_start(job)

            if self.undermine:
                sheet = self.undermine
                job = cog.jobs.Job(
                    partial(get_scanner("hudson_undermine").update_sheet_user,
                            sheet.row, sheet.cry, sheet.name))
                job.set_ident_from_msg(self.msg, 'Updating undermining name/cry')
                job.add_fail_callback([self.bot, self.msg])
                await cog.jobs.background_start(job)

        lines = [
            '__{}__'.format(self.msg.author.display_name),
            'Sheet Name: ' + self.duser.pref_name,
            'Default Cry:{}'.format(' ' + self.duser.pref_cry if self.duser.pref_cry else ''),
            '',
        ]
        if self.cattle:
            lines += [
                '__{} {}__'.format(self.cattle.faction.capitalize(),
                                   self.cattle.type.replace('Sheet', '')),
                '    Cry: {}'.format(self.cattle.cry),
                '    Total: {}'.format(self.cattle.merit_summary()),
            ]
            mlines = [['System', 'Amount']]
            mlines += [[merit.system.name, merit.amount] for merit in self.cattle.merits
                       if merit.amount > 0]
            lines += cog.tbl.wrap_markdown(cog.tbl.format_table(mlines, header=True)).split('\n')
        if self.undermine:
            lines += [
                '__{} {}__'.format(self.undermine.faction.capitalize(),
                                   self.undermine.type.replace('Sheet', '')),
                '    Cry: {}'.format(self.undermine.cry),
                '    Total: {}'.format(self.undermine.merit_summary()),
            ]
            mlines = [['System', 'Hold', 'Redeemed']]
            mlines += [[merit.system.name, merit.held, merit.redeemed] for merit
                       in self.undermine.merits if merit.held + merit.redeemed > 0]
            lines += cog.tbl.wrap_markdown(cog.tbl.format_table(mlines, header=True)).split('\n')

        await self.bot.send_message(self.msg.channel, '\n'.join(lines))

    def update_name(self):
        """ Update the user's cmdr name in the sheets. """
        new_name = ' '.join(self.args.name)
        self.log.info('USER %s - DUser.pref_name from %s -> %s',
                      self.duser.display_name, self.duser.pref_name, new_name)
        cogdb.query.check_pref_name(self.session, self.duser, new_name)

        for sheet in self.duser.sheets(self.session):
            sheet.name = new_name
        self.duser.pref_name = new_name

    def update_cry(self):
        """ Update the user's cry in the sheets. """
        new_cry = ' '.join(self.args.cry)
        self.log.info('USER %s - DUser.pref_cry from %s -> %s',
                      self.duser.display_name, self.duser.pref_cry, new_cry)

        for sheet in self.duser.sheets(self.session):
            sheet.cry = new_cry
        self.duser.pref_cry = new_cry


class WhoIs(Action):
    """
    Who is request to Inara for CMDR info.

    """
    async def execute(self):
        cmdr = await cog.inara.api.search_with_api(' '.join(self.args.cmdr), self.msg)
        if cmdr:
            await cog.inara.api.reply_with_api_result(cmdr["req_id"], cmdr["event_data"], self.msg,
                                                      self.args.wing)


def process_system_args(args):
    """
    Process the system args by:
        Joining text on spaces.
        Removing trailing/leading spaces around commas.
        Split on commas and return list of systems.

    Intended to be used when systems collected with nargs=*/+
    """
    system_names = ' '.join(args).lower()
    system_names = re.sub(r'\s*,\s*', ',', system_names)
    return system_names.split(',')


def sync_drop(drop_args, system_args):
    """ Executes in another process. """
    scanner = get_scanner("hudson_cattle")
    scanner.update_drop(*drop_args)
    scanner.update_system(*system_args)


def sync_holds(holds):
    """ Executes in another process. """
    # TODO: Expand the holds to a continuous rectangle and one update.
    scanner = get_scanner("hudson_undermine")
    for hold in holds:
        scanner.update_hold(*hold)


def init_scanner(name):
    """
    Initialize a scanner based on configuration.
    """
    print("Intializing scanner -> ", name)
    logging.getLogger('cog.actions').info("Initializing the %s scanner.", name)
    sheet = cog.util.get_config("scanners", name)
    cls = getattr(cogdb.query, sheet["cls"])
    scanner = cls(sheet)
    SCANNERS[name] = scanner


def get_scanner(name):
    """
    Store scanners in this module for shared use.
    """
    return SCANNERS[name]


SCANNERS = {}
SCOUT_RND = {
    1: [
        "Epsilon Scorpii",
        "39 Serpentis",
        "Parutis",
        "Mulachi",
        "Aornum",
        "WW Piscis Austrini",
        "LHS 142",
        "LHS 6427",
        "LP 580-33",
        "BD+42 3917",
        "Venetic",
        "Kaushpoos",
    ],
    2: [
        "Atropos",
        "Alpha Fornacis",
        "Rana",
        "Anlave",
        "NLTT 46621",
        "16 Cygni",
        "Adeo",
        "LTT 15449",
        "LHS 3447",
        "Lalande 39866",
        "Abi",
        "Gliese 868",
        "Othime",
        "Phra Mool",
        "Wat Yu",
        "Shoujeman",
        "Phanes",
        "Dongkum",
        "Nurundere",
        "LHS 3749",
        "Mariyacoch",
        "Frey",
    ],
    3: [
        "GD 219",
        "Wolf 867",
        "Gilgamesh",
        "LTT 15574",
        "LHS 3885",
        "Wolf 25",
        "LHS 6427",
        "LHS 1541",
        "LHS 1197",
    ]
}
SCOUT_TEMPLATE = """__**Scout List**__
Total Distance: **{}**ly

```**REQUESTING NEW RECON OBJECTIVES __{} {}__  , {}**

If you are running more than one system, do them in this order and you'll not ricochet the whole galaxy. Also let us know if you want to be a member of the FRC Scout Squad!
@here @FRC Scout

{}

:o7:```"""
SCOUT_INTERACT = """Will generate scout list with the following systems:\n

{}

To add system: type system name **NOT** in list
To remove system: type system name in list
To generate list: reply with **stop**

__This message will delete itself on success or 30s timeout.__"""
