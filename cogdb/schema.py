"""
Define the database schema and some helpers.

N.B. Schema defaults only applied once object commited.
"""
from __future__ import absolute_import, print_function
import datetime

import sqlalchemy as sqla
import sqlalchemy.orm as sqla_orm
import sqlalchemy.ext.declarative

import cog.exc
import cog.tbl
import cogdb


# TODO: System hierarchy mapped to single table. Fair bit of overlap here.
# Example
# SystemBase --> SystemFort -> SystemPrep
#           \--> SystemUM  --> UMControl
#                         \--> UMExpand --> UMOppose
# TODO: Maybe make Merit -> FortMerit, UMMerit

LEN_CMD = 15  # Max length of a subclass of cog.actions
LEN_DID = 30
LEN_NAME = 100
LEN_FACTION = 10
LEN_SHEET = 15
Base = sqlalchemy.ext.declarative.declarative_base()


class EFaction(object):
    """ Switch between the two fed factions. """
    hudson = 'hudson'
    winters = 'winters'


class ESheetType(object):
    """ Type of sheet. """
    cattle = 'SheetCattle'
    undermine = 'SheetUM'


class EUMType(object):
    """ Type of undermine system. """
    control = 'control'
    expand = 'expanding'
    oppose = 'opposing'


class Admin(Base):
    """
    Table that lists admins. Essentially just a boolean.
    All admins are equal, except for removing other admins, then seniority is considered by date.
    This shouldn't be a problem practically.
    """
    __tablename__ = 'admins'

    id = sqla.Column(sqla.String(LEN_DID), primary_key=True)
    date = sqla.Column(sqla.DateTime, default=datetime.datetime.utcnow)  # All dates UTC

    def remove(self, session, other):
        """
        Remove an existing admin.
        """
        if self.date > other.date:
            raise cog.exc.InvalidPerms("You are not the senior admin. Refusing.")
        session.delete(other)
        session.commit()

    def __repr__(self):
        keys = ['id', 'date']
        kwargs = ['{}={!r}'.format(key, getattr(self, key)) for key in keys]

        return "Admin({})".format(', '.join(kwargs))

    def __str__(self):
        return repr(self)

    def __eq__(self, other):
        return self.id == other.id


class ChannelPerm(Base):
    """
    A channel permission to restrict cmd to listed channels.
    """
    __tablename__ = 'perms_channel'

    cmd = sqla.Column(sqla.String(LEN_CMD), primary_key=True)
    server = sqla.Column(sqla.String(30), primary_key=True)
    channel = sqla.Column(sqla.String(40), primary_key=True)

    def __repr__(self):
        keys = ['cmd', 'server', 'channel']
        kwargs = ['{}={!r}'.format(key, getattr(self, key)) for key in keys]

        return "ChannelPerm({})".format(', '.join(kwargs))

    def __str__(self):
        return repr(self)

    def __eq__(self, other):
        return isinstance(self, ChannelPerm) and isinstance(other, ChannelPerm) and (
            str(self) == str(other))


class RolePerm(Base):
    """
    A role permission to restrict cmd to listed roles.
    """
    __tablename__ = 'perms_role'

    cmd = sqla.Column(sqla.String(LEN_CMD), primary_key=True)
    server = sqla.Column(sqla.String(30), primary_key=True)
    role = sqla.Column(sqla.String(40), primary_key=True)

    def __repr__(self):
        keys = ['cmd', 'server', 'role']
        kwargs = ['{}={!r}'.format(key, getattr(self, key)) for key in keys]

        return "RolePerm({})".format(', '.join(kwargs))

    def __str__(self):
        return repr(self)

    def __eq__(self, other):
        return isinstance(self, RolePerm) and isinstance(other, RolePerm) and (
            str(self) == str(other))


