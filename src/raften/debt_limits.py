"""Linear, non-allocating structural preflight before JSON materialization."""

from raften import resource_limits as limits


def preflight_manifest(text: str, source_path: str) -> None:
    """Bound decoder work; the JSON decoder remains the syntax authority."""

    stack: list[tuple[str, int]] = []
    position = tokens = 0

    def require(resource: str, actual: int, limit: int) -> None:
        limits.require_resource(resource, actual, limit,
                                operation="parse-manifest", path=source_path)

    while position < len(text):
        character = text[position]
        if character in " \t\r\n":
            position += 1
            continue
        tokens += 1
        require("manifest_tokens", tokens, limits.MAX_MANIFEST_TOKENS)
        if stack and stack[-1] == ("[", 0) and character != "]":
            stack[-1] = ("[", 1)
            require("manifest_array_items", 1, limits.MAX_MANIFEST_ENTRIES)
        if character in "[{":
            require("manifest_depth", len(stack) + 1, limits.MAX_MANIFEST_DEPTH)
            stack.append((character, 0))
        elif character in "]}":
            if stack:
                stack.pop()
        elif character == ":" and stack and stack[-1][0] == "{":
            count = stack[-1][1] + 1
            require("manifest_object_keys", count, limits.MAX_MANIFEST_OBJECT_KEYS)
            stack[-1] = ("{", count)
        elif character == "," and stack and stack[-1][0] == "[":
            count = stack[-1][1] + 1
            require("manifest_array_items", count, limits.MAX_MANIFEST_ENTRIES)
            stack[-1] = ("[", count)
        elif character == '"':
            position += 1
            while position < len(text):
                current = text[position]
                position += 1
                if current == "\\":
                    position += 1
                elif current == '"':
                    break
            continue
        elif character not in ",:":
            start = position
            while position < len(text) and text[position] not in ' \t\r\n{}[],:"':
                position += 1
            if character in "-0123456789":
                require("manifest_number_characters", position - start,
                        limits.MAX_MANIFEST_NUMBER_CHARACTERS)
            continue
        position += 1
