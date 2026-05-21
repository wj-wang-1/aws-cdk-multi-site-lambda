# CDK 新增客户站点部署模板

## 前提（已完成，无需重复）

以下基础设施已手动配置好：
- ✅ ACM 通配符证书（`*.example.com`）
- ✅ API Gateway 通配符自定义域名（路由模式：**仅限路由规则**）
- ✅ Route 53 托管区域

## 本模板做什么

每次新增客户站点时，自动创建：
1. Lambda 函数（从 ECR 镜像部署）+ CloudWatch 日志组（1 个月保留）
2. REST API（Lambda 代理集成，所有路径转发到 Lambda）
3. **路由规则**（CfnRoutingRule，按 Host 头匹配子域名 → 对应 REST API）
4. Route 53 DNS 记录（子域名 Alias → API Gateway 通配符域名）

## 文件说明

| 文件 | 说明 |
|------|------|
| `app.py` | CDK 主代码，定义 SiteStack |
| `cdk.json` | CDK 项目入口配置 + 环境配置（域名、托管区 ID 等），按实际环境修改 |
| `requirements.txt` | Python 依赖 |

## 使用步骤

### 1. 安装依赖

```bash
pip install -r requirements.txt
npm install -g aws-cdk  # 如果没装过
cdk bootstrap           # 首次使用 CDK 需要执行
```

### 2. 修改配置

编辑 `cdk.json` 的 `context` 区域，填入实际值：

```json
{
  "app": "python3 app.py",
  "context": {
    "domain_name": "example.com",
    "hosted_zone_id": "你的Route53托管区域ID",
    "custom_domain_target": "d-xxx.execute-api.us-west-2.amazonaws.com",
    "custom_domain_hosted_zone_id": "API GW 自定义域名的托管区ID"
  }
}
```

| 配置项 | 在哪里找 |
|--------|---------|
| `hosted_zone_id` | Route 53 → 托管区域 → 区域详情 |
| `custom_domain_target` | API Gateway → 自定义域名 → 终端节点配置 → API Gateway 域名 |
| `custom_domain_hosted_zone_id` | API Gateway → 自定义域名 → 终端节点配置 → 托管区 ID |

### 3. 新增客户

在 `app.py` 底部添加：

```python
SiteStack(app, "Site-pay",
          subdomain="pay",
          ecr_repo_name="pay-app",
          image_tag="v1.0.0",
          architecture=_lambda.Architecture.X86_64,  # 或 ARM_64
          env=env)
```

### 4. 部署

```bash
cdk diff Site-pay     # 预览变更
cdk deploy Site-pay   # 执行部署
```

部署完成后输出访问地址，客户即可通过 `https://pay.example.com` 访问。

### 5. 删除站点

```bash
cdk destroy Site-pay
```

自动清理 Lambda、REST API、路由规则、DNS 记录、日志组。

## 常用命令

| 命令 | 说明 |
|------|------|
| `cdk ls` | 列出所有站点 Stack |
| `cdk diff Site-xxx` | 查看变更（部署前预览） |
| `cdk deploy Site-xxx` | 部署指定站点 |
| `cdk deploy --all` | 部署所有站点 |
| `cdk destroy Site-xxx` | 删除指定站点 |

## 技术说明

### 路由规则实现

CDK L2 目前没有对 API Gateway Routing Rule 的封装，本模板使用 L1 资源 `aws_apigatewayv2.CfnRoutingRule` 实现。路由规则通过 Host 头条件匹配子域名，将请求转发到对应 REST API 的 prod Stage。

### 优先级自动生成

路由规则优先级通过 subdomain 的 MD5 哈希值自动生成（范围 1~999999），确定性且不会因 Python 进程重启而漂移。如需手动控制，可在 SiteStack 中传入 `priority` 参数。

### Lambda 架构

`architecture` 参数必须与 ECR 镜像的构建架构一致：
- `X86_64`：标准 x86 镜像（默认）
- `ARM_64`：ARM 镜像（Graviton，更便宜）

## 注意事项

- ECR 镜像需要提前推送到对应区域
- Lambda 函数返回格式必须符合 REST API 要求（statusCode + headers + body）
- 如果 Lambda 是 Web 框架，需要加适配层（Mangum / serverless-express）
- subdomain 只能包含字母、数字和连字符，不能含点号
- 每个站点是独立的 CloudFormation Stack，互不影响，可独立部署/删除/回滚
