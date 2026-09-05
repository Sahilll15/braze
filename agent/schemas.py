"""Tool arguments.

Each class is the single definition of one tool's inputs: the docstring becomes
the description the model reads, the fields become the JSON Schema it is given,
and the same class validates whatever comes back.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ReadFileArgs(BaseModel):
    """Read a UTF-8 text file from the workspace."""

    path: str = Field(description="File path relative to the workspace root.")
    start_line: int = Field(1, description="1-indexed line to start from.")
    max_lines: int = Field(400, description="Maximum number of lines to return.")


class WriteFileArgs(BaseModel):
    """Create a new file, or replace one entirely. Prefer edit_file for changes to existing files."""

    path: str = Field(description="File path relative to the workspace root.")
    content: str = Field(description="The complete contents of the file.")


class EditFileArgs(BaseModel):
    """Replace one exact block of text in a file. Fails unless old_text appears exactly once."""

    path: str = Field(description="File path relative to the workspace root.")
    old_text: str = Field(
        description=(
            "The exact text to replace, copied from the file including its indentation. "
            "Include enough surrounding lines to make it unique."
        )
    )
    new_text: str = Field(description="The text to put in its place. Use an empty string to delete.")


class ListDirArgs(BaseModel):
    """List the entries of a directory in the workspace."""

    path: str = Field(".", description="Directory path relative to the workspace root.")


class GrepArgs(BaseModel):
    """Search the workspace for a regular expression and return matching lines with their paths."""

    pattern: str = Field(description="A Python regular expression.")
    path: str = Field(".", description="Directory or file to search, relative to the workspace root.")
    max_results: int = Field(60, description="Maximum number of matching lines to return.")


class RunCommandArgs(BaseModel):
    """Run a shell command in the workspace and return its exit code, stdout and stderr."""

    command: str = Field(description="The command to run, as you would type it in a shell.")
    reason: str = Field(description="One short sentence on why this command is needed.")


class FinishArgs(BaseModel):
    """Declare the task complete and stop. Call this exactly once, last."""

    summary: str = Field(description="What you changed and how you verified it.")
