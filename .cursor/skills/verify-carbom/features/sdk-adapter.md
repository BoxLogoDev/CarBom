# SDK adapter

The SDK adapter layer is how a future real vehicle signal source will
plug into the same engine: raw signal dictionaries are converted to
snapshots, applied to a session exactly like simulator snapshots, and —
until a real SDK client exists — the adapter fails loudly instead of
pretending to be connected.

## Sub-features

- `sdk-convert` converts a raw dict to a `SignalSnapshot` with
  `snapshot_from_raw` (missing keys default, unknown keys ignored) and
  back with `raw_from_snapshot` (always all 7 keys, `None` preserved).
- `sdk-bulk` converts iterables in order with `snapshots_from_raws` and
  `raws_from_snapshots` (generators included, empty input -> empty tuple).
- `sdk-apply` applies raw input directly with `apply_raw` / `apply_raws`,
  equivalent to simulator `replay` for the same signal sequence.
- `sdk-poll` polls an injected `read_raw()` client via `VehicleSdkAdapter`
  and applies readings with `poll_into`.
- `sdk-unconnected` reports `is_connected=False` and raises
  `NotImplementedError` from `poll()` / `poll_into` when no client is
  injected, leaving the session unchanged.

## How to get to it (user POV)

- Import the converters and adapter from `engine.adapters.vehicle_sdk`
  (also re-exported from `engine.adapters`).
- Feed raw dicts with the optional keys `rear_door_open`,
  `rear_seat_belt_buckled`, `ignition_on`, `locked`, `hvac_on`,
  `cabin_temp_c`, `timestamp`.
- Inject any object with `read_raw()` into `VehicleSdkAdapter(client=...)`.

## Driving it with the Python API

Preconditions:

- `verify_carbom.py doctor` exits 0 from the project root.
- Drives use fresh `CareSession()` instances and, for comparison, a
  second fresh session driven by simulator `replay`.

- **Round trip.** Convert the full raw form of a dropoff snapshot with `snapshot_from_raw`, then back with `raw_from_snapshot`. The dict is unchanged, and converting it again returns an equal snapshot — including `cabin_temp_c=0.0` and `timestamp=0.0`, which are valid values, not missing keys.
- **Equivalence.** Take the `dropoff_normal` snapshots, turn them into raw dicts, apply them to a fresh session with `apply_raws`, and compare with a simulator `replay` session. Final state, passenger flag, full transition list, guidance, and report all match.
- **Bulk.** Run `snapshots_from_raws` over a generator of the three scenarios' raw dicts. Order is preserved and the result is a tuple; empty input returns an empty tuple.
- **Poll path.** Inject a fake client whose `read_raw()` returns the dropoff raw sequence one item per call and call `poll_into` until the sequence ends. The session reaches COMPLETED, mirroring the simulator path.
- **Unconnected failure.** Construct `VehicleSdkAdapter()` with no client. `is_connected` is False, `poll()` raises `NotImplementedError`, and `poll_into(session)` propagates it with the session still IDLE and its history empty.
- **Proof.** For equivalence, capture both sessions' transition lists and reports side by side; for the unconnected path, capture the raised exception type and the untouched session state.

## Gotchas

- Falsy is not missing: explicit `False` flags, temperature `0.0`, and
  timestamp `0.0` must survive conversion exactly. A converter using
  truthiness to detect presence fails this map.
- Non-boolean flag values are converted by truthiness (for example `1`
  means door open); do not assert a type error for them.
- `apply_raws` with empty input returns the current state and changes
  nothing — the same contract as simulator `replay`, not an error.
- Never describe this layer as a live SDK connection in any report or
  document; the real client hookup is a later stage (account/SDK pending).
