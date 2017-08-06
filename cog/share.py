"""
Common functions.
"""
from __future__ import absolute_import, print_function
import logging
import logging.handlers
import logging.config
import os
import re

import argparse
from argparse import RawDescriptionHelpFormatter as RawHelp
import tempfile
import yaml
try:
    from yaml import CLoader as Loader
except ImportError:
    from yaml import Loader

import cog.exc
import cog.sheets
import cog.tbl


class ThrowArggumentParser(argparse.ArgumentParser):
    """
    ArgumentParser subclass that does NOT terminate the program.
    """
    def print_help(self, file=None):  # pylint: disable=redefined-builtin
        formatter = self._get_formatter()
        formatter.add_text(self.description)
        raise cog.exc.ArgumentHelpError(formatter.format_help())

    def error(self, message):
        raise cog.exc.ArgumentParseError(message, self.format_usage())

    def exit(self, status=0, message=None):
        """
        Suppress default exit behaviour.
        """
        raise cog.exc.ArgumentParseError(message, self.format_usage())


class ModFormatter(logging.Formatter):
    """
    Add a relmod key to record dict.
    This key tracks a module relative this project' root.
    """
    def format(self, record):
        relmod = record.__dict__['pathname'].replace(ROOT_DIR + os.path.sep, '')
        record.__dict__['relmod'] = relmod[:-3]
        return super(ModFormatter, self).format(record)


def rel_to_abs(*path_parts):
    """
    Convert an internally relative path to an absolute one.
    """
    return os.path.join(ROOT_DIR, *path_parts)


def get_config(*keys):
    """
    Return keys straight from yaml config.
    """
    with open(YAML_FILE) as conf:
        conf = yaml.load(conf, Loader=Loader)

    for key in keys:
        conf = conf[key]

    return conf


def init_logging():
    """
    Initialize project wide logging. The setup is described best in config file.

     - On every start the file logs are rolled over.
     - This should be first invocation on startup to set up logging.
    """
    # FIXME: May fail, look at paths in yaml.
    log_folder = os.path.join(tempfile.gettempdir(), 'cog')
    try:
        os.makedirs(log_folder)
    except OSError:
        pass
    print('Logging Folder:', log_folder)
    print('Main Log File:', os.path.join(log_folder, 'info.log'))

    with open(rel_to_abs(get_config('paths', 'log_conf'))) as fin:
        log_conf = yaml.load(fin, Loader=Loader)
    logging.config.dictConfig(log_conf)

    for handler in logging.getLogger('cog').handlers + logging.getLogger('cogdb').handlers:
        if isinstance(handler, logging.handlers.RotatingFileHandler):
            handler.doRollover()


