# PXEye Keycloak Chart

该 Chart 用于部署 NICo REST 配置中可选的 Keycloak 服务。PXEye 父 Chart 默认不会启用它。

本 Chart 不创建任何凭据。渲染前，现场必须提供：

- 含 Keycloak 初始管理员用户名和密码的已有 Secret；
- 含 Keycloak 数据库用户名和密码的已有 Secret；
- 唯一的 Realm 导入来源：不含敏感数据时使用已有 ConfigMap，含客户端密钥时使用已有 Secret；
- 已审核的 JDBC 地址和适用于生产环境的 Keycloak 启动参数。

示例 values 只引用现场已有资源，不将凭据写入 Helm values：

```yaml
admin:
  existingSecret: keycloak-admin
database:
  url: jdbc:postgresql://postgres.nico-rest.svc:5432/keycloak?sslmode=require
  existingSecret: keycloak-db
realm:
  existingSecret: nico-rest-realm
startup:
  args: [start, --import-realm, --http-enabled=true]
```

该 Chart 刻意不以旧版 `start-dev` 模式或硬编码 `admin/admin` 凭据作为默认值。构建期 profile
可以渲染它以收集离线镜像，而交付给现场的父 Chart values 仍保持此可选组件关闭。
