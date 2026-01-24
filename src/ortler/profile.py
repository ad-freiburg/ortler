"""
ProfileWithPapers class for handling OpenReview profile data with imported papers.
"""

import json
import re
from pathlib import Path
from typing import Dict, Any

from .log import log
from .rdf import Rdf
from .client import get_client, get_client_v1


class ProfileWithPapers:
    """
    Class for managing OpenReview profile data with imported DBLP papers.
    """

    @staticmethod
    def empty_profile(
        profile_id: str, error: str = "", status: str = ""
    ) -> Dict[str, Any]:
        """
        Create an empty profile dict for profiles that couldn't be loaded.
        """
        info: Dict[str, Any] = {"id": profile_id}
        if error:
            info["error"] = error
        if status:
            info["status"] = status
        return info

    def __init__(
        self,
        cache_profiles: bool = True,
        cache_dir: str = "cache",
        recache: bool = False,
        cache_only: bool = False,
        skip_publications: bool = False,
    ):
        """
        Initialize ProfileWithPapers with caching options.
        The cache_dir is the top-level cache directory; profiles are stored in cache_dir/profiles.
        If recache is True, skip reading from cache but still write fresh data to cache.
        If cache_only is True, never make API calls - return empty profile if not in cache.
        If skip_publications is True, only fetch profile metadata (not publications).
        """
        self.profile = None
        self.papers = []
        self.cache_profiles = cache_profiles
        self.cache_dir = str(Path(cache_dir) / "profiles")
        self.recache = recache
        self.cache_only = cache_only
        self.skip_publications = skip_publications
        # Track which profiles need updating (set by check_profiles_for_updates)
        self._profiles_needing_update: set[str] = set()
        self._batch_check_done = False
        # Map from input IDs (emails, aliases) to canonical profile IDs
        self._id_to_canonical: Dict[str, str] = {}
        # Load ID mapping from cache if in cache-only mode
        if cache_only:
            self._load_id_mapping()

    def _load_id_mapping(self) -> None:
        """Load ID mapping from cache file (for cache-only mode)."""
        mapping_path = Path(self.cache_dir) / "_id_mapping.json"
        if mapping_path.exists():
            try:
                with open(mapping_path) as f:
                    self._id_to_canonical = json.load(f)
            except Exception:
                pass

    def get_id_mapping(self) -> Dict[str, str]:
        """Return the current ID mapping (for saving to cache)."""
        return self._id_to_canonical.copy()

    def resolve_id(self, profile_id: str) -> str:
        """Resolve a profile ID to its canonical form using the ID mapping."""
        return self._id_to_canonical.get(profile_id, profile_id)

    def check_profiles_for_updates(self, member_ids: list[str]) -> set[str]:
        """
        Batch check which profiles have changed since they were cached.
        Uses batch API calls to fetch current tmdates for all profiles.
        Handles both profile IDs (~...) and email addresses.
        Logs a message for each profile that has changed.
        Returns set of canonical profile IDs that need updating.
        """
        if not member_ids:
            return set()

        # Separate profile IDs and emails
        profile_ids = [mid for mid in member_ids if mid.startswith("~")]
        email_ids = [mid for mid in member_ids if "@" in mid]

        client = get_client()
        all_profiles = []
        not_found: set[str] = set()

        # Batch fetch profiles by ID
        if profile_ids:
            try:
                profiles_by_id = client.search_profiles(ids=profile_ids)
                returned_ids = set()
                for profile in profiles_by_id:
                    all_profiles.append(profile)
                    returned_ids.add(profile.id)
                    # Store canonical ID → canonical ID mapping
                    self._id_to_canonical[profile.id] = profile.id

                # Check for input IDs that didn't match a returned canonical ID
                # These might be aliases/merged profiles, or not yet activated
                for input_id in profile_ids:
                    if (
                        input_id not in returned_ids
                        and input_id not in self._id_to_canonical
                    ):
                        # Fetch individually to resolve the alias
                        try:
                            profile = client.get_profile(input_id)
                            self._id_to_canonical[input_id] = profile.id
                            if profile.id not in returned_ids:
                                all_profiles.append(profile)
                                returned_ids.add(profile.id)
                        except Exception:
                            not_found.add(input_id)
            except Exception as e:
                log.warning(f"Failed to batch check profile IDs: {e}")
                self._profiles_needing_update = set(profile_ids)
                self._batch_check_done = True
                return self._profiles_needing_update

        # Batch fetch profiles by email
        if email_ids:
            try:
                email_results = client.search_profiles(emails=email_ids)
                # email_results is a dict: email -> list of Profile objects
                for email, profiles in email_results.items():
                    if profiles:
                        profile = profiles[0]  # Take first match
                        all_profiles.append(profile)
                        # Store email → canonical ID mapping
                        self._id_to_canonical[email] = profile.id
            except Exception as e:
                log.warning(f"Failed to batch check emails: {e}")
                # Continue with what we have

        # Load cached tmdates using canonical IDs from API response
        cached_tmdates: Dict[str, int] = {}
        for profile in all_profiles:
            canonical_id = profile.id
            cached = self._load_from_cache(canonical_id)
            if cached:
                cached_tmdates[canonical_id] = cached.get("tmdate", 0)

        # Compare tmdates and identify changes
        self._profiles_needing_update = set()
        for profile in all_profiles:
            canonical_id = profile.id
            current_tmdate = profile.tmdate
            cached_tmdate = cached_tmdates.get(canonical_id, 0)

            if canonical_id not in cached_tmdates:
                # New profile, not in cache
                log.info(f"New profile: {canonical_id}")
                self._profiles_needing_update.add(canonical_id)
            elif current_tmdate != cached_tmdate:
                # Profile has changed
                log.info(f"Changed profile: {canonical_id}")
                self._profiles_needing_update.add(canonical_id)

        # Retry profiles that weren't found (may be newly activated)
        for profile_id in not_found:
            if profile_id not in self._id_to_canonical:
                self._profiles_needing_update.add(profile_id)

        self._batch_check_done = True

        # Log summary
        if self._profiles_needing_update:
            log.info(f"Profiles to update: {len(self._profiles_needing_update)}")
        else:
            log.info("No profile changes detected")

        return self._profiles_needing_update

    def get_profile(self, profile_id: str) -> None:
        """
        Get the profile as well as all imported DBLP papers for a given ID.
        On failure, sets up a default empty profile (not cached).

        If check_profiles_for_updates() was called first, uses that info to
        skip fetching for unchanged profiles.

        If cache_only is True, only reads from cache - no API calls.
        """
        # Clear any cached result from previous calls
        if hasattr(self, "_cached_final_result"):
            del self._cached_final_result

        # Cache-only mode: try cache, return empty profile if not found
        if self.cache_only:
            # Resolve to canonical ID if we have a mapping
            canonical_id = self._id_to_canonical.get(profile_id, profile_id)
            cached_data = self._load_from_cache(canonical_id)
            if cached_data:
                self._restore_from_cache(cached_data)
                return
            # Profile not in cache - return empty profile
            self._cached_final_result = self.empty_profile(
                profile_id, status="not in cache"
            )
            return

        # If batch check was done, resolve canonical ID and check if update needed
        if self._batch_check_done and not self.recache:
            canonical_id = self._id_to_canonical.get(profile_id)
            if canonical_id and canonical_id not in self._profiles_needing_update:
                cached_data = self._load_from_cache(canonical_id)
                if cached_data:
                    self._restore_from_cache(cached_data)
                    return

        # Get the client (singleton if no args)
        client = get_client()

        # Try to get the profile; on failure, use a default empty profile
        try:
            self.profile = client.get_profile(profile_id)
        except Exception as e:
            log.warning(f"Failed to get profile for {profile_id}: {e}")
            self._cached_final_result = self.empty_profile(profile_id, str(e))
            return

        # Get the canonical profile ID for caching
        canonical_profile_id = self.profile.id

        # Update ID mapping (handles merged profiles where input ID differs from canonical)
        self._id_to_canonical[profile_id] = canonical_profile_id
        if profile_id != canonical_profile_id:
            log.debug(f"Profile {profile_id} resolved to {canonical_profile_id}")

        # If batch check was done and canonical ID doesn't need update, use cache
        if (
            self._batch_check_done
            and not self.recache
            and canonical_profile_id not in self._profiles_needing_update
        ):
            cached_data = self._load_from_cache(canonical_profile_id)
            if cached_data:
                self._restore_from_cache(cached_data)
                return

        # Check cache using canonical ID (skip if recache is True)
        # This is the fallback when no batch check was done
        if self.cache_profiles and not self.recache and not self._batch_check_done:
            cached_data = self._load_from_cache(canonical_profile_id)
            if cached_data:
                log.debug(
                    f"Profile information retrieved from cache for {canonical_profile_id}"
                )
                self._restore_from_cache(cached_data)
                return

        # Fetch publications (unless skip_publications is True)
        if self.skip_publications:
            # Keep existing publications from cache if available
            cached_data = self._load_from_cache(canonical_profile_id)
            self.papers = cached_data.get("publications", []) if cached_data else []
        else:
            # Fetch all papers for this profile from both API v1 and v2.
            #
            # NOTE: This is exactly how the web UI does it in order to show all
            # publications for a profile.
            seen_ids = set()
            raw_papers = []

            def add_papers(papers):
                for paper in papers:
                    if paper.id not in seen_ids:
                        seen_ids.add(paper.id)
                        raw_papers.append(paper)

            # Query API v2 (current API)
            try:
                add_papers(
                    client.get_all_notes(content={"authorids": canonical_profile_id})
                )
            except Exception as e:
                log.error(f"Error fetching publications from API v2: {e}")

            # Query API v1 (legacy API, contains most DBLP/ORCID imports)
            try:
                add_papers(
                    get_client_v1().get_all_notes(
                        content={"authorids": canonical_profile_id}
                    )
                )
            except Exception as e:
                log.error(f"Error fetching publications from API v1: {e}")

            # Process papers
            self.papers = []
            for paper in raw_papers:
                self.papers.append(paper.to_json())

        # Save to cache if caching is enabled (use canonical profile ID to avoid duplicates)
        if self.cache_profiles:
            self._save_to_cache(canonical_profile_id)

    def _get_cache_filename(self, profile_id: str) -> str:
        """
        Get cache filename for a profile ID, removing tildes.
        """
        clean_id = profile_id.replace("~", "")
        return f"{clean_id}.json"

    def _get_cache_path(self, profile_id: str) -> Path:
        """
        Get full cache file path for a profile ID.
        """
        cache_dir = Path(self.cache_dir)
        filename = self._get_cache_filename(profile_id)
        return cache_dir / filename

    def _load_from_cache(self, profile_id: str) -> Dict[str, Any] | None:
        """
        Load profile and papers data from cache if it exists.
        """
        cache_path = self._get_cache_path(profile_id)

        if cache_path.exists():
            try:
                with open(cache_path, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                # If cache file is corrupted, ignore it
                return None

        return None

    def _save_to_cache(self, profile_id: str) -> None:
        """
        Save current profile and papers data to cache.
        """
        cache_path = self._get_cache_path(profile_id)
        cache_dir = cache_path.parent

        # Create cache directory if it doesn't exist
        cache_dir.mkdir(exist_ok=True)

        # Pre-compute the final output format to avoid processing on load
        profile_json = self.profile.to_json()
        final_result = profile_json.copy()
        final_result["publications"] = self.papers

        # Include active/state fields (not in to_json() but useful for filtering)
        if hasattr(self.profile, "active"):
            final_result["active"] = self.profile.active
        if hasattr(self.profile, "state"):
            final_result["state"] = self.profile.state

        # Save to cache file using JSON
        try:
            with open(cache_path, "w") as f:
                json.dump(final_result, f, indent=2)
        except IOError:
            # If we can't write to cache, just continue without caching
            pass

    def _restore_from_cache(self, cached_data: Dict[str, Any]) -> None:
        """
        Restore profile and papers from cached data.
        """
        # Store the pre-computed final result
        self._cached_final_result = cached_data

    def asJson(self) -> Dict[str, Any]:
        """
        Return profile and papers information as a dictionary.
        """
        # Check if we have cached final result
        if hasattr(self, "_cached_final_result"):
            return self._cached_final_result

        # Build result from live data
        if not self.profile:
            raise ValueError("Profile not loaded. Call get_profile() first.")

        result = self.profile.to_json()
        result["publications"] = self.papers
        return result

    def _add_default_person_triples(self, rdf: Rdf, person_iri: str) -> None:
        """
        Add all standard person triples with :novalue (or "0" for counts).
        Used when profile data is unavailable.
        """
        rdf.add_triple(person_iri, ":id", ":novalue")
        rdf.add_triple(person_iri, ":state", ":novalue")
        rdf.add_triple(person_iri, ":gender", ":novalue")
        rdf.add_triple(person_iri, ":dblp_id", ":novalue")
        rdf.add_triple(person_iri, ":orcid", ":novalue")
        rdf.add_triple(person_iri, ":email", ":novalue")
        rdf.add_triple(person_iri, "rdfs:label", ":novalue")
        rdf.add_triple(person_iri, ":position", ":novalue")
        rdf.add_triple(person_iri, ":institution", ":novalue")
        rdf.add_triple(person_iri, ":country", ":novalue")
        rdf.add_triple(person_iri, ":num_publications", "0")
        rdf.add_triple(person_iri, ":num_relations", "0")

    def addToRdf(
        self,
        rdf: Rdf,
        profile_data: Dict[str, Any],
        person_id: str = "",
        submission_ids: set[str] | None = None,
        processed_publications: set[str] | None = None,
        processed_persons: set[str] | None = None,
    ) -> str:
        """
        Add profile triples to an existing Rdf instance.
        If profile_data has an error, adds default triples with :novalue.
        If person_id is provided, use that for the IRI; otherwise use profile_data's id.
        If submission_ids is provided, profile publications not in that set get
        type :Publication and :status "published".
        If processed_publications is provided, it tracks which publications have
        already had their type/status added (to avoid duplicates).
        If processed_persons is provided, it tracks which persons have already
        had their :num_publications added (to avoid duplicates).
        Returns the person IRI for additional triples.
        """
        effective_id = person_id if person_id else profile_data.get("id", "")
        if not effective_id:
            return ""

        person_iri = rdf.personIri(effective_id)

        # If profile data is unavailable (error or status only), add default triples
        if profile_data.get("error") or profile_data.get("status"):
            self._add_default_person_triples(rdf, person_iri)
            return person_iri

        # Add profile ID
        profile_id = profile_data.get("id", "")
        rdf.add_triple(
            person_iri, ":id", rdf.literal(profile_id) if profile_id else ":novalue"
        )

        # Add profile state (Active Institutional, Needs Moderation, etc.)
        state = profile_data.get("state", "")
        rdf.add_triple(
            person_iri, ":state", rdf.literal(state) if state else ":novalue"
        )

        # Add properties
        rdf.add_triple(
            person_iri, ":gender", rdf.literalFromJson(profile_data, "content.gender")
        )
        dblp_id = rdf.urlFromJson(profile_data, "content.dblp")
        if dblp_id.endswith(".html>"):
            dblp_id = dblp_id[:-6] + ">"  # Remove .html but keep >
        rdf.add_triple(person_iri, ":dblp_id", dblp_id)
        rdf.add_triple(
            person_iri, ":orcid", rdf.urlFromJson(profile_data, "content.orcid")
        )
        rdf.add_triple(
            person_iri,
            ":email",
            rdf.literalFromJson(profile_data, "content.preferredEmail"),
        )

        # Get fullname from the first (preferred) name
        names = profile_data.get("content", {}).get("names", [])
        if names and len(names) > 0:
            fullname = names[0].get("fullname", "")
            if fullname:
                fullname_literal = rdf.literal(fullname)
            else:
                fullname_literal = ":novalue"
        else:
            fullname_literal = ":novalue"
        rdf.add_triple(person_iri, "rdfs:label", fullname_literal)

        # Add current position and institution from history (first entry)
        history = profile_data.get("content", {}).get("history", [])
        current = history[0] if history else {}
        rdf.add_triple(
            person_iri, ":position", rdf.literalFromJson(current, "position")
        )
        rdf.add_triple(
            person_iri, ":institution", rdf.literalFromJson(current, "institution.name")
        )
        rdf.add_triple(
            person_iri, ":country", rdf.literalFromJson(current, "institution.country")
        )

        # Add publications and collect co-authors
        papers = profile_data.get("publications", [])
        coauthors: set[str] = set()
        # Get this person's name for exclusion from co-authors
        person_name = ""
        if names and len(names) > 0:
            person_name = names[0].get("fullname", "")

        for paper in papers:
            paper_id = paper["id"]
            paper_iri = rdf.paperIri(paper_id)
            rdf.add_triple(person_iri, ":publication", paper_iri)
            # Add triples for profile publications that aren't venue submissions
            # Skip if already processed (shared by multiple authors)
            if submission_ids is None or paper_id not in submission_ids:
                if (
                    processed_publications is None
                    or paper_id not in processed_publications
                ):
                    rdf.add_triple(paper_iri, "a", ":Publication")
                    rdf.add_triple(paper_iri, ":status", rdf.literal("published"))
                    # Add title (can be string or dict with 'value' key)
                    title = paper.get("content", {}).get("title", "")
                    if isinstance(title, dict):
                        title = title.get("value", "")
                    if title:
                        title_literal = rdf.literal(title)
                        rdf.add_triple(paper_iri, ":title", title_literal)
                        rdf.add_triple(paper_iri, "rdfs:label", title_literal)
                    if processed_publications is not None:
                        processed_publications.add(paper_id)
            dblp_iri = rdf.dblpUrlFromBibtex(paper)
            if dblp_iri:
                rdf.add_triple(person_iri, ":dblp_publication", dblp_iri)
            # Collect co-authors from this paper
            paper_authors = paper.get("content", {}).get("authors", [])
            if isinstance(paper_authors, dict):
                paper_authors = paper_authors.get("value", [])
            for author_name in paper_authors:
                if author_name and author_name != person_name:
                    coauthors.add(author_name)

        # Count publications with :status "published" (those not in submission_ids)
        if processed_persons is None or effective_id not in processed_persons:
            num_published = sum(
                1
                for p in papers
                if submission_ids is None or p["id"] not in submission_ids
            )
            rdf.add_triple(person_iri, ":num_publications", str(num_published))
            if processed_persons is not None:
                processed_persons.add(effective_id)

        # Add co-author triples (each unique co-author once)
        # Clean suffixes like " 0001" (space + exactly 4 digits)
        cleaned_coauthors = {re.sub(r" \d{4}$", "", name) for name in coauthors}
        for coauthor in cleaned_coauthors:
            rdf.add_triple(person_iri, ":has_coauthor", rdf.literal(coauthor))

        # Add relations (advisors, etc.)
        relations = profile_data.get("content", {}).get("relations", [])
        for rel in relations:
            username = rel.get("username", "")
            name = rel.get("name", "")
            if username:
                # Resolve to canonical ID
                canonical_username = self.resolve_id(username)
                rdf.add_triple(person_iri, ":relation_id", rdf.personIri(canonical_username))
            if name:
                rdf.add_triple(person_iri, ":relation_name", rdf.literal(name))
        rdf.add_triple(person_iri, ":num_relations", str(len(relations)))

        return person_iri

    def asRdf(self) -> str:
        """
        Return profile information as RDF triples.
        """
        # Get profile data (either cached or live)
        if hasattr(self, "_cached_final_result"):
            profile_data = self._cached_final_result
        else:
            if not self.profile:
                raise ValueError("Profile not loaded. Call get_profile() first.")
            profile_data = self.profile.to_json()
            profile_data["publications"] = self.papers

        # Generate RDF output
        rdf = Rdf()
        self.addToRdf(rdf, profile_data)
        return rdf.as_turtle()
