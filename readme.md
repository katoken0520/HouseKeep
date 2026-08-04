# 1. LINE APIについて
LINE_CHANNEL_ACCESS_TOKEN = (.envに記載の通り)\
LINE_CHANNEL_SECRET = (.envに記載の通り)\

LINE Developers: `https://developers.line.biz/console/`\
LINE Official Account Manager: `https://manager.line.biz/`\

公式LINEを使い、アカウントを作成した後、LINE Developersでボットを作成している。また、リッチメニューを作成できる。
今のところ「収入」に関するものは全て切っているので、必要ならOfficial Account Managerからリッチメニューを変えるとよい。
また、リッチメニューの有効期限が2037年12月31日までなので、それ以降更新する必要がある。（2026年8月4日時点）

# 2. Webアプリ化について
Streamlit: `https://share.streamlit.io/`を使っている。GitHubと連携済み。ここのMyAppsから飛ぶと完全版の家計簿管理システムにアクセスできる。

# 3. サーバーについて
Render: `https://dashboard.render.com/`を使用。LINEから簡易的に登録、削除ができるようにするためのサーバー。出先でも登録できるようにサーバーを使用。

# 4. クラウドDBについて
Supabase: `https://supabase.com/`というクラウドデータベースを使っている。ここにDBが格納される。無料。
詳しいことはよくわからないが、Session PoolerというIPv4を使った方法で接続しているらしい。IPv6を使う方だと家ではうまくいかないので。

# 5. scriptsフォルダ
## 5-1. app.py
サーバー上で常に待機状態になっている。LINEでのやり取りはこのプログラムで処理される。「収入」に関するコードも書かれているが、今のところLINEのリッチメニューやdb_to_csv.pyからは消している。

## 5-2. check_db.py
データベースファイル全体を見るプログラム。支出または収入全体を標準出力する。将来的には不要。

## 5-3. db_to_csv.py
データベースファイルからcsvファイルを作成する。今のところ収入のcsvは作成しないようにしている。コメントをつけているだけなので外せばいつでも使える。将来的には不要。

## 5-4. init_db.py
初期設定用プログラム。これを実行するなら一旦dbファイルを消す必要があると思うので、運用していく際はできれば実行しないようにする。将来的には不要。

## 5-5. db_manager.py
いろんな補助機能をまとめている。app.pyやadmin_app.pyで使う。

## 5-6. admin_app.py
ローカルならPC上でさまざまな設定ができる。サーバーでapp.pyが動いていても同時に動かせる。実行手順は、housekeepフォルダで`streamlit run .\scripts\admin_app.py`を実行。