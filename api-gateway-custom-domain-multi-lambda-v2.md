# API Gateway 通配符域名 + 路由规则 + 多 Lambda 分发部署手册（已验证）

> 本文档基于实际部署验证，使用 `*.example.com` 通配符域名，在 us-west-2（俄勒冈）区域完成测试。

## 架构概述

通过一个通配符自定义域名 + REST API 路由规则，根据 Host 头将不同子域名路由到不同 Lambda 函数。

```
                         DNS（所有子域名 Alias → 同一个 API GW 目标域名）
                                          ↓
                              API Gateway 自定义域名
                              *.example.com（通配符）
                                          ↓
                              路由规则（按 Host 头匹配）
                                          ↓
              ┌─────────────────────┼─────────────────────┐
              ↓                     ↓                     ↓
  Host: user.example.com     Host: order.example.com    Host: pay.example.com
              ↓                     ↓                     ↓
        REST API A            REST API B            REST API C
              ↓                     ↓                     ↓
         Lambda A              Lambda B              Lambda C
        (用户服务)             (订单服务)             (支付服务)
```

## 前提条件

- 一个已注册的域名，DNS 托管在 Route 53（或其他 DNS 服务商）
- AWS 账号，具备 Lambda、API Gateway、ACM、Route 53 权限
- 所有资源在**同一个区域**创建（本例为 us-west-2）

---

## 第一步：创建 Lambda 函数

每个子域名对应一个 Lambda 函数。

### 示例代码（Python 3.12/3.13）

**Lambda A（用户服务）：**

```python
import json

def lambda_handler(event, context):
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({
            "message": "Hello from User Service!",
            "path": event.get("path", "/"),
            "method": event.get("httpMethod", "GET")
        })
    }
```

**Lambda B（订单服务）：**

```python
import json

def lambda_handler(event, context):
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({
            "message": "Hello from Order Service!",
            "path": event.get("path", "/"),
            "method": event.get("httpMethod", "GET")
        })
    }
```

### 注意事项

- 运行时选择 Python 3.12 或 3.13
- 处理程序默认为 `lambda_function.lambda_handler`，代码中函数名必须与之对应
- **必须返回 `statusCode` + `headers` + `body` 结构**，否则 API Gateway 会返回 500/502 错误

---

## 第二步：在 ACM 申请通配符证书

1. 进入 **ACM**（必须与 API Gateway 同区域，本例为 us-west-2）
2. 请求公有证书
3. 域名填写：`*.example.com`
4. 选择 DNS 验证 → 在 Route 53 或域名服务商添加验证 CNAME 记录
5. 等待证书状态变为"已颁发"

### 重要说明

- 通配符域名**必须使用 ACM 签发的证书**，不能使用导入的证书（否则会报错："The certificate provided with a wildcard domain must be issued by ACM and not imported"）
- ACM 公有证书**完全免费**，且自动续期
- 在同一域名上申请新证书不会影响现有证书和服务

---

## 第三步：为每个 Lambda 创建 REST API

> **必须使用 REST API**。HTTP API 不支持路由规则功能，也不支持通配符自定义域名按 Host 头路由。

### 创建步骤（以 API A 为例）

1. API Gateway 控制台 → 创建 API → 选择 **REST API**
2. 创建资源：
   - 在根资源 `/` 下点击"创建资源"
   - 勾选"代理资源"，自动生成 `{proxy+}`
3. 创建方法：
   - 在 `/{proxy+}` 上创建 `ANY` 方法
   - 集成类型：Lambda 函数
   - 勾选 **Lambda 代理集成**（推荐，可让 Lambda 获取完整请求信息）
   - 选择对应的 Lambda 函数
4. 同时在根资源 `/` 上也创建 `ANY` 方法（同样配置）
5. **部署 API**：
   - 点击右上角 **"部署 API"** 按钮
   - 选择"新阶段"，阶段名称填 `prod`（或 `test`）
   - 确认部署

> **注意**：如果"部署 API"按钮显示"在 API 更新期间，此操作不可用"，等几秒刷新页面即可。

### 为什么要创建 `/{proxy+}` 代理资源？

`/{proxy+}` 是贪婪匹配，会将根路径后面的**所有子路径**都转发给 Lambda：

