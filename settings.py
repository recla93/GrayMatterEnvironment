"""Tunable knobs for NeuRAG — persisted config surface.

Mirrors gray_matter/settings.py (same shape, same coercion rules) so the two
never drift and the catalog-driven control center renders a NeuRAG `config`
command exactly like Gray-Matter's. One JSON config alongside the vault
(`~/.local/share/neurag/config.json`) — SEPARATE from knowledge.db, so a DB
corruption/rebuild never touches the settings (audit 2026-07-22 rule).

Only known keys are accepted; values are coerced to the default's type; the
file stores only the overrides (so DEFAULTS can evolve). Stdlib only.

Reranker is OFF by default: turning it on downloads a cross-encoder model and
adds retrieval latency, so it stays an explicit opt-in per install.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULTS = {
    "rerank": False,        # cross-encoder rerank stage (opt-in; adds latency + model DL)
    "rerank_pool": 50,      # candidates retrieved before rerank (top_n picked from these)
    "rerank_model": "",     # override cross-encoder model ("" = reranker default)
    # Embedding model, chosen at install time. "" = follow Neuron / the built-in
    # multilingual default, which is what keeps the two in ONE vector space.
    # embed_dim MUST match embed_model: vectors of different widths are not
    # comparable, so changing either later means re-indexing the vault.
    "embed_model": "",
    "embed_dim": 0,         # 0 = derive from embed_model (384 for the default)
    # Max characters per chunk. 0 = derive from the live model's tokenizer,
    # which is the right answer for every shipped model (all truncate at 128
    # tokens). Raise it only for a model with a genuinely bigger window.
    "chunk_max_chars": 0,
}

# Per-knob help + suggestions surfaced by the control center (GUI reads these so
# the NeuRAG settings card is self-describing — keep-in-sync with the knobs).
HELP = {
    "rerank": "Riordina i risultati con un cross-encoder: più precisione, ma "
              "scarica un modello e aggiunge latenza. OFF di default.",
    "rerank_pool": "Quanti candidati recuperare prima del rerank (i top-n si "
                   "scelgono da questi). Più alto = più recall, più costo.",
    "rerank_model": "Modello cross-encoder. Vuoto = default. Per un vault "
                    "italiano conviene il multilingue.",
    "embed_model": "Modello di embedding del vault. Vuoto = segue Neuron "
                   "(stesso spazio vettoriale). Cambiarlo richiede un "
                   "re-index completo: vettori di modelli diversi non sono "
                   "confrontabili.",
    "embed_dim": "Dimensione dei vettori. 0 = derivata da embed_model. Deve "
                 "combaciare col modello, altrimenti la ricerca è rumore.",
    "chunk_max_chars": "Lunghezza massima di un chunk. 0 = derivata dal modello "
                       "attivo (tutti i modelli inclusi tagliano a 128 token, "
                       "circa 400 caratteri). Oltre il limite il testo viene "
                       "troncato dall'embedder e diventa NON cercabile. "
                       "Cambiarlo richiede un re-index.",
}
# Free-text knobs that still have good known values → GUI shows a picker but
# keeps custom input allowed.
SUGGEST = {
    "rerank_model": [
        "",  # = reranker default (Xenova/ms-marco-MiniLM-L-6-v2, EN-centrico)
        "jinaai/jina-reranker-v2-base-multilingual",  # IT/EN, più pesante
        "BAAI/bge-reranker-base",
    ],
    # Keep-in-sync with $EmbedModels in install.ps1 / EM_* in install.sh.
    "embed_model": [
        "",  # = segue Neuron (multilingue 384-dim)
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",  # 384
        "sentence-transformers/all-MiniLM-L6-v2",                       # 384, solo EN
        "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",  # 768
        "intfloat/multilingual-e5-large",                               # 1024
    ],
}


def _coerce(default, value):
    if isinstance(default, bool):
        return value.strip().lower() in ("1", "true", "yes", "on") if isinstance(value, str) else bool(value)
    if isinstance(default, int):
        return int(value)
    if isinstance(default, float):
        return float(value)
    return str(value)


def _config_path(path=None) -> Path:
    if path is not None:
        return Path(path)
    # SSOT: la location vive in neurag/paths.py (accanto al vault, ma file a sé).
    from neurag import paths as _paths
    return _paths.config_path()


def load(path=None) -> dict:
    """DEFAULTS overlaid with the user's config.json (known keys only, type-coerced)."""
    out = dict(DEFAULTS)
    try:
        raw = json.loads(Path(_config_path(path)).read_text(encoding="utf-8"))
    except Exception:
        raw = {}
    for k, v in (raw or {}).items():
        if k in DEFAULTS:
            try:
                out[k] = _coerce(DEFAULTS[k], v)
            except Exception:
                pass
    return out


def get(key, path=None):
    return load(path).get(key)


def set(key, value, path=None) -> dict:
    """Set one known knob (type-coerced), persist only the overrides, return merged."""
    if key not in DEFAULTS:
        raise KeyError(f"unknown setting '{key}' (known: {', '.join(sorted(DEFAULTS))})")
    cfg = load(path)
    cfg[key] = _coerce(DEFAULTS[key], value)
    p = Path(_config_path(path))
    p.parent.mkdir(parents=True, exist_ok=True)
    overrides = {k: v for k, v in cfg.items() if v != DEFAULTS[k]}
    p.write_text(json.dumps(overrides, ensure_ascii=False, indent=2), encoding="utf-8")
    return cfg


def rerank_enabled(path=None) -> bool:
    """Effective reranker state: env NEURAG_RERANK overrides the config file.

    Env wins so a single `NEURAG_RERANK=on` can flip it per-process (CI, tests,
    a one-off session) without persisting; the GUI toggle writes the config file.
    """
    env = os.environ.get("NEURAG_RERANK")
    if env is not None:
        return env.strip().lower() in ("1", "true", "yes", "on")
    return bool(get("rerank", path))
