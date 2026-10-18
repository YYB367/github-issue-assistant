"""Two program-controlled write tools. No model or arbitrary URL input."""
import json
from datetime import datetime, timedelta
from urllib.parse import quote

import httpx

from app.config import GITHUB_RESPONSE_BYTES


class WriteError(Exception):
    def __init__(self, code, uncertain=False):
        self.code, self.uncertain = code, uncertain


class GitHubWriter:
    def __init__(self, settings, client):
        self.settings, self.client = settings, client
        self.repo = settings.allowed_repository
        self.prefix = "/repos/" + "/".join(quote(x, safe="") for x in self.repo.split("/"))

    def check_target(self, op):
        if op["repository"].casefold() != self.repo.casefold():
            raise WriteError("repository_not_allowed")
        if type(op["issue_number"]) is not int or not 1 <= op["issue_number"] <= 2147483647:
            raise WriteError("invalid_issue_number")

    async def request(self, method, path, payload=None, params=None):
        headers = {"Accept":"application/vnd.github+json", "User-Agent":"github-issue-assistant-v4",
                   "X-GitHub-Api-Version":"2026-03-10"}
        token = self.settings.github_token.get_secret_value()
        if token:
            headers["Authorization"] = "Bearer " + token
        writing = method == "POST"
        try:
            async with self.client.stream(method, "https://api.github.com" + path, headers=headers,
                    json=payload, params=params, follow_redirects=False,
                    timeout=self.settings.github_timeout_seconds) as response:
                code = response.status_code
                if code not in (200, 201):
                    uncertain = writing and (code >= 500 or code == 408 or 300 <= code < 400)
                    raise WriteError(f"github_http_{code}", uncertain)
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > GITHUB_RESPONSE_BYTES:
                        raise WriteError("github_response_too_large", writing)
                return json.loads(data)
        except httpx.TimeoutException:
            raise WriteError("github_timeout", writing) from None
        except httpx.RequestError:
            raise WriteError("github_connection_error", writing) from None
        except (ValueError, UnicodeDecodeError):
            raise WriteError("github_invalid_response", writing) from None

    async def repository(self):
        repo = await self.request("GET", self.prefix)
        if not isinstance(repo, dict) or repo.get("private") is not False:
            raise WriteError("repository_not_public")
        if str(repo.get("full_name", "")).casefold() != self.repo.casefold():
            raise WriteError("repository_mismatch")
        return repo

    async def available_labels(self):
        await self.repository()
        names = []
        for page in (1,2):
            data = await self.request("GET", self.prefix + "/labels", params={"per_page":100,"page":page})
            if not isinstance(data, list) or len(data) > 100:
                raise WriteError("github_invalid_response")
            for item in data:
                if not isinstance(item,dict) or not isinstance(item.get("name"),str):
                    raise WriteError("github_invalid_response")
                names.append(item["name"])
            if len(data) < 100:
                return {"labels":names,"possibly_more":False,"limit":200}
        return {"labels":names,"possibly_more":True,"limit":200}

    async def preflight(self, op):
        self.check_target(op)
        if not self.settings.github_token.get_secret_value():
            raise WriteError("github_token_missing")
        user = await self.request("GET", "/user")
        if not isinstance(user,dict) or type(user.get("id")) is not int or user["id"] <= 0:
            raise WriteError("github_identity_unavailable")
        repo = await self.repository()
        permissions = repo.get("permissions") or {}
        # Deliberately conservative local policy: require repository write/maintain/admin.
        # Token's Issues:write scope is still enforced by the actual GitHub endpoint.
        if not any(permissions.get(k) is True for k in ("push","maintain","admin")):
            raise WriteError("repository_write_permission_required")
        if repo.get("archived") or repo.get("disabled"):
            raise WriteError("repository_read_only")
        issue = await self.request("GET", self.prefix + f"/issues/{op['issue_number']}")
        if not isinstance(issue,dict) or issue.get("number") != op["issue_number"]:
            raise WriteError("github_invalid_issue")
        if "pull_request" in issue:
            raise WriteError("pull_request")
        if issue.get("locked"):
            raise WriteError("issue_locked")
        if op["kind"] == "add_labels":
            for label in op["payload"]["labels"]:
                existing = await self.request("GET", self.prefix + "/labels/" + quote(label, safe=""))
                if not isinstance(existing,dict) or existing.get("name") != label:
                    raise WriteError("existing_label_required")
        return {"id":user["id"],"login":str(user.get("login", ""))[:100]}

    async def send(self, op):
        self.check_target(op)
        if not self.settings.github_writes_enabled:
            raise WriteError("writes_disabled")
        if op["kind"] == "publish_comment":
            path = self.prefix + f"/issues/{op['issue_number']}/comments"
            data = await self.request("POST", path, {"body":op["payload"]["body"]})
            if not self.matches_comment(op, data):
                raise WriteError("write_response_unverified", True)
            return {"comment_id":data["id"],"url":op["target_url"] + f"#issuecomment-{data['id']}"}
        if op["kind"] == "add_labels":
            path = self.prefix + f"/issues/{op['issue_number']}/labels"
            data = await self.request("POST", path, {"labels":op["payload"]["labels"]})
            if not isinstance(data,list) or not set(op["payload"]["labels"]) <= {
                    x.get("name") for x in data if isinstance(x,dict) and isinstance(x.get("name"),str)}:
                raise WriteError("write_response_unverified", True)
            return {"labels":op["payload"]["labels"],"url":op["target_url"]}
        raise WriteError("unknown_write_tool")

    def matches_comment(self, op, data):
        return (isinstance(data,dict) and type(data.get("id")) is int and data["id"] > 0
                and data.get("body") == op["payload"]["body"]
                and isinstance(data.get("user"),dict)
                and data["user"].get("id") == (op.get("actor") or {}).get("id")
                and data.get("issue_url") == "https://api.github.com" + self.prefix + f"/issues/{op['issue_number']}")

    async def reconcile(self, op, comment_id=None):
        self.check_target(op)
        await self.repository()
        if op["kind"] == "add_labels":
            data = await self.request("GET", self.prefix + f"/issues/{op['issue_number']}/labels",
                                      params={"per_page":100})
            if isinstance(data,list) and set(op["payload"]["labels"]) <= {
                    x.get("name") for x in data if isinstance(x,dict) and isinstance(x.get("name"),str)}:
                return {"labels":op["payload"]["labels"],"url":op["target_url"],"verified_by":"desired_labels_observed"}
            return None
        if comment_id is not None:
            data = await self.request("GET", self.prefix + f"/issues/comments/{comment_id}")
            if self.matches_comment(op,data):
                return {"comment_id":data["id"],"url":op["target_url"]+f"#issuecomment-{data['id']}","verified_by":"exact_comment"}
            return None
        # Fixed three-page bound. A negative scan is never evidence of absence.
        since=(datetime.fromisoformat(op["created_at"])-timedelta(minutes=1)).isoformat(timespec="seconds").replace("+00:00","Z")
        for page in (1,2,3):
            data = await self.request("GET", self.prefix + f"/issues/{op['issue_number']}/comments",
                params={"per_page":100,"page":page,"since":since})
            if not isinstance(data,list) or len(data)>100:
                raise WriteError("github_invalid_response")
            for item in data:
                if self.matches_comment(op,item):
                    return {"comment_id":item["id"],"url":op["target_url"]+f"#issuecomment-{item['id']}","verified_by":"exact_comment"}
            if len(data)<100:
                break
        return None
