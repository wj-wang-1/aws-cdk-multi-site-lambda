#!/bin/bash
#
# 构建测试镜像并推送到 ECR
#
# 用法：
#   ./build-and-push.sh <仓库名> [区域] [账号ID]
#
# 示例：
#   ./build-and-push.sh user-app
#   ./build-and-push.sh user-app us-west-2 123456789012
#

set -euo pipefail

REPO_NAME="${1:?用法: $0 <仓库名> [区域] [账号ID]}"
REGION="${2:-us-west-2}"
ACCOUNT_ID="${3:-$(aws sts get-caller-identity --query Account --output text)}"
REGISTRY="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
IMAGE_URI="${REGISTRY}/${REPO_NAME}:latest"

echo "==> 目标: ${IMAGE_URI}"

# 1. 创建 ECR 仓库（如果不存在）
if ! aws ecr describe-repositories --repository-names "${REPO_NAME}" --region "${REGION}" &>/dev/null; then
    echo "==> 创建 ECR 仓库: ${REPO_NAME}"
    aws ecr create-repository --repository-name "${REPO_NAME}" --region "${REGION}" --output text
fi

# 2. 登录 ECR
echo "==> 登录 ECR"
aws ecr get-login-password --region "${REGION}" | \
    docker login --username AWS --password-stdin "${REGISTRY}"

# 3. 构建镜像
echo "==> 构建镜像"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
docker build --platform linux/amd64 -t "${REPO_NAME}:latest" "${SCRIPT_DIR}"

# 4. 打标签 & 推送
echo "==> 推送镜像"
docker tag "${REPO_NAME}:latest" "${IMAGE_URI}"
docker push "${IMAGE_URI}"

echo "==> 完成! 镜像: ${IMAGE_URI}"
