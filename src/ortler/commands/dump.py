"""
Dump command for outputting all cached data as RDF.
"""

import json
from argparse import ArgumentParser, Namespace
from pathlib import Path

from ..command import Command
from ..rdf import Rdf
from ..profile import ProfileWithPapers
from ..log import log


class DumpCommand(Command):
    """
    Output all cached data as RDF (for QLever import).
    """

    @property
    def name(self) -> str:
        return "dump"

    @property
    def help(self) -> str:
        return "Output all cached data as RDF"

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--output",
            help="Output file path (default: stdout)",
            default=None,
        )

    def _load_groups(self, cache_dir: str) -> dict[str, dict]:
        """
        Load all group membership from cache.
        Returns dict: role_suffix -> {group_id -> {id, members, tmdate}}
        """
        groups_dir = Path(cache_dir) / "groups"
        all_groups = {}
        if groups_dir.exists():
            for cache_file in groups_dir.glob("*.json"):
                role_suffix = cache_file.stem  # e.g., "Reviewers"
                with open(cache_file) as f:
                    all_groups[role_suffix] = json.load(f)
        return all_groups

    def _load_reduced_loads(self, cache_dir: str) -> dict[str, int]:
        """Load reduced loads from cache."""
        cache_path = Path(cache_dir) / "recruitment" / "reduced_loads.json"
        if cache_path.exists():
            with open(cache_path) as f:
                return json.load(f)
        return {}

    def _load_submissions(self, cache_dir: str) -> list[dict]:
        """Load all submissions from cache."""
        submissions_dir = Path(cache_dir) / "submissions"
        submissions = []
        if submissions_dir.exists():
            for cache_file in submissions_dir.glob("*.json"):
                try:
                    with open(cache_file) as f:
                        submissions.append(json.load(f))
                except Exception:
                    pass
        return submissions

    def _load_review(self, cache_dir: str, submission_id: str) -> dict | None:
        """Load AI review from cache if available."""
        review_path = Path(cache_dir) / "reviews" / f"{submission_id}.json"
        if review_path.exists():
            with open(review_path) as f:
                return json.load(f)
        return None

    def _get_rdf_class(self, role_suffix: str) -> str:
        """Get RDF class name for a role suffix."""
        rdf_classes = {
            "Reviewers": ":PC",
            "Area_Chairs": ":SPC",
            "Senior_Area_Chairs": ":AC",
        }
        return rdf_classes.get(role_suffix, ":Unknown")

    def _add_recruitment_triples(
        self,
        rdf: Rdf,
        args: Namespace,
        all_groups: dict[str, dict],
        reduced_loads: dict[str, int],
        profile_with_papers: ProfileWithPapers,
    ) -> set[str]:
        """
        Add RDF triples for all recruitment roles.
        Returns set of all member profile IDs processed.
        """
        all_member_ids = set()

        for role_suffix, groups_data in all_groups.items():
            group_id = f"{args.venue_id}/{role_suffix}"
            rdf_class = self._get_rdf_class(role_suffix)

            # Determine member status from groups
            confirmed = set()
            invited = set()
            declined = set()

            for gid, gdata in groups_data.items():
                members = set(gdata.get("members", []))
                if gid == group_id:
                    confirmed = members
                elif gid == f"{group_id}/Invited":
                    invited = members
                elif gid == f"{group_id}/Declined":
                    declined = members

            all_members = confirmed | invited | declined
            all_member_ids.update(all_members)

            # First pass: resolve all member IDs to canonical profile IDs
            # and collect all identifiers for each person
            canonical_profiles: dict[str, dict] = {}  # canonical_id -> member_info
            canonical_to_original: dict[
                str, set
            ] = {}  # canonical_id -> set of original IDs

            for member_id in all_members:
                profile_with_papers.get_profile(member_id)
                member_info = profile_with_papers.asJson()
                canonical_id = member_info.get("id", member_id)

                # Store profile info (may overwrite, but same profile)
                canonical_profiles[canonical_id] = member_info

                # Track all original member IDs that resolved to this canonical ID
                if canonical_id not in canonical_to_original:
                    canonical_to_original[canonical_id] = set()
                canonical_to_original[canonical_id].add(member_id)

            # Second pass: determine status for each canonical profile
            # A person is confirmed/declined if ANY of their identifiers are
            for canonical_id, member_info in canonical_profiles.items():
                # Get all identifiers for this person:
                # canonical ID + emails + all original IDs that resolved here
                person_identifiers = {canonical_id}
                person_identifiers.update(
                    member_info.get("content", {}).get("emails", [])
                )
                person_identifiers.update(
                    canonical_to_original.get(canonical_id, set())
                )

                # Determine status: confirmed > declined > pending
                if person_identifiers & confirmed:
                    status = "accepted"
                elif person_identifiers & declined:
                    status = "declined"
                else:
                    status = "pending"

                person_iri = rdf.personIri(canonical_id)

                rdf.add_triple(person_iri, "a", ":Person")
                rdf.add_triple(person_iri, ":role", rdf_class)
                rdf.add_triple(person_iri, ":status", rdf.literal(status))

                # Add reduced_load if present (match by email)
                member_emails = member_info.get("content", {}).get("emails", [])
                for email in member_emails:
                    if email in reduced_loads:
                        rdf.add_triple(
                            person_iri, ":reduced_load", str(reduced_loads[email])
                        )
                        break

                # Add profile data
                profile_with_papers.addToRdf(rdf, member_info, canonical_id)

        return all_member_ids

    def _add_submission_triples(
        self,
        rdf: Rdf,
        args: Namespace,
        submissions: list[dict],
        profile_with_papers: ProfileWithPapers,
    ) -> set[str]:
        """
        Add RDF triples for all submissions.
        Returns set of all author profile IDs.
        """
        all_author_ids = set()
        all_author_reviewer_ids = set()

        for submission in submissions:
            submission_iri = rdf.paperIri(submission["id"])
            content = submission.get("content", {})

            rdf.add_triple(submission_iri, "a", ":Submission")

            # Derive status from ddate and invitations
            # ddate = deletion date (soft delete, shown as greyed out in UI)
            invitations = submission.get("invitations", [])
            if submission.get("ddate"):
                status = "deleted"
                title_prefix = "[D] "
            elif any("Withdrawn_Submission" in inv for inv in invitations):
                status = "withdrawn"
                title_prefix = "[W] "
            elif any("Desk_Rejected_Submission" in inv for inv in invitations):
                status = "desk_rejected"
                title_prefix = "[R] "
            else:
                status = "active"
                title_prefix = ""
            rdf.add_triple(submission_iri, ":status", rdf.literal(status))

            title_value = content.get("title", {}).get("value", "")
            title_literal = (
                rdf.literal(title_prefix + title_value) if title_value else ":novalue"
            )
            rdf.add_triple(submission_iri, ":title", title_literal)
            rdf.add_triple(submission_iri, "rdfs:label", title_literal)

            rdf.add_triple(
                submission_iri,
                ":abstract",
                rdf.literalFromJson(content, "abstract.value"),
            )

            author_ids = rdf.valuesFromJson(content, "authorids.value")
            for author_id in author_ids:
                rdf.add_triple(submission_iri, ":author", rdf.personIri(author_id))
                all_author_ids.add(author_id)

            # Add comma-separated author IDs and names
            author_ids_clean = [aid.lstrip("~") for aid in author_ids]
            rdf.add_triple(
                submission_iri,
                ":author_ids",
                rdf.literal(", ".join(author_ids_clean))
                if author_ids_clean
                else ":novalue",
            )
            author_names = rdf.valuesFromJson(content, "authors.value")
            rdf.add_triple(
                submission_iri,
                ":author_names",
                rdf.literal(", ".join(author_names)) if author_names else ":novalue",
            )
            rdf.add_triple(submission_iri, ":num_authors", str(len(author_ids)))

            author_reviewer_id = content.get("serve_as_reviewer", {}).get("value", "")
            if author_reviewer_id:
                rdf.add_triple(
                    submission_iri, ":author_reviewer", rdf.personIri(author_reviewer_id)
                )
                all_author_reviewer_ids.add(author_reviewer_id)

            rdf.add_triple(
                submission_iri,
                ":created_on",
                rdf.dateTimeFromTimestamp(submission.get("cdate")),
            )
            rdf.add_triple(
                submission_iri,
                ":last_modified_on",
                rdf.dateTimeFromTimestamp(submission.get("mdate")),
            )

            has_pdf = "pdf" in content
            rdf.add_triple(submission_iri, ":has_pdf", "true" if has_pdf else "false")

            # Add AI review triples
            review = self._load_review(args.cache_dir, submission["id"]) or {}
            rdf.add_triple(
                submission_iri,
                ":ai_summary",
                rdf.literalFromJson(review, "summary"),
            )
            rdf.add_triple(
                submission_iri,
                ":ai_methods",
                rdf.literalFromJson(review, "methods"),
            )
            rdf.add_triple(
                submission_iri,
                ":ai_results",
                rdf.literalFromJson(review, "results"),
            )

            strengths = review.get("strengths", [])
            rdf.add_triple(
                submission_iri,
                ":ai_strengths",
                rdf.literal("\n".join(strengths)) if strengths else ":novalue",
            )

            weaknesses = review.get("weaknesses", [])
            rdf.add_triple(
                submission_iri,
                ":ai_weaknesses",
                rdf.literal("\n".join(weaknesses)) if weaknesses else ":novalue",
            )

        # Add author profile triples
        for author_id in all_author_ids:
            profile_with_papers.get_profile(author_id)
            author_info = profile_with_papers.asJson()

            person_iri = rdf.personIri(author_id)
            rdf.add_triple(person_iri, "a", ":Person")
            rdf.add_triple(person_iri, "a", ":Author")
            profile_with_papers.addToRdf(rdf, author_info, author_id)

        # Add Author_Reviewer type and profile triples
        for author_reviewer_id in all_author_reviewer_ids:
            person_iri = rdf.personIri(author_reviewer_id)
            rdf.add_triple(person_iri, "a", ":Author_Reviewer")
            # Add profile triples if not already an author
            if author_reviewer_id not in all_author_ids:
                profile_with_papers.get_profile(author_reviewer_id)
                reviewer_info = profile_with_papers.asJson()
                rdf.add_triple(person_iri, "a", ":Person")
                profile_with_papers.addToRdf(rdf, reviewer_info, author_reviewer_id)

        return all_author_ids

    def execute(self, args: Namespace) -> None:
        """
        Output all cached data as RDF.
        """
        # Load all cached data
        all_groups = self._load_groups(args.cache_dir)
        reduced_loads = self._load_reduced_loads(args.cache_dir)
        submissions = self._load_submissions(args.cache_dir)

        if not all_groups and not submissions:
            log.error("No cached data. Run 'ortler update' first.")
            return

        # Initialize profile loader (cache-only mode)
        profile_with_papers = ProfileWithPapers(
            cache_dir=args.cache_dir, cache_only=True
        )

        rdf = Rdf()

        # Add recruitment triples
        if all_groups:
            member_count = sum(
                len(set().union(*[set(g.get("members", [])) for g in groups.values()]))
                for groups in all_groups.values()
            )
            log.info(f"Adding triples for {member_count} committee members...")
            self._add_recruitment_triples(
                rdf, args, all_groups, reduced_loads, profile_with_papers
            )

        # Add submission triples
        if submissions:
            log.info(f"Adding triples for {len(submissions)} submissions...")
            self._add_submission_triples(rdf, args, submissions, profile_with_papers)

        # Output
        output_content = rdf.as_turtle()

        if args.output:
            with open(args.output, "w") as f:
                f.write(output_content)
            log.info(f"RDF saved to {args.output}")
        else:
            print(output_content)
