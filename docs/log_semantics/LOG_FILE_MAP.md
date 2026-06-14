# Log File Map

## Core Inputs

| File | Role | Phase 1 behavior |
|---|---|---|
| `android*.log` | App and upper-controller behavior: recipe, scene, activity, power, actions, speech, collection and command evidence | Full semantic parsing |
| `temperature*.log` | High-frequency filtered, infrared and output temperature triplets | Full sample parsing |
| `main_board.log` | Controller limits, pot position, rolling, leaning, heating and fluid actions | Inventory only; semantics remain evidence for later validation |
| `debug*.log` | MCU/JNI communication, heater status and error evidence | Inventory plus lightweight heater status/error extraction |
| `dryspices_board.log` | Dry-spice lifecycle such as start, in, finish and missing frame IDs | Inventory only |
| `oildrum_board.log` | Oil-drum controller evidence | Inventory only |

The parser recursively discovers files, records their sizes and paths, and never requires a
database or online service. High-volume `sendMsg`, `readResult`, and `findResult` lines are
counted by default. They are exported only with `--debug-commands`.

## Encoding

Known Android packages are UTF-8-like files that may contain NUL bytes. The reader strips NUL
bytes per line and replaces invalid byte sequences, preserving the original line text after
sanitization. Temperature files are read with the same fault-tolerant streaming path.