class FortOrder(Base):
    """
    Simply store a list of Control systems in the order they should be forted.
    """
    __tablename__ = 'fort_order'

    order = sqla.Column(sqla.Integer, unique=True)
    system_name = sqla.Column(sqla.String(LEN_NAME), primary_key=True)

    def __repr__(self):
        keys = ['order', 'system_name']
        kwargs = ['{}={!r}'.format(key, getattr(self, key)) for key in keys]

        return "FortOrder({})".format(', '.join(kwargs))

    def __str__(self):
        return repr(self)

    def __eq__(self, other):
        return isinstance(self, FortOrder) and isinstance(other, FortOrder) and (
            str(self) == str(other))


class DUser(Base):
    """
    Table to store discord users and their permanent preferences.
    """
    __tablename__ = 'discord_users'

    id = sqla.Column(sqla.String(LEN_DID), primary_key=True)  # Discord id
    display_name = sqla.Column(sqla.String(LEN_NAME))
    pref_name = sqla.Column(sqla.String(LEN_NAME), unique=True, nullable=False)  # pref_name == display_name until change
    pref_cry = sqla.Column(sqla.String(LEN_NAME), default='')
    faction = sqla.Column(sqla.String(LEN_FACTION), default=EFaction.hudson)

    def __repr__(self):
        keys = ['id', 'display_name', 'pref_name', 'pref_cry', 'faction']
        kwargs = ['{}={!r}'.format(key, getattr(self, key)) for key in keys]

        return "DUser({})".format(', '.join(kwargs))

    def __str__(self):
        return repr(self)

    def __eq__(self, other):
        return isinstance(other, DUser) and self.id == other.id

    def switch_faction(self, new_faction=None):
        """ Switch current user faction """
        if not new_faction:
            new_faction = EFaction.hudson if self.faction == EFaction.winters else EFaction.winters
        self.faction = new_faction

    @property
    def mention(self):
        """ Mention this user in a response. """
        return "<@" + self.id + ">"

    def sheets(self, session):
        """ Return all sheets found. """
        return session.query(SheetRow).filter_by(name=self.pref_name).all()

    def get_sheet(self, session, sheet_type, *, faction=None):
        """
        Get a sheet belonging to a certain type. See ESheetType.

        Returns a SheetRow subclass. None if not set.
        """
        if not faction:
            faction = self.faction

        for sheet in self.sheets(session):
            if sheet.type == sheet_type and sheet.faction == faction:
                return sheet

        return None

    def cattle(self, session):
        """ Get users current cattle sheet. """
        return self.get_sheet(session, ESheetType.cattle)

    def undermine(self, session):
        """ Get users current undermining sheet. """
        return self.get_sheet(session, ESheetType.undermine)


class SheetRow(Base):
    """
    Track all infomration about the user in a row of the cattle sheet.
    """
    __tablename__ = 'sheet_users'

    id = sqla.Column(sqla.Integer, primary_key=True)
    type = sqla.Column(sqla.String(LEN_SHEET))  # See ESheetType
    faction = sqla.Column(sqla.String(LEN_FACTION), default=EFaction.hudson)
    name = sqla.Column(sqla.String(LEN_NAME))
    cry = sqla.Column(sqla.String(LEN_NAME), default='')
    row = sqla.Column(sqla.Integer)

    __table_args__ = (
        sqla.UniqueConstraint('name', 'type', 'faction'),
    )
    __mapper_args__ = {
        'polymorphic_identity': 'base_row',
        'polymorphic_on': type
    }

    def __repr__(self):
        keys = ['name', 'type', 'faction', 'row', 'cry']
        kwargs = ['{}={!r}'.format(key, getattr(self, key)) for key in keys]

        return "{}({})".format(self.__class__.__name__, ', '.join(kwargs))

    def __str__(self):
        return "id={!r}, {!r}".format(self.id, self)

    def __eq__(self, other):
        return isinstance(other, SheetRow) and (self.name, self.type, self.faction) == (
            other.name, other.type, other.faction)

    def duser(self, session):
        return session.query(DUser).filter_by(pref_name=self.name).one()


class SheetCattle(SheetRow):
    """ Track user in Hudson cattle sheet. """
    __mapper_args__ = {
        'polymorphic_identity': ESheetType.cattle,
    }

    def merit_summary(self):
        """ Summarize user merits. """
        total = 0
        for drop in self.merits:
            total += drop.amount

        return 'Dropped {}'.format(total)


