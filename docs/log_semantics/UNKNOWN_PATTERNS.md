# Unknown Patterns

`unknown_patterns.csv` retains keyword-bearing lines that look relevant but do not match a
confirmed rule.

Columns are source file, line number, timestamp, raw line, guessed category, reason and a
suggested next action. Relevant keywords include power, temperature, feed, lean, roll, weigh,
error, fail and FrameID.

Unknown lines never fail the package. A new rule should be added only after examples from more
than one package are compared and field semantics are confirmed. Until then, raw evidence is
preferable to a confident but incorrect field name.
