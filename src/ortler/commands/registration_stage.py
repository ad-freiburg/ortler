"""
Registration stage command for creating per-person tasks.
"""

import json
import os
from argparse import ArgumentParser, Namespace
from datetime import datetime
from pathlib import Path

import openreview

from ..client import get_client_v1
from ..command import Command
from ..log import log


class RegistrationStageCommand(Command):
    """
    Create registration stages (per-person tasks) via the OpenReview API.
    """

    @property
    def name(self) -> str:
        return "registration-stage"

    @property
    def help(self) -> str:
        return "Create registration stages (per-person tasks) via OpenReview API"

    def add_arguments(self, parser: ArgumentParser) -> None:
        """
        Add registration-stage command arguments.
        """
        parser.add_argument(
            "--deploy",
            metavar="JSON_FILE",
            help="Deploy a registration stage from a JSON configuration file (creates or updates)",
        )
        parser.add_argument(
            "--start-date",
            help="Start date (YYYY-MM-DD), overrides JSON config",
        )
        parser.add_argument(
            "--due-date",
            help="Due date (YYYY-MM-DD), overrides JSON config",
        )
        parser.add_argument(
            "--exp-date",
            help="Expiration date (YYYY-MM-DD), overrides JSON config",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be done without actually creating the stage",
        )

    def _parse_date(self, date_str: str) -> datetime:
        """Parse a date string in YYYY-MM-DD format."""
        return datetime.strptime(date_str, "%Y-%m-%d")

    def _map_committee(self, committee: str, venue_id: str) -> str:
        """Map committee string to full committee ID."""
        mapping = {
            "authors": f"{venue_id}/Authors",
            "reviewers": f"{venue_id}/Reviewers",
            "area_chairs": f"{venue_id}/Area_Chairs",
            "senior_area_chairs": f"{venue_id}/Senior_Area_Chairs",
            "program_chairs": f"{venue_id}/Program_Chairs",
        }
        key = committee.lower()
        if key in mapping:
            return mapping[key]
        # Assume it's already a full ID
        return committee

    def execute(self, args: Namespace) -> None:
        """
        Execute the registration-stage command.
        """
        if not args.deploy:
            log.error("Please specify --deploy JSON_FILE")
            return

        # Load JSON configuration
        config_path = Path(args.deploy)
        if not config_path.exists():
            log.error(f"Configuration file not found: {config_path}")
            return

        with open(config_path) as f:
            config = json.load(f)

        # Parse dates: command-line overrides JSON, JSON overrides defaults
        if args.start_date:
            start_date = self._parse_date(args.start_date)
        elif config.get("start_date"):
            start_date = self._parse_date(config["start_date"])
        else:
            start_date = datetime.now()

        if args.due_date:
            due_date = self._parse_date(args.due_date)
        elif config.get("due_date"):
            due_date = self._parse_date(config["due_date"])
        else:
            log.error("Due date is required (--due-date or in JSON config)")
            return

        if args.exp_date:
            exp_date = self._parse_date(args.exp_date)
        elif config.get("exp_date"):
            exp_date = self._parse_date(config["exp_date"])
        else:
            from datetime import timedelta

            exp_date = due_date + timedelta(days=7)

        # Get venue ID
        venue_id = os.environ.get("OPENREVIEW_VENUE_ID")
        if not venue_id:
            log.error("OPENREVIEW_VENUE_ID not set")
            return

        # Build RegistrationStage parameters from config
        stage_name = config.get("name", "Registration")
        committee = config.get("committee", "authors")
        committee_id = self._map_committee(committee, venue_id)
        content = config.get("content", {})
        instructions = config.get("instructions")
        title = config.get("title")
        remove_fields = config.get("remove_fields", [])

        # Log configuration
        log.info(f"Creating registration stage: {stage_name}")
        if config.get("description"):
            log.info(f"  Description: {config['description']}")
        log.info(f"  Venue: {venue_id}")
        log.info(f"  Committee: {committee} ({committee_id})")
        log.info(f"  Start date: {start_date.strftime('%Y-%m-%d')}")
        log.info(f"  Due date: {due_date.strftime('%Y-%m-%d')}")
        log.info(f"  Expiration date: {exp_date.strftime('%Y-%m-%d')}")
        log.info(f"  Content fields: {list(content.keys())}")
        if instructions:
            log.info(f"  Instructions: {instructions[:50]}...")
        if title:
            log.info(f"  Title: {title}")

        if args.dry_run:
            log.info("Dry run - not creating stage")
            return

        # Get request form ID from environment
        request_form_id = os.environ.get("OPENREVIEW_REQUEST_FORM_ID")
        if not request_form_id:
            log.error(
                "OPENREVIEW_REQUEST_FORM_ID not set. "
                "Find it in your venue's 'Full venue configuration' link in the PC console."
            )
            return

        # Get client
        client = get_client_v1()

        # Get venue object using the request form ID
        log.info(f"Using request form ID: {request_form_id}")
        try:
            venue = openreview.helpers.get_conference(client, request_form_id)
        except Exception as e:
            log.error(f"Failed to get venue: {e}")
            return

        # Create the registration stage (use plural attribute)
        stage = openreview.stages.RegistrationStage(
            committee_id=committee_id,
            name=stage_name,
            start_date=start_date,
            due_date=due_date,
            expdate=exp_date,
            additional_fields=content,
            remove_fields=remove_fields,
            instructions=instructions or f"Please complete this {stage_name} form.",
            title=title or stage_name,
        )
        venue.registration_stages = [stage]

        # Check if invitation already exists
        invitation_id = f"{committee_id}/-/{stage_name}"
        try:
            client.get_invitation(invitation_id)
            log.info(f"Updating existing invitation: {invitation_id}")
        except openreview.OpenReviewException:
            log.info(f"Creating new invitation: {invitation_id}")

        try:
            # Suppress warnings from openreview library
            import logging

            openreview_logger = logging.getLogger("openreview")
            original_level = openreview_logger.level
            openreview_logger.setLevel(logging.CRITICAL)
            try:
                venue.create_registration_stages()
            finally:
                openreview_logger.setLevel(original_level)
            log.info(f"Successfully created registration stage: {stage_name}")
        except openreview.OpenReviewException as e:
            log.error(f"Failed to create registration stage: {e}")
