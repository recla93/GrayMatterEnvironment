"""Gray-Matter — orchestratore per server MCP Neuron/NeuRAG."""

# Load the GM-level .env BEFORE any submodule — bridges.py resolves its cloud
# tier from os.environ at import time, and spawned workers inherit the daemon's
# environment. No-op under pytest / GM_NO_DOTENV. (Env model, DESIGN §2)
from gray_matter._env import load_dotenv_once as _load_dotenv_once

_load_dotenv_once()

__version__ = "1.3.0"
