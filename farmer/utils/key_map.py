"""Key name to CDP key definition mapping.

Maps human-readable key names (e.g., ``"Enter"``, ``"a"``) to
the ``key``, ``code``, ``keyCode``, and ``text`` fields required
by ``Input.dispatchKeyEvent``.
"""

# Standard key definitions
KEY_DEFINITIONS = {
    # Function keys
    "F1": {"key": "F1", "code": "F1", "keyCode": 112},
    "F2": {"key": "F2", "code": "F2", "keyCode": 113},
    "F3": {"key": "F3", "code": "F3", "keyCode": 114},
    "F4": {"key": "F4", "code": "F4", "keyCode": 115},
    "F5": {"key": "F5", "code": "F5", "keyCode": 116},
    "F6": {"key": "F6", "code": "F6", "keyCode": 117},
    "F7": {"key": "F7", "code": "F7", "keyCode": 118},
    "F8": {"key": "F8", "code": "F8", "keyCode": 119},
    "F9": {"key": "F9", "code": "F9", "keyCode": 120},
    "F10": {"key": "F10", "code": "F10", "keyCode": 121},
    "F11": {"key": "F11", "code": "F11", "keyCode": 122},
    "F12": {"key": "F12", "code": "F12", "keyCode": 123},
    # Navigation
    "Enter": {"key": "Enter", "code": "Enter", "keyCode": 13},
    "Tab": {"key": "Tab", "code": "Tab", "keyCode": 9},
    "Escape": {"key": "Escape", "code": "Escape", "keyCode": 27},
    "Backspace": {"key": "Backspace", "code": "Backspace", "keyCode": 8},
    "Delete": {"key": "Delete", "code": "Delete", "keyCode": 46},
    "Insert": {"key": "Insert", "code": "Insert", "keyCode": 45},
    "Home": {"key": "Home", "code": "Home", "keyCode": 36},
    "End": {"key": "End", "code": "End", "keyCode": 35},
    "PageUp": {"key": "PageUp", "code": "PageUp", "keyCode": 33},
    "PageDown": {"key": "PageDown", "code": "PageDown", "keyCode": 34},
    # Arrow keys
    "ArrowLeft": {"key": "ArrowLeft", "code": "ArrowLeft", "keyCode": 37},
    "ArrowUp": {"key": "ArrowUp", "code": "ArrowUp", "keyCode": 38},
    "ArrowRight": {"key": "ArrowRight", "code": "ArrowRight", "keyCode": 39},
    "ArrowDown": {"key": "ArrowDown", "code": "ArrowDown", "keyCode": 40},
    # Modifiers
    "Shift": {"key": "Shift", "code": "ShiftLeft", "keyCode": 16},
    "Control": {"key": "Control", "code": "ControlLeft", "keyCode": 17},
    "Alt": {"key": "Alt", "code": "AltLeft", "keyCode": 18},
    "Meta": {"key": "Meta", "code": "MetaLeft", "keyCode": 91},
    # Special
    "Space": {"key": " ", "code": "Space", "keyCode": 32},
    " ": {"key": " ", "code": "Space", "keyCode": 32},
    "CapsLock": {"key": "CapsLock", "code": "CapsLock", "keyCode": 20},
}

# Modifier name → modifier flag bitmask
MODIFIER_FLAGS = {
    "Alt": 1,
    "Control": 2,
    "Meta": 4,
    "Shift": 8,
}


def get_key_definition(key: str) -> dict:
    """Get the CDP key definition for ``Input.dispatchKeyEvent``.

    Args:
        key: Key name (e.g., ``"Enter"``, ``"a"``, ``"F1"``).

    Returns:
        Dict with ``key``, ``code``, ``keyCode``, and optionally
        ``text`` (for printable characters).
    """
    if key in KEY_DEFINITIONS:
        return dict(KEY_DEFINITIONS[key])

    # Single printable character
    if len(key) == 1:
        code = f"Key{key.upper()}" if key.isalpha() else ""
        if key.isdigit():
            code = f"Digit{key}"
        key_code = ord(key.upper()) if key.isalpha() else ord(key)
        return {
            "key": key,
            "code": code,
            "keyCode": key_code,
            "text": key,
        }

    # Unknown key — pass through
    return {"key": key, "code": key, "keyCode": 0}


def get_modifier_mask(modifiers: list[str] = None) -> int:
    """Calculate the CDP modifier bitmask from modifier key names.

    Args:
        modifiers: List of modifier names (e.g., ``["Control", "Shift"]``).

    Returns:
        Bitmask integer (Alt=1, Control=2, Meta=4, Shift=8).
    """
    if not modifiers:
        return 0
    mask = 0
    for mod in modifiers:
        mask |= MODIFIER_FLAGS.get(mod, 0)
    return mask
