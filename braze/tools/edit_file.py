from .confine import resolve


def edit_file(path: str, old_text: str, new_text: str) -> str:
    """Replace one exact block of text in a file."""
    file_path = resolve(path)
    if not file_path.is_file():
        return f"Error: no such file: '{path}'. Use list_dir to see what exists."

    original = file_path.read_text(encoding="utf-8")
    count = original.count(old_text)
    if count == 0:
        return (
            f"Error: old_text was not found in '{path}'. Read the file again and copy "
            "the exact text, including indentation."
        )
    # Ambiguity is what silently edits the wrong call site, so refuse rather than guess.
    if count > 1:
        return (
            f"Error: old_text appears {count} times in '{path}'. Include more "
            "surrounding lines so it matches exactly once."
        )

    file_path.write_text(original.replace(old_text, new_text), encoding="utf-8")
    return f"edited {path} (-{len(old_text.splitlines())} +{len(new_text.splitlines())} lines)"
