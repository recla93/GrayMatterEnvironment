"""pytest configuration — sets up PYTHONPATH for the src layout."""
import atexit
import shutil
import sys
import os
import tempfile

src = os.path.join(os.path.dirname(os.path.dirname(__file__)), "src")
if src not in sys.path:
    sys.path.insert(0, src)

# Lo store va isolato QUI, non in un fixture. `GraphRegistry.__init__` risolve
# `NS_GRAPHS_DIR` una volta sola e lo tiene in `self._graphs_dir`, e il
# singleton `_g` nasce all'IMPORT di `neuron.server`: un monkeypatch dentro il
# test arriva sempre troppo tardi, e i test che chiamano `call_tool` scrivevano
# nella memoria REALE dell'utente (verificato: una passata di
# test_store_turn_contract.py portava lo store di %LOCALAPPDATA% da max_turn 7
# a 12). conftest.py è importato prima dei moduli di test: è l'ultimo punto in
# cui l'env fa ancora in tempo.
# Il .env non serve neutralizzarlo: `_env.py` lo salta già sotto pytest.
_STORE = tempfile.mkdtemp(prefix="neuron-tests-")
os.environ["NS_GRAPHS_DIR"] = _STORE
atexit.register(shutil.rmtree, _STORE, True)
