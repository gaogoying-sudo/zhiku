# Session And Timeline Model

## Session Starts

Strong starts are cooking markers, `NewCookingActivity onCreate`, COOKING scene entry, quick
pot raising, `ProtectPotActivity onCreate`, recipe activity, and recipe recording. Closely
adjacent evidence for the same type is merged.

End candidates are zero power, `STOP_CW_ZERO`, protect-pot activity destruction, COOKING scene
exit, 120 seconds without a key event, the next strong start, or end of log.

Sessions are log-internal reconstructions. They do not claim a database job match.

## Metrics

Temperature samples are selected by the session time interval. Session output includes maximum,
average, first and last output temperature. Command and actual power energy use a step integral:
the current power applies until the next power event, while every interval is capped at 60
seconds to avoid inflated energy across log gaps.

## Unified Timeline

Android events, temperature samples, session markers, warnings and errors are sorted by
timestamp. Each Android event is aligned to the nearest temperature sample. Matches are labeled
with `1s`, `3s`, or `5s` windows; the signed delta is retained. No sample outside five seconds
is copied onto an Android event.

## Candidate Risk Tags

Stable keys include temperature thresholds, command/actual power thresholds,
`protect_pot_high_temp`, missing temperature or power feedback, `no_frame_id`,
`heater_error`, and unknown-pattern signals. These are screening candidates, not incident
findings. Compound tags such as pre-feed or post-oil conditions require validated action
windows in a later phase.
