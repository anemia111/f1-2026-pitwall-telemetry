# APEX Race Engineering — 2026 Pit Wall

PS5版 EA SPORTS F1 25「2026 Season Pack」の UDP を Windows PC で受信し、ブラウザから分析・記録・再生するローカルアプリです。最大24台のタイミング、テレメトリー、条件付きの戦略比較、日本語のチーム無線を1つの画面から操作できます。

## Windows で起動

1. [Python 3.12](https://www.python.org/downloads/) をインストールします。セットアップには Windows の Python ランチャー `py` を使います。
2. ZIP をフォルダーに展開し、`Setup.cmd` を実行します。ソースからビルドする場合は [Node.js 22 以降](https://nodejs.org/) も必要です。ビルド済みZIPでは Python の依存パッケージだけをインストールします。
3. `Start-Demo.cmd` を実行し、Edge または Chrome で [http://127.0.0.1:8000/](http://127.0.0.1:8000/) を開きます。
4. デモのヘッダーに **DEMO / 模擬データ**、順位表に24台が表示されます。ゲーム内時間は8倍速で、約35秒で有効ラップ3周分が揃います。セッション終了後は **REPLAY** で記録を開けます。

実機入力はデモを終了してから `Start-Live.cmd` を実行します。保存先の初期値は `data/pitwall.sqlite3` です。記録の開始・停止は **REPLAY** から操作できます。

PowerShell から起動する場合

```powershell
.\Setup.ps1
.\Start-PitWall.ps1 -Demo -DemoRate 60
# 実機モード
.\Start-PitWall.ps1
```

## PS5 とスマートフォンを接続

1. PS5 と PC を同じプライベート LAN に接続します。PCの **CONNECTION** 画面で PC の IPv4 を確認します。
2. PS5 の F1 25 で `Game Options → Settings → UDP Telemetry Settings` を開きます。UDP Telemetry を **On**、Broadcast を **Off**、UDP IP Address を PC の IPv4、Port を **20777**、UDP Format を **2026**、Send Rate を **60 Hz** に設定します。
3. ゲームで走行を開始し、**CONNECTION** の送信元・受信数と **PIT WALL** の車両データを確認します。UDP受信がゼロの場合は [Windows・PS5接続手順](docs/windows-ps5.md) を参照してください。
4. スマートフォンからも見る場合は、`.env.example` を `.env` にコピーし、`APEX_ACCESS_KEY` に専用の12文字以上のキーを設定します。`.\Start-PitWall.ps1 -Lan` で起動し、**CONNECTION** の QR または LAN URL を開いてキーを入力します。QRにキーは含まれません。

ゲーム設定とデータ形式の根拠は [EA公式UDP仕様](https://forums.ea.com/blog/f1-games-game-info-hub-en/ea-sports%E2%84%A2-f1%C2%AE25-2026-season-pack-udp-specification/12187347) です。

## ワークスペース

| 画面 | 操作 |
|---|---|
| PIT WALL | 順位・ギャップ・ラップ・タイヤ・旗・アクティブエアロを確認。順位表で車両を選択 |
| AI ENGINEER | 日本語でペース、ギャップ、タイヤ、戦略、ERS、走行改善を質問。無線頻度・呼び名・音声を設定 |
| DRIVER / LAP COMPARE | 距離または時刻基準のトレース、ラップ比較、タイムデルタ、制動・最低速・再加速の区間比較 |
| CIRCUIT / TYRES / POWER UNIT | 走行から得た座標、エアロ・DRSゾーン、4輪温度と摩耗、ERSとエネルギー履歴 |
| STRATEGY | 条件付きの3案、ピットロスと摩耗閾値の編集、選択の記録、予測と観測結果の照合 |
| REPLAY | 再生・一時停止・速度・シーク・ラップとイベントへのジャンプ、CSV・Parquet・生UDPの書き出し |
| CONNECTION | 接続診断、送信元、無効パケット、書き込みキュー、LAN URL とQR |

チャートは拡大ボタン、Ctrl / Alt + スクロール、ドラッグ、カーソル、系列切替に対応します。ワークスペースは別ウィンドウで開けます。無線は各タブで音声を有効にしたときに再生します。

## 戦略と音声の前提

- 優先度付き無線、ピット候補、タイヤ推定、質問への数値回答は決定論的に処理します。受信や該当パケットが古い場合は判断を止めます。シナリオは観測済みの現スティント、交換セットの在庫、設定したピットロスを使います。
- 戦略は同一コンパウンドでの交換時期を比較します。モンテカルロの帯は設定したモデル内のばらつきです。天候、レース規則、交通、燃料、他車の将来のピットを含むレース全体の予測には未対応です。SC/VSC は今周のピットロス仮定に反映します。
- 端末が提供する日本語ローカル音声がある場合に読み上げます。音声認識はセキュアコンテキストと日本語の端末内認識に対応したブラウザのみです。利用できない端末ではテキストで質問できます。
- 既にインストール済みのローカル Ollama モデルを使う場合は `.env` の `APEX_OLLAMA_MODEL` にモデル名を設定します。定型語で判別できない質問の意図分類に使い、数値と助言本文は決定論的に生成します。ローカル推論に失敗すると定型応答へ戻ります。
- テレメトリーと履歴は PC のローカルDBに記録します。LAN の HTTP モードは信頼できる家庭内ネットワーク向けです。PCのLAN公開は `-Lan` で有効になります。

## 開発・検証

```powershell
.\Setup.ps1 -Build -Dev
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m scripts.bench --seconds 60
# デモが起動している状態で Edge のブラウザ試験
.\.venv\Scripts\python.exe tests/browser_smoke.py --channel msedge
# 保存した生パケットを現在のパーサーで再検査
.\.venv\Scripts\python.exe -m scripts.verify_capture .\apex-session.udp
# 保存済みの予測と実測結果を照合
.\.venv\Scripts\python.exe -m scripts.audit .\data\pitwall.sqlite3 SESSION_ID
# ビルド済みZIPを再作成
.\.venv\Scripts\python.exe -m scripts.package ..\APEX-2026-Pit-Wall-Windows.zip
```

UDP・アーカイブ構造は [プロトコル](docs/udp.md)、アプリ構造は [アーキテクチャ](docs/architecture.md)、検証状況と残作業は [進捗](PROGRESS.md) を参照してください。元の実装は MIT ライセンスです。F1 と EA の名称は互換性を示すために使っています。
