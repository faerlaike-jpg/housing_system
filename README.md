# 潍坊市二手房房价预测系统

基于 **Hadoop + Spark + SparkSQL + Spark MLlib + Django + ECharts** 的二手房数据分析与房价预测系统。

- 前台地址（虚拟机）：**http://192.168.100.102:8000/**
- 后台地址（虚拟机）：**http://192.168.100.102:8000/admin/**

---

## 一、账号与密码

| 角色 | 账号 | 密码 | 说明 |
| :--- | :--- | :--- | :--- |
| 管理员 | `admin` | `admin123456` | 已预置，前台与后台均可登录 |
| 普通用户 | —— | —— | 无预置账号，在登录页的「注册」选项卡自行注册 |

- 默认管理员由 `sql/schema.sql` 写入，密码为 Django PBKDF2 哈希。
- 普通用户（`is_staff = 0`）无法进入 `/admin/` 与 `/ops/`，这是后端权限装饰器拦下的（返回 403），
  前端只是同步隐藏了入口。
- 把某个普通用户提升为管理员：

  ```sql
  UPDATE sys_user SET is_staff = 1, role = 1 WHERE username = '你的账号';
  ```

---

## 二、启动方式

### 2.1 虚拟机启动（推荐，当前部署方式）

服务已由 systemd 托管，并已设置为**开机自启**，正常情况无需手动操作。

```bash
systemctl start housing        # 启动
systemctl stop housing         # 停止
systemctl restart housing      # 重启
systemctl status housing       # 查看状态
systemctl disable housing      # 取消开机自启

journalctl -u housing -f       # 实时查看日志
journalctl -u housing -n 100   # 查看最近 100 行日志
```

单元文件位置：`/etc/systemd/system/housing.service`
项目部署目录：`/opt/module/housing_app/`

也可以用备用脚本（与 systemd 二选一，同时用会抢 8000 端口）：

```bash
cd /opt/module/housing_app
./start.sh        # 前台启动
./stop.sh         # 停止
nohup ./start.sh > run.log 2>&1 &   # 后台启动（日志写入 run.log）
```

### 2.2 本机开发启动（Windows）

```powershell
cd e:\广州软件学院学习资料\毕业设计\housing_system\backend
conda activate housing
python manage.py runserver
```

访问 http://127.0.0.1:8000/ （连接的是虚拟机上的同一个数据库）

> `housing` 是这个项目专用的 conda 环境，里面有 `pyspark`。
> 如果不用它，预测会自动降级为「统计估算」，页面不会报错但精度较低。

### 2.3 运行时依赖

| 依赖 | 用途 | 是否必须 |
| :--- | :--- | :--- |
| MySQL（192.168.100.102:3306） | 存放业务数据 | **必须** |
| Java + Spark（本地模式） | 房价预测 | 使用预测功能时必须 |
| Hadoop / HDFS / YARN | 数据 ETL 与模型训练 | 仅跑大数据任务时需要 |

数据库连接：库名 `housing_db`，账号 `root`，密码 `000000`
（配置在 `backend/housing_project/settings.py`，可用环境变量覆盖）

> 日常浏览、筛选、图表、导出等功能只需要 MySQL。

---

## 三、页面清单

### 3.1 用户端（前台）

| 路径 | 页面 | 主要功能 |
| :--- | :--- | :--- |
| `/` `/data-list/` | 数据列表 + 高级筛选 | 多维筛选、分页、勾选房源、导出 CSV / Excel；**房源收藏（星标）**、**性价比标签列**、**支持 URL 参数预选筛选**（如 `?district=奎文区`）、**筛选条件保存复用**；点标题进详情页 |
| `/house/<id>/` | 房源详情页 | 房源全部属性明细、**性价比分析（模型估值 vs 同类均价）**、**市场价位定位（同区域面积-总价散点图，高亮本房源并画趋势线 + 同类对比条 + 偏离度双向条）**、收藏按钮、同区域推荐房源 |
| `/dashboard/` | 数据分析仪表盘 | 7 张 ECharts 图表 + 统计数字看板（含面积-总价散点分布、特征相关性矩阵、随机森林特征重要性）；**点击区域图表可钻取到数据列表** |
| `/compare/` | 房源对比 | 2–4 套房源并排对比，最优 / 较差指标高亮；点标题进详情页 |
| `/heat-map/` | 二手房热力图 | 各区均价与挂牌量气泡图，支持按均价 / 挂牌量切换；**点击区域气泡可钻取到数据列表** |
| `/predict/` | 房价预测 | 随机森林预测总价与单价 + 同区域相似房源推荐；**新增「小区名称」自动补全**（填写后按小区均价校准，命中时显示「已按小区校准」标签）；推荐卡片可点进详情页 |
| `/login/` | 登录 / 注册 | 两个选项卡切换 |
| `/profile/` | 个人中心 | 修改资料、修改密码、**我的预测记录（可逐条删除）**、**我的房源收藏**、退出登录 |