def make_parser(prefix):
    """
    Returns the bot parser.
    """
    parser = ThrowArggumentParser(prog='', description='simple discord bot')

    subs = parser.add_subparsers(title='subcommands',
                                 description='The subcommands of cog')

    desc = """Admin only commands. Examples:

    {prefix}admin deny\n          Toggle command processing.
    {prefix}admin dump\n          Dump the database to console to inspect.
    {prefix}admin halt\n          Shutdown this bot after short delay.
    {prefix}admin scan\n          Pull and parse the latest sheet information.
    {prefix}admin info @User\n          Information about the mentioned User, DMed to admin.
    """.format(prefix=prefix)
    sub = subs.add_parser(prefix + 'admin', description=desc, formatter_class=RawHelp)
    sub.set_defaults(cmd='admin')
    admin_subs = sub.add_subparsers(title='subcommands',
                                    description='Admin subcommands', dest='subcmd')
    admin_subs.add_parser('deny', help='Toggle command processing.')
    admin_subs.add_parser('dump', help='Dump the db to console.')
    admin_subs.add_parser('halt', help='Stop accepting commands and halt bot.')
    admin_subs.add_parser('scan', help='Scan the sheets for updates.')
    admin_sub = admin_subs.add_parser('info', help='Get info about discord users.')
    admin_sub.add_argument('user', nargs='?', help='The user to get info on.')

    desc = """Update the cattle sheet when you drop at a system.
    Amount dropped must be in range [-800, 800]
    Examples:

    {prefix}drop 600\n           Drop 600 supplies for yourself at the current fortification target.
    {prefix}drop 600 @Shepron\n           Drop 600 supplies for Shepron at the current fortification target.
    {prefix}drop 600 Othime\n           Drop 600 supplies for yourself at Othime.
    {prefix}drop -50 Othime\n           Made a mistake? Subract 50 forts from your drops at Othime.
    {prefix}drop 600 Othime @rjwhite\n           Drop 600 supplies for rjwhite Othime.
    {prefix}drop 600 lala\n           Drop 600 supplies for yourself at Lalande 39866, search used when name is not exact.
    {prefix}drop 600 Othime --set 4560:2000\n           Drop 600 supplies at Othime for yourself, set fort status to 4500 and UM status to 2000.
    """.format(prefix=prefix)
    sub = subs.add_parser(prefix + 'drop', description=desc, formatter_class=RawHelp)
    sub.set_defaults(cmd='drop')
    sub.add_argument('amount', type=int, help='The amount to drop.')
    sub.add_argument('system', nargs='*', help='The system to drop at.')
    sub.add_argument('--set',
                     help='Set the fort:um status of the system. Example-> --set 3400:200')

    desc = """Show fortification status and targets. Examples:

    {prefix}fort\n           Show current fort targets.
    {prefix}fort --next\n           Show the next fortification target (excludes Othime and skipped).
    {prefix}fort --nextn 3\n           Show the next 3 fortification targets (excludes Othime and skipped).
    {prefix}fort --summary\n           Show a breakdown by states of our systems.
    {prefix}fort alpha\n           Show the fortification status of Alpha Fornacis.
    {prefix}fort Othime --set 7500:2000\n           Set othime to 7500 fort status and 2000 um status.
    """.format(prefix=prefix)
    sub = subs.add_parser(prefix + 'fort', description=desc, formatter_class=RawHelp)
    sub.set_defaults(cmd='fort')
    sub.add_argument('system', nargs='*', help='Select this system.')
    sub.add_argument('--set',
                     help='Set the fort:um status of system. Example-> --set 3400:200')
    sub.add_argument('--summary', action='store_true',
                     help='Provide an overview of the fort systems.')
    sub.add_argument('-l', '--long', action='store_true', help='Show systems in table format')
    sub.add_argument('--nextn', type=int,
                     help='Show the next NUM fort targets after current')
    sub.add_argument('-n', '--next', action='store_true',
                     help='Show the next fort target')

    desc = """Update a user's held or redeemed merits. Examples:

    {prefix}hold 1200 burr\n           Set your held merits at Burr to 1200.
    {prefix}hold 900 af leopris @Memau\n           Set held merits at System AF Leopris to 900 held for Memau.
    {prefix}hold --died\n           Reset your held merits to 0 due to dying.
    {prefix}hold --redeem\n           Move all held merits to redeemed column.
    {prefix}hold 720 burr --set 60000:130\n           Update held merits to 720 at Burr expansion and set progress to 60000 merits and 130% opposition.
    """.format(prefix=prefix)
    sub = subs.add_parser(prefix + 'hold', description=desc, formatter_class=RawHelp)
    sub.set_defaults(cmd='hold')
    sub.add_argument('amount', nargs='?', type=int, help='The amount of merits held.')
    sub.add_argument('system', nargs='*', help='The system merits are held in.')
    sub.add_argument('--redeem', action='store_true', help='Redeem all held merits.')
    sub.add_argument('--died', action='store_true', help='Zero out held merits.')
    sub.add_argument('--set', help='Update the galmap progress us:them. Example: --set 3500:200')

    desc = """Give feedback or report a bug. Example:

    {prefix}bug Explain what went wrong ...\n          File a bug report or give feedback.
    """.format(prefix=prefix)
    sub = subs.add_parser(prefix + 'feedback', description=desc, formatter_class=RawHelp)
    sub.set_defaults(cmd='feedback')
    sub.add_argument('content', nargs='+', help='The bug description or feedback.')

    sub = subs.add_parser(prefix + 'status', description='Info about this bot.')
    sub.set_defaults(cmd='status')

    sub = subs.add_parser(prefix + 'time', description='Time in game and to ticks.')
    sub.set_defaults(cmd='time')

    desc = """Get undermining targets and update their galmap status. Examples:

    {prefix}um\n           Show current active undermining targets.
    {prefix}um burr\n           Show the current status and information on Burr.
    {prefix}um afl\n           Show the current status and information on AF Leopris, matched search.
    {prefix}um burr --set 60000:130\n           Set the galmap status of Burr to 60000 and opposition to 130%.
    {prefix}um burr --offset 4000\n           Set the offset difference of cmdr merits and galmap.
    """.format(prefix=prefix)
    sub = subs.add_parser(prefix + 'um', description=desc, formatter_class=RawHelp)
    sub.set_defaults(cmd='um')
    sub.add_argument('system', nargs='*', help='The system to update or show.')
    sub.add_argument('--set',
                     help='Set the status of the system, us:them. Example-> --set 3500:200')
    sub.add_argument('--offset', type=int, help='Set the system galmap offset.')

    desc = """Manipulate your user settings. Examples:

    {prefix}user\n           Show your sheet name, crys and merits per sheet.
    {prefix}user --name Not Gears\n           Set your name to 'Not Gears'.
    {prefix}user --cry The bots are invading!\n           Set your battle cry to "The bots are invading!".
    {prefix}user --hudson\n           Switch to Hudson's sheets.
    {prefix}user --winters\n           Switch to Winters' sheets.
    """.format(prefix=prefix)
    sub = subs.add_parser(prefix + 'user', description=desc, formatter_class=RawHelp)
    sub.set_defaults(cmd='user')
    sub.add_argument('--cry', nargs='+', help='Set your tag/cry in the sheets.')
    sub.add_argument('--name', nargs='+', help='Set your name in the sheets.')
    sub.add_argument('--winters', action='store_true',
                     help='Set yourself to use the Winters sheets.')
    sub.add_argument('--hudson', action='store_true',
                     help='Set yourself to use the Hudson sheets.')

    sub = subs.add_parser(prefix + 'help', description='Show overall help message.')
    sub.set_defaults(cmd='help')
    return parser


def dict_to_columns(data):
    """
    Transform the dict into columnar form with keys as column headers.
    """
    lines = []
    header = []

    for col, key in enumerate(sorted(data)):
        header.append('{} ({})'.format(key, len(data[key])))

        for row, item in enumerate(data[key]):
            try:
                lines[row]
            except IndexError:
                lines.append([])
            while len(lines[row]) != col:
                lines[row].append('')
            lines[row].append(item)

    return [header] + lines


def extract_emoji(text):
    """
    Find and extract all emoji eanchors in message. Return in list.
    """
    return list(set(re.findall(r':\S+:', text)))


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
YAML_FILE = rel_to_abs('data', 'config.yml')
