---
name: wavedrom
description: Draw timing diagrams with WaveDrom (HTML page opened in the browser + white-background PNG/SVG image) to explain digital-logic timing. Use PROACTIVELY whenever explaining or designing cycle-level behavior in Verilog/SystemVerilog/VHDL/RTL — valid/ready or req/ack handshakes, FSM state sequences, pipeline latency, counters, FIFOs, bursts, reset sequences, CDC, testbench stimulus or a simulation mismatch — instead of describing the timing only in prose. Also use when the user asks for a waveform, timing diagram, or /wavedrom.
---

# WaveDrom timing diagrams

The user writes RTL with Claude Code and finds prose descriptions of timing hard to follow. When timing matters, **draw a waveform first, then explain it**.

## Workflow

1. Decide what the diagram must prove (e.g. "data is captured the cycle after valid&&ready", "FSM takes 3 cycles from START to DONE"). Pick only the signals that show it.
2. Write the WaveJSON and render it:
   ```bash
   python3 ~/.claude/skills/wavedrom/scripts/wave2img.py -n <short_name> -d "<caption>" -e "{signal:[ ... ], head:{text:'<title>', tick:0}}"
   ```
   - This writes `~/waveforms/<short_name>.html`, `.json` and an image, and opens the HTML in the user's browser. The HTML uses the official WaveDrom renderer. Keep the files in `~/waveforms` (the default; the script creates it if missing): don't pass `-o` unless the user asks for another place.
   - The image format comes from `~/.config/wavedrom-skill/config.json` (`"format": "png"` by default: white background; also `svg`, `both`, `none`). Pass `-f svg` etc. only when the user asks for a different format for this diagram; if they want to change it permanently, edit the config file.
   - `-n`: always give a meaningful file name, so the user can find the diagram later in `~/waveforms`:
     - `<module or topic>_<what it shows>`, lowercase snake_case, about 2–5 words: `uart_tx_start_bit`, `sync_fifo_full_write_ignored`, `axi_stream_backpressure`, `spi_master_mode0_read`.
     - Use the real module/signal names from the user's code when there is one.
     - For variants add a suffix: `_before` / `_after` (a fix), `_reg` / `_comb` (alternatives).
     - Never generic names like `test`, `wave`, `diagram`, `example`, `tmp`.
     - An existing name is not overwritten: the script saves as `<name>_2`, `<name>_3`, ... and prints the path it used, so report that path. When revising the same diagram the user is looking at, pass `--overwrite` to keep its name.
   - `-d`: a short per-cycle summary shown under the diagram on the page (newlines allowed).
   - Always set `head:{tick:0}` so the diagram has cycle numbers to refer to.
   - For a large diagram, write the JSON to a file in the scratchpad and pass the path instead of `-e`.
   - Several diagrams in one reply: run the script once per diagram (each opens its own tab). Use `--no-open` for any the user doesn't need to see right away.
3. **Check the PNG before replying**: Read the image file and confirm it shows what you meant (transitions and labels in the right cycles). Fix the JSON and re-run if not. The WaveDrom tick numbers mark clock edges: "cycle N" is the column between ticks N and N+1.
4. **Do not paste a text-art waveform into the reply** (the user found it hard to read). Give the image path (and HTML path), then explain by cycle number ("in cycle 3 valid and ready are both high, so …").
5. If the script reports `Image: skipped`, the HTML still works. Mention that images need `~/.claude/skills/wavedrom/scripts/setup.sh`.

When comparing alternatives (e.g. registered vs. combinational ready, or current behaviour vs. the fix), draw one diagram per alternative (`<name>_before`, `<name>_after`), or put both in one diagram using groups.

## Getting the timing right

The diagram must match what the RTL actually does — a wrong waveform is worse than none.

- Each wave character is one clock cycle, numbered from 0 by `head:{tick:0}`. Use `p` for the clock (rising edge at the start of each cycle).
- A register assigned with `<=` in `always @(posedge clk)` changes **in the cycle after** the edge where its inputs were sampled. If `valid && ready` is true in cycle 3, a `q <= d` driven by it shows the new value from cycle 4.
- Combinational signals (`assign`, `always @*`) change in the same cycle as their inputs.
- Show reset when it matters to the explanation (`rst_n` low for the first cycles).
- Mark values you do not know or that do not matter as `x`; tri-state/undriven as `z`.
- If you are not sure about a cycle (e.g. you have not read the module yet), read the code first, or say explicitly that the diagram is an assumption.

## Keep it readable

- About 6–24 cycles and 3–12 signals. Use `|` to skip uneventful stretches.
- Order signals causally: clock, reset, control inputs, state, outputs, data.
- Use `["group name", sig, sig]` to group signals (e.g. `"master"`, `"slave"`), and `{}` for a blank spacer row.
- Use bus colours to carry meaning: `3`–`9` fill the value box (3 yellow, 4 orange, 5 blue, 6 cyan, 7 green, 8 pink, 9 red); `=` and `2` are white. E.g. one colour per FSM state, or the same colour for a value as it moves through pipeline stages.
- **Do not use `node` or `edge`** (no arrows, node letters or arrow labels on the diagram); the user wants a clean waveform. Put causality ("valid&&ready in cycle 2 → q updates in cycle 3") in the reply text and the `-d` caption instead.
- Keep bus labels short (`D0`, `IDLE`, `0x3`); a long label in a one-cycle box overflows. Widen with `config:{hscale:2}` if needed.

## WaveJSON cheat sheet

```js
{ signal: [
  { name: "clk",   wave: "p......." },          // clock: p/n, P/N mark the active edge
  { name: "valid", wave: "0.1..0.." },          // 0 1 = levels, . = hold previous
  { name: "data",  wave: "x.=.=x..", data: ["D0", "D1"] }, // = or 2-9 = bus value, labels from data
  { name: "en",    wave: "01.|0..." },          // | = gap
  {},                                            // spacer
  ["fsm", { name: "state", wave: "2.3.4.2.", data: "IDLE RUN DONE IDLE" }],
  { name: "slow",  wave: "p...", period: 2 },    // each char spans 2 cycles
],
  head: { text: "title", tick: 0 },              // title; tick = first cycle number
  config: { hscale: 1 }                          // widen every cycle
}
```

Wave characters: `p n P N` clock, `0 1` levels, `h l H L` high/low, `x` unknown, `z` high-Z, `= 2 3 4 5 6 7 8 9` bus value, `.` continue, `|` gap.

## Example

User: "When does `q` get the data in `always @(posedge clk) if (valid && ready) q <= data;`?"

```bash
python3 ~/.claude/skills/wavedrom/scripts/wave2img.py -n q_capture \
  -d "cycle 2-3: valid && ready -> q updates at the next edge (cycle 3, cycle 4)" -e "{signal:[
 {name:'clk',   wave:'p......'},
 {name:'valid', wave:'01..0..'},
 {name:'ready', wave:'0.1.0..'},
 {name:'data',  wave:'x34.x..', data:'A B'},
 {name:'q',     wave:'x..44..', data:'B B'}],
 head:{text:'q <= data when valid && ready', tick:0}}"
```

Reply with the file path, then explain: valid and ready are both high in cycles 2 and 3, so the edge at the start of cycle 3 captures B (the value present in cycle 2) and q shows B from cycle 3. The cycle-3 handshake captures B again at the start of cycle 4. A was never captured, because ready was low in cycle 1.

## Other tools

`scripts/wave2term.py` renders the same WaveJSON as text art in the terminal. Use it only if the user asks for a terminal/text version.
