"""bin/tsq finds the API on every call, from the first place that answers, and fails loudly when none does."""

import functools
import http.server
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
TSQ = str(ROOT / "bin" / "tsq")
DEAD = "http://127.0.0.1:9"  # the discard port: nothing answers there


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(url: str) -> None:
    for _ in range(100):
        try:
            if httpx.get(url, timeout=0.5).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    raise RuntimeError(f"{url} never answered")


@pytest.fixture(scope="module")
def api_url():
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "tracesquad.api:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        wait_for(f"{url}/health")
        yield url
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.fixture
def home(tmp_path):
    return tmp_path / "tracesquad-home"


def tsq(home: Path, *args: str, **env: str) -> subprocess.CompletedProcess:
    full_env = {k: v for k, v in os.environ.items() if not k.startswith("TRACESQUAD_")}
    full_env.update(TRACESQUAD_HOME=str(home), TRACESQUAD_DEFAULT_URL=DEAD, **env)
    return subprocess.run([TSQ, *args], env=full_env, capture_output=True, text=True, timeout=60)


def write(home: Path, name: str, text: str) -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / name).write_text(text + "\n")


def test_health_names_the_service(api_url):
    assert httpx.get(f"{api_url}/health").json() == {"service": "tracesquad-api", "status": "ok"}


def test_finds_the_api_from_the_file_serve_writes(api_url, home):
    write(home, "api-url", api_url)
    out = tsq(home, "GET", "/reports/RPT-102")
    assert out.returncode == 0, out.stderr
    assert '"report_id":"RPT-102"' in out.stdout
    assert tsq(home, "url").stdout.strip() == api_url


def test_env_var_wins_over_the_file(api_url, home):
    write(home, "api-url", DEAD)
    assert tsq(home, "url", TRACESQUAD_API_URL=api_url + "/").stdout.strip() == api_url


def test_a_stale_file_falls_through_to_discovery(api_url, home, tmp_path):
    served = tmp_path / "served"
    served.mkdir()
    (served / "api-url").write_text(api_url + "\n")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(served))
    handler.log_message = lambda *a: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        write(home, "api-url", DEAD)
        write(home, "discovery-url", f"http://127.0.0.1:{server.server_address[1]}/api-url")
        assert tsq(home, "url").stdout.strip() == api_url
        doctor = tsq(home, "doctor")
        assert doctor.returncode == 0 and f"tsq will use: {api_url}" in doctor.stdout
    finally:
        server.shutdown()


def test_something_else_on_the_url_is_not_the_api(api_url, home):
    write(home, "api-url", f"{api_url}/docs")  # answers 404 on /health, like an unrelated service would
    out = tsq(home, "url")
    assert out.returncode == 2 and "not reachable" in out.stderr


def test_unreachable_fails_loudly(home):
    out = tsq(home, "GET", "/health")
    assert out.returncode == 2
    assert "not reachable" in out.stderr and "scripts/serve.sh" in out.stderr and "invent" in out.stderr


def test_http_errors_print_the_detail_and_exit_1(api_url, home):
    write(home, "api-url", api_url)
    out = tsq(home, "GET", "/users/U-00000")
    assert out.returncode == 1
    assert '"detail"' in out.stdout and "HTTP 404" in out.stderr


def test_post_bodies_and_query_strings(api_url, home):
    write(home, "api-url", api_url)
    created = tsq(home, "POST", "/sandbox/users", '{"cohort_id": "ios-18.4-BOM-G5-gold_monthly"}')
    assert created.returncode == 0, created.stderr
    assert '"mock_user_id":"MU-' in created.stdout
    logs = tsq(home, "GET", "/logs?user_id=U-48213&env=prod")
    assert logs.returncode == 0 and '"user_id":"U-48213"' in logs.stdout
    assert tsq(home, "get", "deploys").returncode == 0  # lower-case method and a path without "/" work too


def test_serve_installs_tsq_registers_and_cleans_up(home):
    port = free_port()
    env = {**os.environ, "TRACESQUAD_HOME": str(home), "PORT": str(port)}
    proc = subprocess.Popen([str(ROOT / "scripts" / "serve.sh")], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        for _ in range(200):
            if (home / "api-url").exists():
                break
            time.sleep(0.1)
        assert (home / "api-url").read_text().strip() == f"http://127.0.0.1:{port}"
        installed = home / "bin" / "tsq"
        assert installed.read_text() == Path(TSQ).read_text() and os.access(installed, os.X_OK)
        out = subprocess.run([str(installed), "GET", "/health"], capture_output=True, text=True, timeout=30,
                             env={**env, "TRACESQUAD_DEFAULT_URL": DEAD})
        assert out.returncode == 0 and "tracesquad-api" in out.stdout
    finally:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=20)
    assert not (home / "api-url").exists(), "serve.sh should forget its address when it stops"
