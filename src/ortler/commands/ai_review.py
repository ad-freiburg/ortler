"""
AI Review command for generating reviews using OpenAI GPT-4.
"""

import base64
import json
import os
import time
from argparse import ArgumentParser, Namespace
from io import BytesIO
from pathlib import Path
from typing import Any

from openai import OpenAI
from pdf2image import convert_from_path

from ..command import Command
from ..log import log

# Model and pricing configuration
MODEL = "gpt-4o"
INPUT_PRICE_PER_MILLION_TOKENS = 2.50
OUTPUT_PRICE_PER_MILLION_TOKENS = 10.00

DEFAULT_PROMPT = """Write a succinct review with the following parts: (1) Extract the title of the paper; (2) A short summary of what the paper is about and what its contribution is; (3) A summary of the methods used in the paper; (4) A summary of the results presented in the paper; (5) The strengths of the paper if any numbered (S1), (S2), ...; (6) The weaknesses of the paper if any numbered (W1), (W2), ...; (7) A recommendation from the scale: REJECT (-2), WEAK REJECT (-1), BORDERLINE (0), ACCEPT (1), STRONG ACCEPT (2)"""

# JSON schema for structured review output
REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "The title of the paper"},
        "summary": {
            "type": "string",
            "description": "A short summary of the paper and its contribution",
        },
        "methods": {
            "type": "string",
            "description": "A summary of the methods used in the paper",
        },
        "results": {
            "type": "string",
            "description": "A summary of the results presented in the paper",
        },
        "strengths": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Strengths of the paper, numbered as S1, S2, etc.",
        },
        "weaknesses": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Weaknesses of the paper, numbered as W1, W2, etc.",
        },
        "recommendation": {
            "type": "string",
            "enum": [
                "REJECT (-2)",
                "WEAK REJECT (-1)",
                "BORDERLINE (0)",
                "ACCEPT (1)",
                "STRONG ACCEPT (2)",
            ],
            "description": "Recommendation from the given scale",
        },
    },
    "required": [
        "title",
        "summary",
        "methods",
        "results",
        "strengths",
        "weaknesses",
        "recommendation",
    ],
    "additionalProperties": False,
}


def pdf_to_base64_images(pdf_path: Path, dpi: int = 150) -> list[str]:
    """
    Convert PDF pages to base64-encoded PNG images.

    Args:
        pdf_path: Path to PDF file
        dpi: Resolution for conversion (default: 150)

    Returns:
        List of base64-encoded PNG images, one per page
    """
    images = convert_from_path(pdf_path, dpi=dpi)

    base64_images = []
    for image in images:
        buffered = BytesIO()
        image.save(buffered, format="PNG")
        img_bytes = buffered.getvalue()
        base64_img = base64.b64encode(img_bytes).decode("utf-8")
        base64_images.append(base64_img)

    return base64_images


def review_pdf(
    client: OpenAI,
    pdf_path: Path,
    prompt: str,
    schema: dict[str, Any],
    model: str = MODEL,
) -> tuple[dict[str, Any], int, int]:
    """
    Send PDF to GPT-4 API and get structured review.

    Returns:
        Tuple of (review_dict, input_tokens, output_tokens)
    """
    base64_images = pdf_to_base64_images(pdf_path)

    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for base64_img in base64_images:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{base64_img}"},
            }
        )

    messages = [{"role": "user", "content": content}]

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "review", "schema": schema, "strict": True},
        },
        max_tokens=4096,
    )

    review_text = response.choices[0].message.content
    review_dict = json.loads(review_text)

    input_tokens = response.usage.prompt_tokens
    output_tokens = response.usage.completion_tokens

    return review_dict, input_tokens, output_tokens


