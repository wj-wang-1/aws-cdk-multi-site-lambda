# 部署踩坑记录

本文档记录首次部署过程中遇到的问题及解决方案，供后续参考。

---

## 1. `cdk` 命令找不到

**现象：**
```
zsh: command not found: cdk
```

**原因：** 没有全局安装 AWS CDK CLI。

**解决：** 用 `npx` 代替，所有命令前加 `npx`：
```bash
npx cdk deploy Site-user2 Site-order2
npx cdk destroy Site-user2
```

或者全局安装：
```bash
npm install -g aws-cdk
```

---

## 2. `--all` 参数警告

**现象：**
```
Unknown option(s): --all. These will be ignored.
```

**原因：** 通过 `npx` 运行的 CDK 版本可能不支持 `--all` flag（较新版本已支持）。

**解决：** 直接列出 stack 名称代替：
```bash
npx cdk deploy Site-user2 Site-order2
npx cdk diff Site-user2 Site-order2
```

实际上即使出现这个 warning，命令仍然会对所有 stack 执行，可以忽略。

---

## 3. 部署区域错误（us-east-1 而非 us-west-2）

**现象：** `cdk diff` 输出中显示 `execute-api.us-east-1`，但基础设施（通配符域名、ACM 证书）都在 us-west-2。

**原因：** `app.py` 中 region 通过 `os.environ.get("CDK_DEFAULT_REGION", "us-west-2")` 读取，而 AWS CLI 默认 profile 配置的是 us-east-1，环境变量 `CDK_DEFAULT_REGION` 未设置时 fallback 逻辑没生效（实际上是 `AWS_DEFAULT_REGION` 或 profile 里的 region 覆盖了）。

**解决：** 直接在 `app.py` 中硬编码区域，不依赖环境变量：
```python
env = {
    "region": "us-west-2",
    "account": "123456789012",
}
```

**教训：** 对于固定区域的项目，硬编码比环境变量更可靠，避免不同终端 session 配置不一致。

---

## 4. us-west-2 未执行 `cdk bootstrap`

**现象：**
```
current credentials could not be used to assume 'arn:aws:iam::123456789012:role/cdk-hnb659fds-lookup-role-123456789012-us-west-2'
```

**原因：** CDK bootstrap 是按账号+区域执行的。之前只在 us-east-1 做过 bootstrap，us-west-2 没有。

**解决：**
```bash
npx cdk bootstrap aws://123456789012/us-west-2
```

**说明：** 每个账号每个区域只需执行一次，之后所有 CDK 部署复用。Bootstrap 创建的资源（S3 bucket、IAM roles）基本不产生费用。

---

## 5. 本地 curl 卡住 / DNS 解析到 198.18.x.x

**现象：**
```bash
dig user2.example.com +short
198.18.17.174          # ← 异常！这是 RFC 保留地址

curl https://user2.example.com
# 卡住无响应
```

**原因：** 本地 VPN 或 DNS 代理（如 Cisco AnyConnect、GlobalProtect、Cloudflare WARP、Surge 等）劫持了 DNS 解析，将域名映射到内部虚拟 IP。

**验证方式：**
```bash
# 用公共 DNS 查询，绕过本地代理
dig user2.example.com @8.8.8.8 +short
# 返回正常 AWS IP（如 54.244.172.140）说明是本地网络问题
```

**解决方案（任选其一）：**

1. 关闭 VPN / 代理后重试
2. 用 `--resolve` 绕过本地 DNS：
   ```bash
   curl --resolve user2.example.com:443:54.244.172.140 https://user2.example.com
   ```
3. 直接用 API Gateway 原始 endpoint 测试：
   ```bash
   curl https://<api-id>.execute-api.us-west-2.amazonaws.com/prod/
   ```

**说明：** 这不是部署问题，是本地网络环境问题。外部用户访问不受影响。

---

## 6. 部署时 IAM 确认提示卡住

**现象：** 执行 `cdk deploy` 后终端看似卡住不动。

**原因：** CDK 默认开启 `--require-approval broadening`，遇到 IAM 权限变更会暂停等待用户输入 `y/n` 确认。

**解决：** 往上滚动查看终端输出，找到 `Do you wish to deploy these changes (y/n)?`，输入 `y` 回车。

**跳过确认（适合 CI/CD 或测试环境）：**
```bash
npx cdk deploy Site-user2 Site-order2 --require-approval never
```

---

## 快速参考

| 场景 | 命令 |
|------|------|
| 首次 bootstrap | `npx cdk bootstrap aws://123456789012/us-west-2` |
| 预览变更 | `npx cdk diff Site-user2 Site-order2` |
| 部署（需确认） | `npx cdk deploy Site-user2 Site-order2` |
| 部署（跳过确认） | `npx cdk deploy Site-user2 Site-order2 --require-approval never` |
| 删除 | `npx cdk destroy Site-user2 Site-order2` |
| 列出所有 stack | `npx cdk ls` |
