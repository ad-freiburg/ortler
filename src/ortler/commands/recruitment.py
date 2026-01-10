"""
Recruitment command for managing reviewers, area chairs, and senior area chairs.
"""

from argparse import ArgumentParser, Namespace

import openreview

from ..command import Command
from ..client import get_client
from ..utils import get_random_profiles
from ..log import log


class RecruitmentCommand(Command):
    """
    Manage recruitment of reviewers, area chairs, and senior area chairs for the venue.
    """

    @property
    def name(self) -> str:
        return "recruitment"

    @property
    def help(self) -> str:
        return "Manage recruitment for the venue"

    def add_arguments(self, parser: ArgumentParser) -> None:
        """
        Add recruitment command arguments.
        """
        parser.add_argument(
            "--role",
            choices=["pc", "spc", "ac"],
            help="Role type: pc (reviewers), spc (area chairs), ac (senior area chairs)",
        )
        parser.add_argument(
            "--add",
            nargs="+",
            metavar=("GROUP", "USER_ID"),
            help="Add users to a group: --add {accepted,invited,declined} USER_ID [USER_ID ...]",
        )
        parser.add_argument(
            "--remove",
            nargs="+",
            metavar=("GROUP", "USER_ID"),
            help="Remove users from a group: --remove {accepted,invited,declined} USER_ID [USER_ID ...]",
        )
        parser.add_argument(
            "--add-random",
            type=int,
            metavar="K",
            help="Add K random members to the specified role",
        )
        parser.add_argument(
            "--set-reduced-load",
            nargs=2,
            metavar=("PROFILE_ID", "LOAD"),
            help="Set reduced load for a member (e.g., --set-reduced-load ~John_Doe1 2)",
        )
        parser.add_argument(
            "--only-show",
            action="store_true",
            help="Only show what would be added without actually adding",
        )
        parser.add_argument(
            "--search",
            metavar="USER",
            help="Search for a profile ID or email and show all group memberships",
        )

    def execute(self, args: Namespace) -> None:
        """
        Execute recruitment command.
        """
        # Get the singleton client (initialized in main.py)
        client = get_client()

        if args.search:
            self._search_user(args, client)
            return

        # All other actions require --role
        if not args.role:
            log.error("--role is required for this action")
            return

        if args.add:
            if len(args.add) < 2:
                log.error("--add requires GROUP and at least one USER_ID")
                return
            to_group = args.add[0]
            if to_group not in ("accepted", "invited", "declined"):
                log.error(
                    f"Invalid group '{to_group}'. Must be accepted, invited, or declined."
                )
                return
            self._add_specific_members(args, client, to_group, args.add[1:])
        elif args.remove:
            if len(args.remove) < 2:
                log.error("--remove requires GROUP and at least one USER_ID")
                return
            from_group = args.remove[0]
            if from_group not in ("accepted", "invited", "declined"):
                log.error(
                    f"Invalid group '{from_group}'. Must be accepted, invited, or declined."
                )
                return
            self._remove_specific_members(args, client, from_group, args.remove[1:])
        elif args.add_random:
            self._add_random_members(args, client)
        elif args.set_reduced_load:
            self._set_reduced_load(args, client)
        else:
            log.info(
                "No action specified. Use --add, --remove, --add-random, or --set-reduced-load."
            )

    def _search_user(self, args: Namespace, client) -> None:
        """
        Search for a user and show all their group memberships and recruitment status.
        Uses optimized API calls: 1 for profile, 1 for all groups, 3 for recruitment notes.
        """
        user_id = args.search

        # Resolve to canonical profile ID and get all emails (1 API call)
        try:
            profile = client.get_profile(user_id)
            canonical_id = profile.id
            profile_emails = set(profile.content.get("emails", []))
            names = profile.content.get("names", [])
            fullname = names[0].get("fullname", "") if names else ""
            log.info(f"Profile: {fullname} ({canonical_id})")
            log.info(f"Emails: {', '.join(profile_emails)}")
        except Exception as e:
            log.error(f"Could not find profile for '{user_id}': {e}")
            return

        # Get all groups the user is a member of
        log.info("")
        log.info("Group memberships:")

        user_groups = []
        # Query by profile ID and each email (some groups use emails as member IDs)
        for member_id in [canonical_id] + list(profile_emails):
            try:
                user_groups.extend(
                    client.get_groups(member=member_id, prefix=args.venue_id)
                )
            except Exception:
                pass  # No groups found for this identifier

        # Deduplicate by group ID
        seen_ids = set()
        unique_groups = []
        for g in user_groups:
            if g.id not in seen_ids:
                seen_ids.add(g.id)
                unique_groups.append(g)

        if unique_groups:
            for group in unique_groups:
                log.info(group.id)
        else:
            log.info("(none)")

        # Check for recruitment notes (3 API calls, filter locally)
        log.info("")
        log.info("Recruitment notes:")
        found_notes = False

        for role in ["pc", "spc", "ac"]:
            group_suffix = self._get_group_suffix(role)
            invitation = f"{args.venue_id}/{group_suffix}/-/Recruitment"

            try:
                notes = client.get_all_notes(invitation=invitation)
                for note in notes:
                    user_email = note.content.get("user", {}).get("value", "")
                    if user_email in profile_emails:
                        found_notes = True
                        response = note.content.get("response", {}).get("value", "N/A")
                        reduced_load = note.content.get("reduced_load", {}).get(
                            "value", ""
                        )
                        msg = f"{invitation}: response={response}"
                        if reduced_load:
                            msg += f", reduced_load={reduced_load}"
                        log.info(msg)
            except Exception:
                pass

        if not found_notes:
            log.info("(none)")

    def _get_group_suffix(self, role: str) -> str:
        """
        Map CLI role name to OpenReview group suffix.
        """
        role_mapping = {
            "pc": "Reviewers",
            "spc": "Area_Chairs",
            "ac": "Senior_Area_Chairs",
        }
        return role_mapping[role]

    def _get_role_display_name(self, role: str) -> str:
        """
        Get human-readable display name for role.
        """
        display_names = {
            "pc": "PC aka Reviewers",
            "spc": "SPC aka Area Chairs",
            "ac": "AC aka Senior Area Chairs",
        }
        return display_names[role]

    def _get_placeholder_prefix(self, role: str) -> str:
        """
        Get placeholder prefix for random profile generation.
        """
        prefixes = {
            "pc": "Random PC",
            "spc": "Random SPC",
            "ac": "Random AC",
        }
        return prefixes[role]

    def _get_reduced_loads(self, args: Namespace, client) -> dict[str, int]:
        """
        Fetch reduced_load values from recruitment notes.
        Returns a dict mapping user email/profile ID to their reduced load as integer.
        """
        group_suffix = self._get_group_suffix(args.role)
        recruitment_invitation = f"{args.venue_id}/{group_suffix}/-/Recruitment"

        reduced_loads = {}
        try:
            notes = client.get_all_notes(invitation=recruitment_invitation)
            for note in notes:
                content = note.content
                if "reduced_load" in content and content["reduced_load"].get("value"):
                    user = content.get("user", {}).get("value", "")
                    load_str = content["reduced_load"]["value"]
                    if user and load_str:
                        try:
                            reduced_loads[user] = int(load_str)
                        except ValueError:
                            pass
        except Exception as e:
            log.warning(f"Could not fetch recruitment notes: {e}")

        return reduced_loads

    def _set_reduced_load(self, args: Namespace, client) -> None:
        """
        Set the reduced load for a member by updating their recruitment note.
        """
        profile_id, load_str = args.set_reduced_load

        try:
            load = int(load_str)
        except ValueError:
            log.error(f"Invalid load value: {load_str}. Must be an integer.")
            return

        group_suffix = self._get_group_suffix(args.role)
        recruitment_invitation = f"{args.venue_id}/{group_suffix}/-/Recruitment"

        # Resolve profile ID to canonical form and get emails
        try:
            profile = client.get_profile(profile_id)
            canonical_id = profile.id
            profile_emails = set(profile.content.get("emails", []))
            log.info(f"Setting reduced load for {canonical_id} to {load}")
        except Exception as e:
            log.error(f"Could not find profile {profile_id}: {e}")
            return

        # Find the recruitment note for this user (by email)
        try:
            notes = client.get_all_notes(invitation=recruitment_invitation)
            recruitment_note = None
            for note in notes:
                user_email = note.content.get("user", {}).get("value", "")
                if user_email in profile_emails:
                    recruitment_note = note
                    break

            if not recruitment_note:
                # Check if user is actually in the confirmed group
                try:
                    group = client.get_group(f"{args.venue_id}/{group_suffix}")
                    is_member = canonical_id in (group.members or [])
                except Exception:
                    is_member = False

                if is_member:
                    log.error(
                        f"No recruitment note found for {canonical_id}. "
                        "The user was added directly to the group without "
                        "going through recruitment."
                    )
                    log.info(
                        "To set reduced load, send them a recruitment email via "
                        "OpenReview UI first, then use this command after they respond."
                    )
                else:
                    log.error(
                        f"No recruitment note found for {canonical_id}. "
                        "The user may not have responded to recruitment yet."
                    )
                return

        except Exception as e:
            log.error(f"Could not fetch recruitment notes: {e}")
            return

        # Update the recruitment note with the new reduced_load using the meta Edit invitation
        try:
            client.post_note_edit(
                invitation=f"{args.venue_id}/-/Edit",
                signatures=[args.venue_id],
                note=openreview.api.Note(
                    id=recruitment_note.id,
                    content={
                        "reduced_load": {"value": str(load)},
                    },
                ),
            )
            log.info(f"Successfully set reduced load for {canonical_id} to {load}")
        except Exception as e:
            log.error(f"Could not update recruitment note: {e}")

    def _add_specific_members(
        self, args: Namespace, client, to_group: str, user_ids: list[str]
    ) -> None:
        """
        Add specific members by ID to the specified role group.
        """
        role_display = self._get_role_display_name(args.role)
        log.info(f"Adding {len(user_ids)} to {to_group} {role_display}...")

        # Get the group based on to_group
        group_suffix = self._get_group_suffix(args.role)
        if to_group == "accepted":
            group_id = f"{args.venue_id}/{group_suffix}"
        elif to_group == "invited":
            group_id = f"{args.venue_id}/{group_suffix}/Invited"
        else:  # declined
            group_id = f"{args.venue_id}/{group_suffix}/Declined"

        try:
            group = client.get_group(group_id)
            log.info(f"Found existing group: {group_id}")
            existing_members = set(group.members or [])
        except Exception:
            log.info(f"Group {group_id} does not exist yet.")
            log.info("Creating it would require appropriate permissions.")
            existing_members = set()

        # Fetch profile information and check for duplicates
        log.info(f"\n{role_display.capitalize()} to add:")
        new_count = 0
        duplicate_count = 0
        names = []

        for user_id in user_ids:
            # Try to get profile information
            try:
                if user_id.startswith("~") or "@" in user_id:
                    profile = client.get_profile(user_id)
                    name = (
                        profile.get_preferred_name()
                        if hasattr(profile, "get_preferred_name")
                        else user_id
                    )
                else:
                    name = user_id
            except Exception:
                name = user_id

            names.append(name)

            if user_id in existing_members:
                log.info(f"  - {name} ({user_id}) [ALREADY A MEMBER]")
                duplicate_count += 1
            else:
                log.info(f"  - {name} ({user_id})")
                new_count += 1

        log.info("\nSummary:")
        log.info(f"  New {role_display}: {new_count}")
        log.info(f"  Already members: {duplicate_count}")
        log.info(f"  Total: {len(user_ids)}")

        if new_count > 0:
            # Prepare the updated members list
            new_members = list(existing_members.union(set(user_ids)))

            if args.only_show:
                log.info(
                    f"\nTo add these {role_display}, the group would need to be updated with:"
                )
                log.info(f"  Group ID: {group_id}")
                log.info(f"  Total members after addition: {len(new_members)}")
                log.info(
                    f"\nNote: This is a preview only. Run without --only-show to actually add {role_display}."
                )
            else:
                # Actually add the members
                log.info("\nUpdating group...")
                try:
                    # Add only the new members (not duplicates)
                    new_member_ids = [
                        uid for uid in user_ids if uid not in existing_members
                    ]
                    client.add_members_to_group(group_id, new_member_ids)
                    log.info(
                        f"Successfully added {new_count} new {role_display} to {group_id}"
                    )
                    log.info(f"  Total members now: {len(new_members)}")
                except Exception as e:
                    log.error(f" Failed to update group: {e}")
        else:
            log.info(f"\nNo new {role_display} to add (all are already members).")

    def _remove_specific_members(
        self, args: Namespace, client, from_group: str, user_ids: list[str]
    ) -> None:
        """
        Remove specific members by ID from the specified role group.
        """
        role_display = self._get_role_display_name(args.role)
        log.info(f"Removing {len(user_ids)} from {from_group} {role_display}...")

        # Get the group based on from_group
        group_suffix = self._get_group_suffix(args.role)
        if from_group == "accepted":
            group_id = f"{args.venue_id}/{group_suffix}"
        elif from_group == "invited":
            group_id = f"{args.venue_id}/{group_suffix}/Invited"
        else:  # declined
            group_id = f"{args.venue_id}/{group_suffix}/Declined"

        try:
            group = client.get_group(group_id)
            log.info(f"Found existing group: {group_id}")
            existing_members = set(group.members or [])
        except Exception as e:
            log.error(f" Could not fetch group {group_id}: {e}")
            return

        # Fetch profile information and check membership
        log.info(f"\n{role_display.capitalize()} to remove:")
        remove_count = 0
        not_member_count = 0
        names = []

        for user_id in user_ids:
            # Try to get profile information
            try:
                if user_id.startswith("~") or "@" in user_id:
                    profile = client.get_profile(user_id)
                    name = (
                        profile.get_preferred_name()
                        if hasattr(profile, "get_preferred_name")
                        else user_id
                    )
                else:
                    name = user_id
            except Exception:
                name = user_id

            names.append(name)

            if user_id in existing_members:
                log.info(f"  - {name} ({user_id})")
                remove_count += 1
            else:
                log.info(f"  - {name} ({user_id}) [NOT A MEMBER]")
                not_member_count += 1

        log.info("\nSummary:")
        log.info(f"  To remove: {remove_count}")
        log.info(f"  Not members: {not_member_count}")
        log.info(f"  Total: {len(user_ids)}")

        if remove_count > 0:
            # Prepare the updated members list
            remaining_members = [m for m in existing_members if m not in user_ids]

            if args.only_show:
                log.info(
                    f"\nTo remove these {role_display}, the group would need to be updated with:"
                )
                log.info(f"  Group ID: {group_id}")
                log.info(f"  Total members after removal: {len(remaining_members)}")
                log.info(
                    f"\nNote: This is a preview only. Run without --only-show to actually remove {role_display}."
                )
            else:
                # Actually remove the members
                log.info("\nUpdating group...")
                try:
                    # Remove only the members that exist
                    members_to_remove = [
                        uid for uid in user_ids if uid in existing_members
                    ]
                    client.remove_members_from_group(group_id, members_to_remove)
                    log.info(
                        f"Successfully removed {remove_count} {role_display} from {group_id}"
                    )
                    log.info(f"  Total members now: {len(remaining_members)}")
                except Exception as e:
                    log.error(f" Failed to update group: {e}")
        else:
            log.info(f"\nNo {role_display} to remove (none are members).")

    def _add_random_members(self, args: Namespace, client) -> None:
        """
        Add random members to the specified role group.
        """
        num_members = args.add_random
        role_display = self._get_role_display_name(args.role)
        log.info(f"Adding {num_members} random {role_display} to {args.venue_id}...")

        # Get random profiles
        log.info(f"Finding {num_members} random profiles...")
        names, profile_ids = get_random_profiles(
            client,
            num_members,
            placeholder_prefix=self._get_placeholder_prefix(args.role),
        )

        # Get the group
        group_suffix = self._get_group_suffix(args.role)
        group_id = f"{args.venue_id}/{group_suffix}"

        try:
            group = client.get_group(group_id)
            log.info(f"Found existing group: {group_id}")
            existing_members = set(group.members or [])
        except Exception:
            log.info(f"Group {group_id} does not exist yet.")
            log.info("Creating it would require appropriate permissions.")
            existing_members = set()

        # Display the members that would be added
        log.info(f"\n{role_display.capitalize()} to add:")
        new_count = 0
        duplicate_count = 0

        for name, profile_id in zip(names, profile_ids):
            if profile_id in existing_members:
                log.info(f"  - {name} ({profile_id}) [ALREADY A MEMBER]")
                duplicate_count += 1
            else:
                log.info(f"  - {name} ({profile_id})")
                new_count += 1

        log.info("\nSummary:")
        log.info(f"  New {role_display}: {new_count}")
        log.info(f"  Already members: {duplicate_count}")
        log.info(f"  Total: {len(profile_ids)}")

        if new_count > 0:
            # Prepare the updated members list
            new_members = list(existing_members.union(set(profile_ids)))

            if args.only_show:
                log.info(
                    f"\nTo add these {role_display}, the group would need to be updated with:"
                )
                log.info(f"  Group ID: {group_id}")
                log.info(f"  Total members after addition: {len(new_members)}")
                log.info(
                    f"\nNote: This is a preview only. Run without --only-show to actually add {role_display}."
                )
            else:
                # Actually add the members
                log.info("\nUpdating group...")
                try:
                    # Add only the new members (not duplicates)
                    new_member_ids = [
                        pid for pid in profile_ids if pid not in existing_members
                    ]
                    client.add_members_to_group(group_id, new_member_ids)
                    log.info(
                        f"Successfully added {new_count} new {role_display} to {group_id}"
                    )
                    log.info(f"  Total members now: {len(new_members)}")
                except Exception as e:
                    log.error(f" Failed to update group: {e}")
        else:
            log.info(f"\nNo new {role_display} to add (all are already members).")
