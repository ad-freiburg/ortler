"""
Invitations command for listing venue invitations.
"""

from argparse import ArgumentParser, Namespace

from ..command import Command
from ..utils import get_client
from ..log import log


class InvitationsCommand(Command):
    """
    List all invitations for the venue.
    """

    @property
    def name(self) -> str:
        return "invitations"

    @property
    def help(self) -> str:
        return "List all invitations for the venue"

    def add_arguments(self, parser: ArgumentParser) -> None:
        """
        Add invitations command arguments.
        """
        # No additional arguments for this command
        pass

    def execute(self, args: Namespace) -> None:
        """
        List all invitations for the venue.
        """
        # Get the singleton client (initialized in main.py)
        client = get_client()

        log.info(f"Fetching invitations for venue: {args.venue_id}...")
        invitations = client.get_all_invitations(prefix=args.venue_id)
        log.info(f"Found {len(invitations)} invitations:")
        for inv in invitations:
            print(f"  - {inv.id}")
