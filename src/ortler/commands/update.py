"""
Update command for incrementally syncing cache with OpenReview.
"""

import json
from argparse import ArgumentParser, Namespace
from datetime import datetime
from pathlib import Path

from ..command import Command
from ..client import get_client
from ..profile import ProfileWithPapers
from ..log import log


class UpdateCommand(Command):
    """
    Incrementally update the cache with changes from OpenReview since the last update.
    """

    @property
    def name(self) -> str:
        return "update"

    @property
    def help(self) -> str:
        return "Incrementally update cache with changes from OpenReview"

    def add_arguments(self, parser: ArgumentParser) -> None:
        """
        Add update command arguments.
        """
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be updated without making changes",
        )
        parser.add_argument(
            "--recache",
            choices=["submissions", "profiles", "profiles-with-publications", "all"],
            help="Force re-fetch: submissions, profiles (metadata only), "
            "profiles-with-publications, all (submissions + profiles-with-publications)",
        )

    def _get_metadata_path(self, cache_dir: str) -> Path:
        """Get path to cache metadata file."""
        return Path(cache_dir) / "metadata.json"

    def _load_metadata(self, cache_dir: str) -> dict:
        """Load cache metadata (including last_update_timestamp)."""
        metadata_path = self._get_metadata_path(cache_dir)
        if metadata_path.exists():
            with open(metadata_path) as f:
                return json.load(f)
        return {}

    def _save_metadata(self, cache_dir: str, metadata: dict) -> None:
        """Save cache metadata."""
        metadata_path = self._get_metadata_path(cache_dir)
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

    def _get_tracked_profiles(self, args: Namespace, client) -> set[str]:
        """
        Get all profile IDs we're tracking (from groups and submission authors).
        """
        tracked = set()

        # Get members from recruitment groups
        group_suffixes = ["Reviewers", "Area_Chairs", "Senior_Area_Chairs"]
        for suffix in group_suffixes:
            group_id = f"{args.venue_id}/{suffix}"
            try:
                groups = client.get_groups(prefix=group_id)
                for group in groups:
                    tracked.update(group.members or [])
            except Exception:
                pass

        # Get authors from submissions cache
        submissions_cache_dir = Path(args.cache_dir) / "submissions"
        if submissions_cache_dir.exists():
            for cache_file in submissions_cache_dir.glob("*.json"):
                try:
                    with open(cache_file) as f:
                        submission = json.load(f)
                    author_ids = (
                        submission.get("content", {})
                        .get("authorids", {})
                        .get("value", [])
                    )
                    tracked.update(author_ids)
                except Exception:
                    pass

        return tracked

    def _update_submissions(
        self, args: Namespace, client, last_update: int, dry_run: bool
    ) -> tuple[list[str], int, int]:
        """
        Update submissions cache with new/modified submissions.
        Includes active, withdrawn, and desk-rejected submissions.
        Returns (new_author_ids, new_count, modified_count).
        """
        # All submission types to track
        submission_types = [
            ("Submission", "New submission"),
            ("Withdrawn_Submission", "Withdrawn submission"),
            ("Desk_Rejected_Submission", "Desk-rejected submission"),
        ]
        submissions_cache_dir = Path(args.cache_dir) / "submissions"

        new_author_ids = []
        new_count = 0
        modified_count = 0

        for suffix, label in submission_types:
            invitation = f"{args.venue_id}/-/{suffix}"

            # Get new submissions (created after last update)
            # Use trash=True to include deleted submissions (have ddate set)
            try:
                new_submissions = list(
                    client.get_all_notes(
                        invitation=invitation, mintcdate=last_update, trash=True
                    )
                )
            except Exception as e:
                log.warning(f"Failed to fetch new {suffix}: {e}")
                new_submissions = []

            for submission in new_submissions:
                new_count += 1
                author_ids = submission.content.get("authorids", {}).get("value", [])
                new_author_ids.extend(author_ids)

                if not dry_run:
                    submissions_cache_dir.mkdir(parents=True, exist_ok=True)
                    cache_path = submissions_cache_dir / f"{submission.id}.json"
                    with open(cache_path, "w") as f:
                        json.dump(submission.to_json(), f, indent=2)

                log.info(f"{label}: {submission.id}")

            # Get modified submissions (sort by tmdate, stop when older than last_update)
            # Use trash=True to include deleted submissions (have ddate set)
            try:
                all_submissions = client.get_notes(
                    invitation=invitation, sort="tmdate:desc", limit=100, trash=True
                )
                for submission in all_submissions:
                    if submission.tmdate < last_update:
                        break
                    # Skip if it's a new submission (already processed)
                    if submission.tcdate >= last_update:
                        continue

                    modified_count += 1

                    if not dry_run:
                        submissions_cache_dir.mkdir(parents=True, exist_ok=True)
                        cache_path = submissions_cache_dir / f"{submission.id}.json"
                        with open(cache_path, "w") as f:
                            json.dump(submission.to_json(), f, indent=2)

                    log.info(f"Modified {suffix.lower()}: {submission.id}")

            except Exception as e:
                log.warning(f"Failed to check modified {suffix}: {e}")

        return new_author_ids, new_count, modified_count

    def _update_dblp_publications(
        self,
        args: Namespace,
        last_update: int,
        tracked_profiles: set[str],
    ) -> set[str]:
        """
        Check for new DBLP publications and return profile IDs that need updating.
        Only runs for incremental updates (skips if last_update is 0).
        """
        profiles_with_new_pubs = set()

        # Skip DBLP check when last_update is 0 - would fetch millions of records
        if last_update == 0:
            log.info("Skipping DBLP check (no previous update timestamp)")
            return profiles_with_new_pubs

        new_dblp = []

        # Check API v2 (newer imports use DBLP.org/-/Record)
        try:
            client = get_client()
            new_dblp_v2 = list(
                client.get_all_notes(
                    invitation="DBLP.org/-/Record", mintcdate=last_update
                )
            )
            new_dblp.extend(new_dblp_v2)
        except Exception:
            pass

        if not new_dblp:
            log.info("No new DBLP publications found")
            return profiles_with_new_pubs

        log.info(f"Found {len(new_dblp)} new DBLP publications globally")

        # Check which of our tracked profiles have new publications
        for pub in new_dblp:
            # Handle API v2 content format: content.authorids.value
            content = pub.content if hasattr(pub, "content") else {}
            if isinstance(content, dict):
                author_ids = content.get("authorids", {})
                if isinstance(author_ids, dict):
                    author_ids = author_ids.get("value", [])
                elif not isinstance(author_ids, list):
                    author_ids = []
            else:
                author_ids = []

            for author_id in author_ids:
                if author_id in tracked_profiles:
                    profiles_with_new_pubs.add(author_id)
                    log.info(f"New publication for tracked profile: {author_id}")

        return profiles_with_new_pubs

    def _update_profiles(
        self,
        args: Namespace,
        tracked_profiles: set[str],
        profiles_with_new_pubs: set[str],
        dry_run: bool,
        recache_profiles: bool = False,
        recache_publications: bool = False,
    ) -> int:
        """
        Update profiles that have changed (tmdate) or have new publications.
        Also saves ID mapping (email -> canonical profile ID) for cache-only mode.
        If recache_profiles is True, re-fetch all profiles (metadata only).
        If recache_publications is True, also re-fetch all publications.
        Returns count of updated profiles.
        """
        if not tracked_profiles:
            return 0

        profile_with_papers = ProfileWithPapers(cache_dir=args.cache_dir, recache=False)

        # Batch check which profiles have changed (also builds ID mapping)
        changed_profiles = profile_with_papers.check_profiles_for_updates(
            list(tracked_profiles)
        )

        # Save ID mapping for cache-only mode (email/alias -> canonical ID)
        if not dry_run:
            id_mapping = profile_with_papers.get_id_mapping()
            if id_mapping:
                mapping_path = Path(args.cache_dir) / "profiles" / "_id_mapping.json"
                mapping_path.parent.mkdir(parents=True, exist_ok=True)
                with open(mapping_path, "w") as f:
                    json.dump(id_mapping, f, indent=2)
                log.info(f"Saved ID mapping for {len(id_mapping)} profiles")

        # Determine which profiles to update
        if recache_profiles or recache_publications:
            # Re-fetch all profiles
            profiles_to_update = tracked_profiles
        else:
            # Only update changed profiles or those with new publications
            profiles_to_update = changed_profiles | profiles_with_new_pubs

        if not profiles_to_update:
            return 0

        if dry_run:
            for profile_id in profiles_to_update:
                reason = []
                if recache_publications:
                    reason.append("recache profiles-with-publications")
                elif recache_profiles:
                    reason.append("recache profiles")
                elif profile_id in changed_profiles:
                    reason.append("tmdate changed")
                if profile_id in profiles_with_new_pubs:
                    reason.append("new publications")
                log.info(f"Would update profile: {profile_id} ({', '.join(reason)})")
            return len(profiles_to_update)

        # Determine whether to fetch publications
        fetch_publications = recache_publications or not recache_profiles

        # Force recache for profiles that need updating
        profile_with_papers_recache = ProfileWithPapers(
            cache_dir=args.cache_dir,
            recache=True,
            skip_publications=not fetch_publications,
        )

        updated_count = 0
        for profile_id in profiles_to_update:
            try:
                profile_with_papers_recache.get_profile(profile_id)
                updated_count += 1
            except Exception as e:
                log.warning(f"Failed to update profile {profile_id}: {e}")

        return updated_count

    def _update_groups(
        self, args: Namespace, client, last_update: int, dry_run: bool
    ) -> list[str]:
        """
        Update group membership cache.
        Returns list of changed group IDs.
        """
        changed_groups = []
        groups_cache_dir = Path(args.cache_dir) / "groups"
        group_suffixes = ["Reviewers", "Area_Chairs", "Senior_Area_Chairs"]

        for suffix in group_suffixes:
            base_group_id = f"{args.venue_id}/{suffix}"
            try:
                # Fetch all related groups (main, /Invited, /Declined)
                groups = client.get_groups(prefix=base_group_id)
                group_data = {}

                for group in groups:
                    group_data[group.id] = {
                        "id": group.id,
                        "members": group.members or [],
                        "tmdate": group.tmdate,
                    }

                    if group.tmdate >= last_update:
                        if base_group_id not in changed_groups:
                            changed_groups.append(base_group_id)
                            log.info(f"Group membership changed: {base_group_id}")

                # Save to cache
                if not dry_run:
                    groups_cache_dir.mkdir(parents=True, exist_ok=True)
                    cache_path = groups_cache_dir / f"{suffix}.json"
                    with open(cache_path, "w") as f:
                        json.dump(group_data, f, indent=2)

            except Exception as e:
                log.warning(f"Failed to fetch group {base_group_id}: {e}")

        return changed_groups

    def _update_reduced_loads(self, args: Namespace, client, dry_run: bool) -> None:
        """
        Update reduced loads cache for all recruitment roles.
        """
        reduced_loads_cache_dir = Path(args.cache_dir) / "recruitment"
        group_suffixes = ["Reviewers", "Area_Chairs", "Senior_Area_Chairs"]

        all_reduced_loads = {}

        for suffix in group_suffixes:
            recruitment_invitation = f"{args.venue_id}/{suffix}/-/Recruitment"
            try:
                notes = client.get_all_notes(invitation=recruitment_invitation)
                for note in notes:
                    content = note.content
                    if "reduced_load" in content and content["reduced_load"].get(
                        "value"
                    ):
                        user = content.get("user", {}).get("value", "")
                        load_str = content["reduced_load"]["value"]
                        if user and load_str:
                            try:
                                all_reduced_loads[user] = int(load_str)
                            except ValueError:
                                pass
            except Exception as e:
                log.warning(f"Failed to fetch reduced loads for {suffix}: {e}")

        # Save to cache
        if not dry_run and all_reduced_loads:
            reduced_loads_cache_dir.mkdir(parents=True, exist_ok=True)
            cache_path = reduced_loads_cache_dir / "reduced_loads.json"
            with open(cache_path, "w") as f:
                json.dump(all_reduced_loads, f, indent=2)
            log.info(f"Cached {len(all_reduced_loads)} reduced load entries")

    def execute(self, args: Namespace) -> None:
        """
        Execute the update command.
        """
        client = get_client()

        # Load metadata
        metadata = self._load_metadata(args.cache_dir)
        last_update = metadata.get("last_update_timestamp", 0)

        # Handle --recache options (not a hierarchy, except profiles < profiles-with-publications)
        # Note: DBLP scan only runs during incremental updates, not when recaching
        recache = args.recache or ""
        recache_submissions = recache in ("submissions", "all")
        recache_profiles = recache in ("profiles", "profiles-with-publications", "all")
        recache_publications = recache in ("profiles-with-publications", "all")

        if recache_submissions:
            last_update = 0

        if args.recache:
            log.info(f"Recache requested: {args.recache}")

        if last_update > 0:
            last_update_str = datetime.fromtimestamp(last_update / 1000).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            log.info(f"Last update: {last_update_str}")
        else:
            log.info("No previous update found, this will be the initial sync")

        # Record current time as the new update timestamp
        current_time = int(datetime.now().timestamp() * 1000)

        # Step 1: Get currently tracked profiles
        log.info("Collecting tracked profiles...")
        tracked_profiles = self._get_tracked_profiles(args, client)
        log.info(f"Tracking {len(tracked_profiles)} profiles")

        # Step 2: Update submissions (discovers new authors)
        log.info("Checking for new/modified submissions...")
        new_author_ids, new_subs, modified_subs = self._update_submissions(
            args, client, last_update, args.dry_run
        )

        # Add new authors to tracked profiles
        tracked_profiles.update(new_author_ids)

        # Step 3: Check for new DBLP publications (only for incremental updates)
        log.info("Checking for new DBLP publications...")
        profiles_with_new_pubs = self._update_dblp_publications(
            args, last_update, tracked_profiles
        )

        # Step 4: Update changed profiles
        log.info("Checking for profile changes...")
        updated_profiles = self._update_profiles(
            args,
            tracked_profiles,
            profiles_with_new_pubs,
            args.dry_run,
            recache_profiles,
            recache_publications,
        )

        # Step 5: Update group membership cache
        log.info("Updating group membership cache...")
        changed_groups = self._update_groups(args, client, last_update, args.dry_run)

        # Step 6: Update reduced loads cache
        log.info("Updating reduced loads cache...")
        self._update_reduced_loads(args, client, args.dry_run)

        # Save new timestamp (unless dry run)
        if not args.dry_run:
            metadata["last_update_timestamp"] = current_time
            self._save_metadata(args.cache_dir, metadata)

        # Summary
        log.info("")
        log.info("=== Update Summary ===")
        log.info(f"New submissions: {new_subs}")
        log.info(f"Modified submissions: {modified_subs}")
        log.info(f"Profiles with new publications: {len(profiles_with_new_pubs)}")
        log.info(f"Profiles updated: {updated_profiles}")
        log.info(f"Groups with membership changes: {len(changed_groups)}")

        if args.dry_run:
            log.info("")
            log.info("(Dry run - no changes made)")
