"""
For main documentation consult cog/bot.py
"""
from __future__ import absolute_import, print_function
import sys

__version__ = '0.2.0'

try:
    assert sys.version_info[0:2] >= (3, 5)
except AssertionError:
    print('This entire program must be run with python >= 3.5')
    print('If unavailable on platform, see https://github.com/pyenv/pyenv')
    sys.exit(1)