class SheetUM(SheetRow):
    """ Track user in Hudson undermining sheet. """
    __mapper_args__ = {
        'polymorphic_identity': ESheetType.undermine,
    }

    def merit_summary(self):
        """ Summarize user merits. """
        held = 0
        redeemed = 0
        for hold in self.merits:
            held += hold.held
            redeemed += hold.redeemed

        return 'Holding {}, Redeemed {}'.format(held, redeemed)


class Drop(Base):
    """
    Every drop made by a user creates a fort entry here.
    User maintains a sub collection of these for easy access.
    """
    __tablename__ = 'merits'

    id = sqla.Column(sqla.Integer, primary_key=True)
    amount = sqla.Column(sqla.Integer)
    system_id = sqla.Column(sqla.Integer, sqla.ForeignKey('systems.id'), nullable=False)
    user_id = sqla.Column(sqla.Integer, sqla.ForeignKey('sheet_users.id'), nullable=False)

    def __repr__(self):
        keys = ['system_id', 'user_id', 'amount']
        kwargs = ['{}={!r}'.format(key, getattr(self, key)) for key in keys]

        return "Drop({})".format(', '.join(kwargs))

    def __str__(self):
        system = ''
        if getattr(self, 'system'):
            system = "system={!r}, ".format(self.system.name)

        suser = ''
        if getattr(self, 'user'):
            suser = "user={!r}, ".format(self.user.name)

        return "id={!r}, {}{}{!r}".format(self.id, system, suser, self)

    def __eq__(self, other):
        return isinstance(other, Drop) and (self.user_id, self.system_id) == (
            other.user_id, other.system_id)

    def __lt__(self, other):
        return self.amount < other.amount


class Hold(Base):
    """
    Represents a user's held and redeemed merits within an undermining system.
    """
    __tablename__ = 'um_merits'

    id = sqla.Column(sqla.Integer, primary_key=True)
    system_id = sqla.Column(sqla.Integer, sqla.ForeignKey('um_systems.id'), nullable=False)
    user_id = sqla.Column(sqla.Integer, sqla.ForeignKey('sheet_users.id'), nullable=False)
    held = sqla.Column(sqla.Integer)
    redeemed = sqla.Column(sqla.Integer)

    def __repr__(self):
        keys = ['system_id', 'user_id', 'held', 'redeemed']
        kwargs = ['{}={!r}'.format(key, getattr(self, key)) for key in keys]

        return "Hold({})".format(', '.join(kwargs))

    def __str__(self):
        system = ''
        if getattr(self, 'system', None):
            system = "system={!r}, ".format(self.system.name)

        suser = ''
        if getattr(self, 'user', None):
            suser = "user={!r}, ".format(self.user.name)

        return "id={!r}, {}{}{!r}".format(self.id, system, suser, self)

    def __eq__(self, other):
        return isinstance(other, Hold) and (self.user_id, self.system_id) == (
            other.user_id, other.system_id)

    def __lt__(self, other):
        return self.held + self.redeemed < other.held + other.redeemed


class KOS(Base):
    """
    Represents a the kos list.
    """
    __tablename__ = 'kos'

    id = sqla.Column(sqla.Integer, primary_key=True)
    cmdr = sqla.Column(sqla.String(100), unique=True, nullable=False)
    faction = sqla.Column(sqla.String(100), nullable=False)
    danger = sqla.Column(sqla.Integer)
    is_friendly = sqla.Column(sqla.Boolean)

    def __repr__(self):
        keys = ['cmdr', 'faction', 'danger', 'is_friendly']
        kwargs = ['{}={!r}'.format(key, getattr(self, key)) for key in keys]

        return "KOS({})".format(', '.join(kwargs))

    def __str__(self):
        return "id={!r}, {!r}".format(self.id, self)

    def __eq__(self, other):
        return isinstance(other, KOS) and (self.cmdr) == (other.cmdr)

    def __hash__(self):
        return hash((self.id, self.cmdr))

    @property
    def friendly(self):
        return 'FRIENDLY' if self.is_friendly else 'KILL'


