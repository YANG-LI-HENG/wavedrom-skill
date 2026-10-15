# wavedrom skill for Claude Code

讓 Claude Code 在解釋 Verilog/RTL 時序時，主動畫出 [WaveDrom](https://wavedrom.com/) 波形，存成 HTML + 白底 PNG（或 SVG）並自動用瀏覽器打開。

- `SKILL.md`：skill 本體，說明什麼時候畫、怎麼寫 WaveJSON、怎麼確保時序和 RTL 一致
- `scripts/wave2img.py`：WaveJSON → `~/waveforms/<name>.html`（官方 WaveDrom 渲染，可下載 SVG/PNG）+ 圖片（預設白底 `.png`）+ `.json`
- `scripts/setup.sh`：安裝產生圖片用的 Python WaveDrom + cairosvg（建在 `~/.local/share/wavedrom-venv`，不需 sudo）
- `scripts/wave2term.py`：同樣的 WaveJSON 轉成 terminal 文字波形（備用）

## 安裝

```bash
git clone git@github.com:YANG-LI-HENG/wavedrom-skill.git ~/.claude/skills/wavedrom
~/.claude/skills/wavedrom/scripts/setup.sh
```

## 手動使用

```bash
python3 scripts/wave2img.py -n demo -e "{signal:[{name:'clk',wave:'p....'},{name:'d',wave:'x3.4x',data:'A B'}], head:{tick:0}}"
```

## 設定

`~/.config/wavedrom-skill/config.json`（命令列參數優先）：

```json
{ "format": "png", "out": "~/waveforms", "scale": 2, "open": true }
```

- `format`：`png`（白底，預設）、`svg`、`both`、`none`
- `out`：輸出資料夾
- `scale`：PNG 放大倍率
- `open`：畫完是否自動用瀏覽器打開 HTML

單次覆寫：`wave2img.py -f svg ...`、`--scale 3`、`--no-open`
