"""Compatibility import for host-side reporters.

The dashboard image copies the implementation as a top-level module, while
repository scripts import it from the shared ``ft_userdata`` path.
"""

from ft_dashboard.hyperliquid_reconciliation import *  # noqa: F401,F403
