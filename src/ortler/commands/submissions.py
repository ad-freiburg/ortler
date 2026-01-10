"""
Submissions command for showing submission information.
"""

import json
from pathlib import Path

from argparse import ArgumentParser, Namespace

from ..command import Command
from ..log import log


class SubmissionsCommand(Command):
    """
    Show summary of cached submissions.
    """

    @property
    def name(self) -> str:
        return "submissions"

    @property
    def help(self) -> str:
        return "Show summary of cached submissions"

    def add_arguments(self, parser: ArgumentParser) -> None:
        """
        Add submissions command arguments.
        """
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Print detailed information about each submission",
        )

    def _get_cache_dir(self, cache_dir: str) -> Path:
        """Get the submissions cache directory."""
        return Path(cache_dir) / "submissions"

    def execute(self, args: Namespace) -> None:
        """
        Show summary of cached submissions.
        Use 'ortler dump' to output full data as RDF.
        """
        # Load submissions from cache
        submissions_cache_dir = self._get_cache_dir(args.cache_dir)
        if not submissions_cache_dir.exists():
            log.error("No cached submissions. Run 'ortler update' first.")
            return

        submissions_data = []
        for cache_file in submissions_cache_dir.glob("*.json"):
            try:
                with open(cache_file) as f:
                    submissions_data.append(json.load(f))
            except Exception:
                pass

        if not submissions_data:
            log.error("No cached submissions. Run 'ortler update' first.")
            return

        # Get the set of distinct author IDs
        all_author_ids = set()
        for submission in submissions_data:
            author_ids = (
                submission.get("content", {}).get("authorids", {}).get("value", [])
            )
            for author_id in author_ids:
                all_author_ids.add(author_id)

        # Count submissions with PDFs
        with_pdf = sum(1 for s in submissions_data if "pdf" in s.get("content", {}))

        log.info(f"Cached submissions: {len(submissions_data)}")
        log.info(f"  With PDF: {with_pdf}")
        log.info(f"  Distinct authors: {len(all_author_ids)}")

        # Check for AI reviews
        reviews_dir = Path(args.cache_dir) / "reviews"
        if reviews_dir.exists():
            review_count = len(list(reviews_dir.glob("*.json")))
            log.info(f"  AI reviews: {review_count}")

        # Print detailed info
        if args.verbose:
            for i, submission in enumerate(submissions_data, 1):
                content = submission.get("content", {})
                title = content.get("title", {}).get("value", "No title")
                authors = content.get("authors", {}).get("value", "N/A")
                log.info(f"\n{i}. {title}")
                log.info(f"   ID: {submission.get('id')}")
                log.info(f"   Authors: {authors}")
