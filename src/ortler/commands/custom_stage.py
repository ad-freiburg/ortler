"""
Custom stage command for creating author tasks.
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


class CustomStageCommand(Command):
    """
    Create custom stages (author tasks) via the OpenReview API.
    """

    @property
    def name(self) -> str:
        return "custom-stage"

    @property
    def help(self) -> str:
        return "Create custom stages (author tasks) via OpenReview API"

    def add_arguments(self, parser: ArgumentParser) -> None:
        """
        Add custom-stage command arguments.
        """
        parser.add_argument(
            "--deploy",
            metavar="JSON_FILE",
            help="Deploy a custom stage from a JSON configuration file (creates or updates)",
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

    def _map_invitees(self, invitees: list[str]) -> list:
        """Map invitee strings to CustomStage.Participants enum values."""
        mapping = {
            "authors": openreview.stages.CustomStage.Participants.AUTHORS,
            "reviewers": openreview.stages.CustomStage.Participants.REVIEWERS,
            "reviewers_assigned": openreview.stages.CustomStage.Participants.REVIEWERS_ASSIGNED,
            "reviewers_submitted": openreview.stages.CustomStage.Participants.REVIEWERS_SUBMITTED,
            "area_chairs": openreview.stages.CustomStage.Participants.AREA_CHAIRS,
            "area_chairs_assigned": openreview.stages.CustomStage.Participants.AREA_CHAIRS_ASSIGNED,
            "senior_area_chairs": openreview.stages.CustomStage.Participants.SENIOR_AREA_CHAIRS,
            "senior_area_chairs_assigned": openreview.stages.CustomStage.Participants.SENIOR_AREA_CHAIRS_ASSIGNED,
            "program_chairs": openreview.stages.CustomStage.Participants.PROGRAM_CHAIRS,
            "everyone": openreview.stages.CustomStage.Participants.EVERYONE,
        }
        result = []
        for invitee in invitees:
            key = invitee.lower()
            if key in mapping:
                result.append(mapping[key])
            else:
                log.warning(f"Unknown invitee type: {invitee}")
        return result

    def _map_reply_to(self, reply_to: str) -> openreview.stages.CustomStage.ReplyTo:
        """Map reply_to string to CustomStage.ReplyTo enum value."""
        mapping = {
            "forum": openreview.stages.CustomStage.ReplyTo.FORUM,
            "withforum": openreview.stages.CustomStage.ReplyTo.WITHFORUM,
            "reviews": openreview.stages.CustomStage.ReplyTo.REVIEWS,
            "metareviews": openreview.stages.CustomStage.ReplyTo.METAREVIEWS,
            "rebuttals": openreview.stages.CustomStage.ReplyTo.REBUTTALS,
        }
        key = reply_to.lower()
        if key in mapping:
            return mapping[key]
        log.error(f"Unknown reply_to type: {reply_to}")
        return openreview.stages.CustomStage.ReplyTo.FORUM

    def _map_source(self, source: str) -> openreview.stages.CustomStage.Source:
        """Map source string to CustomStage.Source enum value."""
        mapping = {
            "all_submissions": openreview.stages.CustomStage.Source.ALL_SUBMISSIONS,
            "accepted_submissions": openreview.stages.CustomStage.Source.ACCEPTED_SUBMISSIONS,
            "public_submissions": openreview.stages.CustomStage.Source.PUBLIC_SUBMISSIONS,
            "flagged_submissions": openreview.stages.CustomStage.Source.FLAGGED_SUBMISSIONS,
        }
        key = source.lower()
        if key in mapping:
            return mapping[key]
        log.error(f"Unknown source type: {source}")
        return openreview.stages.CustomStage.Source.ALL_SUBMISSIONS

    def execute(self, args: Namespace) -> None:
        """
        Execute the custom-stage command.
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

            exp_date = due_date + timedelta(days=1)

        # Get venue ID
        venue_id = os.environ.get("OPENREVIEW_VENUE_ID")
        if not venue_id:
            log.error("OPENREVIEW_VENUE_ID not set")
            return

        # Build CustomStage parameters from config
        stage_name = config.get("name", "Custom_Stage")
        reply_to = self._map_reply_to(config.get("reply_to", "forum"))
        source = self._map_source(config.get("source", "all_submissions"))
        invitees = self._map_invitees(config.get("invitees", ["authors"]))
        readers = self._map_invitees(config.get("readers", []))
        content = config.get("content", {})

        # Optional parameters
        multi_reply = config.get("multi_reply", False)
        notify_readers = config.get("notify_readers", False)
        email_pcs = config.get("email_pcs", False)
        email_sacs = config.get("email_sacs", False)
        allow_de_anonymization = config.get("allow_de_anonymization", False)

        # Log configuration
        log.info(f"Creating custom stage: {stage_name}")
        if config.get("description"):
            log.info(f"  Description: {config['description']}")
        log.info(f"  Venue: {venue_id}")
        log.info(f"  Reply to: {config.get('reply_to', 'forum')}")
        log.info(f"  Source: {config.get('source', 'all_submissions')}")
        log.info(f"  Invitees: {config.get('invitees', ['authors'])}")
        log.info(f"  Readers: {config.get('readers', ['default'])}")
        log.info(f"  Start date: {start_date.strftime('%Y-%m-%d')}")
        log.info(f"  Due date: {due_date.strftime('%Y-%m-%d')}")
        log.info(f"  Expiration date: {exp_date.strftime('%Y-%m-%d')}")
        log.info(f"  Multi-reply: {multi_reply}")
        log.info(f"  Notify readers: {notify_readers}")
        log.info(f"  Email PCs: {email_pcs}")
        log.info(f"  Email SACs: {email_sacs}")
        log.info(f"  Allow de-anonymization: {allow_de_anonymization}")
        log.info(f"  Content fields: {list(content.keys())}")

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

        # Create the custom stage
        venue.custom_stage = openreview.stages.CustomStage(
            name=stage_name,
            reply_to=reply_to,
            source=source,
            start_date=start_date,
            due_date=due_date,
            exp_date=exp_date,
            invitees=invitees,
            readers=readers,
            content=content,
            multi_reply=multi_reply,
            notify_readers=notify_readers,
            email_pcs=email_pcs,
            email_sacs=email_sacs,
            allow_de_anonymization=allow_de_anonymization,
        )

        # Check if invitation already exists
        invitation_id = f"{venue_id}/-/{stage_name}"
        try:
            client.get_invitation(invitation_id)
            log.info(f"Updating existing invitation: {invitation_id}")
        except openreview.OpenReviewException:
            log.info(f"Creating new invitation: {invitation_id}")

        try:
            # Suppress the "Can not retrieve invitation" warning from openreview
            import logging

            openreview_logger = logging.getLogger("openreview")
            original_level = openreview_logger.level
            openreview_logger.setLevel(logging.CRITICAL)
            try:
                venue.create_custom_stage()
            finally:
                openreview_logger.setLevel(original_level)
            log.info(f"Successfully created custom stage: {stage_name}")
        except openreview.OpenReviewException as e:
            log.error(f"Failed to create custom stage: {e}")
