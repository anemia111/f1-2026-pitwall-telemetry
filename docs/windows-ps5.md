# Windows と PS5 の接続

## 受信確認

- デモの UDP ポートは 20778、実機の初期値は 20777 です。デモ用の外部送信機を使う場合は `python -m pitwall.server --demo --demo-listen-only` と `python -m pitwall.demo --hz 60` を別のコンソールで起動します。
- PS5 の送信先は PC の LAN 側 IPv4 です。スマートフォンには UDP を直接送らず、PC の TCP 8000 から WebSocket と HTTPS非対応のローカルHTTPを配信します。
- Windows のネットワークプロファイルが **プライベート** であることを確認します。PCとPS5間の通信が遮断されるゲストWi-Fiやクライアント分離ネットワークでは到達しません。
- 自車のテレメトリーは自分で参照できます。オンライン対戦で他車が共有を制限している場合、燃料、ERS、車体ダメージなどは N/A になることがあります。

## Windows ファイアウォール

初回起動時の Windows ダイアログでプライベートネットワークのみ許可するか、管理者 PowerShell で受信ルールを追加します。以下は Windows の設定を変更するコマンドです。必要なポートだけを選んで実行してください。

```powershell
New-NetFirewallRule -DisplayName "APEX F1 2026 UDP" -Direction Inbound -Action Allow -Protocol UDP -LocalPort 20777 -Profile Private -RemoteAddress LocalSubnet
# スマートフォンなどの別端末から閲覧する場合のみ
New-NetFirewallRule -DisplayName "APEX Pit Wall LAN" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8000 -Profile Private -RemoteAddress LocalSubnet
```

PS5のIPが固定されている場合、`.env` の `APEX_PS5_IP` に入力するとアプリが他の送信元を無視します。通常は最初の有効な送信元を選び、5秒間データが途絶えた後に他の送信元への切り替えを許可します。実機用UDPを受けるPCでは、ルーターのポート転送を設定せずLAN内で利用します。

## LAN ブラウザ

```powershell
Copy-Item .env.example .env
# .env の APEX_ACCESS_KEY を編集
.\Start-PitWall.ps1 -Lan
```

- PC とスマートフォンの両方で、初回はキーが必要です。LAN専用のキーを用意し、他サービスのパスワードを再利用しないでください。
- Windows PC の **CONNECTION** に複数の IPv4 が表示された場合は、PS5 と同じネットワークのアドレスを選択します。
- スマートフォンは横向き表示にするとタイミング表を広く使えます。表の残り列は横スクロールで確認できます。
- HTTP の LAN IP は通常、音声認識用のセキュアコンテキストになりません。PCでの `http://127.0.0.1:8000/` は、対応ブラウザと日本語端末内認識パックがあれば利用できます。読み上げは端末が提供する日本語ローカル音声を利用します。

## 切り分け

| 症状 | 確認 |
|---|---|
| UDP 待機が続く | 実機モード、同じLAN、PC IPv4、20777/UDP、ゲーム内走行開始 |
| 無効パケットが増える | Format 2026、ゲームの更新、CONNECTIONのパケットバージョン・長さエラー |
| 受信はあるが時系列が空 | 記録が有効か、Lap DataとCar Telemetryが同じフレームで届いているか |
| 戦略が保留 | レース種別、乾燥路面、有効ラップ数、交換セット情報、赤旗・停止・欠損 |
| スマートフォンで開けない | `-Lan`、PCのLAN IPv4、TCP許可、端末同士の通信を許可したWi-Fi |
| 保存に失敗する | 空き容量、書き込み権限、アーカイブキューとドロップ数 |

バックアップを取る場合はアプリを終了してから `data/pitwall.sqlite3` をコピーします。記録量は受信頻度や車両数に依存し、24台・60 Hzで1時間あたり数GBになることがあります。
