# 逐格魚種素材

16種原創生物，每種6格、每秒8格游動循環；減少動態設定固定姿態，必要魚位仍依伺服器移動。四張1536×1024透明WebP依當場魚種載入，總計約1.63MiB；不載入第三方遊戲圖檔，不用舊圖做載入過渡。原PNG保留於本機產圖目錄，不進發佈包。

| 圖集 | 生物 | 原始提示詞 |
|---|---|---|
| swim-coast.webp | 沙丁、小丑、鯖魚、紅鯛 | [coast](asset-prompts/fishing-swim-coast-20261026.txt) |
| swim-ocean.webp | 鮪魚、魟魚、旗魚、龍魚 | [ocean](asset-prompts/fishing-swim-ocean-20261026.txt) |
| swim-boss.webp | 金蟹、章魚、電鰻、海龍 | [boss](asset-prompts/fishing-swim-boss-20261026.txt) |
| swim-legend.webp | 金甲龜、獵鯊、人魚、鯨王 | [legend](asset-prompts/fishing-swim-legend-20261026.txt) |

工具：內建ImageGen，transparent_background=true；Pillow僅將PNG轉為WebP（quality82、method6）。場上逐格動畫使用新圖集，圖鑑與休閒保留適用的原創靜態素材。炮台與寶箱沿用前版楠團自製arcade-atlas，沒有複製參考遊戲資產。
