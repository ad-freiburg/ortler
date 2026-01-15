"""
Mail command for sending emails via OpenReview.
"""

import os
import random
import re
from argparse import ArgumentParser, Namespace
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from ..command import Command
from ..client import get_client
from ..log import log
from ..qlever import query_results_by_recipient
from ..utils import format_author_name


class MailCommand(Command):
    """
    Send emails from a file with headers and body via OpenReview.
    """

    separator = "\n\n----------"

    @property
    def name(self) -> str:
        return "mail"

    @property
    def help(self) -> str:
        return "Send emails via OpenReview from a file with headers and body"

    def add_arguments(self, parser: ArgumentParser) -> None:
        """
        Add mail command arguments.
        """
        parser.add_argument(
            "file",
            help="File containing email headers and body (blank line separates headers from body)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and show the email without sending",
        )
        parser.add_argument(
            "--test-run",
            metavar="PROFILE",
            help="Send all emails to PROFILE instead of actual recipients (for testing)",
        )
        parser.add_argument(
            "--recipients-from-sparql-query",
            metavar="URL_OR_HASH",
            help="Replace To: recipients with results from a SPARQL query (URL or short hash)",
        )
        parser.add_argument(
            "--random-sample",
            type=int,
            metavar="N",
            help="Randomly select N recipients (useful for testing)",
        )

    def _get_name(self, profile) -> str:
        """
        Get the name from a profile: first name if available, otherwise full name,
        otherwise extract from profile ID.
        """
        content = profile.content if hasattr(profile, "content") else {}
        names = content.get("names", [])
        if names:
            first_name = names[0].get("first")
            if first_name:
                return first_name
            fullname = names[0].get("fullname", "")
            if fullname:
                return fullname
        # Fallback: extract name from profile ID (e.g., ~K__J__Amala1 -> K J Amala)
        if hasattr(profile, "id") and profile.id:
            return format_author_name(profile.id)
        return ""

    def _parse_from_header(self, from_header: str) -> dict:
        """
        Parse From header into sender dict with fromName and fromEmail.
        Handles formats like: "Name <email>" or just "email"
        """
        match = re.match(r"(.+?)\s*<(.+?)>", from_header)
        if match:
            return {
                "fromName": match.group(1).strip(),
                "fromEmail": match.group(2).strip(),
            }
        return {"fromName": "", "fromEmail": from_header.strip()}

    def _personalize_body(
        self,
        body: str,
        placeholders: set[str],
        recipient: str,
        query_data_by_recipient: dict[str, dict],
        client,
    ) -> str:
        """
        Substitute placeholders in the body for a specific recipient.
        """
        personalized_body = body

        # Substitute {{name}} from profile if present
        if "name" in placeholders:
            try:
                profile = client.get_profile(recipient)
                name = self._get_name(profile)
            except Exception:
                # Profile not found - extract name from recipient ID
                name = format_author_name(recipient)
            personalized_body = personalized_body.replace(
                "{{name}}", name if name else ""
            )

        # Substitute query variables if available
        if recipient in query_data_by_recipient:
            row_data = query_data_by_recipient[recipient]
            for var, value in row_data.items():
                personalized_body = personalized_body.replace(
                    "{{" + var + "}}", value if value else ""
                )

        return personalized_body

    def _generate_mbox(
        self,
        recipients: list[str],
        headers: dict,
        body: str,
        placeholders: set[str],
        query_data_by_recipient: dict[str, dict],
        client,
    ) -> str:
        """
        Generate mbox content for all emails that will be sent.
        """
        mbox_lines = []
        timestamp = datetime.now().strftime("%a %b %d %H:%M:%S %Y")
        from_email = self._parse_from_header(headers["From"])["fromEmail"]

        for recipient in recipients:
            # Personalize body if needed
            if placeholders:
                email_body = self._personalize_body(
                    body, placeholders, recipient, query_data_by_recipient, client
                )
            else:
                email_body = body

            # MBOX format: "From sender date" line
            mbox_lines.append(f"From {from_email} {timestamp}")
            mbox_lines.append(f"From: {headers['From']}")
            mbox_lines.append(f"To: {recipient}")
            mbox_lines.append(f"Subject: {headers['Subject']}")
            mbox_lines.append("")  # Blank line between headers and body
            mbox_lines.append(email_body + self.separator)
            mbox_lines.append("")  # Blank line between messages

        return "\n".join(mbox_lines)

    def execute(self, args: Namespace) -> None:
        """
        Send email from a file with headers and body via OpenReview.
        """
        client = get_client()

        # Read the file
        with open(args.file, "r") as f:
            content = f.read()

        # Extract and preserve comment lines, check for # Query: comment
        query_from_file = None
        content_lines = content.split("\n")
        comment_lines = []
        while content_lines and content_lines[0].strip().startswith("#"):
            line = content_lines.pop(0)
            comment_lines.append(line)
            if line.strip().startswith("# Query:"):
                query_from_file = line.strip()[8:].strip()
        content = "\n".join(content_lines)

        # Use query from file if no command-line argument was given
        query_hash_or_url = args.recipients_from_sparql_query or query_from_file

        # Replace To: recipients from SPARQL query if requested
        query_data_by_recipient: dict[str, dict] = {}
        if query_hash_or_url:
            if query_from_file and not args.recipients_from_sparql_query:
                log.info(f"Using query from file: {query_from_file}")

            if not content.startswith("To:"):
                log.error(
                    "Mail file must start with 'To:' (after any # comments) "
                    "when using a SPARQL query for recipients"
                )
                return
            query_recipients, query_data_by_recipient = query_results_by_recipient(
                query_hash_or_url
            )
            new_to_line = "To: " + ", ".join(query_recipients)
            # Replace the first line (To: ...) with the new recipients
            content = new_to_line + content[content.index("\n") :]

        # Split headers and body (separated by blank line)
        parts = content.split("\n\n", 1)
        if len(parts) < 2:
            log.error(
                "Invalid email format: no blank line separating headers from body"
            )
            return

        headers_section, body = parts

        # Clean up body: remove trailing empty lines
        body = body.rstrip()

        # Parse headers
        headers = {}
        for line in headers_section.strip().split("\n"):
            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.strip()] = value.strip()

        # Validate required headers
        if "To" not in headers:
            log.error("Missing required header: To")
            return
        if "Subject" not in headers:
            log.error("Missing required header: Subject")
            return

        # Get From header from file or environment
        if "From" not in headers:
            from_env = os.environ.get("MAIL_FROM")
            if from_env:
                headers["From"] = from_env
            else:
                log.error("Missing required header: From (set in file or $MAIL_FROM)")
                return

        # Parse sender - only use if email ends with @openreview.net
        parsed_sender = self._parse_from_header(headers["From"])
        if parsed_sender["fromEmail"].endswith("@openreview.net"):
            sender = parsed_sender
        else:
            sender = None  # Let OpenReview use default

        # Parse recipients (To and Cc) - extract email/profile ID from "Name <email>" format
        original_recipients = []
        for r in headers.get("To", "").split(","):
            r = r.strip()
            parsed = self._parse_from_header(r)
            original_recipients.append(parsed["fromEmail"] if "<" in r else r)

        # Apply random sampling if specified
        sampled = False
        if args.random_sample and args.random_sample < len(original_recipients):
            original_recipients = random.sample(original_recipients, args.random_sample)
            sampled = True

        # Write updated content back to file (with sampled recipients if applicable)
        if query_hash_or_url:
            new_to_line = "To: " + ", ".join(original_recipients)
            content = new_to_line + content[content.index("\n") :]
            with open(args.file, "w") as f:
                if comment_lines:
                    f.write("\n".join(comment_lines) + "\n")
                f.write(content)

        # For test-run, redirect all emails to the test profile
        if args.test_run:
            recipients = [args.test_run] * len(original_recipients)
        else:
            recipients = original_recipients

        cc_recipients = []
        if "Cc" in headers:
            for r in headers["Cc"].split(","):
                r = r.strip()
                parsed = self._parse_from_header(r)
                cc_recipients.append(parsed["fromEmail"] if "<" in r else r)

        # Get Reply-To (with or without hyphen), keep full format with name
        reply_to_header = headers.get("Reply-To") or headers.get("Reply To")
        if reply_to_header:
            reply_to = reply_to_header.strip()
        else:
            reply_to = headers["From"]

        # Check if personalization is needed
        # Find all {{variable}} placeholders in the body
        placeholder_pattern = re.compile(r"\{\{(\w+)\}\}")
        placeholders = set(placeholder_pattern.findall(body))
        needs_personalization = bool(placeholders)

        # Show what we're sending
        log.info("")
        log.info(f"From: {headers.get('From')}")
        to_list = ", ".join(original_recipients)
        if args.test_run:
            to_display = f"{args.test_run} (TEST-RUN, original: {to_list})"
        elif sampled:
            to_display = f"{to_list} (RANDOM SAMPLE of {args.random_sample})"
        else:
            to_display = to_list
        log.info(f"To: {to_display}")
        if cc_recipients:
            log.info(f"Cc: {headers.get('Cc')}")
        if reply_to != headers["From"]:
            log.info(f"Reply-To: {reply_to}")
        log.info(f"Subject: {headers.get('Subject')}")
        log.info(f"\n{body}")

        n = len(original_recipients)
        num_recipients = "one recipient" if n == 1 else f"{n} recipients"

        if args.dry_run:
            log.warning(
                f"Dry run: without --dry-run, email would be sent to {num_recipients}: "
                f"{to_display}"
            )
            return

        # Generate mbox file with all emails (templates resolved)
        mbox_content = self._generate_mbox(
            original_recipients,
            headers,
            body,
            placeholders,
            query_data_by_recipient,
            client,
        )
        mail_path = Path(args.file)
        mbox_path = mail_path.with_suffix(".mbox")
        with open(mbox_path, "w") as f:
            f.write(mbox_content)

        # Confirm before sending
        try:
            input(
                f"\nPreview with resolved templates written to {mbox_path}"
                f"\n\033[94mPress CTRL+C to abort, RETURN to send email to "
                f"{num_recipients}: {to_display}\033[0m "
            )
        except KeyboardInterrupt:
            log.warning("\nAborted")
            return

        # Build invitation ID for messaging
        invitation = f"{args.venue_id}/-/Edit"

        # Send the email(s) to To recipients
        sent_count = 0
        failed_count = 0
        if needs_personalization:
            # Send individual personalized messages
            # Use original_recipients for data lookup, recipients for actual sending
            for i, original_recipient in enumerate(original_recipients):
                send_to = recipients[i]

                personalized_body = self._personalize_body(
                    body,
                    placeholders,
                    original_recipient,
                    query_data_by_recipient,
                    client,
                )

                try:
                    client.post_message(
                        subject=headers["Subject"],
                        recipients=[send_to],
                        message=personalized_body + self.separator,
                        invitation=invitation,
                        sender=sender,
                        replyTo=reply_to,
                    )
                    sent_count += 1
                except Exception as e:
                    log.warning(f"Failed to send to {send_to}: {e}")
                    failed_count += 1
        else:
            # Send single message to all To recipients
            try:
                client.post_message(
                    subject=headers["Subject"],
                    recipients=recipients,
                    message=body + self.separator,
                    invitation=invitation,
                    sender=sender,
                    replyTo=reply_to,
                )
                sent_count = len(recipients)
            except Exception as e:
                log.error(f"Failed to send email: {e}")
                failed_count = len(recipients)

        # Report results
        def pluralize(n):
            return "one recipient" if n == 1 else f"{n} recipients"

        if failed_count == 0:
            log.info(f"Email sent successfully to {pluralize(sent_count)}")
        else:
            log.info(
                f"Email sent to {pluralize(sent_count)}, failed for {pluralize(failed_count)}"
            )

        # Send FYI to Cc recipients (skip in test-run mode)
        if cc_recipients and not args.test_run:
            fyi_subject = f"FYI: {headers['Subject']}"
            subject_encoded = quote(headers["Subject"], safe="")
            message_log_url = (
                f"https://openreview.net/messages?subject={subject_encoded}"
            )

            # Build query link if a SPARQL query was used
            query_link_line = ""
            if query_hash_or_url:
                query_link_line = (
                    f"\n\n[Click here to see the SPARQL query that was used to "
                    f"compute the list of recipients]({query_hash_or_url})"
                )

            fyi_body = (
                f"FYI, the mail below was sent to {num_recipients}: "
                f"{headers.get('To')}"
                f"{query_link_line}\n\n"
                f"[Click here to see all messages with that subject in the OpenReview message log]({message_log_url})"
                f"{self.separator}\n\n"
                f"{body}"
                f"{self.separator}"
            )

            try:
                client.post_message(
                    subject=fyi_subject,
                    recipients=cc_recipients,
                    message=fyi_body,
                    invitation=invitation,
                    sender=sender,
                )
                log.info(f"FYI sent to Cc: {headers.get('Cc')}")
            except Exception as e:
                log.error(f"Failed to send FYI to Cc: {e}")
