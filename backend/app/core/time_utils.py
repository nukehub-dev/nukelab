"""
Time duration parsing utilities.
"""

import re


def parse_duration(duration_str: str) -> int:
    """
    Parse a duration string into seconds.
    
    Supports formats like:
    - "30m" -> 1800 seconds
    - "1h" -> 3600 seconds  
    - "24h" -> 86400 seconds
    - "1d" -> 86400 seconds
    - "1w" -> 604800 seconds
    
    Returns seconds as integer.
    """
    if not duration_str:
        return 0
    
    duration_str = str(duration_str).strip().lower()
    
    # Try to parse as plain integer (assume seconds)
    try:
        return int(duration_str)
    except ValueError:
        pass
    
    # Parse with units
    match = re.match(r'^(\d+(?:\.\d+)?)\s*([smhdw])$', duration_str)
    if not match:
        raise ValueError(f"Invalid duration format: {duration_str}. Use formats like '30m', '1h', '24h', '1d'")
    
    value = float(match.group(1))
    unit = match.group(2)
    
    multipliers = {
        's': 1,
        'm': 60,
        'h': 3600,
        'd': 86400,
        'w': 604800,
    }
    
    return int(value * multipliers[unit])


def format_duration(seconds: int) -> str:
    """Format seconds into a human-readable duration string."""
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        return f"{seconds // 60}m"
    elif seconds < 86400:
        return f"{seconds // 3600}h"
    elif seconds < 604800:
        return f"{seconds // 86400}d"
    else:
        return f"{seconds // 604800}w"
