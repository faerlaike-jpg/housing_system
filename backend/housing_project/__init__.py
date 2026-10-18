import pymysql

# 使用 PyMySQL 作为 MySQLdb 的替代实现，免去本地编译 mysqlclient 的麻烦
pymysql.install_as_MySQLdb()
