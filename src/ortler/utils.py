"""
Utility functions for generating random papers and PDFs.
"""

import json
import os
import random
import re
import string
import tempfile
from typing import Any

from openai import OpenAI
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from .client import get_client



def format_author_name(author_id: str) -> str:
    """
    Convert author ID to proper name format.

    Example: ~Hannah_Bast1 -> Hannah Bast
    >>> format_author_name("~Hannah_Bast1")
    'Hannah Bast'
    """
    if author_id.startswith("~"):
        name = author_id[1:]
        name = re.sub(r"\d+$", "", name)
        name = name.replace("_", " ")
        return name
    else:
        return author_id


def generate_random_paper(
    model: str, prompt: str, author_ids: list[str], api_key: str | None = None
) -> tuple[str, str, list[str]]:
    """
    Generate a random SIGIR paper title, abstract, and author names using OpenAI API.

    Returns:
        tuple: (title, abstract, authors)
    """
    if not api_key:
        api_key = os.environ.get("OPENAI_API_KEY")

    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable not set")

    try:
        client = OpenAI(api_key=api_key)

        # Add author IDs to the prompt
        author_list = ", ".join(author_ids)
        full_prompt = f"{prompt}\n\nAuthor IDs: {author_list}\n\nConvert author IDs (like ~Hannah_Bast1) to proper names (like Hannah Bast) in Firstname Lastname format."

        # Define JSON schema
        json_schema: dict[str, Any] = {
            "type": "json_schema",
            "json_schema": {
                "name": "paper_generation",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "The paper title"},
                        "abstract": {
                            "type": "string",
                            "description": "The paper abstract (exactly three sentences)",
                        },
                        "authors": {
                            "type": "array",
                            "description": "List of author names in Firstname Lastname format",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["title", "abstract", "authors"],
                    "additionalProperties": False,
                },
            },
        }

        # GPT-5 models use max_completion_tokens and only support temperature=1
        if model.startswith("gpt-5"):
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert in Information Retrieval and SIGIR conference papers.",
                    },
                    {"role": "user", "content": full_prompt},
                ],
                max_completion_tokens=500,
                response_format=json_schema,
            )
        else:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert in Information Retrieval and SIGIR conference papers.",
                    },
                    {"role": "user", "content": full_prompt},
                ],
                max_tokens=500,
                temperature=0.9,
                response_format=json_schema,
            )

        content = response.choices[0].message.content
        if content is None:
            raise RuntimeError("OpenAI API returned empty content")
        content = content.strip()

        # Parse JSON response
        data = json.loads(content)

        title: str = data["title"]
        abstract: str = data["abstract"]
        authors: list[str] = data["authors"]

        # Ensure authors is a list
        if isinstance(authors, str):
            authors = [authors]

        # Ensure we have the right number of authors
        if len(authors) != len(author_ids):
            authors = [format_author_name(aid) for aid in author_ids]

        return title, abstract, authors

    except Exception as e:
        raise RuntimeError(f"OpenAI API error: {e}")


def get_random_profiles(
    num_profiles: int, placeholder_prefix: str = "Random User"
) -> tuple[list[str], list[str]]:
    """
    Get random profiles by searching with random two-letter strings.

    Args:
        num_profiles: Number of random profiles to retrieve
        placeholder_prefix: Prefix for placeholder names if not enough profiles found

    Returns:
        Tuple of (names, profile_ids)
    """
    client = get_client()
    names: list[str] = []
    profile_ids: list[str] = []

    max_attempts = 50  # Prevent infinite loops
    attempts = 0

    while len(profile_ids) < num_profiles and attempts < max_attempts:
        # Generate random two-letter search string
        search_term = "".join(random.choices(string.ascii_lowercase, k=2))

        try:
            profiles = client.search_profiles(term=search_term)

            if profiles:
                # Pick a random profile from results
                profile = random.choice(profiles)
                profile_id: str = profile.id

                # Avoid duplicates
                if profile_id not in profile_ids:
                    profile_ids.append(profile_id)
                    # Get preferred name
                    name = (
                        profile.get_preferred_name()
                        if hasattr(profile, "get_preferred_name")
                        else profile_id
                    )
                    names.append(name)
        except Exception:
            pass  # Continue trying with different search terms

        attempts += 1

    # If we couldn't find enough profiles, pad with placeholder
    while len(names) < num_profiles:
        names.append(f"{placeholder_prefix} {len(names) + 1}")
        profile_ids.append(f"random{len(names)}@example.com")

    return names, profile_ids


def get_random_authors(
    num_authors: int
) -> tuple[list[str], list[str]]:
    """
    Get random authors by searching with random two-letter strings.
    """
    return get_random_profiles(num_authors, placeholder_prefix="Random Author")


def create_dummy_pdf(title: str, authors: list[str], abstract: str) -> str:
    """
    Create a simple dummy PDF for testing submissions.
    """
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".pdf", delete=False) as f:
        pdf = canvas.Canvas(f.name, pagesize=letter)
        width, height = letter
        max_width = width - 144

        # Title - wrap it like abstract
        pdf.setFont("Helvetica-Bold", 16)
        y = height - 72
        title_words = title.split()
        title_lines: list[str] = []
        current_line: list[str] = []

        for word in title_words:
            current_line.append(word)
            test_line = " ".join(current_line)
            if pdf.stringWidth(test_line, "Helvetica-Bold", 16) > max_width:
                current_line.pop()
                title_lines.append(" ".join(current_line))
                current_line = [word]

        if current_line:
            title_lines.append(" ".join(current_line))

        for line in title_lines:
            pdf.drawString(72, y, line)
            y -= 20

        # Authors
        y -= 10
        pdf.setFont("Helvetica", 12)
        authors_text = ", ".join(authors)
        # Wrap authors too if needed
        if pdf.stringWidth(authors_text, "Helvetica", 12) > max_width:
            # Split into multiple lines if too long
            author_words = authors_text.split()
            author_lines: list[str] = []
            current_line = []
            for word in author_words:
                current_line.append(word)
                test_line = " ".join(current_line)
                if pdf.stringWidth(test_line, "Helvetica", 12) > max_width:
                    current_line.pop()
                    author_lines.append(" ".join(current_line))
                    current_line = [word]
            if current_line:
                author_lines.append(" ".join(current_line))
            for line in author_lines:
                pdf.drawString(72, y, line)
                y -= 16
        else:
            pdf.drawString(72, y, authors_text)
            y -= 16

        # Abstract
        y -= 40
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(72, y, "Abstract")

        y -= 20
        pdf.setFont("Helvetica", 10)
        # Wrap abstract text
        max_width = width - 144
        words = abstract.split()
        lines: list[str] = []
        current_line = []

        for word in words:
            current_line.append(word)
            test_line = " ".join(current_line)
            if pdf.stringWidth(test_line, "Helvetica", 10) > max_width:
                current_line.pop()
                lines.append(" ".join(current_line))
                current_line = [word]

        if current_line:
            lines.append(" ".join(current_line))

        for line in lines[:20]:  # Limit to 20 lines
            pdf.drawString(72, y, line)
            y -= 14
            if y < 72:
                break

        pdf.save()
        return f.name
