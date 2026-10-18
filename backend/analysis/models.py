from django.db import models


class StatDistrict(models.Model):
    """区域维度统计表，由 Spark 写入。"""

    district = models.CharField("行政区", max_length=64, primary_key=True)
    house_count = models.IntegerField("挂牌量", null=True, blank=True)
    avg_total_price = models.DecimalField("平均总价", max_digits=10, decimal_places=2, null=True, blank=True)
    avg_unit_price = models.DecimalField("平均单价", max_digits=10, decimal_places=2, null=True, blank=True)
    avg_square = models.DecimalField("平均面积", max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        managed = False
        db_table = "stat_district"
        verbose_name = "区域统计"
        verbose_name_plural = "区域统计"


class StatDecoration(models.Model):
    """装修维度统计表，由 Spark 写入。"""

    decoration = models.CharField("装修情况", max_length=64, primary_key=True)
    house_count = models.IntegerField("挂牌量", null=True, blank=True)
    avg_unit_price = models.DecimalField("平均单价", max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        managed = False
        db_table = "stat_decoration"
        verbose_name = "装修统计"
        verbose_name_plural = "装修统计"


class StatRoomType(models.Model):
    """户型维度统计表，由 Spark 写入。"""

    room_num = models.IntegerField("室数量", primary_key=True)
    house_count = models.IntegerField("挂牌量", null=True, blank=True)
    avg_unit_price = models.DecimalField("平均单价", max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        managed = False
        db_table = "stat_room_type"
        verbose_name = "户型统计"
        verbose_name_plural = "户型统计"


class StatCommunityTop(models.Model):
    """热门小区 TOP20 统计表，由 Spark 写入。"""

    community = models.CharField("小区名称", max_length=128, primary_key=True)
    district = models.CharField("所属区域", max_length=64)
    house_count = models.IntegerField("挂牌量", null=True, blank=True)
    avg_total_price = models.DecimalField("平均总价", max_digits=10, decimal_places=2, null=True, blank=True)
    avg_unit_price = models.DecimalField("平均单价", max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        # 真实表使用 (community, district) 复合主键；此处以 community 作为
        # Django 主键代理。model 仅用于只读统计查询，不影响实际数据库结构。
        managed = False
        db_table = "stat_community_top"
        verbose_name = "热门小区统计"
        verbose_name_plural = "热门小区统计"


class StatFeatureImportance(models.Model):
    """随机森林特征重要性表，由 train_rf_model.py 训练后写入。"""

    feature = models.CharField("特征", max_length=64, primary_key=True)
    importance = models.DecimalField("重要性得分", max_digits=10, decimal_places=6,
                                     null=True, blank=True)

    class Meta:
        managed = False
        db_table = "stat_feature_importance"
        verbose_name = "特征重要性"
        verbose_name_plural = "特征重要性"


class StatModelMetric(models.Model):
    """
    线上模型评估指标表（单行），由 train_upgraded_model.py 训练结束时写入。

    之所以落库而不是写死在代码里：管理端的「数据运维面板」要展示的是
    「当前线上模型到底什么水平」，重训一次就应该自动刷新，避免文档里的
    数字和实际模型脱节。
    """

    id = models.IntegerField("主键", primary_key=True)
    algorithm = models.CharField("算法", max_length=64, null=True, blank=True)
    feature_count = models.IntegerField("入模特征数", null=True, blank=True)
    num_trees = models.IntegerField("树数量", null=True, blank=True)
    max_depth = models.IntegerField("最大深度", null=True, blank=True)
    rmse = models.DecimalField("RMSE", max_digits=12, decimal_places=4, null=True, blank=True)
    mae = models.DecimalField("MAE", max_digits=12, decimal_places=4, null=True, blank=True)
    r2 = models.DecimalField("R2", max_digits=12, decimal_places=6, null=True, blank=True)
    mape = models.DecimalField("MAPE", max_digits=12, decimal_places=4, null=True, blank=True)
    train_rows = models.IntegerField("训练集样本数", null=True, blank=True)
    test_rows = models.IntegerField("测试集样本数", null=True, blank=True)
    trained_at = models.DateTimeField("训练时间")

    class Meta:
        managed = False
        db_table = "stat_model_metric"
        verbose_name = "模型评估指标"
        verbose_name_plural = "模型评估指标"

    def __str__(self):
        return f"{self.algorithm} - R2 {self.r2}"
