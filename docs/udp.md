# UDP 2026 ワイヤ仕様と検証

EAが掲載した **Data Output from F1 25 2026 Season Pack (Season 8)**、Version 1.2 と、同じ投稿の C++ テレメトリー構造を参照しました。Season 8 文書はF2のドライバーIDを追加しています。パケットの形式識別にはヘッダーの `packetFormat = 2026` を使用します。ゲーム年フィールドはヘッダーとして保持します。 [EA公式UDP仕様と添付ファイル](https://forums.ea.com/blog/f1-games-game-info-hub-en/ea-sports%E2%84%A2-f1%C2%AE25-2026-season-pack-udp-specification/12187347)

ヘッダーはパディングなしの little-endian 29 byte です。

| Offset | Type | Field |
|---:|---|---|
| 0 | uint16 | packetFormat |
| 2, 3, 4 | uint8 | gameYear, gameMajorVersion, gameMinorVersion |
| 5, 6 | uint8 | packetVersion, packetId |
| 7 | uint64 | sessionUID |
| 15 | float32 | sessionTime (s) |
| 19, 23 | uint32 | frameIdentifier, overallFrameIdentifier |
| 27, 28 | uint8 | playerCarIndex, secondaryPlayerCarIndex |

| ID | Packet | Bytes |
|---:|---|---:|
| 0 | Motion | 1325 |
| 1 | Session | 926 |
| 2 | Lap Data | 1399 |
| 3 | Event | 45 |
| 4 | Participants | 1470 |
| 5 | Car Setups | 1233 |
| 6 | Car Telemetry | 1448 |
| 7 | Car Status | 1445 |
| 8 | Final Classification | 1134 |
| 9 | Lobby Info | 1062 |
| 10 | Car Damage | 1133 |
| 11 | Session History | 1460 |
| 12 | Tyre Sets | 231 |
| 13 | Motion Ex | 273 |
| 14 | Time Trial | 104 |
| 15 | Lap Positions | 1231 |
| 16 | Car Telemetry 2 | 269 |

全17種類はパケットバージョン1です。構造とフィールド順は `pitwall/schema_2026.json`、型ごとのデコーダーは `pitwall/protocol_2026.py` にあります。固定長の全車配列は24台、車両インデックスは0–23、二次プレイヤー未設定は255です。Event のペイロードは4文字コードで共用体を選び、未知コードのペイロードは解釈せず保存します。Session UIDはブラウザへ文字列で渡します。浮動小数点の NaN / Infinity は値欠損に変換します。

タイヤの配列は **RL / RR / FL / FR**、速度は km/h、温度は °C、空気圧は PSI、燃料は kg、エネルギーは J です。セクターとギャップの分部は `minutes × 60,000 + milliseconds` で復元します。タイミングの S3 は Session History と前周タイムが一致するときだけ表示します。

## 書き出し

CSV と Parquet はラップ・時系列分析用に、同一 overall frame の Lap Data と Car Telemetry を最大約10 Hzで抽出したものです。生UDPエクスポートは検証に通った入力を残します。ヘッダーは ASCII `APEXUDP1` の8 byte。以後は、little-endian の `float64 到着秒 + uint32 epoch + uint16 サイズ + データグラム` の繰り返しです。 `python -m scripts.verify_capture session.udp` で再デコードできます。