> **权限**：浏览、筛选、图表、对比、热力图对游客开放；
> **数据导出与房价预测需登录**（前者属于数据索取，后者要写入预测历史），
> 游客打开预测页会看到「请先登录」提示条。

### 3.2 管理端（后台）

入口：**登录后右上角用户名下拉菜单**（仅管理员可见），包含「数据运维面板」与「管理后台」。

| 模块 | 地址 | 功能 |
| :--- | :--- | :--- |
| 数据运维面板 | `/ops/` | **管理员专属**：线上模型评估指标（RMSE / MAE / R² / MAPE、树数、训练时间）、特征重要性、12 张数据表概览与最近更新时间、大数据链路就绪状态 |
| 系统用户 | `/admin/users/sysuser/` | 查看 / 搜索注册用户、启用停用账号、修改角色 |
| 二手房房源 | `/admin/houses/houseinfo/` | 房源明细增删改查，支持按区域 / 装修 / 电梯筛选 |
| 房价预测历史 | `/admin/houses/predicthistory/` | 查看每次预测的输入参数与预测结果 |
| 房源收藏 | `/admin/houses/userfavorite/` | 查看用户收藏记录 |

> 用户管理与数据管理复用 Django Admin 实现；`stat_*` 离线统计结果表由 Spark 写入，
> 由仪表盘与 `/ops/` 面板展示，不单独放在后台。
>
> 权限落地方式：后端 `users/permissions.py` 提供 `admin_required` 装饰器（API）与
> `AdminRequiredMixin`（页面），未登录返回 401、非管理员返回 403；
> 前端 `base.html` 按 `request.user.is_admin` 控制入口显隐。

---

## 四、项目结构

```
housing_system/
├── sql/
│   └── schema.sql                  # MySQL 初始化：建库 + 12 张业务表 + 用户关联表 + 默认管理员
├── spark_jobs/                     # 大数据与机器学习
│   ├── spark_etl_analytics.py      # 数据清洗、SparkSQL 统计、写入 MySQL
│   ├── train_rf_model.py           # 随机森林训练 + 特征重要性导出（初版）
│   ├── train_model_compare.py      # 模型对比实验（线性回归/随机森林/GBT）
│   ├── train_upgraded_model.py     # 升级模型训练 + 小区编码落库（当前线上版本）
│   ├── batch_valuation.py          # 房源性价比批量打分（模型估值 + 同类比价）
│   ├── predict_service.py          # 模型加载与在线预测服务
│   ├── models/rf_housing_model/    # 初版模型（原 7 特征）
│   ├── models/rf_housing_model_v2/ # 升级模型（原 7 特征 + 小区目标编码）
│   └── tools/hadoop/bin/           # Windows 下加载 Spark 模型所需的本地库
└── backend/                        # Django 工程
    ├── manage.py
    ├── requirements.txt
    ├── housing_project/            # 配置文件（settings / urls / wsgi）
    ├── users/                      # 自定义用户模型 SysUser + 注册登录接口 + 角色权限装饰器
    ├── houses/                     # 列表 / 详情 / 对比 / 地图 / 预测 / 收藏 / 导出
    ├── analysis/                   # 离线统计接口 + 特征关系分析 + 管理员运维面板
    ├── templates/                  # 10 个前端页面（含管理员 /ops/ 运维面板）
    └── static/                     # 全局 CSS / JS
```

---

## 五、数据库表结构

数据库：`housing_db`（共 12 张业务表 + Django 自带的 `auth_*` / `django_*` 框架表
+ `sys_user_groups` / `sys_user_user_permissions` 两张用户关联表）

| 表名 | 说明 | 写入方 |
| :--- | :--- | :--- |
| `sys_user` | 用户账号（用户名、密码哈希、手机号、头像、角色） | Django |
| `house_info` | 二手房明细数据（18338 条） | Spark ETL |
| `stat_district` | 区域维度统计（挂牌量 / 平均总价 / 平均单价 / 平均面积） | Spark ETL |
| `stat_decoration` | 装修维度统计 | Spark ETL |
| `stat_room_type` | 户型维度统计 | Spark ETL |
| `stat_community_top` | 热门小区 TOP20 | Spark ETL |
| `stat_feature_importance` | 随机森林特征重要性 | 训练脚本 |
| `stat_model_metric` | 线上模型评估指标（RMSE / MAE / R² / MAPE 等，供运维面板展示） | 升级模型训练脚本 |
| `house_valuation` | 房源性价比估值（模型预测价 / 同类均价 / 偏离度） | 批量打分脚本 |
| `community_encoding` | 小区目标编码表（升级模型的小区均价特征） | 升级模型训练脚本 |
| `user_favorite` | 用户收藏房源 | Django |
| `predict_history` | 房价预测历史记录 | Django |