| 配置 | 能匹配的请求 | 不能匹配的 |
|------|------------|-----------|
| 只有 `/` 的 ANY | `https://user.example.com/` | `https://user.example.com/api/users` |
| `/` + `/{proxy+}` | **所有路径**（`/`、`/api/users`、`/health` 等） | 无 |

- 如果业务只需要响应根路径 `/`，可以不创建代理资源
- 如果业务有多级路径（如 `/api/users`、`/callback`），**必须创建 `/{proxy+}`**，否则子路径请求会返回 403
- 建议统一加上，由 Lambda 代码内部自行处理路由逻辑

对每个 Lambda 重复以上步骤，各自创建独立的 REST API 并部署。

---

## 第四步：创建通配符自定义域名

API Gateway 控制台 → 左侧菜单 **自定义域名** → **添加域名**

| 配置项 | 值 |
|--------|-----|
| 域名 | `*.example.com` |
| ACM 证书 | 选择 `*.example.com`（ACM 签发的） |
| 端点类型 | 区域（Regional） |
| 安全策略 | `SecurityPolicy_TLS13_1_3_2025_09`（推荐，REST API 支持） |
| **路由模式** | **仅限路由规则** |

### 关键说明

- **路由模式必须选"仅限路由规则"**，不要选"仅限 API 映射"。选错后不可更改，只能删除重建。
- 安全策略选 TLS 1.3 增强策略没问题（REST API 支持）。如果用 HTTP API 则只能选 TLS 1.2，但本方案用的是 REST API。
- 创建后状态为"正在更新"，通常**几分钟到 40 分钟**变为"可用"，这是正常现象。

---

## 第五步：创建路由规则

自定义域名状态变为"可用"后，进入 `*.example.com` 详情页 → **路由详情** → 添加路由规则。

### 规则 1：user.example.com → REST API A

| 配置项 | 值 |
|--------|-----|
| 条件类型 | Header |
| Header 名 | `Host` |
| Header 值 | `user.example.com` |
| 目标 API | REST API A（用户服务） |
| 目标阶段 | `prod` |
| 优先级 | 10 |

### 规则 2：order.example.com → REST API B

| 配置项 | 值 |
|--------|-----|
| 条件类型 | Header |
| Header 名 | `Host` |
| Header 值 | `order.example.com` |
| 目标 API | REST API B（订单服务） |
| 目标阶段 | `prod` |
| 优先级 | 20 |

### 优先级说明

- 数字越小优先级越高（10 比 20 先匹配）
- **每条规则优先级不能重复**
- 建议留间隔（10, 20, 30...），方便后续插入新规则
- 由于每条规则的 Host 条件互斥（不同子域名），优先级实际上不影响路由结果，只是系统要求必须不同

### catch-all 默认路由（可选）

可以不配置。不配的话，未匹配的子域名访问会返回 403 Forbidden，对生产环境更安全。

---

## 第六步：配置 DNS 解析

在自定义域名详情页获取 **API Gateway 域名**（如 `d-xxxxxxxxxx.execute-api.us-west-2.amazonaws.com`）。

### 使用 Route 53

为每个子域名创建 A 记录（Alias）：

1. Route 53 → 托管区域 → 选择域名 → 创建记录
2. 配置：
   - 记录名：`user`（.example.com）
   - 记录类型：A
   - 开启"别名"
   - 流量路由至：API Gateway API 的别名
   - 区域：选择 API Gateway 所在区域
   - 终端节点：选择或**直接粘贴** API Gateway 域名

3. 对 `order`、`pay` 等子域名重复操作，**所有子域名指向同一个 API Gateway 域名**

> **踩坑提醒**：Route 53 下拉列表有时加载不出终端节点，直接在搜索框**粘贴 API Gateway 域名**即可匹配到，这不是配置错误。

### 使用其他 DNS 服务商

添加 CNAME 记录：

```
user.example.com   → CNAME → d-xxxxxxxxxx.execute-api.us-west-2.amazonaws.com
order.example.com  → CNAME → d-xxxxxxxxxx.execute-api.us-west-2.amazonaws.com
pay.example.com    → CNAME → d-xxxxxxxxxx.execute-api.us-west-2.amazonaws.com
```

---

## 第七步：验证

```bash
curl https://user.example.com
# {"statusCode": 200, "headers": {...}, "body": "{\"message\": \"Hello from User Service!\", ...}"}

curl https://order.example.com
# {"statusCode": 200, "headers": {...}, "body": "{\"message\": \"Hello from Order Service!\", ...}"}
```

