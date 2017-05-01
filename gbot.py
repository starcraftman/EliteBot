#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import asyncio
import logging
import logging.handlers
import os
import sys
import tempfile
try:
    from urllib.request import urlopen
except ImportError:
    from urllib import urlopen

import discord
import yaml
try:
    from yaml import CLoader as Loader, CDumper as Dumper
except ImportError:
    from yaml import Loader, Dumper

import fort

# TODO: discord.ext.bot -> wrapper
# TODO: Secure to channel/server/users
# TODO: Add basic IFF
# TODO: Generate standard test csv file
# TODO: Improve message formatting for uneven systems
# TODO: Download csv as background task every 2 minutes

def init_logging():
    """
    Initialize project wide logging.
      - 'discord' logger is used by the discord.py framework.
      - 'gbot' logger will be used to log anything in this project.

    Both loggers will:
      - Send all messsages >= WARN to STDERR.
      - Send all messages >= INFO to rotating file log in /tmp.

    IMPORTANT: On every start of gbot, the logs are rolled over. 5 runs kept max.
    """
    log_folder = os.path.join(tempfile.gettempdir(), 'gbot')
    if not os.path.exists(log_folder):
        os.makedirs(log_folder)
    discord_file = os.path.join(log_folder, 'discordpy.log')
    gbot_file = os.path.join(log_folder, 'gbot.log')
    print('discord.py log ' + discord_file)
    print('gbot log: ' + gbot_file)
    fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(msg)s')

    d_logger = logging.getLogger('discord')
    d_logger.setLevel(logging.INFO)
    handler = logging.handlers.RotatingFileHandler(discord_file,
                                                   backupCount=5, encoding='utf-8')
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(fmt)
    handler.doRollover()
    d_logger.addHandler(handler)

    g_logger = logging.getLogger('gbot')
    g_logger.setLevel(logging.INFO)
    handler = logging.handlers.RotatingFileHandler(gbot_file,
                                                   backupCount=5, encoding='utf-8')
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(fmt)
    handler.doRollover()
    g_logger.addHandler(handler)

    handler = logging.StreamHandler(sys.stderr);
    handler.setLevel(logging.WARNING)
    handler.setFormatter(fmt)
    d_logger.addHandler(handler)
    g_logger.addHandler(handler)

# Simple background coroutine example for later, adapt to refresh csv.
# async def my_task():
    # await client.wait_until_ready()
    # counter = 0
    # while not client.is_closed:
        # counter += 1
        # print('Counter', counter)
        # await asyncio.sleep(5)

client = discord.Client()
# client.loop.create_task(my_task())
init_logging()

def get_config(key):
    with open('yaml.private') as conf:
        return yaml.load(conf)[key]

def get_fort_table():
    with urlopen(get_config('url_cattle')) as fin:
        lines = str(fin.read()).split(r'\r\n')

    lines = [line.strip() for line in lines]
    systems, data = fort.parse_csv(lines)

    return fort.FortTable(systems, data)

@client.event
async def on_ready():
    print('Logged in as')
    print(client.user.name)
    print(client.user.id)
    print('------')

@client.event
async def on_message(message):
    """
    Notes:
        message.author - Returns member object
            message.author.roles -> List of Role objects. First always @everyone.
                message.author.roles[0].name -> String name of role.
        message.channel - Channel object.
            message.channel.name -> Name of channel.
            message.channel.server -> server of channel.
        message.content - The text
    """
    # Ignore all bots.
    if message.author.bot or not message.content.startswith('!'):
        return

    if message.content.startswith('!fort'):
        table = get_fort_table()

        if message.content == '!fort next long':
            msg = '\n'.join(table.next_objectives(True))
        elif message.content == '!fort next':
            msg = '\n'.join(table.next_objectives())
        else:
            msg = table.objectives()

    elif message.content.startswith('!info'):
        roles = ', '.join([role.name for role in message.author.roles[1:]])
        msg = 'Author: {aut} has Roles: {rol}'.format(aut=message.author.name, rol=roles)
        msg += '\nSent from channel [{ch}] on server [{se}]'.format(ch=message.channel.name,
                                                                se=message.channel.server)

    elif message.content.startswith('!mirror'):
        msg = '{mention}: {msg}'.format(mention=message.author.mention,
                                        msg=message.content.replace('!mirror ', ''))

    elif message.content.startswith('!help'):
        msg = '\n'.join([
                'Available commands:',
               '!fort - Show current fort targets.',
               '!fort next - Show the next 5 targets.',
               '!fort next long - Show status of the next 5 targets.',
               '!info - Dump user data.',
               '!mirror - Repeat what you write to you.',
               ])
    else:
        msg = 'Did not understand: {}'.format(message.content)
        msg += '\nGet more info with: !help'

    await client.send_message(message.channel, msg)

def main():
    try:
        client.run(get_config('token'))
    finally:
        client.close()

if __name__ == "__main__":
    main()
