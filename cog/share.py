"""
Common functions.
"""
from __future__ import absolute_import, print_function
import functools
import logging
import logging.handlers
import logging.config
import os

import argparse
import tempfile
import yaml
try:
    from yaml import CLoader as Loader
except ImportError:
    from yaml import Loader

import cogdb.query
import cog.sheets
import cog.tbl


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
YAML_FILE = os.path.join(ROOT_DIR, '.secrets', 'config.yaml')


class ArgumentParseError(Exception):
    """ Error raised instead of exiting on argparse error. """
    pass


class ThrowArggumentParser(argparse.ArgumentParser):
    def error(self, message=None):
        """
        Suppress default exit after error.
        """
        raise ArgumentParseError()

    def exit(self, status=0, message=None):
        """
        Suppress default exit behaviour.
        """
        raise ArgumentParseError()


class ModFormatter(logging.Formatter):
    """
    Add a relmod key to record dict.
    This key tracks a module relative this project' root.
    """
    def format(self, record):
        relmod = record.__dict__['pathname'].replace(ROOT_DIR + os.path.sep, '')
        record.__dict__['relmod'] = relmod[:-3]
        return super(ModFormatter, self).format(record)


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

    IMPORTANT: On every start the file logs are rolled over.
    """
    log_folder = os.path.join(tempfile.gettempdir(), 'cog')
    try:
        os.makedirs(log_folder)
    except OSError:
        pass
    print('LOGGING FOLDER:', log_folder)

    with open(rel_to_abs('log.yaml')) as fin:
        log_conf = yaml.load(fin, Loader=Loader)
    logging.config.dictConfig(log_conf)

    for handler in logging.getLogger('cog').handlers + logging.getLogger('cogdb').handlers:
        if isinstance(handler, logging.handlers.RotatingFileHandler):
            handler.doRollover()


def init_db(sheet_id):
    """
    Scan sheet and fill database if empty.
    """
    session = cogdb.Session()

    if not session.query(cogdb.schema.System).all():
        secrets = get_config('secrets', 'sheets')
        sheet = cog.sheets.GSheet(sheet_id, rel_to_abs(secrets['json']),
                                  rel_to_abs(secrets['token']))

        system_col = cogdb.query.first_system_column(sheet.get_with_formatting('!A10:J10'))
        cells = sheet.whole_sheet()
        user_col, user_row = cogdb.query.first_user_row(cells)
        scanner = cogdb.query.SheetScanner(cells, system_col, user_col, user_row)
        systems = scanner.systems()
        users = scanner.users()
        session.add_all(systems + users)
        session.commit()

        forts = scanner.forts(systems, users)
        session.add_all(forts)
        session.commit()


def rel_to_abs(path):
    """
    Convert an internally relative path to an absolute one.
    """
    return os.path.join(ROOT_DIR, path)


def make_parser(table):
    """
    Returns the bot parser.
    """
    parser = ThrowArggumentParser(prog='cog', description='simple discord bot')

    subs = parser.add_subparsers(title='subcommands',
                                 description='The subcommands of cog')

    sub = subs.add_parser('fort', description='Show next fort target.')
    sub.add_argument('-l', '--long', action='store_true', default=False,
                     help='show detailed stats')
    sub.add_argument('-n', '--next', action='store_true', default=False,
                     help='show NUM systems after current')
    sub.add_argument('num', nargs='?', type=int, default=5,
                     help='number of systems to display')
    sub.set_defaults(func=functools.partial(parse_fort, table))

    sub = subs.add_parser('user', description='Manipulate sheet users.')
    sub.add_argument('-a', '--add', action='store_true', default=False,
                     help='Add a user to table if not present.')
    sub.add_argument('-q', '--query', action='store_true', default=False,
                     help='Return username and row if exists.')
    sub.add_argument('user', nargs='+',
                     help='The user to interact with.')
    sub.set_defaults(func=functools.partial(parse_user, table))

    sub = subs.add_parser('drop', description='Drop forts for user at system.')
    sub.add_argument('amount', type=int, help='The amount to drop.')
    sub.add_argument('-s', '--system', required=True, nargs='+',
                     help='The system to drop at.')
    sub.add_argument('-u', '--user', nargs='+',
                     help='The user to drop for.')
    sub.set_defaults(func=functools.partial(parse_drop, table))

    sub = subs.add_parser('dump', description='Dump the current db.')
    sub.set_defaults(func=parse_dumpdb)

    sub = subs.add_parser('help', description='Show overall help message.')
    sub.set_defaults(func=parse_help)
    return parser


def parse_help(_):
    """
    Simply prints overall help documentation.
    """
    lines = [
        ['Command', 'Effect'],
        ['!fort', 'Show current fort target.'],
        ['!fort -l', 'Show current fort target\'s status.'],
        ['!fort -n NUM', 'Show the next NUM targets. Default NUM = 5.'],
        ['!fort -nl NUM', 'Show status of the next NUM targets.'],
        ['!user -a USER', 'Add a USER to table.'],
        ['!user -q USER', 'Check if user is in table.'],
        ['!drop AMOUNT -s SYSTEM -u USER', 'Increase by AMOUNT forts for USER at SYSTEM'],
        ['!info', 'Display information on user.'],
        ['!help', 'This help message.'],
    ]
    return cog.tbl.wrap_markdown(cog.tbl.format_table(lines, header=True))


def parse_dumpdb(_):
    cogdb.query.dump_db()


def parse_fort(table, args):
    if args.next:
        systems = table.next_targets(args.num)
    else:
        systems = table.targets()

    if args.long:
        lines = [systems[0].__class__.header] + [system.table_row for system in systems]
        msg = cog.tbl.wrap_markdown(cog.tbl.format_table(lines, sep='|', header=True))
    else:
        msg = '\n'.join([system.name for system in systems])

    return msg


def parse_user(table, args):
    args.user = ' '.join(args.user)
    user = table.find_user(args.user)

    if user:
        if args.query or args.add:
            msg = "User '{}' already present in row {}.".format(user.sheet_name,
                                                                user.sheet_row)
    else:
        if args.add:
            new_user = table.add_user(args.user)
            msg = "Added '{}' to row {}.".format(new_user.sheet_name,
                                                 new_user.sheet_row)
        else:
            msg = "User '{}' not found.".format(args.user)

    return msg


def parse_drop(table, args):
    args.system = ' '.join(args.system)
    if args.user:
        args.user = ' '.join(args.user)

    system = table.add_fort(args.system, args.user, args.amount)
    try:
        lines = [system.__class__.header, system.table_row]
        return cog.tbl.wrap_markdown(cog.tbl.format_table(lines, sep='|', header=True))
    except cog.exc.InvalidCommandArgs as exc:
        return str(exc)
