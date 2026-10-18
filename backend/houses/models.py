from django.db import models


class HouseInfo(models.Model):
    """
    二手房明细数据表 house_info（由 Spark ETL 写入，Django 只读查询）。
    """

    id = models.IntegerField("房源编号", primary_key=True)
    title = models.CharField("标题", max_length=255, null=True, blank=True)
    total_price = models.DecimalField("总价(万元)", max_digits=10, decimal_places=2, null=True, blank=True)
    unit_price = models.IntegerField("单价(元/㎡)", null=True, blank=True)
    square = models.DecimalField("面积(㎡)", max_digits=10, decimal_places=2, null=True, blank=True)
    size = models.CharField("户型结构", max_length=64, null=True, blank=True)
    room_num = models.IntegerField("室数量", null=True, blank=True)
    hall_num = models.IntegerField("厅数量", null=True, blank=True)
    floor = models.CharField("楼层信息", max_length=64, null=True, blank=True)
    floor_type = models.CharField("楼层位置", max_length=32, null=True, blank=True)
    total_floors = models.IntegerField("总楼层数", null=True, blank=True)
    direction = models.CharField("房屋朝向", max_length=64, null=True, blank=True)
    type = models.CharField("建筑类型", max_length=64, null=True, blank=True, db_column="type")
    district = models.CharField("行政区域", max_length=64, null=True, blank=True)
    nearby = models.CharField("附近商圈", max_length=255, null=True, blank=True)
    community = models.CharField("小区名称", max_length=128, null=True, blank=True)
    decoration = models.CharField("装修情况", max_length=64, null=True, blank=True)
    elevator = models.CharField("电梯", max_length=16, null=True, blank=True)
    elevator_num = models.CharField("梯户比例", max_length=64, null=True, blank=True, db_column="elevatorNum")
    ownership = models.CharField("产权性质", max_length=64, null=True, blank=True)

    class Meta:
        managed = False
        db_table = "house_info"
        verbose_name = "二手房房源"
        verbose_name_plural = "二手房房源"

    def __str__(self):
        return self.title or str(self.id)


class PredictHistory(models.Model):
    """房价预测历史记录表 predict_history。"""

    predict_id = models.AutoField("记录ID", primary_key=True)
    user = models.ForeignKey(
        "users.SysUser", null=True, blank=True, on_delete=models.SET_NULL,
        db_column="user_id", verbose_name="用户",
    )
    district = models.CharField("行政区", max_length=50, null=True, blank=True)
    square = models.DecimalField("面积", max_digits=10, decimal_places=2, null=True, blank=True)
    room_num = models.IntegerField("室数量", null=True, blank=True)
    hall_num = models.IntegerField("厅数量", null=True, blank=True)
    total_floors = models.IntegerField("总楼层数", null=True, blank=True)
    decoration = models.CharField("装修", max_length=50, null=True, blank=True)
    elevator = models.CharField("电梯", max_length=10, null=True, blank=True)
    predicted_total_price = models.DecimalField("预测总价", max_digits=10, decimal_places=2, null=True, blank=True)
    predicted_unit_price = models.DecimalField("预测单价", max_digits=10, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField("预测时间")

    class Meta:
        managed = False
        db_table = "predict_history"
        verbose_name = "房价预测历史"
        verbose_name_plural = "房价预测历史"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.district} - {self.predicted_total_price}"


class UserFavorite(models.Model):
    """
    用户收藏房源表 user_favorite。

    注意：house_id 在数据库里刻意没有建外键约束——Spark ETL 用 TRUNCATE
    方式重写 house_info，而被外键引用的表无法 TRUNCATE。这里用 house_id
    普通字段关联，不使用 ForeignKey。
    """

    fav_id = models.AutoField("收藏ID", primary_key=True)
    user = models.ForeignKey(
        "users.SysUser", on_delete=models.CASCADE,
        db_column="user_id", verbose_name="用户",
    )
    house_id = models.IntegerField("房源编号")
    created_at = models.DateTimeField("收藏时间")

    class Meta:
        managed = False
        db_table = "user_favorite"
        ordering = ["-created_at"]
        verbose_name = "房源收藏"
        verbose_name_plural = "房源收藏"

    def __str__(self):
        return f"{self.user_id} -> {self.house_id}"


class HouseValuation(models.Model):
    """
    房源性价比估值表 house_valuation（由 batch_valuation.py 批量打分写入）。

    两套偏离度字段的含义见该脚本注释：deviation_pct 相对模型估值，
    peer_deviation_pct 相对同区域同户型均价。同样只用普通字段关联 house_id，
    不建外键（原因见 UserFavorite 的说明）。
    """

    house_id = models.IntegerField("房源编号", primary_key=True)
    predicted_total_price = models.DecimalField("模型预测总价", max_digits=10, decimal_places=2,
                                                null=True, blank=True)
    predicted_unit_price = models.DecimalField("模型预测单价", max_digits=10, decimal_places=2,
                                               null=True, blank=True)
    actual_total_price = models.DecimalField("实际挂牌总价", max_digits=10, decimal_places=2,
                                             null=True, blank=True)
    deviation_pct = models.DecimalField("相对模型估值偏离度", max_digits=10, decimal_places=2,
                                        null=True, blank=True)
    peer_unit_price = models.DecimalField("同类均价", max_digits=10, decimal_places=2,
                                          null=True, blank=True)
    peer_deviation_pct = models.DecimalField("相对同类均价偏离度", max_digits=10, decimal_places=2,
                                             null=True, blank=True)
    updated_at = models.DateTimeField("计算时间")

    class Meta:
        managed = False
        db_table = "house_valuation"
        verbose_name = "房源性价比估值"
        verbose_name_plural = "房源性价比估值"

    def __str__(self):
        return f"{self.house_id} - {self.peer_deviation_pct}"


class CommunityEncoding(models.Model):
    """
    小区目标编码表 community_encoding（由 train_upgraded_model.py 写入）。

    升级版模型新增了 community_te 特征（用小区历史平均单价做目标编码）。
    预测时 Django 需要据小区名查出该值；查不到时按 区域 -> 全局 逐级兜底。
    """

    community = models.CharField("小区名称", max_length=128, primary_key=True)
    district = models.CharField("所属区域", max_length=64, null=True, blank=True)
    house_count = models.IntegerField("样本数")
    te_value = models.DecimalField("目标编码值", max_digits=10, decimal_places=4)

    class Meta:
        managed = False
        db_table = "community_encoding"
        verbose_name = "小区目标编码"
        verbose_name_plural = "小区目标编码"

    def __str__(self):
        return f"{self.community} - {self.te_value}"