> `sys_user_groups` / `sys_user_user_permissions` 是 `SysUser` 继承 `AbstractUser`
> 带来的 M2M 中间表。因 `SysUser` 为 `managed = False`，`migrate` 不会自动建这两张表，
> 缺表会导致**后台删除用户时报 1146 错误**，故在 `sql/schema.sql` 中一并为建。
>
> 除 `sys_user`、`user_favorite`、`predict_history` 外，其余表由 Spark 侧以 `TRUNCATE + INSERT` 方式重写，
> 表结构以 `sql/schema.sql` 为准（Django 侧模型全部为 `managed = False`，不参与建表）。

---

## 六、接口清单

统一返回格式：`{"code": 0, "msg": "success", "data": ...}`，`code` 非 0 表示失败。

| 模块 | 接口 | 说明 |
| :--- | :--- | :--- |
| 用户 | `POST /api/user/register/` | 注册 |
| 用户 | `POST /api/user/login/` | 登录（建立会话） |
| 用户 | `POST /api/user/logout/` | 退出登录 |
| 用户 | `GET` / `POST` `/api/user/profile/` | 查看 / 修改资料、修改密码 |
| 房源 | `GET /api/house/list/` | 列表 + 多维筛选 + 分页 |
| 房源 | `GET /api/house/detail/?id=` | 房源详情（含是否已收藏） |
| 房源 | `GET /api/house/position/?id=` | 该房源在「同区域 面积-总价 分布」中的位置（抽样散点 + 拟合线 + 自身坐标，供详情页价位定位图） |
| 房源 | `GET /api/house/compare/?ids=` | 2–4 套房源对比（含最优 / 较差） |
| 房源 | `GET /api/house/map_data/` | 热力图打点数据 |
| 房源 | `POST /api/house/predict/` | 房价预测（随机森林）+ 相似推荐；可选传 `community` 按小区校准（**需登录**） |
| 房源 | `GET /api/house/community_list/` | 小区列表（供预测表单自动补全，支持 `district` / `q` / `limit`） |
| 房源 | `GET /api/house/predict_history/` | 我的预测记录（需登录） |
| 房源 | `POST /api/house/predict_history/delete/` | 删除我的某条预测记录（需登录，只能删本人记录） |
| 房源 | `POST /api/house/favorite/` | 收藏 / 取消收藏（需登录） |
| 房源 | `GET /api/house/favorites/` | 我的收藏列表（需登录） |
| 房源 | `GET /api/house/favorite_ids/` | 已收藏 id 列表（供列表页标记） |
| 房源 | `GET /api/house/export/` | 按当前筛选导出 CSV / Excel（**需登录**） |
| 分析 | `GET /api/analysis/stats/` | 离线统计结果（区域 / 装修 / 户型 / 小区 + 汇总） |
| 分析 | `GET /api/analysis/relations/` | 特征关系（面积-总价散点与拟合、相关性矩阵、特征重要性） |
| 分析 | `GET /api/analysis/ops_status/` | **管理员专属**：运维面板数据（表概览 / 模型指标 / 特征重要性 / 链路状态），越权返回 403 |

---

## 七、大数据链路（按需执行）

虚拟机上的相关路径：

| 内容 | 路径 |
| :--- | :--- |
| HDFS 原始数据 | `/housing/raw/sh_data.csv` |
| ETL / 训练脚本 | `/opt/module/housing/` |
| MySQL JDBC 驱动 | `/opt/software/mysql/mysql-connector-j-8.0.31.jar` |
| Spark | `/opt/module/spark`（3.3.1） |
| Hadoop | `/opt/module/hadoop`（`fs.defaultFS = hdfs://hadoop102:8020`） |

执行步骤：

