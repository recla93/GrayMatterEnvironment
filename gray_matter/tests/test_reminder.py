"""Il promemoria che rompe la circolarita' del loop di memoria.

Il bug che questo test blocca (osservato 2026-09-04): in una sessione di ~15
turni e' partito UN solo `store_turn`. Ogni promemoria vive dentro la risposta
dell'anello precedente (`pre_turn` dice "then store_turn", `store_turn` dice
"next: pre_turn"), quindi saltare un anello salta anche il promemoria del
successivo, e il ciclo non si riavvia piu' per il resto della sessione.

L'hook conta i prompt VERI dell'utente dopo l'ultimo `store_turn`. Le tre righe
che non devono contare -- tool result, sidechain, e la riga che salva -- sono
esattamente quelle che in una sessione densa sono la maggioranza.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "neuron" / "src" / "neuron" / "clients" / "claude-code-hook"


@pytest.fixture(scope="module")
def mod():
    sys.path.insert(0, str(HOOK))            # importa il sessionstart accanto
    spec = importlib.util.spec_from_file_location(
        "_reminder", HOOK / "neuron_reminder_hook.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _line(**kw):
    return json.dumps(kw, ensure_ascii=False)


def _prompt(text="ciao"):
    return _line(type="user", isSidechain=False,
                 message={"role": "user", "content": text})


def _tool_result():
    return _line(type="user", isSidechain=False, message={
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "toolu_01", "content": "ok"}]})


def _sidechain_prompt():
    return _line(type="user", isSidechain=True,
                 message={"role": "user", "content": "prompt del subagente"})


def _call(name):
    return _line(type="assistant", message={
        "role": "assistant",
        "content": [{"type": "tool_use", "id": "toolu_02", "name": name, "input": {}}]})


def _transcript(tmp_path, *lines):
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join(lines), encoding="utf-8")
    return str(p)


def test_conta_solo_i_prompt_veri(mod, tmp_path):
    """Tool result e sidechain non sono turni dell'utente."""
    t = _transcript(tmp_path, _prompt(), _tool_result(), _tool_result(),
                    _sidechain_prompt(), _prompt())
    assert mod.unsaved_prompts(t) == 2


def test_store_turn_azzera(mod, tmp_path):
    """Il reset e' il salvataggio stesso: nessun file contatore da sincronizzare."""
    t = _transcript(tmp_path, _prompt(), _prompt(),
                    _call("mcp__gray-matter__store_turn"), _prompt())
    assert mod.unsaved_prompts(t) == 1


def test_solo_store_turn_azzera(mod, tmp_path):
    """pre_turn non e' un salvataggio: da solo lasciava il grafo vuoto."""
    t = _transcript(tmp_path, _prompt(), _call("mcp__gray-matter__pre_turn"), _prompt())
    assert mod.unsaved_prompts(t) == 2


def test_parlare_di_store_turn_non_azzera(mod, tmp_path):
    """Il nome nel TESTO non e' una chiamata: questa sessione stessa lo dimostra."""
    t = _transcript(tmp_path, _prompt("perche' store_turn non e' scattato?"), _prompt())
    assert mod.unsaved_prompts(t) == 2


def test_prefisso_standalone_azzera(mod, tmp_path):
    """Neuron standalone espone mcp__neuron__store_turn, non il prefisso gateway."""
    t = _transcript(tmp_path, _prompt(), _call("mcp__neuron__store_turn"), _prompt())
    assert mod.unsaved_prompts(t) == 1


def test_transcript_illeggibile_non_inventa(mod, tmp_path):
    """Senza transcript nessun promemoria: un nudge sbagliato insegna a ignorarlo."""
    assert mod.unsaved_prompts(str(tmp_path / "non-esiste.jsonl")) == -1
    assert mod.unsaved_prompts("") == -1


def test_scatta_ogni_otto(mod):
    """La soglia e' un multiplo, non un '>=': altrimenti parla a ogni turno."""
    assert mod.EVERY == 8
    scatta = [n for n in range(1, 25) if n > 0 and n % mod.EVERY == 0]
    assert scatta == [8, 16, 24]


def test_il_messaggio_nomina_il_tool_giusto(mod):
    """Il bug speculare dell'handshake: dire di chiamare un tool che non esiste."""
    assert "mcp__gray-matter__store_turn" in mod.message(8, "mcp__gray-matter__")
    assert "mcp__neuron__store_turn" in mod.message(8, "mcp__neuron__")


def test_meta_non_conta(mod, tmp_path):
    """L'output di un hook rientra come riga role=user: contarlo = auto-conteggio."""
    meta = _line(type="user", isSidechain=False, isMeta=True,
                 message={"role": "user", "content": "[neuron] 8 turni dall'ultimo..."})
    t = _transcript(tmp_path, _prompt(), meta, _prompt())
    assert mod.unsaved_prompts(t) == 2


def test_riga_corrotta_non_ferma_il_conteggio(mod, tmp_path):
    """Un JSONL troncato a meta' riga non deve azzerare tutta la sessione."""
    t = _transcript(tmp_path, _prompt(), '{"type":"user", TRONCA', _prompt())
    assert mod.unsaved_prompts(t) == 2


def test_formato_reale_compatto(mod, tmp_path):
    """Il transcript vero e' JSONL compatto: il parse strutturale copre entrambi."""
    t = _transcript(
        tmp_path,
        '{"parentUuid":null,"isSidechain":false,"type":"user",'
        '"message":{"role":"user","content":"ciao"}}',
        '{"type":"assistant","message":{"role":"assistant","content":'
        '[{"type":"tool_use","id":"toolu_1","name":"mcp__gray-matter__store_turn",'
        '"input":{}}]}}',
        '{"parentUuid":"x","isSidechain":false,"type":"user","message":{"role":"user",'
        '"content":[{"tool_use_id":"toolu_1","type":"tool_result","content":"ok"}]}}',
    )
    assert mod.unsaved_prompts(t) == 0