class System(Base):
    """
    Represent a single system for fortification.
    Object can be flushed and queried from the database.

    data: List to be unpacked: ump, trigger, status, notes):
    Data tuple is to be used to make a table, with header

    args:
        id: Set by the database, unique id.
        name: Name of the system. (string)
        fort_status: Current reported status from galmap/users. (int)
        trigger: Total trigger of merits required. (int)
        undermine: Percentage of undermining of the system. (float)
        notes: Any notes attached to the system. (string)
        sheet_col: The name of the column in the excel. (string)
        sheet_order: Order systems should be ordered. (int)
    """
    __tablename__ = 'systems'

    header = ['Type', 'System', 'Missing', 'Merits (Fort%/UM%)', 'Notes']

    id = sqla.Column(sqla.Integer, primary_key=True)
    name = sqla.Column(sqla.String(LEN_NAME), unique=True)
    fort_status = sqla.Column(sqla.Integer)
    trigger = sqla.Column(sqla.Integer)
    um_status = sqla.Column(sqla.Integer, default=0)
    undermine = sqla.Column(sqla.Float, default=0.0)
    fort_override = sqla.Column(sqla.Float, default=0.0)
    distance = sqla.Column(sqla.Float)
    notes = sqla.Column(sqla.String(LEN_NAME), default='')
    sheet_col = sqla.Column(sqla.String(5))
    sheet_order = sqla.Column(sqla.Integer)
    type = sqla.Column(sqla.String(5))

    __mapper_args__ = {
        'polymorphic_identity': 'fort',
        'polymorphic_on': type
    }

    def __repr__(self):
        keys = ['name', 'fort_status', 'trigger', 'um_status',
                'undermine', 'distance', 'notes', 'sheet_col', 'sheet_order']
        kwargs = ['{}={!r}'.format(key, getattr(self, key)) for key in keys]

        return "System({})".format(', '.join(kwargs))

    def __str__(self):
        return "id={!r}, cmdr_merits={!r}, {!r}".format(self.id, self.cmdr_merits, self)

    def __eq__(self, other):
        return isinstance(other, System) and self.name == other.name

    def __lt__(self, other):
        """ Order systems by remaining supplies needed. """
        if isinstance(other, self.__class__):
            return self.missing < other.missing

    @property
    def cmdr_merits(self):
        """ Total merits dropped by cmdrs """
        total = 0
        for drop in self.merits:
            total += drop.amount
        return total

    @property
    def ump(self):
        """ Return the undermine percentage, stored as decimal. """
        return '{:.1f}'.format(self.undermine * 100)

    @property
    def current_status(self):
        """ Simply return max fort status reported. """
        # FIXME: Hack until import sheet included.
        supplies = max(self.fort_status, self.cmdr_merits)
        if self.fort_override > supplies / self.trigger:
            return int(self.fort_override * self.trigger)

        return supplies

    @property
    def skip(self):
        """ The system should be skipped. """
        notes = self.notes.lower()
        return 'leave' in notes or 'skip' in notes

    @property
    def is_fortified(self):
        """ The remaining supplies to fortify """
        # FIXME: Hack until import sheet included.
        if self.fort_override >= 1.0:
            return True

        return self.current_status >= self.trigger

    @property
    def is_undermined(self):
        """ The system has been undermined """
        return self.undermine >= 1.00

    @property
    def missing(self):
        """ The remaining supplies to fortify """
        return max(0, self.trigger - self.current_status)

    @property
    def completion(self):
        """ The fort completion percentage """
        try:
            comp_cent = self.current_status / self.trigger * 100
        except ZeroDivisionError:
            comp_cent = 0

        return '{:.1f}'.format(comp_cent)

    @property
    def table_row(self):
        """
        Return a tuple of important data to be formatted for table output.
        Each element should be mapped to separate column.
        See header.
        """
        status = '{:>4}/{} ({}%/{}%)'.format(self.current_status, self.trigger,
                                             self.completion, self.ump)

        return (self.type.capitalize(), self.name,
                '{:>4}'.format(self.missing), status, self.notes)

    def set_status(self, new_status):
        """
        Update the fort_status and um_status of this System based on new_status.
        Format of new_status: fort_status[:um_status]

        Raises: ValueError
        """
        for val, attr in zip(new_status.split(':'), ['fort_status', 'um_status']):
            new_val = int(val)
            if new_val < 0:
                raise cog.exc.InvalidCommandArgs('New fort/um status must be in range: [0, \u221E]')

            setattr(self, attr, int(val))

    def display(self, *, miss=None):
        """
        Return a useful short representation of System.

        Kwargs:
            missing: A trinary:
                - None, show missing only if < 1500 left
                - True, display missing
                - False, do not display missing
        """
        umd = ''
        if self.um_status > 0:
            umd = ', {} :Undermin{}:'.format(
                self.um_status, 'ed' if self.is_undermined else 'ing')
        elif self.is_undermined:
            umd = ', :Undermined:'

        msg = '**{}** {:>4}/{} :Fortif{}:{}'.format(
            self.name, self.current_status, self.trigger,
            'ied' if self.is_fortified else 'ying', umd)

        if miss or miss is not False and (self.missing and self.missing < 1500):
            msg += ' ({} left)'.format(self.missing)

        if self.notes:
            msg += ' ' + self.notes

        return msg

    def display_details(self):
        """ Return a highly detailed system display. """
        miss = ' ({} left)'.format(self.missing) if self.missing else ''
        lines = [
            ['Completion', '{}%{}'.format(self.completion, miss)],
            ['CMDR Merits', '{}/{}'.format(self.cmdr_merits, self.trigger)],
            ['Fort Status', '{}/{}'.format(self.fort_status, self.trigger)],
            ['UM Status', '{} ({:.2f}%)'.format(self.um_status, self.undermine * 100)],
            ['Notes', self.notes],
        ]

        return '**{}**\n'.format(self.name) + cog.tbl.wrap_markdown(cog.tbl.format_table(lines))


