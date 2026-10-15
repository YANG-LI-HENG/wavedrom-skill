---
name: wavedrom
description: Draw timing diagrams (WaveDrom WaveJSON rendered as a text waveform in the terminal) to explain digital-logic timing. Use PROACTIVELY whenever explaining or designing cycle-level behavior in Verilog/SystemVerilog/VHDL/RTL — valid/ready or req/ack handshakes, FSM state sequences, pipeline latency, counters, FIFOs, bursts, reset sequences, CDC, testbench stimulus or a simulation mismatch — instead of describing the timing only in prose. Also use when the user asks for a waveform, timing diagram, or /wavedrom.
---

# WaveDrom timing diagrams in the terminal

The user writes RTL with Claude Code and finds prose descriptions of timing hard to follow. When timing matters, **show a waveform first, then explain it**.

## Workflow

1. Decide what the diagram must prove (e.g. "data is captured the cycle after valid&&ready", "FSM takes 3 cycles from START to DONE"). Pick only the signals that show it.
2. Write the WaveJSON and render it:
   ```bash
   python3 ~/.claude/skills/wavedrom/scripts/wave2term.py -e "{signal:[ ... ]}"
   ```
   For larger diagrams write the JSON to a file in the scratchpad directory and pass the path. Add `--ascii` if the user reports broken box characters.
3. **Paste the script output verbatim into your reply inside a ```text code block.** Bash output is not reliably shown to the user, so the diagram only reaches them if you put it in your message. Do not hand-edit the rendered art.
4. Below the block, include the `WaveDrom editor:` link the script printed, so the user can open the full graphical version (and edit it). Text in your reply can't carry terminal colours, so also add one line telling the user they can view the coloured version with `! python3 ~/.claude/skills/wavedrom/scripts/wave2term.py --last`. Every render overwrites the saved diagram, so when a reply has several diagrams, `--last` shows only the final one.
5. Then explain, referring to cycle numbers from the header row ("in cycle 3 valid and ready are both high, so …").

When comparing alternatives (e.g. registered vs. combinational ready, or current behaviour vs. the fix), draw one diagram per alternative, or put both in one diagram using groups.

## Getting the timing right

The diagram must match what the RTL actually does — a wrong waveform is worse than none.

- Each column is one clock cycle; the header shows cycle numbers. Use `p` for the clock (rising edge at the start of each cycle).
- A register assigned with `<=` in `always @(posedge clk)` changes **in the cycle after** the edge where its inputs were sampled. If `valid && ready` is true in cycle 3, a `q <= d` driven by it shows the new value from cycle 4.
- Combinational signals (`assign`, `always @*`) change in the same cycle as their inputs.
- Show reset when it matters to the explanation (`rst_n` low for the first cycles).
- Mark values you do not know or that do not matter as `x`; tri-state/undriven as `z`.
- If you are not sure about a cycle (e.g. you have not read the module yet), read the code first, or say explicitly that the diagram is an assumption.

## Keep it readable

- About 6–20 cycles and 3–10 signals. Use `|` to skip uneventful stretches.
- Order signals causally: clock, reset, control inputs, state, outputs, data.
- Use `["group name", sig, sig]` to group signals (e.g. `"master"`, `"slave"`), and `{}` for a blank spacer row.
- Use bus colours to carry meaning: `3`–`9` colour the box outline and label (3 yellow, 4 orange, 5 blue, 6 cyan, 7 green, 8 pink, 9 red, as in WaveDrom); `=` and `2` are uncoloured. E.g. one colour per FSM state, or the same colour for a value as it moves through pipeline stages.
- Keep bus labels short (`D0`, `IDLE`, `0x3`). Cycles widen automatically so every label fits, up to 16 characters per cycle; longer labels are truncated with `…`.
- Each signal takes three rows plus a blank line, so stay within about 8 signals per diagram. If the script warns the diagram is too wide, cut cycles, shorten labels, or pass `--width 4`.

## WaveJSON cheat sheet

```js
{ signal: [
  { name: "clk",   wave: "p......." },          // clock: p/n, P/N mark the active edge
  { name: "valid", wave: "0.1..0.." },          // 0 1 = levels, . = hold previous
  { name: "data",  wave: "x.=.=x..", data: ["D0", "D1"] }, // = or 2-9 = bus value, labels from data
  { name: "en",    wave: "01.|0...", node: ".a..b" },       // | = gap; node letters under cycles
  {},                                            // spacer
  ["fsm", { name: "state", wave: "2.3.4.2.", data: "IDLE RUN DONE IDLE" }],
  { name: "slow",  wave: "p...", period: 2 },    // each char spans 2 cycles
],
  edge: ["a~>b enable window"],                  // printed as a text note under the diagram
  head: { text: "title", tick: 0 },              // title; tick = first cycle number
  config: { hscale: 1 }                          // widen every cycle
}
```

Wave characters: `p n P N` clock, `0 1` levels, `h l H L` high/low, `x` unknown, `z` high-Z, `= 2 3 4 5 6 7 8 9` bus value, `.` continue, `|` gap.

The terminal renderer doesn't draw `edge` arrows (it prints them as text) or skins; the editor link shows them in full.

## Example

User: "When does `q` get the data in `always @(posedge clk) if (valid && ready) q <= data;`?"

```bash
python3 ~/.claude/skills/wavedrom/scripts/wave2term.py -e "{signal:[
 {name:'clk',   wave:'p......'},
 {name:'valid', wave:'01..0..'},
 {name:'ready', wave:'0.1.0..'},
 {name:'data',  wave:'x34.x..', data:'A B'},
 {name:'q',     wave:'x..44..', data:'B B'}]}"
```

Paste the output in a ```text block and add the editor link. Then explain: valid and ready are both high in cycles 2 and 3, so the edge at the start of cycle 3 captures B (the value present in cycle 2) and q shows B from cycle 3. The cycle-3 handshake captures B again at the start of cycle 4. A was never captured, because ready was low in cycle 1.
