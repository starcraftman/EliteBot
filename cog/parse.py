"""
Everything related to parsing arguements from the received text.

By setting defaults passed on the parser (cmd, subcmd) can differeciate
what action to be invoked.
"""
from __future__ import absolute_import, print_function

import argparse
from argparse import RawDescriptionHelpFormatter as RawHelp

import cog.exc

PARSERS = []


class ThrowArggumentParser(argparse.ArgumentParser):
    """
    ArgumentParser subclass that does NOT terminate the program.
    """
    def print_help(self, file=None):  # pylint: disable=redefined-builtin
        formatter = self._get_formatter()
        formatter.add_text(self.description)
        raise cog.exc.ArgumentHelpError(formatter.format_help())

    def error(self, message):
        raise cog.exc.ArgumentParseError(message)

    def exit(self, status=0, message=None):
        """
        Suppress default exit behaviour.
        """
        raise cog.exc.ArgumentParseError(message)


def make_parser(prefix):
    """
    Returns the bot parser.
    """
    parser = ThrowArggumentParser(prog='', description='simple discord bot')

    subs = parser.add_subparsers(title='subcommands',
                                 description='The subcommands of cog')

    for func in PARSERS:
        func(subs, prefix)

    return parser


def register_parser(func):
    """ Simple registration function, use as decorator. """
    PARSERS.append(func)
    return func


@register_parser
def subs_admin(subs, prefix):
    """ Subcommand parsing for admin """
    desc = """Admin only commands. Examples:

{prefix}admin add @GearsandCogs
        Add GearsandCogs to the admin group.
{prefix}admin remove @GearsandCogs
        Remove GearsandCogs from the admin group.
{prefix}admin add BGS #hudson_bgs
        Whitelist bgs command for hudson_bgs channel.
{prefix}admin remove BGS #hudson_bgs
        Remove whitelist for bgs command in hudson_bgs.
{prefix}admin add Drop FRC Member
        Whitelist bgs command for members with role "FRC Member".
{prefix}admin remove Drop FRC Member
        Remove whitelist for bgs command of users with role "FRC Member".
{prefix}admin active -m 3 #hudson_operations #hudson_bgs
        Generate an activity report on cmdrs in listed channels, look back about 3 months.
{prefix}admin cast A message here
        Broadcast a message to all channels.
{prefix}admin cycle
        Point bot to new cycle's sheets.
{prefix}admin deny
        Toggle command processing.
{prefix}admin dump
        Dump the database to console to inspect.
{prefix}admin halt
        Shutdown this bot after short delay.
{prefix}admin scan
        Pull and parse the latest sheet information.
{prefix}admin info @User
        Information about the mentioned User, DMed to admin.
    """.format(prefix=prefix)
    sub = subs.add_parser(prefix + 'admin', description=desc, formatter_class=RawHelp)
    sub.set_defaults(cmd='Admin')
    admin_subs = sub.add_subparsers(title='subcommands',
                                    description='Admin subcommands', dest='subcmd')
    admin_sub = admin_subs.add_parser('add', help='Add an admin or permission.')
    admin_sub.add_argument('rule_cmd', nargs='?', help='The the command to restrict.')
    admin_sub.add_argument('role', nargs='*', help='The role name, if a role restriction.')
    admin_sub = admin_subs.add_parser('remove', help='Remove an admin or permission.')
    admin_sub.add_argument('rule_cmd', nargs='?', help='The the command to restrict.')
    admin_sub.add_argument('role', nargs='*', help='The role name, if a role restriction.')
    admin_sub = admin_subs.add_parser('cast', help='Broadcast a message to all channels.')
    admin_sub.add_argument('content', nargs='+', help='The message to send, no hyphens.')
    admin_subs.add_parser('cycle', help='Roll sheets to new cycle.')
    admin_subs.add_parser('deny', help='Toggle command processing.')
    admin_subs.add_parser('dump', help='Dump the db to console.')
    admin_subs.add_parser('halt', help='Stop accepting commands and halt bot.')
    admin_subs.add_parser('scan', help='Scan the sheets for updates.')
    admin_sub = admin_subs.add_parser('info', help='Get info about discord users.')
    admin_sub.add_argument('user', nargs='?', help='The user to get info on.')
    admin_sub = admin_subs.add_parser('active', help='Get a report on user activity.')
    admin_sub.add_argument('-m', '--months', type=int, default=3, nargs='?',
                           help='The number of months to look back.')


