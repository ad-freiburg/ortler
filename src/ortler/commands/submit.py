"""
Submit command for submitting papers to OpenReview.
"""

import json
import os
import sys
from argparse import ArgumentParser, Namespace

import numpy as np
import openreview

from ..command import Command
from ..log import log
from ..utils import (
    create_dummy_pdf,
    generate_random_paper,
    get_client,
    get_random_authors,
)


class SubmitCommand(Command):
    """
    Submit papers to OpenReview.
    """

    @property
    def name(self) -> str:
        return "submit"

    @property
    def help(self) -> str:
        return "Submit papers to OpenReview (requires matching PDF and JSON files)"

    def add_arguments(self, parser: ArgumentParser) -> None:
        """
        Add submit command arguments.
        """
        parser.add_argument(
            "pdf_files",
            nargs="*",
            help="PDF files to submit (will look for matching .json files)",
        )
        parser.add_argument(
            "--authors",
            help="Comma-separated list of author names (e.g., 'Alice Smith,Bob Jones')",
        )
        parser.add_argument(
            "--authorids",
            help="Comma-separated list of author IDs/emails (e.g., 'alice@example.com,bob@example.com')",
        )
        parser.add_argument(
            "--keywords",
            help="Comma-separated list of keywords (optional)",
        )
        parser.add_argument(
            "--random",
            type=int,
            metavar="K",
            help="Generate K random paper submissions (for testing)",
        )
        parser.add_argument(
            "--only-show",
            action="store_true",
            help="Only show paper metadata without actually submitting to OpenReview",
        )
        parser.add_argument(
            "--mean-num-authors",
            type=float,
            default=3.0,
            help="Mean number of authors for Poisson distribution (default: 3.0)",
        )
        parser.add_argument(
            "--paper-model",
            default="gpt-4o-mini",
            help="OpenAI model for paper generation (default: 'gpt-4o-mini'). Try 'gpt-5-mini' if available. Requires OPENAI_API_KEY env var.",
        )
        parser.add_argument(
            "--paper-prompt",
            default=(
                "Generate a title, abstract, and author names for a creative and diverse research paper. "
                "Be creative and explore diverse topics within computer science. "
                "Vary your approach and be original - avoid repetitive patterns.\n\n"
                "Respond with JSON in this exact format:\n"
                "{\n"
                '  "title": "paper title",\n'
                '  "abstract": "exactly three sentences describing motivation, methods, and key findings",\n'
                '  "authors": ["Firstname Lastname", "Firstname Middlename Lastname", ...]\n'
                "}"
            ),
            help="Prompt for generating paper title, abstract, and author names",
        )

    def execute(self, args: Namespace) -> None:
        """
        Submit papers to OpenReview.
        """
        # Get the singleton client (initialized in main.py)
        client = get_client()

        # Construct the submission invitation ID
        submission_invitation = f"{args.venue_id}/-/Submission"

        # Handle random paper generation
        if args.random:
            self._submit_random_papers(args, client, submission_invitation)
            return

        # Original submission logic
        self._submit_pdf_files(args, client, submission_invitation)

    def _submit_random_papers(
        self,
        args: Namespace,
        client: openreview.api.OpenReviewClient,
        submission_invitation: str,
    ) -> None:
        """
        Generate and submit random papers.
        """
        log.info(f"Generating {args.random} random paper submissions...")
        log.info(f"Mean number of authors (Poisson λ): {args.mean_num_authors}")
        log.info(f"Using OpenAI model: {args.paper_model}")

        # ANSI codes for bold
        BOLD = "\033[1m"
        RESET = "\033[0m"

        successful = 0
        failed = 0

        for i in range(args.random):
            # Generate number of authors from Poisson distribution
            num_authors = max(1, np.random.poisson(args.mean_num_authors))

            log.info(f"{BOLD}Paper {i + 1}/{args.random}{RESET}")
            log.info(f"Number of authors: {num_authors}")

            # Get random author IDs
            log.info(f"Finding {num_authors} random authors...")
            _, authorids = get_random_authors(client, num_authors)

            # Generate random title, abstract, and author names
            log.info(
                f"Generating title, abstract, and author names using {args.paper_model}..."
            )
            title, abstract, authors = generate_random_paper(
                args.paper_model, args.paper_prompt, authorids
            )

            # Print metadata
            log.info(f"Title: {title}")
            log.info(f"Authors: {', '.join(authors)}")
            log.info(f"Author IDs: {', '.join(authorids)}")
            log.info(f"Abstract: {abstract}")

            # Submit or just show
            if not args.only_show:
                pdf_path = None
                try:
                    log.info("Submitting to OpenReview...")

                    # Get the logged-in user's profile ID for signatures
                    user_profile = client.get_profile(args.username)
                    user_signature = user_profile.id

                    # Ensure we have at least one keyword
                    keywords = (
                        args.keywords.split(",")
                        if args.keywords
                        else ["Information Retrieval"]
                    )

                    # Create dummy PDF
                    log.info("Creating PDF...")
                    pdf_path = create_dummy_pdf(title, authors, abstract)

                    # Upload PDF
                    log.info("Uploading PDF...")
                    pdf_url = client.put_attachment(
                        pdf_path, submission_invitation, "pdf"
                    )

                    # Create submission note
                    note = openreview.api.Note(
                        content={
                            "title": {"value": title},
                            "abstract": {"value": abstract},
                            "authors": {"value": authors},
                            "authorids": {"value": authorids},
                            "keywords": {"value": keywords},
                            "pdf": {"value": pdf_url},
                        }
                    )

                    # Submit the note
                    submission = client.post_note_edit(
                        invitation=submission_invitation,
                        signatures=[user_signature],
                        note=note,
                    )

                    submission_id = submission["note"]["id"]
                    log.info(f"Submitted successfully: {submission_id}")
                    successful += 1

                except Exception as e:
                    log.error(f"Submission failed: {e}")
                    failed += 1
                finally:
                    # Clean up temporary PDF
                    if pdf_path and os.path.exists(pdf_path):
                        os.unlink(pdf_path)

        # Print summary if actually submitting
        if not args.only_show and args.random > 0:
            log.info(f"{BOLD}Summary{RESET}")
            log.info(f"Successful: {successful}")
            log.info(f"Failed: {failed}")
            log.info(f"Total: {args.random}")

    def _submit_pdf_files(
        self,
        args: Namespace,
        client: openreview.api.OpenReviewClient,
        submission_invitation: str,
    ) -> None:
        """
        Submit papers from PDF files with corresponding JSON metadata.
        """
        # Get author information
        if not args.authors or not args.authorids:
            log.error("--authors and --authorids are required for submission")
            log.error(
                "Example: --authors 'Alice Smith,Bob Jones' --authorids 'alice@example.com,bob@example.com'"
            )
            sys.exit(1)

        authors = [a.strip() for a in args.authors.split(",")]
        authorids = [a.strip() for a in args.authorids.split(",")]

        if len(authors) != len(authorids):
            log.error(
                f"Number of authors ({len(authors)}) must match number of authorids ({len(authorids)})"
            )
            sys.exit(1)

        # Process each PDF file
        successful = 0
        failed = 0

        for pdf_path in args.pdf_files:
            # Check if PDF exists
            if not os.path.exists(pdf_path):
                log.error(f"PDF not found: {pdf_path}")
                failed += 1
                continue

            # Look for corresponding JSON file
            base_name = os.path.splitext(pdf_path)[0]
            json_path = base_name + ".json"

            if not os.path.exists(json_path):
                log.error(f"JSON file not found for {pdf_path}: {json_path}")
                failed += 1
                continue

            # Load JSON metadata
            try:
                with open(json_path, "r") as f:
                    metadata = json.load(f)
            except json.JSONDecodeError as e:
                log.error(f"Invalid JSON in {json_path}: {e}")
                failed += 1
                continue

            # Extract title and abstract
            title = metadata.get("title", "")
            abstract = metadata.get("summary", "")

            if not title:
                log.error(f"No title found in {json_path}")
                failed += 1
                continue

            if not abstract:
                log.warning(
                    f"No summary/abstract found in {json_path}, using empty abstract"
                )

            # Extract keywords if available
            keywords = args.keywords.split(",") if args.keywords else []

            log.info(f"Submitting: {title}")
            log.info(f"  PDF: {pdf_path}")
            log.info(f"  Authors: {', '.join(authors)}")

            try:
                # Upload PDF
                log.info("  Uploading PDF...")
                pdf_url = client.put_attachment(pdf_path, submission_invitation, "pdf")

                # Create submission note
                log.info("  Creating submission...")
                note = openreview.api.Note(
                    content={
                        "title": {"value": title},
                        "abstract": {"value": abstract},
                        "authors": {"value": authors},
                        "authorids": {"value": authorids},
                        "keywords": {"value": keywords},
                        "pdf": {"value": pdf_url},
                    }
                )

                # Submit the note
                submission = client.post_note_edit(
                    invitation=submission_invitation,
                    signatures=[authorids[0]],  # Use first author as signature
                    note=note,
                )

                log.info(f"  SUCCESS: Submitted with ID: {submission['note']['id']}")
                successful += 1

            except Exception as e:
                log.error(f"  FAILED: {e}")
                failed += 1

        # Summary
        log.info(f"{'=' * 50}")
        log.info("Submission Summary:")
        log.info(f"  Successful: {successful}")
        log.info(f"  Failed: {failed}")
        log.info(f"  Total: {successful + failed}")
