# 1. LINE APIとサーバーについて
## 1-1. LINE側の管理
LINE_CHANNEL_ACCESS_TOKEN = (.envに記載の通り)\
LINE_CHANNEL_SECRET = (.envに記載の通り)\

LINE Developers: `https://developers.line.biz/console/`\
LINE Official Account Manager: `https://manager.line.biz/`\

公式LINEを使い、アカウントを作成した後、LINE Developersでボットを作成している。また、リッチメニューを作成できる。
今のところ「収入」に関するものは全て切っているので、必要ならOfficial Account Managerからリッチメニューを変えるとよい。
また、リッチメニューの有効期限が2037年12月31日までなので、それ以降更新する必要がある。（2026年8月4日時点）

## 1-2. サーバー側の管理
あ

# 2. csvフォルダ
`scripts/db_to_csv.py`を実行するとここに書き出される。csvファイルには日付が名前としてつく。これをエクセルで読み込む。

# 3. dbフォルダ
SQLiteを用いたデータベースはここに格納される。消さないように注意！一応消しにくいように保護はかけている。

# 4. scriptsフォルダ
## 4-1. app.py
サーバー上で常に実行されており、LINEでのやり取りはこのプログラムが実行される。「収入」に関するコードも書かれているが、今のところLINEのリッチメニューやdb_to_csv.pyからは消している。

## 4-2. check_db.py
データベースファイル全体を見るプログラム。支出または収入全体を標準出力する。

## 4-3. db_to_csv.py
データベースファイルからcsvファイルを作成する。今のところ収入のcsvは作成しないようにしている。コメントをつけているだけなので外せばいつでも使える。

## 4-4. init_db.py
初期設定用プログラム。これを実行するなら一旦dbファイルを消す必要があると思うので、運用していく際はできれば実行しないようにする。

## 4-5. db_manager.py
いろんな補助機能をまとめている。app.pyやadmin_app.pyで使う。

## 4-6. admin_app.py
ローカルならPC上でさまざまな設定ができる。サーバーでapp.pyが動いていても同時に動かせる。実行手順は、housekeepフォルダで`streamlit run .\scripts\admin_app.py`を実行。


# 5. housekeep.xlsx
家計簿全体のエクセルファイル。支出シートや収入シートにcsvファイルを読み込むとロードできる。