class PrepSystem(System):
    """
    A prep system that must be fortified for expansion.
    """
    __mapper_args__ = {
        'polymorphic_identity': 'prep',
    }

    @property
    def is_fortified(self):
        """ Prep systems never get finished. """
        return False

    def display(self, *, miss=None):
        """
        Return a useful short representation of PrepSystem.
        """
        return 'Prep: ' + super().display(miss=miss)


class SystemUM(Base):
    """
    A control system we intend on undermining.
    """
    __tablename__ = 'um_systems'

    id = sqla.Column(sqla.Integer, primary_key=True)
    name = sqla.Column(sqla.String(LEN_NAME), unique=True)
    type = sqla.Column(sqla.String(15))  # EUMType
    sheet_col = sqla.Column(sqla.String(5))
    goal = sqla.Column(sqla.Integer)
    security = sqla.Column(sqla.String(LEN_NAME))
    notes = sqla.Column(sqla.String(LEN_NAME))
    close_control = sqla.Column(sqla.String(LEN_NAME))
    progress_us = sqla.Column(sqla.Integer)
    progress_them = sqla.Column(sqla.Float)
    map_offset = sqla.Column(sqla.Integer, default=0)
    exp_trigger = sqla.Column(sqla.Integer, default=0)

    __mapper_args__ = {
        'polymorphic_identity': 'base_system',
        'polymorphic_on': type
    }

    @staticmethod
    def factory(kwargs):
        """ Simple factory to make undermining systems. """
        cls = kwargs.pop('cls')
        return cls(**kwargs)

    def __repr__(self):
        keys = ['name', 'type', 'sheet_col', 'goal', 'security', 'notes',
                'progress_us', 'progress_them', 'close_control', 'map_offset']
        kwargs = ['{}={!r}'.format(key, getattr(self, key)) for key in keys]

        return "SystemUM({})".format(', '.join(kwargs))

    def __str__(self):
        """
        Show additional computed properties.
        """
        return "id={!r}, cmdr_merits={!r}, {!r}".format(self.id, self.cmdr_merits, self)

    def __eq__(self, other):
        return isinstance(other, SystemUM) and self.name == other.name

    @property
    def completion(self):
        """ The completion percentage formatted as a string """
        try:
            comp_cent = (self.goal - self.missing) / self.goal * 100
        except ZeroDivisionError:
            comp_cent = 0

        completion = '{:.0f}%'.format(comp_cent)

        return completion

    @property
    def cmdr_merits(self):
        """ Total merits held and redeemed by cmdrs """
        total = 0
        for hold in self.merits:
            total += hold.held + hold.redeemed
        return total

    @property
    def missing(self):
        """ The remaining supplies to fortify """
        return self.goal - max(self.cmdr_merits + self.map_offset, self.progress_us)

    @property
    def descriptor(self):
        """ Descriptive prefix for string. """
        return self.type.capitalize()

    @property
    def is_undermined(self):
        """
        Return true only if the system is undermined.
        """
        return self.missing <= 0

    def display(self):
        """
        Format a simple summary for users.
        """
        lines = [
            [self.descriptor, '[{}] {}'.format(self.security[0].upper(), self.name)],
            [self.completion, 'Merits {} {}'.format('Missing' if self.missing > 0 else 'Leading',
                                                    str(abs(self.missing)))],
            ['Our Progress ' + str(self.progress_us),
             'Enemy Progress {:.0f}%'.format(self.progress_them * 100)],
            ['Nearest Hudson', self.close_control],
        ]

        return cog.tbl.wrap_markdown(cog.tbl.format_table(lines))

    def set_status(self, new_status):
        """
        Update the fort_status and um_status of this System based on new_status.
        Format of new_status: fort_status[:um_status]

        Raises: ValueError
        """
        vals = new_status.split(':')
        if len(vals) == 2:
            new_them = float(vals[1]) / 100
            if new_them < 0:
                raise cog.exc.InvalidCommandArgs('New "progress them" must be a % in range: [0, \u221E]')
            self.progress_them = new_them

        new_us = int(vals[0])
        if new_us < 0:
            raise cog.exc.InvalidCommandArgs('New "progress us" must be a number merits in range: [0, \u221E]')
        self.progress_us = new_us


