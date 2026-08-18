"""Simula un venv senza gray_matter: qualunque import lo trova assente.

Serve a provare il contratto standalone senza costruire un venv pulito da 1 GB:
il finder rifiuta gray_matter e tutti i suoi sottomoduli, esattamente come
farebbe un'installazione dove non e' mai stato messo.
"""
import sys


class _Blocker:
    def find_module(self, name, path=None):
        return self.find_spec(name, path)

    def find_spec(self, name, path=None, target=None):
        if name == "gray_matter" or name.startswith("gray_matter."):
            # ModuleNotFoundError con `name` valorizzato: e' cio' che solleva
            # davvero un modulo assente. Con un ImportError nudo,
            # `pytest.importorskip` non riconosce il modulo e FALLISCE invece di
            # skippare — lo strumento inventerebbe un guasto che non c'e'.
            raise ModuleNotFoundError(
                f"No module named {name!r} (standalone simulato)", name=name)
        return None


sys.meta_path.insert(0, _Blocker())
sys.modules.pop("gray_matter", None)
