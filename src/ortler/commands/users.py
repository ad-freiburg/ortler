"""
Users command for listing users, profiles, and groups.
"""

from argparse import ArgumentParser, Namespace

from ..command import Command
from ..utils import get_client
from ..log import log


class UsersCommand(Command):
    """
    List users/profiles and groups for the venue.
    """

    @property
    def name(self) -> str:
        return "users"

    @property
    def help(self) -> str:
        return "List users, profiles, and groups"

    def add_arguments(self, parser: ArgumentParser) -> None:
        """
        Add users command arguments.
        """
        parser.add_argument(
            "--search",
            help="Search for profiles by term (in username or email)",
        )
        parser.add_argument(
            "--groups",
            action="store_true",
            help="List all groups for the venue",
        )
        parser.add_argument(
            "-v",
            "--verbose",
            action="store_true",
            help="Show detailed information",
        )

    def execute(self, args: Namespace) -> None:
        """
        List users/profiles and groups for the venue.
        """
        # Get the singleton client (initialized in main.py)
        client = get_client()

        if args.search:
            # Search for profiles
            log.info(f"Searching profiles with term: {args.search}...")
            profiles = client.search_profiles(term=args.search)

            log.info(f"Found {len(profiles)} profiles:")
            for profile in profiles:
                preferred_name = (
                    profile.get_preferred_name()
                    if hasattr(profile, "get_preferred_name")
                    else "N/A"
                )
                preferred_email = (
                    profile.get_preferred_email()
                    if hasattr(profile, "get_preferred_email")
                    else "N/A"
                )
                print(f"  - {profile.id}")
                print(f"    Name: {preferred_name}")
                print(f"    Email: {preferred_email}")

        elif args.groups:
            # List all groups for venue
            log.info(f"Fetching groups for venue: {args.venue_id}...")
            groups = client.get_all_groups(prefix=args.venue_id)

            log.info(f"Found {len(groups)} groups:")
            for group in groups:
                member_count = len(group.members) if group.members else 0
                print(f"  - {group.id} ({member_count} members)")

                if args.verbose and group.members:
                    for member in group.members[:10]:  # Show first 10
                        print(f"      {member}")
                    if member_count > 10:
                        print(f"      ... and {member_count - 10} more")

        else:
            # Get all users across all venue groups
            log.info(f"Fetching all users for venue: {args.venue_id}...")
            groups = client.get_all_groups(prefix=args.venue_id)

            # Collect all unique user IDs (not group IDs)
            all_users = set()
            for group in groups:
                if group.members:
                    for member in group.members:
                        # Skip if it's a group ID (contains /)
                        if "/" not in member:
                            all_users.add(member)

            all_users_list = sorted(all_users)
            log.info(f"Found {len(all_users_list)} unique users:")

            for user in all_users_list:
                print(f"  - {user}")

                # Optionally get profile details
                if args.verbose:
                    try:
                        # Check if it's a profile ID or email
                        if user.startswith("~") or "@" in user:
                            profile = client.get_profile(user)
                            name = (
                                profile.get_preferred_name()
                                if hasattr(profile, "get_preferred_name")
                                else "N/A"
                            )
                            email = (
                                profile.get_preferred_email()
                                if hasattr(profile, "get_preferred_email")
                                else "N/A"
                            )
                            print(f"    Name: {name}, Email: {email}")
                    except Exception as e:
                        if args.verbose:
                            log.error(f"Could not fetch profile for {user}: {e}")
