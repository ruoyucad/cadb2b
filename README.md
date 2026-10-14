# cadb2b — 加拿大政府采购中标商情报

把加拿大联邦政府公开的采购数据（CanadaBuys）整理成"**哪些加拿大公司经常中政府的标、中的是什么货**"，给中国工厂找渠道客户用。

> 中国工厂一般没法直接投加拿大政府的标，但可以给经常中标的加拿大本地供应商供货。信息差在于：工厂不知道谁在中标、该找谁。

## 数据来源

全部来自官方开放数据（Open Government Licence – Canada，可商用，需注明来源），不需要爬虫：

| 数据 | 内容 | 时间范围 |
|---|---|---|
| Contract history | 谁拿了什么合同、金额、供应商地址、员工规模、**货物原产国占比** | 2009 至今 |
| Award notices | 中标公告 | 2012 至今 |
| Tender notices | 正在招标的项目 | 实时（每天/每2小时刷新）|

链接和字段定义见 `cbintel/sources.py`。

## 快速开始

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python -m cbintel all --quick     # 先跑小数据（跳过2023年以前的大文件），几分钟
python -m cbintel all             # 全量，含2009年起的历史
```

也可以分步跑：

```bash
python -m cbintel download        # 下载CSV到 data/raw/（没变化的文件会跳过）
python -m cbintel build           # 导入DuckDB、清洗、建表
python -m cbintel report --top 50 --segment 46 --segment 56   # 导出指定品类
```

输出在 `output/`：

- `supplier_leaderboard.csv` — 各品类近5年中标排行（中文表头，Excel可直接打开）
- `open_goods_tenders.csv` — 当前开放的货物类招标，附"该品目历史中标者"
- `segment_overview.md` — 各品类的中标公司数、合同数、金额，用来选赛道

## 处理逻辑

```
data/raw/*.csv
   └─ stg_*                    原始数据，字段改成 snake_case，去掉法语重复列
       └─ fct_contract          每个(合同, 供应商)一行：取最后一次修订的累计金额，最早的中标日期；
       │                        award notices 只补充 contract history 里没有的合同
       └─ dim_supplier          每家供应商一行：同一家公司的不同写法合并
       │                        （Inc./Ltd./Ltée、大小写、法语重音）
       └─ mart_supplier_segment 供应商 × 品类（只算货物类、适合中国制造的品类、近5年）
       └─ mart_supplier_leaderboard  品类内排名
       └─ mart_open_goods_tenders    正在招标 + 历史中标者
```

排名打分偏向**反复中标**的公司（说明有稳定需求），而不是只中过一次大单的；如果合同里申报过中国产品，额外加分（说明已经在从中国进货）。

## 为什么用 DuckDB 而不是 MySQL

- **不用装服务器**：DuckDB 是一个Python包，数据库就是一个文件（`data/cbintel.duckdb`），像 SQLite 一样。MySQL 要装、要起服务、要管账号。
- **专为分析设计**：这个项目是"读大CSV → 聚合 → 排名"，正是列式数据库擅长的。百万行的聚合在笔记本上几秒钟。
- **直接读CSV/Parquet**：`SELECT * FROM 'file.csv'` 就能查，省掉导入步骤。
- 以后要做带登录的网站，网站后台（用户、订阅、付费）再用 Postgres/MySQL；DuckDB 负责算好结果，导出给网站用。两者分工，不冲突。

想直接查数据：

```bash
python -c "import duckdb; print(duckdb.connect('data/cbintel.duckdb').sql('SELECT * FROM mart_supplier_leaderboard LIMIT 20'))"
```

或安装 DuckDB CLI / DBeaver 打开 `data/cbintel.duckdb`。

## 测试

```bash
pytest -q
```

测试用的是按真实字段结构生成的小样本（`tests/fixtures.py`），不需要联网。

## 注意

- 本仓库是公开的，所以 `data/` 和 `output/` 不进 git（也超过 GitHub 100MB 单文件限制）。原始数据随时可以重新下载。
- 只收录政府公开的企业信息和企业官网公开的销售联系方式，不收录个人信息。
- 再发布时需注明：*Contains information licensed under the Open Government Licence – Canada.*

## 下一步

- [ ] 用真实数据跑一遍，检查供应商合并效果，调整品类和打分
- [ ] 补全官网 / 公开销售邮箱（搜索 + LLM 抽取），填 `dim_supplier.website` 等字段
- [ ] LLM 生成每家公司的中文摘要（买什么、多少钱、多久一次），填 `summary_zh`
- [ ] 选 2–3 个品类出样本报告，测试付费意愿
- [ ] 再决定做网站（登录查看）还是公众号推送