class UMControl(SystemUM):
    """ Undermine an enemy control system. """
    __mapper_args__ = {
        'polymorphic_identity': EUMType.control,
    }


class UMExpand(SystemUM):
    """ An expansion we want. """
    __mapper_args__ = {
        'polymorphic_identity': EUMType.expand,
    }

    @property
    def is_undermined(self):
        """
        Expansions are never finished until tick.
        """
        return False

    @property
    def completion(self):
        """ The completion percentage formatted as a string """
        try:
            comp_cent = max(self.progress_us,
                            self.cmdr_merits + self.map_offset) * 100 / self.exp_trigger
        except ZeroDivisionError:
            comp_cent = 0

        comp_cent -= self.progress_them * 100
        prefix = 'Leading by' if comp_cent >= 0 else 'Behind by'
        completion = '{} {:.0f}%'.format(prefix, abs(comp_cent))

        return completion


class UMOppose(UMExpand):
    """ We want to oppose the expansion. """
    __mapper_args__ = {
        'polymorphic_identity': EUMType.oppose,
    }

    @property
    def descriptor(self):
        """ Descriptive prefix for string. """
        suffix = 'expansion'
        if self.notes != '':
            suffix = self.notes.split()[0]
        return 'Opposing ' + suffix


def kwargs_um_system(cells, sheet_col):
    """
    Return keyword args parsed from cell frame.

    Format !D1:E11:
        1: Title | Title
        2: Exp Trigger/Opp. Tigger | % safety margin  -> If cells blank, not expansion system.
        3: Leading by xx% OR behind by xx% (
        4: Estimated Goal (integer)
        5: CMDR Merits (Total merits)
        6: Missing Merits
        7: Security Level | Notes
        8: Closest Control (string)
        9: System Name (string)
        10: Our Progress (integer) | Type String (Ignore)
        11: Enemy Progress (percentage) | Type String (Ignore)
        12: Skip
        13: Map Offset (Map Value - Cmdr Merits)
    """
    try:
        main_col, sec_col = cells[0], cells[1]

        if main_col[8] == '' or 'template' in main_col[8].lower():
            raise cog.exc.SheetParsingError

        if main_col[0].startswith('Exp'):
            cls = UMExpand
        elif main_col[0] != '':
            cls = UMOppose
        else:
            cls = UMControl

        # Cell is not guaranteed to exist in list
        try:
            map_offset = parse_int(main_col[12])
        except IndexError:
            map_offset = 0

        return {
            'exp_trigger': parse_int(main_col[1]),
            'goal': parse_int(main_col[3]),  # FIXME: May come down as float. This would truncate.
            'security': main_col[6].strip().replace('Sec: ', ''),
            'notes': sec_col[6].strip(),
            'close_control': main_col[7].strip(),
            'name': main_col[8].strip(),
            'progress_us': parse_int(main_col[9]),
            'progress_them': parse_float(main_col[10]),
            'map_offset': map_offset,
            'sheet_col': sheet_col,
            'cls': cls,
        }
    except (IndexError, TypeError):
        raise cog.exc.SheetParsingError