两个子域名返回不同 Lambda 的响应，验证成功 ✅

---

## 新增子域名流程

后续新增 `pay.example.com → Lambda C`：

1. 创建 Lambda 函数 C
2. 创建 REST API → 集成 Lambda C → 部署到 `prod`
3. 在 `*.example.com` 下添加路由规则：
   - Host = `pay.example.com` → 新 REST API / `prod`
   - 优先级：30
4. Route 53 添加 `pay` 的 A 记录（Alias 指向同一个 API Gateway 域名）

**不需要新建自定义域名，不需要新证书，不需要改现有配置。**

---

## 常见问题与踩坑记录

### Q: 通配符域名能用导入的证书吗？
**不能。** 必须由 ACM 签发。报错信息："The certificate provided with a wildcard domain must be issued by ACM and not imported."

### Q: 安全策略选 TLS 1.3 后能用 HTTP API 吗？
**不能。** HTTP API 不支持 TLS 1.3 增强策略，也不支持路由规则。本方案必须用 REST API。

### Q: 路由模式选错了怎么办？
只能**删除自定义域名重新创建**，路由模式创建后不可更改。

### Q: 自定义域名一直显示"正在更新"？
正常现象，等几分钟到 40 分钟变为"可用"。

### Q: Route 53 Alias 下拉找不到 API Gateway 终端节点？
直接在搜索框**粘贴 API Gateway 域名**即可，这是控制台 UI 加载问题，不是配置错误。

### Q: Lambda 返回 500/502 错误？
检查 Lambda 函数返回格式，必须是：
```json
{
  "statusCode": 200,
  "headers": {"Content-Type": "application/json"},
  "body": "字符串"
}
```

### Q: 报错 "Handler 'lambda_handler' missing on module 'lambda_function'"？
Lambda 控制台的"处理程序"配置与代码中的函数名不匹配。默认处理程序是 `lambda_function.lambda_handler`，代码中函数名必须是 `lambda_handler`。

### Q: "部署 API"按钮灰色不可点？
提示"在 API 更新期间，此操作不可用"，等几秒刷新页面即可。

### Q: 优先级能重复吗？
**不能。** 每条路由规则必须设置不同的优先级数字。

### Q: 优先级影响不同子域名的访问吗？
**不影响。** 因为每条规则的 Host 条件互斥，请求只会匹配到一条规则。优先级只在多条规则可能同时匹配同一请求时才有意义。

### Q: 不配 catch-all 默认路由会怎样？
未匹配的子域名访问返回 403 Forbidden，对生产环境更安全。

---

## 注意事项汇总

| 事项 | 说明 |
|------|------|
| API 类型 | 必须用 **REST API**，HTTP API 不支持路由规则 |
| 路由模式 | 创建域名时选"仅限路由规则"，创建后不可更改 |
| 证书 | 通配符域名必须 ACM 签发，不能导入；免费且自动续期 |
| 区域一致 | 自定义域名、REST API、ACM 证书必须在同一区域 |
| 优先级 | 不能重复，数字越小越先匹配，建议留间隔 |
| DNS | 所有子域名指向同一个 API Gateway 域名 |
| Lambda 返回格式 | 必须返回 statusCode + headers + body 结构 |
| 处理程序 | Lambda 控制台配置的处理程序名必须与代码中函数名一致 |
| 费用 | ACM 证书免费；REST API 按请求计费（$3.50/百万请求） |

---

## 参考文档

- [路由规则说明](https://docs.aws.amazon.com/apigateway/latest/developerguide/rest-api-routing-rules.html)
- [路由规则示例（含通配符域名 Example 4）](https://docs.aws.amazon.com/apigateway/latest/developerguide/rest-api-routing-rules-examples.html)
- [设置路由模式](https://docs.aws.amazon.com/apigateway/latest/developerguide/rest-api-routing-mode.html)
- [通配符自定义域名](https://docs.aws.amazon.com/apigateway/latest/developerguide/wildcard-custom-domain-names.html)
- [自定义域名安全策略](https://docs.aws.amazon.com/apigateway/latest/developerguide/apigateway-custom-domain-tls-version.html)
- [REST API 自定义域名设置](https://docs.aws.amazon.com/apigateway/latest/developerguide/how-to-custom-domains.html)
