#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK

"""
A command-line tool for managing OpenReview venues.

Author: Hannah Bast <bast@cs.uni-freiburg.de>
"""

import argparse
import importlib
import os
import pkgutil
from pathlib import Path

import argcomplete
from dotenv import load_dotenv

from . import commands
from .command import Command

# Load environment variables from .env file if it exists
load_dotenv(interpolate=False)


def discover_commands() -> list[Command]:
    """
    Automatically find all commands in the `commands` package. Returns a list
    of Command instances.
    """
    command_instances: list[Command] = []
    commands_path = Path(commands.__file__).parent

    # Find all subclasses of `Command` in the `commands` package.
    for _, module_name, _ in pkgutil.iter_modules([str(commands_path)]):
        module = importlib.import_module(f".commands.{module_name}", package="ortler")
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, Command)
                and attr is not Command
            ):
                command_instances.append(attr())
    return command_instances


def main() -> None:
    parser = argparse.ArgumentParser(
        description="A command-line tool for managing OpenReview venues"
    )

    # Global command-independent arguments.
    parser.add_argument(
        "--api-url",
        default=os.environ.get("OPENREVIEW_API_URL"),
        help="OpenReview API URL (default: $OPENREVIEW_API_URL)",
    )
    parser.add_argument(
        "--username",
        default=os.environ.get("OPENREVIEW_USERNAME"),
        help="OpenReview username (default: $OPENREVIEW_USERNAME)",
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("OPENREVIEW_PASSWORD"),
        help="OpenReview password (default: $OPENREVIEW_PASSWORD)",
    )
    parser.add_argument(
        "--venue-id",
        default=os.environ.get("OPENREVIEW_VENUE_ID"),
        help="Venue ID (default: $OPENREVIEW_VENUE_ID)",
    )
    parser.add_argument(
        "--impersonate",
        default=os.environ.get("OPENREVIEW_IMPERSONATE_GROUP"),
        help="Group ID to impersonate (for venue organizers) (default: $OPENREVIEW_IMPERSONATE_GROUP)",
    )
    parser.add_argument(
        "--cache-dir",
        default=os.environ.get("CACHE_DIR", "cache"),
        help="Cache directory (default: $CACHE_DIR or 'cache')",
    )

    # Add subparser for each command (the arguments are in the respective
    # command class).
    subparsers = parser.add_subparsers(dest="command_name", help="Available commands")
    discovered_commands = discover_commands()
    for command in discovered_commands:
        command_parser = subparsers.add_parser(
            command.name, help=command.help, description=command.help
        )
        command.add_arguments(command_parser)
        command_parser.set_defaults(command=command)

    # Parse arguments with argcomplete support.
    argcomplete.autocomplete(parser, always_complete_options="long")
    args = parser.parse_args()

    if hasattr(args, "command"):
        # Set client parameters from command-line arguments (if provided)
        # The client will be created lazily when first needed
        from .client import set_client_params

        set_client_params(args.api_url, args.username, args.password, args.impersonate)

        args.command.execute(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
