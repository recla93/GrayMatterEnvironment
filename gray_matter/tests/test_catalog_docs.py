"""La guida dei comandi nel control center: completa, bilingue, e non bugiarda.

Il valore di questi test è nel tempo: chi aggiungerà un subcomando alla CLI lo
vedrà comparire da solo nella GUI (per introspezione) e scoprirà QUI che gli
manca la spiegazione, invece di scoprirlo un utente davanti a un comando muto.
"""

import pytest

from gray_matter import catalog


def _all_commands(lang: str):
    for env in catalog.environments(lang):
        if env["installed"]:
            for cmd in env["commands"]:
                yield (env["key"], cmd["name"]), cmd


@pytest.mark.parametrize("lang", ["it", "en"])
def test_every_visible_command_says_what_it_does_and_when_to_use_it(lang):
    """Sapere cosa fa un comando non basta a sapere se è quello giusto adesso:
    servono entrambe le risposte, in entrambe le lingue."""
    missing_what = [k for k, c in _all_commands(lang) if not (c["help"] or "").strip()]
    missing_when = [k for k, c in _all_commands(lang) if not (c["when"] or "").strip()]
    assert not missing_what, f"[{lang}] comandi senza descrizione: {missing_what}"
    assert not missing_when, f"[{lang}] comandi senza 'quando serve': {missing_when}"


def test_docs_entries_are_complete():
    """Una lingua a metà è peggio di una assente: la GUI la mostrerebbe comunque."""
    for key, entry in catalog.DOCS.items():
        assert len(entry) == 4, f"{key}: servono cosa_it, quando_it, what_en, when_en"
        for i, part in enumerate(entry):
            assert part and part.strip(), f"{key}: parte {i} vuota"


def test_the_two_languages_actually_differ():
    """Guardia contro il copia-incolla: una voce dove l'inglese è identico
    all'italiano è quasi sempre una traduzione dimenticata."""
    same = [k for k, (wi, ni, we, ne) in catalog.DOCS.items()
            if wi == we and ni == ne]
    assert not same, f"IT ed EN identici (traduzione mancante?): {same}"


def test_docs_do_not_describe_commands_that_do_not_exist():
    """Il caso vero che ha trovato questo test: ('neuron', 'uninstall') era
    documentato ma Neuron non ha quel comando — la disinstallazione passa da
    `neuron setup --uninstall`. Una guida che descrive comandi inesistenti è
    peggio di nessuna guida."""
    installed = {e["key"] for e in catalog.environments() if e["installed"]}
    real = {k for k, _c in _all_commands("it")}
    stale = {k for k in catalog.DOCS if k[0] in installed} - real
    assert not stale, f"DOCS descrive comandi inesistenti: {sorted(stale)}"


def test_doc_for_falls_back_instead_of_raising():
    """Un comando nuovo non ancora descritto deve comunque comparire nella GUI,
    con il testo argparse: la guida mancante non può nascondere il comando."""
    assert catalog.doc_for(("gray-matter", "non-esiste-affatto")) == ("", "")
    assert catalog.doc_for(("gray-matter", "doctor"), "en")[0] != ""
    assert catalog.doc_for(("gray-matter", "doctor"), "it")[0] != ""


def test_language_selection_changes_the_text():
    it_what, it_when = catalog.doc_for(("gray-matter", "doctor"), "it")
    en_what, en_when = catalog.doc_for(("gray-matter", "doctor"), "en")
    assert it_what != en_what and it_when != en_when
    # lingua sconosciuta -> italiano, il default storico della GUI
    assert catalog.doc_for(("gray-matter", "doctor"), "kl") == (it_what, it_when)