@register_parser
def subs_bgs(subs, prefix):
    """ Subcommand parsing for bgs """
    desc = """BGS related commands. Examples:

{prefix}bgs age 16 cygni
        Show exploiteds in 16 Cygni bubble by age.
{prefix}bgs dash othime
        Show the bgs state of a bubble's exploited systems.
{prefix}bgs edmc
        Present the optimized route to jump and update EDMC for default systems.
{prefix}bgs edmc Rana, Frey
        Present the optimized route to jump and update EDMC for Rana, Frey.
{prefix}bgs exp Rana
        Show all factions in Rana, select one, then show all expansion candidates.
{prefix}bgs expto Rana
        Show all factions that could possibly expand to Rana.
{prefix}bgs faction
        Show a report for all systems where default factions present.
{prefix}bgs faction Democrats of Muncheim
        Show a report for all systems where Democrats of Muncheim present.
{prefix}bgs find Frey
        Show all Feudal/Patronage factions near Frey, expanding in 15ly increments.
{prefix}bgs find Frey --max 50
        Show all Feudal/Patronage factions near Frey within 50ly.
{prefix}bgs inf Sol
        Show the factions and their influence in Sol.
{prefix}bgs report Sol
        Show an overall report for one or more bubbles.
{prefix}bgs sys Frey
        Show a system overview and all factions.
    """.format(prefix=prefix)
    sub = subs.add_parser(prefix + 'bgs', description=desc, formatter_class=RawHelp)
    sub.set_defaults(cmd='BGS', system=[])
    bgs_subs = sub.add_subparsers(title='subcommands',
                                  description='BGS subcommands', dest='subcmd')
    bgs_sub = bgs_subs.add_parser('age', help='Get the age of exploiteds around a control.')
    bgs_sub.add_argument('system', nargs='+', help='The system to lookup.')
    bgs_sub = bgs_subs.add_parser('dash', help='Dashboard overview of exploiteds around a control.')
    bgs_sub.add_argument('system', nargs='+', help='The system to lookup.')
    bgs_sub = bgs_subs.add_parser('edmc', help='Create the EDMC update route.')
    bgs_sub.add_argument('system', nargs='*', help='The control systems to update.')
    bgs_sub = bgs_subs.add_parser('exp', help='Find expansion candidates from system.')
    bgs_sub.add_argument('system', nargs='+', help='The system to lookup.')
    bgs_sub = bgs_subs.add_parser('expto', help='Find all possible expansion candidates to system.')
    bgs_sub.add_argument('system', nargs='+', help='The system to lookup.')
    bgs_sub = bgs_subs.add_parser('faction', help='Show faction report by system.')
    bgs_sub.add_argument('faction', nargs='*', help='The faction(s) to lookup.')
    bgs_sub = bgs_subs.add_parser('find', help='Show favorable factions around a system.')
    bgs_sub.add_argument('system', nargs='+', help='The system to lookup.')
    bgs_sub.add_argument('-m', '--max', type=int, help='The radius to look within.')
    bgs_sub = bgs_subs.add_parser('inf', help='Get the influence of factions inside a system.')
    bgs_sub.add_argument('system', nargs='+', help='The system to lookup.')
    bgs_sub = bgs_subs.add_parser('report', help='Get an overall report of the bubble.')
    bgs_sub.add_argument('system', nargs='*', default=[], help='The system to lookup.')
    bgs_sub = bgs_subs.add_parser('sys', help='Get a complete system overview.')
    bgs_sub.add_argument('system', nargs='+', help='The system to lookup.')


@register_parser
def subs_dist(subs, prefix):
    """ Subcommand parsing for dist """
    desc = """Determine the distance from the first system to all others.
    The system names must match __exactly__. Match is not case sensitive.
    Examples:

{prefix}dist sol, frey, Rana
        Display the distance from Sol to Frey and Rana.
    """.format(prefix=prefix)
    sub = subs.add_parser(prefix + 'dist', description=desc, formatter_class=RawHelp)
    sub.set_defaults(cmd='Dist')
    sub.add_argument('system', nargs='+', help='The systems in question.')


