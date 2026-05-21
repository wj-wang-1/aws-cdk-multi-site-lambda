import json


def handler(event, context):
    """最简 Lambda 处理函数，用于验证部署链路。"""
    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
        },
        "body": json.dumps({
            "message": f"Hello from {event.get('headers', {}).get('Host', 'unknown')}",
            "path": event.get("path", "/"),
            "method": event.get("httpMethod", "GET"),
        }),
    }
