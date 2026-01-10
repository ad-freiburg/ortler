"""
Base command class for all CLI commands.
"""

from abc import ABC, abstractmethod
from argparse import ArgumentParser, Namespace


class Command(ABC):
    """
    Abstract base class for all commands.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """
        The command name (used for the subcommand).

        Returns:
            Command name (e.g., 'submit', 'users')
        """
        pass

    @property
    @abstractmethod
    def help(self) -> str:
        """
        Short help text for the command.

        Returns:
            Help text shown in command list
        """
        pass

    @abstractmethod
    def add_arguments(self, parser: ArgumentParser) -> None:
        """
        Add command-specific arguments to the argument parser.

        Args:
            parser: argparse.ArgumentParser instance for this command
        """
        pass

    @abstractmethod
    def execute(self, args: Namespace) -> None:
        """
        Execute the command with the given arguments.

        Args:
            args: Parsed command-line arguments from argparse
        """
        pass
