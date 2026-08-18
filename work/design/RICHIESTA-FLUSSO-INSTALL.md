in ordine: pyturso non è optional in Neurag (rendiamolo mandatory con fallback a sqlite),
Click su install.CMD di GrayMatter e dovrebbe: 
Controllare se ci sono instanze già installate della full suite (GM, Neuron, NeuRAG), se già install chiedere se si vuole fare repair (se si, chiedi quale riparare o tutta la suite).
(non sto elencando i fallback e ricerca python o altre deps, ci sono e ci devono essere sempre).
Install OK, tutti registrati e non standalone (collab con GM), viene creata la GUI sul desktop di GM, si apre.

NEURON = 
Installer di Neuron se si vuole standalone o con GM. Raccomandato con GM viene chiesto se si vuole installare (Si, No, Standalone (3 opzioni, lasciamo aperta la scelta, se utente scrive NO, controlla se installato già GM, se install effettua register al gateway, altrimenti standalone. Se scrive si, controlla se presente, altrimenti install GM). Si processa install, dipendenze, tutti i vari fallback ci sono per dipendenze mancanti (le scarica, se fallisce, scarica fallback). Viene creata la GUI con solo Neuron disponibile.

NeuRAG= Uguale a Neuron, install però non ha dipendenze mandatory (pyturso, dovrebbe esserci wheel in NeuRAG).


Appena hai controllato che sia tutto in ordine, fai un audit con carenze, migliorie flusso install, errori, problemi di coesione. Lascia audit su desktop con l'analisi che hai già fatto ed aggiungi il resto sotto)

