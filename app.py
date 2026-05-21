"""
CDK 部署模板：新增客户站点（Lambda + REST API + 路由规则 + DNS）

前提条件（已手动完成，无需重复操作）：
- 通配符域名 *.example.com 已在 API Gateway 创建（路由模式：仅限路由规则）
- ACM 通配符证书已签发
- Route 53 托管区域已存在

本模板只做一件事：新增一个客户站点
1. 创建 Lambda 函数（从 ECR 镜像）
2. 创建 REST API（代理集成，转发所有请求到 Lambda）
3. 在通配符域名下添加路由规则（CfnRoutingRule，按 Host 头匹配子域名）
4. 在 Route 53 添加子域名 DNS 记录

使用方式：
  cdk deploy Site-客户名

注意：
- CDK L2 目前没有 Routing Rule 封装，使用 L1（aws_apigatewayv2.CfnRoutingRule）实现
- RoutingRule 资源属于 ApiGatewayV2 命名空间，但可路由到 REST API（V1）
- 路由规则基于 Host 头匹配，每个子域名对应一条规则
"""

import hashlib
import os
from aws_cdk import (
    Stack,
    App,
    Aws,
    CfnOutput,
    Duration,
    RemovalPolicy,
    aws_lambda as _lambda,
    aws_apigateway as apigw,
    aws_apigatewayv2 as apigwv2,
    aws_route53 as route53,
    aws_route53_targets as targets,
    aws_ecr as ecr,
    aws_logs as logs,
)
from constructs import Construct


def _stable_priority(subdomain: str) -> int:
    """
    根据子域名生成确定性的 priority（1 ~ 999999）。

    不能用 Python 内置 hash()：PYTHONHASHSEED 随机化会导致每次 cdk synth
    生成不同的 priority，造成模板漂移和 RoutingRule 资源不必要的更新。
    """
    digest = hashlib.md5(subdomain.encode("utf-8")).hexdigest()
    return int(digest, 16) % 999_999 + 1