class AiReviewCommand(Command):
    """
    Generate AI reviews for submission PDFs using OpenAI GPT-4.
    """

    @property
    def name(self) -> str:
        return "ai-review"

    @property
    def help(self) -> str:
        return "Generate AI reviews for submission PDFs using OpenAI GPT-4"

    def add_arguments(self, parser: ArgumentParser) -> None:
        """
        Add ai-review command arguments.
        """
        parser.add_argument(
            "submission_ids",
            nargs="*",
            help="Submission IDs to review (default: all cached PDFs)",
        )
        parser.add_argument(
            "--prompt",
            type=str,
            default=DEFAULT_PROMPT,
            help="Custom prompt for the review",
        )
        parser.add_argument(
            "--model",
            type=str,
            default=MODEL,
            help=f"OpenAI model to use (default: {MODEL})",
        )
        parser.add_argument(
            "--recache",
            action="store_true",
            help="Re-generate reviews even if cached",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show which PDFs would be reviewed without actually reviewing",
        )

    def _get_pdf_dir(self, cache_dir: str) -> Path:
        """Get the PDFs cache directory."""
        return Path(cache_dir) / "pdfs"

    def _get_review_dir(self, cache_dir: str) -> Path:
        """Get the reviews cache directory."""
        return Path(cache_dir) / "reviews"

    def _get_review_path(self, cache_dir: str, submission_id: str) -> Path:
        """Get cache file path for a review."""
        return self._get_review_dir(cache_dir) / f"{submission_id}.json"

    def _load_review(self, cache_dir: str, submission_id: str) -> dict | None:
        """Load review from cache if available."""
        review_path = self._get_review_path(cache_dir, submission_id)
        if review_path.exists():
            with open(review_path) as f:
                return json.load(f)
        return None

    def _save_review(self, cache_dir: str, submission_id: str, review: dict) -> None:
        """Save review to cache."""
        review_path = self._get_review_path(cache_dir, submission_id)
        review_path.parent.mkdir(parents=True, exist_ok=True)
        with open(review_path, "w") as f:
            json.dump(review, f, indent=2, ensure_ascii=False)

    def execute(self, args: Namespace) -> None:
        """
        Generate AI reviews for submission PDFs.
        """
        # Check for OpenAI API key
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            log.error("OPENAI_API_KEY environment variable not set")
            return

        pdf_dir = self._get_pdf_dir(args.cache_dir)

        # Determine which PDFs to process
        if args.submission_ids:
            # Specific submission IDs provided
            pdf_files = []
            for submission_id in args.submission_ids:
                pdf_path = pdf_dir / f"{submission_id}.pdf"
                if pdf_path.exists():
                    pdf_files.append((submission_id, pdf_path))
                else:
                    log.warning(f"PDF not found for submission {submission_id}")
        else:
            # All cached PDFs
            if not pdf_dir.exists():
                log.error(
                    f"PDF cache directory not found: {pdf_dir}\n"
                    "Run 'ortler submissions --dump json' first to download PDFs"
                )
                return
            pdf_files = [(p.stem, p) for p in sorted(pdf_dir.glob("*.pdf"))]

        if not pdf_files:
            log.info("No PDFs to review")
            return

        # Filter out already reviewed (unless --recache)
        to_review = []
        cached_count = 0
        for submission_id, pdf_path in pdf_files:
            if not args.recache and self._load_review(args.cache_dir, submission_id):
                cached_count += 1
            else:
                to_review.append((submission_id, pdf_path))

        total_count = len(pdf_files)
        log.info(
            f"Found {total_count} PDFs: {cached_count} already reviewed, "
            f"{len(to_review)} to review"
        )

        if args.dry_run:
            if to_review:
                log.info("Would review the following submissions:")
                for submission_id, _ in to_review:
                    log.info(f"  - {submission_id}")
            return

        if not to_review:
            log.info("All reviews cached, nothing to do")
            return

        # Initialize OpenAI client
        client = OpenAI(api_key=api_key)

        # Process each PDF
        total_input_tokens = 0
        total_output_tokens = 0
        success_count = 0
        failed_count = 0

        for index, (submission_id, pdf_path) in enumerate(to_review, start=1):
            log.info(
                f"[{index}/{len(to_review)}] Generating review for {submission_id} ..."
            )

            try:
                start_time = time.time()

                review_dict, input_tokens, output_tokens = review_pdf(
                    client=client,
                    pdf_path=pdf_path,
                    prompt=args.prompt,
                    schema=REVIEW_SCHEMA,
                    model=args.model,
                )

                elapsed_time = time.time() - start_time

                # Calculate price
                price = (
                    input_tokens * INPUT_PRICE_PER_MILLION_TOKENS / 1_000_000
                    + output_tokens * OUTPUT_PRICE_PER_MILLION_TOKENS / 1_000_000
                )

                # Add statistics to the review
                output_dict = {
                    "submission_id": submission_id,
                    "statistics": {
                        "num_input_tokens": input_tokens,
                        "num_output_tokens": output_tokens,
                        "price_dollars": round(price, 2),
                        "time_seconds": round(elapsed_time, 1),
                        "model": args.model,
                    },
                    **review_dict,
                }

                # Save review
                self._save_review(args.cache_dir, submission_id, output_dict)

                total_input_tokens += input_tokens
                total_output_tokens += output_tokens
                success_count += 1

                log.info(
                    f"  Title: {review_dict.get('title', 'Unknown')[:60]}..."
                    if len(review_dict.get("title", "")) > 60
                    else f"  Title: {review_dict.get('title', 'Unknown')}"
                )
                log.info(
                    f"  Recommendation: {review_dict.get('recommendation', 'Unknown')}"
                )
                log.info(
                    f"  Tokens: {input_tokens} in / {output_tokens} out, "
                    f"${price:.2f}, {elapsed_time:.1f}s"
                )

            except KeyboardInterrupt:
                log.warning("\nInterrupted by user")
                break
            except Exception as e:
                log.error(f"  Failed: {e}")
                failed_count += 1
                continue

        # Summary
        total_price = (
            total_input_tokens * INPUT_PRICE_PER_MILLION_TOKENS / 1_000_000
            + total_output_tokens * OUTPUT_PRICE_PER_MILLION_TOKENS / 1_000_000
        )
        log.info("")
        log.info(
            f"Summary: {success_count} reviewed, {failed_count} failed, "
            f"{cached_count} cached"
        )
        log.info(
            f"Total tokens: {total_input_tokens} in / {total_output_tokens} out, "
            f"${total_price:.2f}"
        )
