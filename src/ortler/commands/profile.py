"""
Profile command for retrieving complete profile information for a user.
"""

import json
import sys
from argparse import ArgumentParser, Namespace

from ..command import Command
from ..profile import ProfileWithPapers
from ..log import log


class ProfileCommand(Command):
    """
    Get complete profile information for a given user name.
    """

    @property
    def name(self) -> str:
        return "profile"

    @property
    def help(self) -> str:
        return "Get complete profile information for a given user name"

    def add_arguments(self, parser: ArgumentParser) -> None:
        """
        Add profile command arguments.
        """
        parser.add_argument(
            "profile_id",
            help="Username (e.g., ~John_Doe1) or email address to get profile for",
        )
        parser.add_argument(
            "--output",
            help="Output file path (default: stdout)",
        )
        parser.add_argument(
            "--as-rdf",
            action="store_true",
            help="Output profile as RDF triples instead of JSON",
        )

    def execute(self, args: Namespace) -> None:
        """
        Get complete profile information for the specified user.
        """
        # Client is already initialized in main.py
        try:
            profile_with_papers = ProfileWithPapers(cache_dir=args.cache_dir)
            profile_with_papers.get_profile(args.profile_id)

            if args.as_rdf:
                result_content = profile_with_papers.asRdf()
            else:
                result_content = json.dumps(profile_with_papers.asJson(), indent=2)

            # Output to file or stdout
            if args.output:
                with open(args.output, "w") as f:
                    f.write(result_content)
                log.info(f"Profile information saved to {args.output}")
            else:
                print(result_content)

        except Exception as e:
            log.error(f"Error retrieving profile for '{args.profile_id}': {e}")
            sys.exit(1)
