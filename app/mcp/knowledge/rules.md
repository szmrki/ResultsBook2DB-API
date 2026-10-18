# rb2db 競技規則の変遷

<!-- このファイルは scripts/generate_rules_md.py が app/mcp/knowledge/rules/*.yaml から生成している。直接編集せず、YAML を直して生成し直すこと。 -->

Results Book に記録される値（盤面・投球・得点）や、その解釈に影響する競技規則の変更だけをまとめたもの。
**時期をまたいで集計・比較する前に、間に規則変更が挟まっていないかをここで確かめること。**

- 対象外: スウィーピング・ブラシ、服装、まれな反則への罰則、手続きの細かな変更など（記録に表れないもの）
- 一次情報源は WCF（World Curling）の規則書。WCF 版が見つからない年は JCA（日本カーリング協会）の日本語版で補っている
- 収録範囲は WCF 2011 年 6 月版〜2026 年 9 月版（§3 の版の一覧を参照）。それより前の大会（OWG2010）の規則は未調査

---

## 1. 集計で必ず気をつける境目

| 版 | 対象 | トピック | 種別 | 内容 |
|---|---|---|---|---|
| 2015 年 10 月版 | MD | MD の事前配置ストーン | 変更 | ハウス内の事前配置ストーン（Position B）の位置が、ティー（ハウスの中心）の後ろ端に接する位置から、4 フィートの円の後方（ストーンの後ろ端を 4 フィートの円の後ろ端に合わせる位置）に移った。 |
| 2015 年 10 月版 | MD | MD のパワープレー | 導入 | MD にパワープレーが新設された。1 試合に 1 回、置き石の配置を決める権利を持つチームが選べ、ハウス内の置き石をハウスの左右どちらかに（後ろ端をティーラインに付けて）、ガードの置き石を同じ側に置く。エキストラエンドでは使えない。 |
| 2017 年 10 月版 | 4人制 | フリーガードゾーン | 変更 | フリーガードゾーンの保護が、エンドの 5 投目より前（4 ロックルール）から 6 投目より前（5 ロックルール）に延びた。2017 年 10 月の改定で決まり、2018 年 10 月から適用された。 |
| 2018 年 10 月版 | MD | MD のブランクエンド後の置き石の配置権 | 変更 | MD で、計測しても同距離でブランクエンドになった場合は、置き石の配置を決める権利が次のエンドも変わらない、という例外が加わった。それまでは、ブランクエンドになれば同距離の場合も配置を決める権利が移っていた。 |
| 2022 年 10 月版 | 4人制 | ノーティックショット | 試験導入 | ノーティックルールが試験ルールとして、2022-23 シーズンのすべての大会（MD の大会を除く）で使われた。エンドの 5 投目までに、フリーガードゾーン内でセンターラインに触れている相手のストーンを、センターラインから外れる位置かフリーガードゾーンの外へ動かした場合、相手チームは「投げたストーンを取り除いて元に戻す」か「そのままにする」かを選べる。 |
| 2023 年 7 月版 | 4人制 | ノーティックショット | 導入 | 2022-23 シーズンの試験ルールだったノーティックルールが、規則書に正式に加わった（R7）。内容は試験ルールと同じで、車いすカーリングと MD には適用しない。 |
| 2026 年 9 月版 | MD | MD の事前配置ストーン | 変更 | ハウス手前側の事前配置ストーン（Position A）を置く基準点が、3 点から 4 点に変わった。基準の取り方も「ホッグラインとハウス前端の中間点」から「ハウス前端からの距離」に変わった。 |

それぞれのデータへの影響（どの大会が境目のどちら側か）は §2 を参照。

---

## 2. トピックごとの年表

### フリーガードゾーン（Free Guard Zone (FGZ)）

対象: 4人制。ハウス手前のガードを、エンド序盤に相手がアウトにすることを制限する規定。MD には別の規定がある（md_early_removal）。

- **2017 年 10 月版**（変更） フリーガードゾーンの保護が、エンドの 5 投目より前（4 ロックルール）から 6 投目より前（5 ロックルール）に延びた。2017 年 10 月の改定で決まり、2018 年 10 月から適用された。
  - 変更前: 5 投目より前に、相手のフリーガードゾーンのストーンをプレー外に出してはいけない（4 ロックルール）。
  - 変更後: 6 投目より前に、相手のフリーガードゾーンのストーンをプレー外に出してはいけない（5 ロックルール）。
  - データへの影響: 4 人制では 2018-19 シーズン（2018 年 10 月以降）の大会から 5 ロックルール。rb2db の four では、ECC2018（2018 年 11 月）以降が 5 ロックルールで、それより前の大会（OWG2010 から 2018 年春の WMCC2018・WWCC2018・WJCC2018 まで）はすべて 4 ロックルールで行われた。序盤のガードの残り方やショットの種類、ブランクエンドの割合を時期をまたいで比べるときは分けること。MD は別の規定（4 投目より前は置き石を含めてプレー外に出せない）なので関係しない。
  - 出典: jca-2017-12-notice（R6 (b)）

### ノーティックショット（No-Tick Shot）

対象: 4人制。センターライン上のガードを、エンド序盤に横へずらすことを制限する規定。

- **2022 年 10 月版**（試験導入） ノーティックルールが試験ルールとして、2022-23 シーズンのすべての大会（MD の大会を除く）で使われた。エンドの 5 投目までに、フリーガードゾーン内でセンターラインに触れている相手のストーンを、センターラインから外れる位置かフリーガードゾーンの外へ動かした場合、相手チームは「投げたストーンを取り除いて元に戻す」か「そのままにする」かを選べる。
  - データへの影響: 規則書への正式な追加は 2023 年版だが、4 人制の大会では 2022-23 シーズンからノーティックが効いている。ノーティックの前後で比べるときは、2022 年版の施行時期ではなく 2022-23 シーズンを境にすること。序盤（5 投目まで）のショットの種類やガードの残り方が変わりうる。
  - 出典: wcf-2022-trial（Trial Rule 2022-2023 p.2）
- **2023 年 7 月版**（導入） 2022-23 シーズンの試験ルールだったノーティックルールが、規則書に正式に加わった（R7）。内容は試験ルールと同じで、車いすカーリングと MD には適用しない。
  - データへの影響: 試験ルールからの継続なので、2022-23 シーズン以降の 4 人制の大会はすべてノーティックの下で行われている。md には関係しない。
  - 出典: wcf-2023-changes（R7 p.12）

### MD の事前配置ストーン（Mixed Doubles positioned stones）

対象: MD。MD で各エンド開始時に置くストーン（Position A / B）の位置と、置く側の決め方。

- **2015 年 10 月版**（変更） ハウス内の事前配置ストーン（Position B）の位置が、ティー（ハウスの中心）の後ろ端に接する位置から、4 フィートの円の後方（ストーンの後ろ端を 4 フィートの円の後ろ端に合わせる位置）に移った。
  - 変更前: センターライン上で、ストーンの前端がティーの後ろ端に接する位置。
  - 変更後: センターライン上で、ストーンの後ろ端が 4 フィートの円の後ろ端にそろう位置。
  - データへの影響: rb2db の座標系で計算すると、ハウス内の置き石の中心は変更前 y ≈ 38.55、変更後 y ≈ 38.87（計算値）。2026-10-18 時点の md データでは y ≈ 38.83〜38.87 に集まっており、変更後の位置と一致する。md のデータは WMDCC2016（2016 年 4 月）からなので、すべて変更後の大会。
  - 出典: wcf-2015-rules（R15 (f) (ii)）
- **2026 年 9 月版**（変更） ハウス手前側の事前配置ストーン（Position A）を置く基準点が、3 点から 4 点に変わった。基準の取り方も「ホッグラインとハウス前端の中間点」から「ハウス前端からの距離」に変わった。
  - 変更前: ホッグラインとハウス前端の中間点、およびそこから 3 フィート（914 mm）前後の計 3 点。
  - 変更後: ハウス前端から 4'6"（1.372 m）・6'6"（1.981 m）・8'6"（2.591 m）・10'6"（3.200 m）の計 4 点。
  - データへの影響: md の事前配置ストーン（shots.number = 0 に紐づく stones）のうち、ガード側の y 座標の分布がこの版を境に変わりうる。rb2db の座標系（Tee Line y = 38.405、ハウス半径 1.829 m）で基準点を計算すると、変更前は y ≈ 33.376 / 34.290 / 35.204、変更後は y ≈ 33.376 / 33.985 / 34.595 / 35.204（いずれも計算値。ストーンは点の直前か直後に置く）。2026-10-18 時点の md データ（すべて変更前の大会）では、ガード側の y はほぼすべて 35.0〜35.3 にあり、ハウス寄りの基準点付近に集中している。版をまたいで事前配置ストーンの位置を集計するときは、版ごとに分けること。
  - 出典: wcf-2026-changes（R17 (b) I p.25-26）

### MD のパワープレー（Mixed Doubles Power Play）

対象: MD。MD で事前配置ストーンを横にずらして置ける選択肢。使える回数と条件。

- **2015 年 10 月版**（導入） MD にパワープレーが新設された。1 試合に 1 回、置き石の配置を決める権利を持つチームが選べ、ハウス内の置き石をハウスの左右どちらかに（後ろ端をティーラインに付けて）、ガードの置き石を同じ側に置く。エキストラエンドでは使えない。
  - データへの影響: ends.is_power_play が意味を持つのはこの版以降。md のデータは WMDCC2016 からなので、すべてパワープレーのある規則の下で行われている。
  - 出典: wcf-2015-rules（R15 (f) (iii)）

### MD のブランクエンド後の置き石の配置権（Mixed Doubles - placement decision after a blank end）

対象: MD。MD で、両者無得点のエンドの後、次のエンドの置き石の配置を決める権利がどちらになるか。配置を決めるチームは通常ハンマーを取るので、ハンマーの推移を左右する。

- **2018 年 10 月版**（変更） MD で、計測しても同距離でブランクエンドになった場合は、置き石の配置を決める権利が次のエンドも変わらない、という例外が加わった。それまでは、ブランクエンドになれば同距離の場合も配置を決める権利が移っていた。
  - データへの影響: 同距離によるブランクエンドはまれだが、ハンマー（color_hammer）の推移の規則そのものが変わる。rb2db を生成するシステムは現行の規則（同距離なら配置を決める権利が移らない）に合わせて処理しているため、この版より前の md の大会（WMDCC2016・WMDCC2017・OWG2018・WMDCC2018）では旧規則で処理する必要がある。
  - 出典: jca-2018-11（R15 (g) (iii)）

### 持ち時間（Thinking time）

対象: 4人制・MD 共通。1試合・延長エンドごとの持ち時間。

- **2014 年 10 月版**（変更） 持ち時間の方式が、試合時間（playing time。投球中も時計が進み、10 エンドで 73 分）から、考慮時間（thinking time。投球中は時計が止まり、10 エンドで 38 分）に変わった。
  - 変更前: 10 エンドで 73 分、8 エンドで 59 分、MD は 46 分の試合時間（playing time）。
  - 変更後: 10 エンドで 38 分、8 エンドで 30 分、MD は 22 分の考慮時間（thinking time）。延長は 1 エンドごとに 4 分 30 秒（MD は 3 分）。
  - データへの影響: 2026-10 時点の rb2db には時間の記録がないので、集計への影響はない。将来、残り時間や使用時間を取り込む場合は、この版より前（2014 年冬季五輪など）と後で時間の意味が異なるので、そのまま比べないこと。
  - 出典: wcf-2014-rules（C6 (a)）

### 記録に影響する変更が見つかっていないトピック

確認済みの版（§3）の範囲では、次のトピックに記録へ影響する変更はなかった。

- MD の序盤のストーン除去の制限（MD）: MD で、エンドの 4 投目より前は、置き石やハウス内のストーンを含めてどのストーンもプレー外に出せない規定。4 人制のフリーガードゾーンに当たる。
- ブランクエンド後のハンマー（4人制）: 4 人制で、両者無得点のエンドの後もハンマーは移らない（どちらかが得点するまで投球順を保つ）規定。MD は規則が異なる（md_placement_after_blank）。
- エンド数（4人制・MD 共通）: 1試合のエンド数（10 / 8 など）。
- 第1エンドのハンマーの決め方（4人制・MD 共通）: 試合開始時のハンマーを決める方法（LSD など）。
- エキストラエンド（4人制・MD 共通）: 同点で規定エンドを終えたときの延長の扱い。
- コンシードの条件（4人制・MD 共通）: 試合を途中で終える（コンシードする）ことができる条件。ends の NULL の出方に影響する。
- タイムアウト（4人制・MD 共通）: チームタイムアウトの回数と時間。

---

## 3. 版の一覧

「確認済み」の版で §2 に記載がないトピックは、その版で記録に影響する変更がなかったことを表す。
「主要トピックのみ」の版は調査の起点で、それより前からの変更は調べていない。

| 版 | 対応する JCA 版 | 確認状況 | 記録に影響する変更 |
|---|---|---|---|
| 2011 年 6 月版 | — | 主要トピックのみ | 0 件 |
| 2014 年 10 月版 | 2015.06 | 確認済み | 1 件 |
| 2015 年 10 月版 | 2016.02 | 確認済み | 2 件 |
| 2016 年 10 月版 | 2017.12 | 確認済み | 0 件 |
| 2017 年 10 月版 | 2017.12 | 確認済み | 1 件 |
| 2018 年 10 月版 | 2018.11 | 確認済み | 1 件 |
| 2019 年 10 月版 | 2019.10 | 確認済み | 0 件 |
| 2020 年 10 月版 | 2020.11 | 確認済み | 0 件 |
| 2021 年 10 月版 | 2021.11 | 確認済み | 0 件 |
| 2022 年 10 月版 | 2022.11 | 確認済み | 1 件 |
| 2023 年 7 月版 | 2023.10 | 確認済み | 1 件 |
| 2024 年版 | 2024.10 | 確認済み | 0 件 |
| 2025 年版 | 2025.09 | 確認済み | 0 件 |
| 2026 年 9 月版 | 2026.09 | 確認済み | 1 件 |

- 表紙の日付を施行日の目安としている（本文に施行日の明記がない版がほとんど）。例外は §2 に書いてある（5 ロックルールは 2017 年 10 月版で決まり 2018 年 10 月から適用、など）
- JCA 版の年月は日本語版の公開時期で、WCF の施行日とは別物

---

## 4. 大会と版の対応づけ

`events` には大会の年（`year`）しかなく、開始日がない（追加予定: szmrki/ResultsBook2DB#30）。そのため現状は、大会の開催時期と版の日付を比べて判断する。

- 規則は毎年秋に改定される。秋に開催される大会（ECC・PCCC など）はその年の版、冬〜春に開催される大会（OWG・WMCC・WWCC・WJCC・WMDCC など）は前年秋の版で行われる、が目安
- 境目に近い大会は §2 の「データへの影響」に大会名で書いてある

---

## 5. 原典

§2 の「出典」の ID と対応する。元の URL が消えているものは Wayback Machine の保存版を載せている。

- `wcf-2026-rules`（WCF・規則書）: https://worldcurling.org/wp-content/uploads/2026/10/Rules-2026_Clean.pdf
- `wcf-2026-changes`（WCF・変更箇所を示した版）: https://worldcurling.org/wp-content/uploads/2026/08/Rules2026-ChangeLog.pdf
- `wcf-2023-rules`（WCF・規則書）: https://worldcurling.org/wp-content/uploads/2023/07/2023-The-Rules-of-Curling.pdf
- `wcf-2023-changes`（WCF・変更箇所を示した版）: https://web.archive.org/web/20240115220358/https://worldcurling.org/wp-content/uploads/2023/07/2023-The-Rules-of-Curling-_Change-Log.pdf
- `wcf-2022-rules`（WCF・規則書）: https://web.archive.org/web/2022/https://s3.eu-west-1.amazonaws.com/media.worldcurling.org/media.worldcurling.org/wcf_worldcurling/2022/09/19104837/2022-The-Rules-of-Curling19092022.pdf
- `wcf-2022-changes`（WCF・変更箇所を示した版）: https://web.archive.org/web/2022/https://s3.eu-west-1.amazonaws.com/media.worldcurling.org/media.worldcurling.org/wcf_worldcurling/2022/09/19104846/2022-The-Rules-of-Curling-Change_Log_19092022.pdf
- `wcf-2022-trial`（WCF・試験ルール）: https://web.archive.org/web/2023/https://s3.eu-west-1.amazonaws.com/media.worldcurling.org/media.worldcurling.org/wcf_worldcurling/2023/01/24084936/Trial-Rule-2022-2023_19012023.pdf
- `wcf-2021-rules`（WCF・規則書）: https://web.archive.org/web/2021/https://s3.eu-west-1.amazonaws.com/media.worldcurling.org/media.worldcurling.org/wcf_worldcurling/2021/10/11092643/2021-The-Rules-of-Curling.pdf
- `wcf-2021-changes`（WCF・変更箇所を示した版）: https://web.archive.org/web/2021/https://s3.eu-west-1.amazonaws.com/media.worldcurling.org/media.worldcurling.org/wcf_worldcurling/2021/10/11092658/2021-The-Rules-of-Curling-Change-Log.pdf
- `wcf-2020-rules`（WCF・規則書）: https://web.archive.org/web/2020/https://s3.eu-west-1.amazonaws.com/media.worldcurling.org/media.worldcurling.org/wcf_worldcurling/2020/10/13151044/2020-The-Rules-of-Curling.pdf
- `wcf-2020-changes`（WCF・変更箇所を示した版）: https://web.archive.org/web/2020/https://s3.eu-west-1.amazonaws.com/media.worldcurling.org/media.worldcurling.org/wcf_worldcurling/2020/10/13151057/2020-The-Rules-of-Curling-Change-log.pdf
- `wcf-2019-rules`（WCF・規則書）: https://web.archive.org/web/2019/https://s3-eu-west-1.amazonaws.com/media.worldcurling.org/media.worldcurling.org/wcf_worldcurling/2019/09/17100751/2019-The-Rules-of-Curling.pdf
- `wcf-2019-changes`（WCF・変更箇所を示した版）: https://web.archive.org/web/2019/https://s3-eu-west-1.amazonaws.com/media.worldcurling.org/media.worldcurling.org/wcf_worldcurling/2019/09/17100941/2019-The-Rules-of-Curling-_Changelog.pdf
- `wcf-2016-changes`（WCF・The Rules of Curling Showing Changes (September 2016)）: https://web.archive.org/web/20170814181955/http://www.worldcurling.org/download/?dl==AFVxIkVWZ1RhxmRWR1aatWVFlVeWxGcDJlRapVUq5UV
- `wcf-2016-rules`（WCF・The Rules of Curling (October 2016)）: https://web.archive.org/web/20161031214914/http://www.worldcurling.org/download/?dl==AFVxIkVWZ1RhxmRWR1aatWVFlVeWxGc3NlRapVUq5UV
- `wcf-2015-summary`（WCF・Summary Rule and Policy Changes 2015）: https://web.archive.org/web/20160412203619/http://www.worldcurling.org/download/?dl==AFVxIkVWZ1RhxmRWR1aatWVFlVeWxGc3dlRsRzUUZUV
- `wcf-2015-changes`（WCF・The Rules of Curling Showing Changes (October 2015)）: https://web.archive.org/web/20160412142617/http://www.worldcurling.org/download/?dl==AFVxIkVWZ1RhxmRWR1aatWVFlVeWxGcDZlRWlVUq5UV
- `wcf-2015-rules`（WCF・The Rules of Curling (October 2015)）: https://web.archive.org/web/20160412140257/http://www.worldcurling.org/download/?dl==AFVxIkVWZ1RhxmRWR1aatWVFlVeWxGcz1UMWlVUq5UV
- `wcf-2014-changes`（WCF・Change Log: WCF Rules of Curling 2011 to 2014）: https://web.archive.org/web/20150906185959/http://www.worldcurling.org/download/?dl==AFVxIkVWZ1RhxmRWR1aatWVFlVeWxGczNlRah1UqZUV
- `wcf-2014-rules`（WCF・WCF Rules of Curling (October 2014)）: https://web.archive.org/web/20150906133707/http://www.worldcurling.org/download/?dl==AFVxIkVWZ1RhxmRWR1aatWVFlVeWxGcvNlRah1UqZUV
- `wcf-2011-rules`（WCF・WCF Rules of Curling (June 2011)）: https://web.archive.org/web/20140115034244/http://www.worldcurling.org/download/?dl==AFVxIkVWZ1RhxmRWR1aatWVFlVeWxGcvdlRkRzUXhXV
- `jca-2026-09`（JCA・規則書）: https://web.archive.org/web/20261002105029/https://www.curling.or.jp/sites/default/files/2026-09/rule-2026-09-01-38.pdf
- `jca-2025-09`（JCA・規則書）: https://web.archive.org/web/20251011125634/https://www.curling.or.jp/committee/competition/rule-2025-09-01-37.pdf
- `jca-2024-10`（JCA・規則書）: https://web.archive.org/web/20250217210207/https://www.curling.or.jp/committee/competition/rule-2024-10-1-36.pdf
- `jca-2023-10`（JCA・規則書）: https://web.archive.org/web/20231211164506/http://curling.or.jp/committee/competition/rule-2023-10-1-36.pdf
- `jca-2022-11`（JCA・規則書）: https://web.archive.org/web/20230128105818/http://curling.or.jp/committee/competition/rule-2022-11-1-34.pdf
- `jca-2021-11`（JCA・規則書）: https://web.archive.org/web/20211203013014/http://curling.or.jp/committee/competition/rule-2021-11-1-34.pdf
- `jca-2020-11`（JCA・規則書）: https://web.archive.org/web/20210128055400/http://curling.or.jp/committee/competition/rule-2020-11-1-35.pdf
- `jca-2018-11`（JCA・規則書）: https://web.archive.org/web/20190708164940/http://www.curling.or.jp/senmoniinkai/kyogi/new-rule-2018-11-p01-p37.pdf
- `jca-2017-12-notice`（JCA・改定案内）: https://web.archive.org/web/20180209204357/http://www.curling.or.jp/senmoniinkai/kyogi/2017-12new-rule-info.pdf
- `jca-2016-02-notice`（JCA・改定案内）: https://web.archive.org/web/20160813111757/http://curling.or.jp/senmoniinkai/kyogi/2016.02.04new-rule-info.pdf
- `jca-2015-06-notice`（JCA・改定案内）: https://web.archive.org/web/20160813115945/http://curling.or.jp/senmoniinkai/kyogi/2015.06new-rule-info.pdf
