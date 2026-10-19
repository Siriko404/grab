import http.client
import json


class RpcDown(Exception):
    """The engine is not reachable."""


class RpcError(Exception):
    """The engine answered with an error."""


class Rpc:
    def __init__(self, port: int, secret: str):
        self.port = port
        self.secret = secret

    def call(self, method: str, *params, timeout: float = 5.0):
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": "grab",
                "method": method if "." in method else "aria2." + method,
                "params": [f"token:{self.secret}", *params],
            }
        )
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        try:
            conn.request("POST", "/jsonrpc", body, {"Content-Type": "application/json"})
            data = conn.getresponse().read()
        except (OSError, http.client.HTTPException) as e:
            raise RpcDown(str(e)) from e
        finally:
            conn.close()
        try:
            obj = json.loads(data)
        except ValueError as e:
            raise RpcDown("bad response from engine") from e
        if "error" in obj:
            raise RpcError(obj["error"].get("message", "engine error"))
        return obj["result"]

    def alive(self) -> bool:
        try:
            self.call("getVersion", timeout=1.0)
            return True
        except (RpcDown, RpcError):
            return False
