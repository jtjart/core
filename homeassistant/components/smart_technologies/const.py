"""Constants for the SMART Technologies integration."""

from datetime import timedelta
from enum import StrEnum
import logging

DOMAIN = "smart_technologies"
LOGGER = logging.getLogger(__package__)

ENTRY_TITLE = "SMART UX60"

# The projector does not push changes, so it is polled. Every command takes
# roughly 150-250 ms on the wire (the RS-232 guide requires ~10 ms between
# characters), so the poll is deliberately conservative:
#
# * the power state is read on every update;
# * "live" settings (input, volume, mute, ...) are read on every update while the
#   projector is on;
# * everything else is configuration that rarely changes outside Home Assistant
#   and is only re-read every SLOW_INTERVAL;
# * a setting is only polled while an enabled entity needs it.
UPDATE_INTERVAL = timedelta(seconds=30)
SLOW_INTERVAL = timedelta(minutes=10)

# A refresh may start slightly before a full interval has elapsed.
INTERVAL_SLACK = 2.0

# How long to wait for further entities to register before reading newly needed settings.
REFRESH_COOLDOWN = 1.0

# Consecutive failed updates (about five minutes) before a repair issue is raised.
ISSUE_THRESHOLD = 10
ISSUE_CANNOT_COMMUNICATE = "cannot_communicate"


def enum_option(member: StrEnum) -> str:
    """Return the translatable option key for a library enum member."""
    return member.name.lower()