@register_parser
def subs_drop(subs, prefix):
    """ Subcommand parsing for drop """
    desc = """Update the cattle sheet when you drop at a system.
    Amount dropped must be in range [-800, 800]
    Examples:

{prefix}drop 600 Rana
        Drop 600 supplies for yourself at Rana.
{prefix}drop -50 Rana
        Made a mistake? Subract 50 forts from your drops at Rana.
{prefix}drop 600 Rana @rjwhite
        Drop 600 supplies for rjwhite Rana.
{prefix}drop 600 lala
        Drop 600 supplies for yourself at Lalande 39866, search used when name is not exact.
{prefix}drop 600 Rana --set 4560:2000
{prefix}drop 600 Rana -s 4560:2000
        Drop 600 supplies at Rana for yourself, set fort status to 4500 and UM status to 2000.
    """.format(prefix=prefix)
    sub = subs.add_parser(prefix + 'drop', description=desc, formatter_class=RawHelp)
    sub.set_defaults(cmd='Drop')
    sub.add_argument('amount', type=int, help='The amount to drop.')
    sub.add_argument('system', nargs='+', help='The system to drop at.')
    sub.add_argument('-s', '--set',
                     help='Set the fort:um status of the system. Example-> --set 3400:200')


@register_parser
def subs_feedback(subs, prefix):
    """ Subcommand parsing for feedback """
    desc = """Give feedback or report a bug. Example:

{prefix}bug Explain what went wrong ...
        File a bug report or give feedback.
    """.format(prefix=prefix)
    sub = subs.add_parser(prefix + 'feedback', description=desc, formatter_class=RawHelp)
    sub.set_defaults(cmd='Feedback')
    sub.add_argument('content', nargs='+', help='The bug description or feedback.')


@register_parser
def subs_fort(subs, prefix):
    """ Subcommand parsing for fort """
    desc = """Show fortification status and targets. Examples:

{prefix}fort
        Show current fort objectives.
{prefix}fort --details Sol
{prefix}fort -d Sol
        Show a detailed view of Sol, including all CMDR merits.
{prefix}fort --miss 1000
        Show all systems missing <= 1000 supplies.
{prefix}fort --next 5
{prefix}fort -n 5
        Show the next 5 fortification targets (excluding Othime and skipped).
{prefix}fort --order Sol, Adeo, Frey
        Set the fort order to: Sol -> Adeo -> Frey, then fallback to default.
{prefix}fort --order
        Return the fort order to default sheet order.
{prefix}fort --summary
        Show a breakdown by states of our systems.
{prefix}fort alpha
        Show the fortification status of Alpha Fornacis.
{prefix}fort alpha, sol, ran
        Show the fortification status of Alpha Fornacis, Sol and Rana.
{prefix}fort Othime --set 7500:2000
{prefix}fort Othime -s 7500:2000
        Set othime to 7500 fort status and 2000 um status.
    """.format(prefix=prefix)
    sub = subs.add_parser(prefix + 'fort', description=desc, formatter_class=RawHelp)
    sub.set_defaults(cmd='Fort')
    sub.add_argument('system', nargs='*', help='Select this system.')
    sub.add_argument('-s', '--set',
                     help='Set the fort:um status of system. Example-> --set 3400:200')
    sub.add_argument('--order', action='store_true',
                     help='Set the fort order. Comma separate list of systems.')
    sub.add_argument('--summary', action='store_true',
                     help='Provide an overview of the fort systems.')
    sub.add_argument('--miss', type=int,
                     help='Show systems missing <= MISS merits.')
    # sub.add_argument('-l', '--long', action='store_true', help='Show systems in table format')
    sub.add_argument('-n', '--next', type=int,
                     help='Show the next NUM fort targets after current')
    sub.add_argument('-d', '--details', action='store_true',
                     help='Show details on selected systems (will truncate to 4).')


@register_parser
def subs_help(subs, prefix):
    """ Subcommand parsing for help """
    sub = subs.add_parser(prefix + 'help', description='Show overall help message.')
    sub.set_defaults(cmd='Help')