def kwargs_fort_system(lines, order, column):
    """
    Simple adapter that parses the data and puts it into kwargs to
    be used when initializing the System object.

    lines: A list of the following
        0   - undermine % (comes as float 0.0 - 1.0)
        1   - completion % (comes as float 0.0 - 1.0)
        2   - fortification trigger
        3   - missing merits
        4   - merits dropped by commanders
        5   - status updated manually (defaults to '', map to 0)
        6   - undermine updated manually (defaults to '', map to 0)
        7   - distance from hq (float, always set)
        8   - notes (defaults '')
        9   - system name
    order: The order of this data set relative others.
    column: The column string this data belongs in.
    """
    try:
        if lines[9] == '':
            raise cog.exc.SheetParsingError

        return {
            'undermine': parse_float(lines[0]),
            'fort_override': parse_float(lines[1]),
            'trigger': parse_int(lines[2]),
            'fort_status': parse_int(lines[5]),
            'um_status': parse_int(lines[6]),
            'distance': parse_float(lines[7]),
            'notes': lines[8].strip(),
            'name': lines[9].strip(),
            'sheet_col': column,
            'sheet_order': order,
        }
    except (IndexError, TypeError):
        raise cog.exc.SheetParsingError


def parse_int(word):
    """ Parse into int, on failure return 0 """
    try:
        return int(word)
    except ValueError:
        return 0


def parse_float(word):
    """ Parse into float, on failure return 0.0 """
    try:
        return float(word)
    except ValueError:
        return 0.0


def empty_tables(session, *, perm=False):
    """
    Drop all tables.
    """
    classes = [Drop, Hold, System, SystemUM, SheetRow]
    if perm:
        classes += [DUser]

    for cls in classes:
        for matched in session.query(cls):
            session.delete(matched)
    session.commit()


def recreate_tables():
    """
    Recreate all tables in the database, mainly for schema changes and testing.
    """
    Base.metadata.drop_all(cogdb.engine)
    Base.metadata.create_all(cogdb.engine)


# Relationships
# TODO: Is there a better way?
#   Now using two one way selects, feels icky.
#   I cannot enforce this key constraint as both sides are inserted independently
#   So instead of a key I make two one way joins and cast the key.
# DUser.sheets = sqla_orm.relationship("SheetRow",
                                    # primaryjoin="DUser.pref_name == foreign(SheetRow.name)",
                                    # cascade_backrefs=False)
# SheetRow.duser = sqla_orm.relationship("DUser",
                                    # primaryjoin="SheetRow.name == foreign(DUser.pref_name)",
                                    # cascade_backrefs=False)

