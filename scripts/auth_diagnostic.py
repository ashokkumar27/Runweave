"""One read-only authentication request; allowlisted output only, no retries."""

from pathlib import Path

ALLOWED_CODES = {
    "insufficient_quota",
    "rate_limit_exceeded",
    "invalid_api_key",
    "ip_not_authorized",
    "model_not_found",
    "unsupported_parameter",
    "invalid_request_error",
}
ALLOWED_TYPES = {"invalid_request_error", "authentication_error", "permission_error", "rate_limit_error"}


def safe_error(body):
    if not isinstance(body, dict):
        return "unclassified", "unclassified"
    error = body.get("error")
    if not isinstance(error, dict):
        error = body
    code, kind = error.get("code"), error.get("type")
    return (
        code if isinstance(code, str) and code in ALLOWED_CODES else "unclassified",
        kind if isinstance(kind, str) and kind in ALLOWED_TYPES else "unclassified",
    )


def main():
    import httpx
    from dotenv import dotenv_values

    from agent_runtime.config import Settings

    values = dotenv_values(Path(__file__).resolve().parents[1] / ".env.local")
    key = values.get("OPENAI_API_KEY")
    if not key:
        print("status=none code=unclassified type=unclassified")
        return 2
    try:
        overrides = {}
        if values.get("OPENAI_FORCE_IPV4") is not None:
            overrides["openai_force_ipv4"] = values["OPENAI_FORCE_IPV4"]
        force_ipv4 = Settings(**overrides).openai_force_ipv4
        transport = httpx.HTTPTransport(
            local_address="0.0.0.0" if force_ipv4 else None, trust_env=False, retries=0
        )
        with httpx.Client(timeout=10, trust_env=False, follow_redirects=False, transport=transport) as client:
            response = client.get(
                "https://api.openai.com/v1/models", headers={"Authorization": f"Bearer {key}"}
            )
        try:
            code, kind = safe_error(response.json()) if response.is_error else ("none", "none")
        except Exception:
            code, kind = "unclassified", "unclassified"
        print(f"status={response.status_code} code={code} type={kind}")
        return int(response.is_error)
    except Exception:
        print("status=none code=unclassified type=unclassified")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