class SiteStack(Stack):
    def __init__(self, scope: Construct, id: str,
                 subdomain: str,
                 ecr_repo_name: str,
                 image_tag: str = "latest",
                 architecture: _lambda.Architecture = _lambda.Architecture.X86_64,
                 memory_size: int = 512,
                 timeout_seconds: int = 30,
                 priority: int | None = None,
                 **kwargs):
        """
        参数说明：
        - subdomain: 子域名前缀，如 "user"（最终访问 user.example.com）
                     只能包含字母、数字和连字符，不能含点号
        - ecr_repo_name: ECR 仓库名称，如 "user-app"
        - image_tag: 镜像标签，默认 "latest"
        - architecture: Lambda 架构，X86_64 或 ARM_64，需与 ECR 镜像架构一致
        - memory_size: Lambda 内存（MB），默认 512
        - timeout_seconds: Lambda 超时（秒），默认 30
        - priority: RoutingRule 优先级（1-1,000,000，必须唯一）。
                    为 None 时基于 subdomain 计算确定性默认值
        """
        super().__init__(scope, id, **kwargs)

        # ----- 从 context 读取共享配置 -----
        domain_name = self.node.try_get_context("domain_name")
        hosted_zone_id = self.node.try_get_context("hosted_zone_id")
        custom_domain_target = self.node.try_get_context("custom_domain_target")
        custom_domain_hosted_zone_id = self.node.try_get_context("custom_domain_hosted_zone_id")

        for key, val in {
            "domain_name": domain_name,
            "hosted_zone_id": hosted_zone_id,
            "custom_domain_target": custom_domain_target,
            "custom_domain_hosted_zone_id": custom_domain_hosted_zone_id,
        }.items():
            if not val:
                raise ValueError(
                    f"缺少 context 配置 '{key}'，请在 cdk.json 的 context 中补全或使用 -c {key}=... 传入"
                )

        wildcard_domain_name = f"*.{domain_name}"
        full_domain = f"{subdomain}.{domain_name}"

        # ============================================================
        # 1. 创建 Lambda 函数（ECR 镜像部署）
        # ============================================================
        repo = ecr.Repository.from_repository_name(self, "Repo", ecr_repo_name)

        # 显式创建日志组，设置保留期限避免无限堆积
        log_group = logs.LogGroup(
            self, "FunctionLogGroup",
            log_group_name=f"/aws/lambda/site-{subdomain}",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.DESTROY,
        )

        function = _lambda.DockerImageFunction(
            self, "Function",
            function_name=f"site-{subdomain}",
            code=_lambda.DockerImageCode.from_ecr(
                repository=repo,
                tag_or_digest=image_tag,
            ),
            architecture=architecture,
            timeout=Duration.seconds(timeout_seconds),
            memory_size=memory_size,
            description=f"站点函数: {full_domain}",
            log_group=log_group,
        )

        # ============================================================
        # 2. 创建 REST API（Lambda 代理集成）
        # ============================================================
        # proxy=True 自动创建 /{proxy+} + 根路径 ANY，匹配所有请求
        api = apigw.LambdaRestApi(
            self, "Api",
            rest_api_name=f"api-{subdomain}",
            handler=function,
            proxy=True,
            deploy_options=apigw.StageOptions(stage_name="prod"),
            description=f"REST API: {full_domain}",
        )

        # ============================================================
        # 3. 添加路由规则（L1: aws_apigatewayv2.CfnRoutingRule）
        # ============================================================
        # 通配符域名的 ARN 格式：
        # arn:aws:apigateway:<region>::/domainnames/<domain>
        # 注意：account 段是空的，这是 API Gateway 的 ARN 约定
        domain_arn = (
            f"arn:{Aws.PARTITION}:apigateway:{Aws.REGION}::"
            f"/domainnames/{wildcard_domain_name}"
        )

        rule_priority = priority if priority is not None else _stable_priority(subdomain)

        apigwv2.CfnRoutingRule(
            self, "RoutingRule",
            domain_name_arn=domain_arn,
            priority=rule_priority,
            conditions=[
                apigwv2.CfnRoutingRule.ConditionProperty(
                    match_headers=apigwv2.CfnRoutingRule.MatchHeadersProperty(
                        any_of=[
                            apigwv2.CfnRoutingRule.MatchHeaderValueProperty(
                                header="Host",
                                value_glob=full_domain,
                            )
                        ]
                    )
                )
            ],
            actions=[
                apigwv2.CfnRoutingRule.ActionProperty(
                    invoke_api=apigwv2.CfnRoutingRule.ActionInvokeApiProperty(
                        api_id=api.rest_api_id,
                        stage=api.deployment_stage.stage_name,
                    )
                )
            ],
        )

        # ============================================================
        # 4. 在 Route 53 添加子域名 DNS 记录（Alias 到通配符自定义域名）
        # ============================================================
        hosted_zone = route53.HostedZone.from_hosted_zone_attributes(
            self, "Zone",
            hosted_zone_id=hosted_zone_id,
            zone_name=domain_name,
        )

        # 引用已有的通配符自定义域名（用于 Alias 目标）
        custom_domain = apigw.DomainName.from_domain_name_attributes(
            self, "ExistingDomain",
            domain_name=wildcard_domain_name,
            domain_name_alias_hosted_zone_id=custom_domain_hosted_zone_id,
            domain_name_alias_target=custom_domain_target,
        )

        route53.ARecord(
            self, "DnsRecord",
            zone=hosted_zone,
            record_name=subdomain,
            target=route53.RecordTarget.from_alias(
                targets.ApiGatewayDomain(custom_domain)
            ),
            comment=f"站点: {full_domain}",
        )

        # ============================================================
        # 输出
        # ============================================================
        CfnOutput(self, "SiteUrl", value=f"https://{full_domain}")
        CfnOutput(self, "ApiId", value=api.rest_api_id)
        CfnOutput(self, "FunctionName", value=function.function_name)
        CfnOutput(self, "RoutingRulePriority", value=str(rule_priority))


# ============================================================
# 站点定义（新增客户在这里添加）
# ============================================================
app = App()

# 部署环境（从环境变量读取，或在 cdk.json 中通过 context 配置）
env = {
    "region": "us-west-2",
    "account": os.environ.get("CDK_DEFAULT_ACCOUNT", "123456789012"),
}

# --- 客户 A：user2.example.com ---
SiteStack(app, "Site-user2",
          subdomain="user2",
          ecr_repo_name="user2-app",
          image_tag="latest",
          architecture=_lambda.Architecture.X86_64,
          env=env)

# --- 客户 B：order2.example.com ---
SiteStack(app, "Site-order2",
          subdomain="order2",
          ecr_repo_name="order2-app",
          image_tag="latest",
          architecture=_lambda.Architecture.X86_64,
          env=env)

# --- 新增客户模板 ---
# SiteStack(app, "Site-新客户名",
#           subdomain="新客户名",                    # 子域名前缀（字母数字连字符，不含点号）
#           ecr_repo_name="仓库名",                  # ECR 仓库名称
#           image_tag="v1.0.0",                     # 镜像标签
#           architecture=_lambda.Architecture.X86_64,  # 或 ARM_64
#           memory_size=1024,                        # 可选，默认 512MB
#           timeout_seconds=60,                      # 可选，默认 30s
#           priority=100,                           # 可选，未指定时按 subdomain 自动派生
#           env=env)

app.synth()
