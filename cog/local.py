#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Stub version of bot, doesn't connect to discord.
Instead parses CLI to test commands/outputs locally.
"""
from __future__ import absolute_import, print_function
import logging
import sys

import mock
import cog.share


# TODO: investigate use of discord.ext.bot || make own bot class
# TODO: Secure commands against servers/channels/users
# TODO: Allow management commands to add/remove above
# TODO: Add basic whois support, default lookup in local to channel db
# TODO: Add wider search, across server, inara and other sources

# Simple background coroutine example for later, adapt to refresh csv.
# async def my_task():
    # await client.wait_until_ready()
    # counter = 0
    # while not client.is_closed:
        # counter += 1
        # print('Counter', counter)
        # await asyncio.sleep(5)
# client.loop.create_task(my_task())


def main():
    """
    Simply operate the bot locally by command line input.
    """
    cog.share.init_logging()
    cog.share.init_db(cog.share.get_config('hudson', 'cattle', 'id'))
    logging.getLogger('cog.local').error('Local loop is ready.')

    try:
        parser = cog.share.make_parser()

        while True:
            try:
                line = sys.stdin.readline().rstrip()
                args = parser.parse_args(line.split(' '))
                msg = args.func(args, mock.Mock(), mock.Mock())
                if msg:
                    print(msg.replace('```', ''))
            except cog.share.ArgumentParseError:
                print('Invalid command:', line)
    except KeyboardInterrupt:
        print('\nTerminating loop. Thanks for testing.')


if __name__ == "__main__":
    main()
