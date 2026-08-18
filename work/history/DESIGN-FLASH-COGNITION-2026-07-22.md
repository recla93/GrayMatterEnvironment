# Design — Flash più "umani": stocasticità, asimmetria, intrusione

**Data:** 2026-07-22
**Scopo:** tre innesti mirati per avvicinare i flash semantici alla variabilità della memoria umana, senza riscrivere il motore. Ordine consigliato: **1 → 2 → 3** (la 3 è ricerca, non un fix). Default **conservativi**: a knob spenti il comportamento resta identico a oggi.

Stato di partenza (verificato nel codice):
- Peso assegnato su soglie cosine FISSE: `strong` >0.65 · `medium` >0.45 · else `tangential` (`neuron/stimulus.py:68`; variante `>0.5` in `neuron/server.py:1556`).
- Firing del flash: shift di topic + `FLASH_MIN_GAP` + cooldown per-concetto (`_flashed`) + safety-net (`gray_matter/server.py:189-238`).
- Link deduplicati **nei due versi** → grafo di fatto NON orientato per `link_type` (`neuron/models.py:521-526`); peso categoriale 3-livelli; Hebbian simmetrico (`reinforce_coactivation`). Eccezione direzionale: `drift`.
- Flash = testo iniettato nel context (pre_turn/pulse o piggyback 🧠/⚡), architettura request/response a turni.

---

## 1. Firing stocastico stato-dipendente

**Obiettivo:** lo stesso stimolo, nello stesso stato, a volte scatta e a volte no; e la probabilità cresce/cala con uno "stato" (arousal, fatica, attenzione).

**Dove tocca:**
- `neuron/stimulus.py` (assegnazione peso / selezione candidati) e il punto di firing in `gray_matter/server.py` (`_safety_net_note` / il gate flash).
- `gray_matter/settings.py` `DEFAULTS` (nuovi knob → compaiono nella GUI Preferences).

**Meccanismo:**
- Sostituire il taglio netto con un **campionamento**: dato il cosine `s` di ogni candidato, `p = sigmoid((s - θ) / T)` e si **estrae** (Bernoulli) invece di soglia dura. `T` = temperatura (0 → comportamento attuale deterministico; >0 → variabilità).
- Uno scalare di **stato** `arousal ∈ [0,1]` modula la soglia effettiva `θ_eff = θ - k·arousal` (arousal alto → più flash) e/o `T`. `arousal` può derivare da segnali già presenti: sentiment/intent dell'extraction, densità di attività recente, o restare un knob manuale.
- **Fatica** come budget: `flash_budget` che decade nella sessione e si ricarica nell'idle → dopo molti flash ravvicinati la probabilità cala, come l'attenzione che si esaurisce.

**Config (knob, default = OFF/attuale):** `flash_temperature=0.0`, `flash_arousal=0.0`, `flash_budget=∞`. Con questi la logica coincide bit-per-bit con oggi (nessun campionamento).

**Rischi:** non-determinismo nei test → gating dietro `T>0`, e seed fisso nei test. Rumore percepito → tenere `T` basso di default e rate-limit invariati.

**Effort:** basso-medio. Un punto solo (selezione candidati) + 3 knob. Test: con `T=0` output identico; con `T>0` e seed, distribuzione attesa su N run.

---

## 2. Asimmetria direzionale ("fuoco→rosso" ≠ "rosso→fuoco")

**Obiettivo:** alcune associazioni sono più forti in un verso. Oggi impossibile: il dedup collassa `A→B` e `B→A`.

**Dove tocca:**
- `neuron/models.py`: `add_link` (rimuovere/rendere opzionale il dedup del verso inverso, righe 521-526), il modello `Link` (peso), `reinforce_coactivation` (Hebbian).
- Traversata in `neuron/server.py`/`models.py` (`get_context`/neighbors): renderla **direction-aware** quando il knob è attivo.
- **Migrazione**: i grafi esistenti hanno archi collassati → serve un flag di schema; i vecchi restano simmetrici, i nuovi possono divergere.

**Meccanismo:**
- Tenere **due archi diretti** distinti `A→B` e `B→A`, ciascuno col proprio peso.
- Passare da categoriale (strong/medium/tangential) a un **peso continuo per-direzione** (o mantenere il categoriale ma per-arco). L'Hebbian diventa **asimmetrico**: rinforza `source→target` secondo l'**ordine di attivazione** nel turno (chi accende chi), non entrambe le direzioni.
- Retrieval: un flash da `A` pesa `A→B`; da `B` pesa `B→A`. La `drift` (già direzionale) diventa il caso generale, non l'eccezione.

**Config:** `directional_links=false` (default = comportamento attuale, dedup simmetrico). A `true` si attivano archi diretti + Hebbian asimmetrico + traversata orientata.

**Rischi:** raddoppio potenziale degli archi (memoria/pruning: alzare la pressione del decay). Compatibilità dei grafi salvati → gate di schema + migrazione lazy (un vecchio arco simmetrico si può "sdoppiare" alla prima riattivazione). Le due direzioni vanno pruneate indipendentemente.

**Effort:** medio. Il data model ha già `source`/`target`; il lavoro è dedup + Hebbian + traversata + migrazione.

---

## 3. Intrusione mid-stream (ricerca, non fix)

**Obiettivo:** l'associazione che sorge **mentre** stai già rispondendo, non solo al confine del turno.

**Realtà architetturale:** MCP è request/response a turni. Oggi il flash atterra a `pre_turn` o piggyback su una risposta-tool — **mai a metà della generazione**. Un'intrusione vera richiede streaming + un side-channel che interrompa il decoding: **fuori dalla portata** del transport attuale.

**Opzioni (in ordine di realismo):**
- **(a) Pseudo-intrusione a granularità di tool-call** (fattibile ora): se durante un turno il modello fa più tool-call, il piggyback può iniettare un flash **tra una call e l'altra** invece che solo a inizio turno — dà la sensazione di "mi è appena venuto in mente" a metà ragionamento. Zero cambi di transport; solo scelta di *dove* nel flusso di tool agganciare il 🧠.
- **(b) Budget d'interruzione + salienza-gated** (fattibile ora): l'intrusione scatta solo se la salienza dell'associazione supera quella del focus corrente di un margine (competizione esplicita), non a ogni occasione — modella "l'interruzione vince solo se è abbastanza forte".
- **(c) Vera interruzione mid-token** (ricerca): richiede un runtime a streaming con hook di decodifica e un controller che possa iniettare/riorientare. Cambio architetturale grosso; segnare come traccia lunga.

**Config:** `intrusion_mode = off | between_tools | salience_gated`. Default `off`.

**Rischi:** (a)/(b) possono spezzare il filo se troppo aggressivi → budget stretto + margine di salienza alto. (c) è un progetto a sé.

**Effort:** (a) basso, (b) basso-medio, (c) alto/ricerca.

---

## Compatibilità & rollout
- **Tutti i knob default = comportamento attuale**: chi non li tocca non vede differenze (né nei test).
- Knob nuovi in `gray_matter/settings.py` `DEFAULTS` → auto-esposti nella card Impostazioni della GUI (o `<tool> config`).
- La 2 richiede un **flag di schema** sui grafi + migrazione lazy; la 1 e la 3(a/b) non toccano lo storage.
- Ordine: **1** (variabilità, innesto isolato) → **2** (asimmetria, tocca storage) → **3a/3b** (intrusione soft) → **3c** solo se serve davvero.
- Test: 1 con seed fisso e `T=0` = identità; 2 con `directional_links` on/off su un grafo tmp (dedup vs archi diretti); 3a/b su una sequenza multi-tool sintetica.