# Fortification relations
Drop.user = sqla_orm.relationship('SheetCattle', uselist=False, back_populates='merits',
                                  lazy='select')
SheetCattle.merits = sqla_orm.relationship('Drop',
                                           cascade='all, delete, delete-orphan',
                                           back_populates='user',
                                           lazy='select')
Drop.system = sqla_orm.relationship('System', uselist=False, back_populates='merits',
                                    lazy='select')
System.merits = sqla_orm.relationship('Drop',
                                      cascade='all, delete, delete-orphan',
                                      back_populates='system',
                                      lazy='select')

# Undermining relations
Hold.user = sqla_orm.relationship('SheetUM', uselist=False, back_populates='merits',
                                  lazy='select')
SheetUM.merits = sqla_orm.relationship('Hold',
                                       cascade='all, delete, delete-orphan',
                                       back_populates='user',
                                       lazy='select')
Hold.system = sqla_orm.relationship('SystemUM', uselist=False, back_populates='merits',
                                    lazy='select')
SystemUM.merits = sqla_orm.relationship('Hold',
                                        cascade='all, delete, delete-orphan',
                                        back_populates='system',
                                        lazy='select')


if cogdb.TEST_DB:
    recreate_tables()
else:
    Base.metadata.create_all(cogdb.engine)


def main():  # pragma: no cover
    """
    This continues to exist only as a sanity test for schema and relations.
    """
    Base.metadata.drop_all(cogdb.engine)
    Base.metadata.create_all(cogdb.engine)
    session = cogdb.Session()

    dusers = (
        DUser(id='197221', pref_name='GearsandCogs'),
        DUser(id='299221', pref_name='rjwhite'),
        DUser(id='293211', pref_name='vampyregtx'),
    )
    session.add_all(dusers)
    session.commit()

    sheets = (
        SheetCattle(name='GearsandCogs', row=15),
        SheetCattle(name='rjwhite', row=16),
        SheetCattle(name='vampyregtx', row=17),
        SheetUM(name='vampyregtx', row=22),
        SheetCattle(name='vampyregtx', faction=EFaction.winters, row=22),
        SheetUM(name='vampyregtx', faction=EFaction.winters, row=22),
    )

    session.add_all(sheets)
    session.commit()

    systems = (
        System(name='Frey', sheet_col='F', sheet_order=1, fort_status=0,
               trigger=7400, undermine=0),
        System(name='Adeo', sheet_col='G', sheet_order=2, fort_status=0,
               trigger=5400, undermine=0),
        System(name='Sol', sheet_col='H', sheet_order=3, fort_status=0,
               trigger=6000, undermine=0),
    )
    session.add_all(systems)
    session.commit()

    drops = (
        Drop(user_id=sheets[0].id, system_id=systems[0].id, amount=700),
        Drop(user_id=sheets[1].id, system_id=systems[0].id, amount=700),
        Drop(user_id=sheets[0].id, system_id=systems[2].id, amount=1400),
        Drop(user_id=sheets[2].id, system_id=systems[1].id, amount=2100),
        Drop(user_id=sheets[2].id, system_id=systems[0].id, amount=300),
    )
    session.add_all(drops)
    session.commit()

    def mprint(*args):
        """ Padded print. """
        args = [str(x) for x in args]
        print(*args)

    pad = ' ' * 3

    print('DiscordUsers----------')
    for user in session.query(DUser):
        mprint(user)
        mprint(pad, user.sheets)
        mprint(user.cattle)

    print('SheetUsers----------')
    for user in session.query(SheetRow):
        mprint(user)
        mprint(pad, user.duser)

    print('Systems----------')
    for sys in session.query(System):
        mprint(sys)
        mprint(pad, sys.merits)
        mprint(sorted(sys.merits))

    print('Drops----------')
    for drop in session.query(Drop):
        mprint(drop)
        mprint(pad, drop.user)
        mprint(pad, drop.system)


if __name__ == "__main__":  # pragma: no cover
    main()
