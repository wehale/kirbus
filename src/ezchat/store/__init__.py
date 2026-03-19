"""ezchat state persistence — ~/.ezchat/"""
from .channels import load_channels, save_channels
from .history  import load_cmd_history, save_cmd_history
from .log      import (
    append_message,
    conv_path,
    now_ts,
    read_recent,
    sign_message,
    verify_log,
    verify_sig,
)
from .peers    import get_pubkeys, load_peers, upsert_peer

__all__ = [
    # log
    "append_message", "conv_path", "now_ts", "read_recent",
    "sign_message", "verify_log", "verify_sig",
    # channels
    "load_channels", "save_channels",
    # history
    "load_cmd_history", "save_cmd_history",
    # peers
    "load_peers", "upsert_peer", "get_pubkeys",
]
