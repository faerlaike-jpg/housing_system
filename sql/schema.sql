-- =============================================================================
-- 潍坊市二手房房价预测系统 - MySQL 8.0 数据库初始化脚本
-- 说明：本脚本是全项目「业务表」的唯一权威 DDL。
--       Django 侧对应模型均设置 managed = False，不会由 migrate 再次建表，
--       因此请务必先执行本脚本，再执行 python manage.py migrate（只建框架表）。
-- 执行：mysql -u root -p < schema.sql
-- =============================================================================

DROP DATABASE IF EXISTS housing_db;
CREATE DATABASE housing_db DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
USE housing_db;

-- -----------------------------------------------------------------------------
-- 1. 用户信息表 sys_user
--    字段与 Django AbstractUser 完全对齐，便于自定义用户模型直接复用；
--    额外扩展 phone / avatar / role 三个业务字段。
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS sys_user;
CREATE TABLE sys_user (
    id            BIGINT       NOT NULL AUTO_INCREMENT COMMENT '用户ID',
    password      VARCHAR(128) NOT NULL             COMMENT '密码哈希值',
    last_login    DATETIME     NULL                 COMMENT '最后登录时间',
    is_superuser  TINYINT(1)   NOT NULL DEFAULT 0   COMMENT '是否超级管理员',
    username      VARCHAR(150) NOT NULL             COMMENT '账号',
    first_name    VARCHAR(150) NOT NULL DEFAULT ''  COMMENT '名',
    last_name     VARCHAR(150) NOT NULL DEFAULT ''  COMMENT '姓',
    email         VARCHAR(254) NOT NULL DEFAULT ''  COMMENT '邮箱',
    is_staff      TINYINT(1)   NOT NULL DEFAULT 0   COMMENT '是否可登录后台',
    is_active     TINYINT(1)   NOT NULL DEFAULT 1   COMMENT '是否启用',
    date_joined   DATETIME     NOT NULL             COMMENT '注册时间',
    phone         VARCHAR(20)  NOT NULL DEFAULT ''  COMMENT '手机号',
    avatar        VARCHAR(255) NOT NULL DEFAULT 'default_avatar.png' COMMENT '头像地址',
    role          TINYINT      NOT NULL DEFAULT 0   COMMENT '角色 0普通用户 1管理员',
    PRIMARY KEY (id),
    UNIQUE KEY uk_sys_user_username (username)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_general_ci COMMENT = '用户信息表';

-- -----------------------------------------------------------------------------
-- 1.1 Django 框架关联表（sys_user 的 groups / user_permissions 中间表）
--     SysUser 继承 AbstractUser，Django 在「删除用户」时会去清理这两张 M2M
--     中间表；但 SysUser 是 managed = False（不参与 migrate 建表），这两张表
--     不会被自动创建，导致后台删除用户时报
--     ProgrammingError: (1146, "Table 'housing_db.sys_user_groups' doesn't exist")
--     这里手动补齐。列名按 Django 规则取 model_name，故外键列为 sysuser_id。
--     注意：auth_group / auth_permission 由 migrate 在本脚本之后创建，故此处
--     不建它们的外键，只建索引——Django 的级联删除不依赖该外键。
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS sys_user_groups;
CREATE TABLE sys_user_groups (
    id         BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键',
    sysuser_id BIGINT NOT NULL COMMENT '用户ID(sys_user.id)',
    group_id   INT    NOT NULL COMMENT '用户组ID(auth_group.id)',
    PRIMARY KEY (id),
    UNIQUE KEY uk_sys_user_groups (sysuser_id, group_id),
    KEY idx_sys_user_groups_group (group_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_general_ci COMMENT = '用户-用户组关联表';

DROP TABLE IF EXISTS sys_user_user_permissions;
CREATE TABLE sys_user_user_permissions (
    id            BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键',
    sysuser_id    BIGINT NOT NULL COMMENT '用户ID(sys_user.id)',
    permission_id INT    NOT NULL COMMENT '权限ID(auth_permission.id)',
    PRIMARY KEY (id),
    UNIQUE KEY uk_sys_user_user_permissions (sysuser_id, permission_id),
    KEY idx_sys_user_user_permissions_perm (permission_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_general_ci COMMENT = '用户-权限关联表';

-- -----------------------------------------------------------------------------
-- 2. 二手房明细数据表 house_info
--    由 Spark ETL 脚本以 mode="overwrite" 写入，Django 只读。
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS house_info;
CREATE TABLE house_info (
    id           INT            NOT NULL COMMENT '房源编号',
    title        VARCHAR(255)   NULL     COMMENT '房源标题',
    total_price  DECIMAL(10, 2) NULL     COMMENT '总价(万元)',
    unit_price   INT            NULL     COMMENT '单价(元/㎡)',
    square       DECIMAL(10, 2) NULL     COMMENT '建筑面积(㎡)',
    size         VARCHAR(64)    NULL     COMMENT '户型结构',
    room_num     INT            NULL     COMMENT '室数量',
    hall_num     INT            NULL     COMMENT '厅数量',
    floor        VARCHAR(64)    NULL     COMMENT '楼层信息',
    floor_type   VARCHAR(32)    NULL     COMMENT '楼层位置(高/中/低)',
    total_floors INT            NULL     COMMENT '总楼层数',
    direction    VARCHAR(64)    NULL     COMMENT '房屋朝向',
    `type`       VARCHAR(64)    NULL     COMMENT '建筑类型',
    district     VARCHAR(64)    NULL     COMMENT '行政区域',
    nearby       VARCHAR(255)   NULL     COMMENT '附近商圈',
    community    VARCHAR(128)   NULL     COMMENT '小区名称',
    decoration   VARCHAR(64)    NULL     COMMENT '装修情况',
    elevator     VARCHAR(16)    NULL     COMMENT '电梯 有/无',
    elevatorNum  VARCHAR(64)    NULL     COMMENT '梯户比例',
    ownership    VARCHAR(64)    NULL     COMMENT '产权性质',
    PRIMARY KEY (id),
    KEY idx_house_district (district),
    KEY idx_house_community (community),
    KEY idx_house_total_price (total_price),
    KEY idx_house_square (square)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_general_ci COMMENT = '二手房明细数据表';

-- -----------------------------------------------------------------------------
-- 3. Spark 聚合分析结果表（4 张单维度结果表，由 Spark 写入，Django 只读）
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS stat_district;
CREATE TABLE stat_district (
    district        VARCHAR(64)    NOT NULL COMMENT '行政区',
    house_count     INT            NULL     COMMENT '挂牌量',
    avg_total_price DECIMAL(10, 2) NULL     COMMENT '平均总价(万元)',
    avg_unit_price  DECIMAL(10, 2) NULL     COMMENT '平均单价(元/㎡)',
    avg_square      DECIMAL(10, 2) NULL     COMMENT '平均面积(㎡)',
    PRIMARY KEY (district)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_general_ci COMMENT = '区域维度统计表';

DROP TABLE IF EXISTS stat_decoration;
CREATE TABLE stat_decoration (
    decoration     VARCHAR(64)    NOT NULL COMMENT '装修情况',
    house_count    INT            NULL     COMMENT '挂牌量',
    avg_unit_price DECIMAL(10, 2) NULL     COMMENT '平均单价(元/㎡)',
    PRIMARY KEY (decoration)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_general_ci COMMENT = '装修维度统计表';

DROP TABLE IF EXISTS stat_room_type;
CREATE TABLE stat_room_type (
    room_num       INT            NOT NULL COMMENT '室数量',
    house_count    INT            NULL     COMMENT '挂牌量',
    avg_unit_price DECIMAL(10, 2) NULL     COMMENT '平均单价(元/㎡)',
    PRIMARY KEY (room_num)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_general_ci COMMENT = '户型维度统计表';

DROP TABLE IF EXISTS stat_community_top;
CREATE TABLE stat_community_top (
    community       VARCHAR(128)   NOT NULL COMMENT '小区名称',
    district        VARCHAR(64)    NOT NULL COMMENT '所属区域',
    house_count     INT            NULL     COMMENT '挂牌量',
    avg_total_price DECIMAL(10, 2) NULL     COMMENT '平均总价(万元)',
    avg_unit_price  DECIMAL(10, 2) NULL     COMMENT '平均单价(元/㎡)',
    PRIMARY KEY (community, district)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_general_ci COMMENT = '热门小区TOP20统计表';

DROP TABLE IF EXISTS stat_feature_importance;
CREATE TABLE stat_feature_importance (
    feature    VARCHAR(64)    NOT NULL COMMENT '特征名',
    importance DECIMAL(10, 6) NULL     COMMENT '重要性得分',
    PRIMARY KEY (feature)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_general_ci COMMENT = '随机森林特征重要性表';

DROP TABLE IF EXISTS stat_model_metric;
CREATE TABLE stat_model_metric (
    id            INT            NOT NULL DEFAULT 1 COMMENT '固定为 1，保证单行',
    algorithm     VARCHAR(64)    NULL     COMMENT '算法名称',
    feature_count INT            NULL     COMMENT '入模特征数',
    num_trees     INT            NULL     COMMENT '树数量',
    max_depth     INT            NULL     COMMENT '最大深度',
    rmse          DECIMAL(12, 4) NULL     COMMENT '均方根误差(万元)',
    mae           DECIMAL(12, 4) NULL     COMMENT '平均绝对误差(万元)',
    r2            DECIMAL(12, 6) NULL     COMMENT '决定系数 R2',
    mape          DECIMAL(12, 4) NULL     COMMENT '平均绝对百分比误差(%)',
    train_rows    INT            NULL     COMMENT '训练集样本数',
    test_rows     INT            NULL     COMMENT '测试集样本数',
    trained_at    DATETIME       NOT NULL COMMENT '训练时间',
    PRIMARY KEY (id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_general_ci COMMENT = '线上模型评估指标表';

DROP TABLE IF EXISTS house_valuation;
CREATE TABLE house_valuation (
    house_id              INT            NOT NULL COMMENT '房源编号',
    predicted_total_price DECIMAL(10, 2) NULL     COMMENT '模型预测总价(万元)',
    predicted_unit_price  DECIMAL(10, 2) NULL     COMMENT '模型预测单价(元/㎡)',
    actual_total_price    DECIMAL(10, 2) NULL     COMMENT '实际挂牌总价(万元)',
    deviation_pct         DECIMAL(10, 2) NULL     COMMENT '相对模型估值的偏离度%(挂牌-预测)/预测*100，负值=低于估值',
    peer_unit_price       DECIMAL(10, 2) NULL     COMMENT '同区域同户型平均单价(元/㎡)',
    peer_deviation_pct    DECIMAL(10, 2) NULL     COMMENT '相对同类房源均价的偏离度%',
    updated_at            DATETIME       NOT NULL COMMENT '计算时间',
    PRIMARY KEY (house_id),
    KEY idx_valuation_deviation (deviation_pct),
    KEY idx_valuation_peer (peer_deviation_pct)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_general_ci COMMENT = '房源性价比估值表';

DROP TABLE IF EXISTS community_encoding;
CREATE TABLE community_encoding (
    community   VARCHAR(128)   NOT NULL COMMENT '小区名称',
    district    VARCHAR(64)    NULL     COMMENT '所属行政区域（用于兜底查询）',
    house_count INT            NOT NULL COMMENT '该小区样本数',
    te_value    DECIMAL(10, 4) NOT NULL COMMENT '平滑目标编码值(元/㎡)',
    PRIMARY KEY (community),
    KEY idx_ce_district (district)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_general_ci COMMENT = '小区目标编码表';

-- -----------------------------------------------------------------------------
-- 4. 用户收藏表 user_favorite
--    注意：house_id 刻意不加外键约束。因为 Spark ETL 用 TRUNCATE 方式重写
--    house_info，而被外键引用的表无法执行 TRUNCATE，加约束会导致 ETL 失败。
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS user_favorite;
CREATE TABLE user_favorite (
    fav_id     INT      NOT NULL AUTO_INCREMENT COMMENT '收藏ID',
    user_id    BIGINT   NOT NULL COMMENT '用户ID',
    house_id   INT      NOT NULL COMMENT '房源编号',
    created_at DATETIME NOT NULL COMMENT '收藏时间',
    PRIMARY KEY (fav_id),
    UNIQUE KEY uk_fav_user_house (user_id, house_id),
    KEY idx_fav_user (user_id),
    KEY idx_fav_house (house_id),
    CONSTRAINT fk_fav_user FOREIGN KEY (user_id) REFERENCES sys_user (id) ON DELETE CASCADE
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_general_ci COMMENT = '用户收藏表';

-- -----------------------------------------------------------------------------
-- 5. 房价预测历史记录表 predict_history
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS predict_history;
CREATE TABLE predict_history (
    predict_id            INT            NOT NULL AUTO_INCREMENT COMMENT '预测记录ID',
    user_id               BIGINT         NULL     COMMENT '用户ID',
    district              VARCHAR(50)    NULL     COMMENT '行政区',
    square                DECIMAL(10, 2) NULL     COMMENT '面积(㎡)',
    room_num              INT            NULL     COMMENT '室数量',
    hall_num              INT            NULL     COMMENT '厅数量',
    total_floors          INT            NULL     COMMENT '总楼层数',
    decoration            VARCHAR(50)    NULL     COMMENT '装修情况',
    elevator              VARCHAR(10)    NULL     COMMENT '电梯 有/无',
    predicted_total_price DECIMAL(10, 2) NULL     COMMENT '预测总价(万元)',
    predicted_unit_price  DECIMAL(10, 2) NULL     COMMENT '预测单价(元/㎡)',
    created_at            DATETIME       NOT NULL COMMENT '预测时间',
    PRIMARY KEY (predict_id),
    KEY idx_predict_user (user_id),
    CONSTRAINT fk_predict_user FOREIGN KEY (user_id) REFERENCES sys_user (id) ON DELETE SET NULL
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_general_ci COMMENT = '房价预测历史记录表';

-- -----------------------------------------------------------------------------
-- 6. 默认管理员账号
--    账号：admin  密码：admin123456
--    密码为 Django PBKDF2-SHA256 真实哈希（make_password 生成并 check_password 校验通过），
--    可直接用于 Django 认证登录与 /admin/ 后台。
-- -----------------------------------------------------------------------------
INSERT INTO sys_user (password, is_superuser, username, first_name, last_name, email,
                      is_staff, is_active, date_joined, phone, avatar, role)
VALUES ('pbkdf2_sha256$600000$WA7nTpCfg07zlTEyv8w6rz$Hw1me7QCDjEYKbowbC+QD5oNPhg/GrLtOP7wCQG8D+4=',
        1, 'admin', '系统', '管理员', 'admin@housing.com',
        1, 1, NOW(), '13800000000', 'default_avatar.png', 1);
