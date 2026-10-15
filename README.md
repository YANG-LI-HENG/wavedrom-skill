# wavedrom skill for Claude Code

讓 Claude Code 在解釋 Verilog/RTL 時序時，主動畫出 [WaveDrom](https://wavedrom.com/) 波形，並直接顯示在 terminal 中。

- `SKILL.md`：skill 本體，說明什麼時候畫波形、怎麼寫 WaveJSON，以及如何確保時序和 RTL 一致
- `scripts/wave2term.py`：把 WaveJSON 轉成 Unicode/ASCII 波形，並產生 WaveDrom editor 連結（純 Python，不需安裝套件）

## 安裝

```bash
git clone <this repo> ~/.claude/skills/wavedrom
```

## 手動使用

```bash
python3 scripts/wave2term.py -e "{signal:[{name:'clk',wave:'p....'},{name:'d',wave:'x=.=x',data:'A B'}]}"
python3 scripts/wave2term.py wave.json --ascii
```