@register_parser
def subs_hold(subs, prefix):
    """ Subcommand parsing for hold """
    desc = """Update a user's held or redeemed merits. Examples:

{prefix}hold 1200 burr
        Set your held merits at Burr to 1200.
{prefix}hold 900 af leopris @Memau
        Set held merits at System AF Leopris to 900 held for Memau.
{prefix}hold --died
{prefix}hold -d
        Reset your held merits to 0 due to dying.
{prefix}hold --redeem
{prefix}hold -r
        Move all held merits to redeemed column.
{prefix}hold 720 burr --set 60000:130
{prefix}hold 720 burr -s 60000:130
        Update held merits to 720 at Burr expansion and set progress to 60000 merits for us
and 130% opposition.
    """.format(prefix=prefix)
    sub = subs.add_parser(prefix + 'hold', description=desc, formatter_class=RawHelp)
    sub.set_defaults(cmd='Hold')
    sub.add_argument('amount', nargs='?', type=int, help='The amount of merits held.')
    sub.add_argument('system', nargs='*', help='The system merits are held in.')
    sub.add_argument('-r', '--redeem', action='store_true', help='Redeem all held merits.')
    sub.add_argument('-d', '--died', action='store_true', help='Zero out held merits.')
    sub.add_argument('-s', '--set',
                     help='Update the galmap progress us:them. Example: --set 3500:200')


@register_parser
def subs_kos(subs, prefix):
    """ Subcommand parsing for kos """
    desc = """KOS related commands. Examples:

{prefix}kos report user_name Explain why he is reported after name.
        Report an enemy PP user for KOS addition.
{prefix}kos search user_name
        Search for a user, list all possible matching users.
{prefix}kos pull
        Pull all changes from sheet. Mainly to be used after modifying list.
    """.format(prefix=prefix)
    sub = subs.add_parser(prefix + 'kos', description=desc, formatter_class=RawHelp)
    sub.set_defaults(cmd='KOS', system=[])
    bgs_subs = sub.add_subparsers(title='subcommands',
                                  description='KOS subcommands', dest='subcmd')
    bgs_sub = bgs_subs.add_parser('report', help='Report user to KOS.')
    bgs_sub.add_argument('cmdr', help='The CMDR reported.')
    bgs_sub.add_argument('reason', nargs='+', help='The reason reported.')
    bgs_sub = bgs_subs.add_parser('search', help='Search for a user.')
    bgs_sub.add_argument('term', help='The username to look for.')
    bgs_sub = bgs_subs.add_parser('pull', help='Pull data from sheet.')


@register_parser
def subs_pin(subs, prefix):
    """ Subcommand parsing for pin """
    sub = subs.add_parser(prefix + 'pin', description='Make an objectives pin and keep updating.')
    sub.set_defaults(cmd='Pin')


@register_parser
def subs_repair(subs, prefix):
    """ Subcommand parsing for repair """
    desc = """Find a station with both L pad and shipyard near you.

{prefix}repair arnemil
        Show suitable stations <= 15ly from Arnemil with arrival <= 1000ls
{prefix}repair arnemil --arrival 4000
{prefix}repair arnemil -a 4000
        Show suitable stations <= 15ly from Arnemil with arrival <= 4000ls
{prefix}repair arnemil --distance 30
{prefix}repair arnemil -d 30
        Show suitable stations <= 30ly from Arnemil with arrival <= 1000ls
    """.format(prefix=prefix)
    sub = subs.add_parser(prefix + 'repair', description=desc, formatter_class=RawHelp)
    sub.set_defaults(cmd='Repair')
    sub.add_argument('system', nargs="+", help='The reference system.')
    sub.add_argument('-a', '--arrival', type=int, default=1000, help='Station must be within arrival ls.')
    sub.add_argument('-d', '--distance', type=int, default=15, help='Max system distance')


@register_parser
def subs_route(subs, prefix):
    """ Subcommand parsing for route """
    desc = """Plot the shortest route between the listed systems.

{prefix}route rana, sol, nanomam, frey
        Show the route that minimizes jumps to visit all systems, starting at Rana
{prefix}route rana, sol, nanomam, frey --optimum
{prefix}route rana, sol, nanomam, frey -o
        Show the route that minimizes jumps to visit all systems, start is not fixed
    """.format(prefix=prefix)
    sub = subs.add_parser(prefix + 'route', description=desc, formatter_class=RawHelp)
    sub.set_defaults(cmd='Route')
    sub.add_argument('system', nargs="+", help='The systems to plot.')
    sub.add_argument('-o', '--optimum', action="store_true", help="Determine the optimum solution.")