```bash
# 1) 上传数据到 HDFS
hdfs dfs -mkdir -p /housing/raw
hdfs dfs -put sh_data.csv /housing/raw/

# 2) 数据清洗与统计（重写 house_info 与 4 张 stat 表，表结构保持不变）
cd /opt/module/housing
export PYSPARK_PYTHON=/usr/bin/python3
spark-submit --master 'local[*]' \
  --jars /opt/software/mysql/mysql-connector-j-8.0.31.jar \
  spark_etl_analytics.py

# 3) 训练随机森林模型（保存到 HDFS）并把特征重要性写入 MySQL
spark-submit --master 'local[*]' \
  --jars /opt/software/mysql/mysql-connector-j-8.0.31.jar \
  train_rf_model.py

# 4) 房源性价比批量打分（用模型对全部房源估值，写入 house_valuation）
#    注意：模型已同步到本地副本，用 file:// 前缀可直接从本地加载，不必依赖 HDFS
export RF_MODEL_PATH=file:///opt/module/housing_app/spark_jobs/models/rf_housing_model
spark-submit --master 'local[*]' \
  --jars /opt/software/mysql/mysql-connector-j-8.0.31.jar \
  batch_valuation.py

# 5) 训练升级模型（原 7 特征 + 小区目标编码）并把小区编码表写入 MySQL
#    当前线上预测用的就是这一步产出的模型（rf_housing_model_v2）
export MODEL_OUT=file:///opt/module/housing/models/rf_housing_model_v2
spark-submit --master 'local[*]' \
  --jars /opt/software/mysql/mysql-connector-j-8.0.31.jar \
  train_upgraded_model.py

# 6) 模型对比实验（可选，用于论文"模型优化与对比"章节）
spark-submit --master 'local[*]' \
  --jars /opt/software/mysql/mysql-connector-j-8.0.31.jar \
  train_model_compare.py
```

模型评估结果（**同一划分下**的对比）：

| 版本 | 特征 | RMSE | MAE | R² |
| :--- | :--- | ---: | ---: | ---: |
| 初版 | 原 7 特征 | 23.09 | 13.91 | 0.7551 |
| **当前线上（升级版）** | 原 7 特征 + 小区目标编码 | **19.45** | **11.34** | **0.8262** |

> 线上初版单独训练时曾得到 R² = 0.7834，与上表 0.7551 的差异来自**单次随机划分的波动**
> （清洗后行数略有变化，`randomSplit` 切出的测试集不同）。上表五组实验共用同一划分，
> 因此版本间的横向对比是有效的。

特征重要性（**线上升级模型**，随机森林，合计 1.0）：

| 特征 | 重要性 |
| :--- | :--- |
| 面积 | 44.08% |
| 室数 | 21.59% |
| 小区均价（目标编码） | 17.39% |
| 所属区域 | 5.20% |
| 厅数 | 4.92% |
| 总楼层 | 4.66% |
| 装修情况 | 1.49% |
| 有无电梯 | 0.66% |

> 面积与室数合计约 65.7%，是决定房价的主导因素；**小区均价（目标编码）以 17.39% 位列第三**，
> 小区级信息（17.39%）远高于行政区级（5.20%），这也是升级模型加入小区编码后 R² 提升的主因。
> 面积与总价的相关系数 `r = 0.8758`。

> 注意：训练脚本保存模型时用的是普通绝对路径，在 Hadoop 集群上会被解析到 HDFS
> （`hdfs://hadoop102:8020/opt/module/housing/models/rf_housing_model`）。
> 部署目录下给 Django 加载的是从 HDFS 取回的本地副本。

---

## 八、常见问题

**Q：页面能打开，但预测显示「统计估算（模型未就绪）」？**
说明没加载到 Spark 模型，系统自动降级了。检查：
- 本机开发时是否用了 `conda activate housing`；
- 模型目录 `spark_jobs/models/rf_housing_model` 是否存在；
- 虚拟机上看 `journalctl -u housing | grep PREDICT` 是否有「预热完成」。

**Q：第一次预测比较慢？**
服务启动时会在后台预热 Spark（约十几秒），预热完成后每次预测约 0.2–0.6 秒。虚拟机开机后稍等一下即可。

**Q：改了代码怎么生效？**
虚拟机上是 `--noreload` 模式，需要重启服务：`systemctl restart housing`。
本机开发是自动重载，保存文件即生效。

**Q：数据库连接信息在哪里改？**
`backend/housing_project/settings.py`，支持环境变量覆盖：
`DB_HOST` / `DB_PORT` / `DB_NAME` / `DB_USER` / `DB_PASSWORD`。

**Q：为什么收藏按钮点了没反应 / 个人中心看不到预测记录？**
这两个功能都需要登录。未登录时点击收藏会提示「请先登录后再收藏房源」，
个人中心的「我的预测记录」「我的房源收藏」也只在登录后加载。

**Q：如何新增一个管理员？**
在 `/admin/users/sysuser/` 里编辑用户，勾选「职员状态（is_staff）」并设置「角色 = 1」；
或者直接执行第一节里的 SQL。