@register_parser
def subs_scout(subs, prefix):
    """ Subcommand parsing for scout """
    desc = """Generate a scouting list. Control output with flags.
    Examples:

{prefix}scout
        Generate a scouting list.
    """.format(prefix=prefix)
    sub = subs.add_parser(prefix + 'scout', description=desc, formatter_class=RawHelp)
    sub.set_defaults(cmd='Scout')
    sub.add_argument('-r', '--round', type=int, help='The round to run.', choices=[1, 2, 3])
    sub.add_argument('-c', '--custom', nargs='+', help='Run a custom scout of systems.')


@register_parser
def subs_status(subs, prefix):
    """ Subcommand parsing for status """
    sub = subs.add_parser(prefix + 'status', description='Info about this bot.')
    sub.set_defaults(cmd='Status')


@register_parser
def subs_time(subs, prefix):
    """ Subcommand parsing for time """
    sub = subs.add_parser(prefix + 'time', description='Time in game and to ticks.')
    sub.set_defaults(cmd='Time')


@register_parser
def subs_trigger(subs, prefix):
    """ Subcommand parsing for trigger """
    desc = """Predict the expected triggers for the requested systems.

{prefix}trigger Rana, Arnemil
        Calculate triggers for requested systems from Hudson HQ.
{prefix}trigger Rana, Arnemil --power winters
{prefix}trigger Rana, Arnemil -p winters
        Calculate triggers for requested systems from Winters HQ.
    """.format(prefix=prefix)
    sub = subs.add_parser(prefix + 'trigger', description=desc, formatter_class=RawHelp)
    sub.set_defaults(cmd='Trigger')
    sub.add_argument('system', nargs='+', help='The system(s) to calculate triggers for.')
    sub.add_argument('-p', '--power', nargs='+', default=["hudson"], help='The power to calculate from.')


@register_parser
def subs_um(subs, prefix):
    """ Subcommand parsing for um """
    desc = """Get undermining targets and update their galmap status. Examples:

{prefix}um
        Show current active undermining targets.
{prefix}um burr
        Show the current status and information on Burr.
{prefix}um afl
        Show the current status and information on AF Leopris, matched search.
{prefix}um burr --set 60000:130
{prefix}um burr -s 60000:130
        Set the galmap status of Burr to 60000 and opposition to 130%.
{prefix}um burr --offset 4000
{prefix}um burr -o 4000
        Set the offset difference of cmdr merits and galmap.
{prefix}um --list
        Show all outstanding merits by users and system.
    """.format(prefix=prefix)
    sub = subs.add_parser(prefix + 'um', description=desc, formatter_class=RawHelp)
    sub.set_defaults(cmd='UM')
    sub.add_argument('system', nargs='*', help='The system to update or show.')
    sub.add_argument('-s', '--set',
                     help='Set the status of the system, us:them. Example-> --set 3500:200')
    sub.add_argument('-o', '--offset', type=int, help='Set the system galmap offset.')
    sub.add_argument('-l', '--list', action='store_true', help='Show all outstanding merits on sheet.')


@register_parser
def subs_user(subs, prefix):
    """ Subcommand parsing for user """
    desc = """Manipulate your user settings. Examples:

{prefix}user
        Show your sheet name, crys and merits per sheet.
{prefix}user --name Not Gears
        Set your name to 'Not Gears'.
{prefix}user --cry The bots are invading!
        Set your battle cry to "The bots are invading!".
    """.format(prefix=prefix)
    sub = subs.add_parser(prefix + 'user', description=desc, formatter_class=RawHelp)
    sub.set_defaults(cmd='User')
    sub.add_argument('--cry', nargs='+', help='Set your tag/cry in the sheets.')
    sub.add_argument('--name', nargs='+', help='Set your name in the sheets.')


@register_parser
def subs_whois(subs, prefix):
    """ Subcommand parsing for whois """
    desc = """Lookup information for a commander on Inara.cz

{prefix}whois GearsandCogs
        Find out who this GearsandCogs fellow is ...
{prefix}whois GearsandCogs --wing
        Find this fellow and his wing.
{prefix}whois gears
        Search for all CMDRs with 'gears' in their name
    """.format(prefix=prefix)
    sub = subs.add_parser(prefix + 'whois', description=desc, formatter_class=RawHelp)
    sub.set_defaults(cmd='WhoIs')
    sub.add_argument('cmdr', nargs='+', help='Commander name.')
    sub.add_argument("--wing", action='store_true', help="Return with more details about commander wing.")
