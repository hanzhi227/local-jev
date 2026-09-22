# Host a JEV-compatible server

The server is a long-lived process: it loads weights once and serializes
inference requests. Examples and benchmarks connect over HTTP and never load
their own copy of the model. The initial download requires network access;
cached weights can be reused afterward.

## Apple Silicon

```sh
bash scripts/setup.sh
.venv/bin/jev --backend mlx
```

The default is MLX with 8-bit quantization. Allow roughly 9 GB of free memory
during loading and 4.5 GB while running. `--mlx-bits 4` lowers steady memory
to roughly 2.4 GB but still needs the loading headroom. These are approximate
observations for the default Qwen3.5-4B model, not enforced resource limits.

To run at login:

```sh
bash deploy/install_launchd.sh
curl http://127.0.0.1:8077/ready
```

The installer saves current `JEV_*` environment settings in a per-user launchd
service. Logs go to `private/logs/`. Run the installer again after changing
settings, or `bash deploy/install_launchd.sh uninstall` to remove the service.
This starts at user login, not before login. MLX requires native macOS; a Linux
container on a Mac does not provide the Metal backend.

## Linux or CPU inference

Install `uv`, Git, CMake, and a C/C++ compiler, then obtain a Qwen3.5-4B GGUF as
described in the root README:

```sh
bash scripts/setup.sh llamacpp
.venv/bin/jev --backend llamacpp --gguf /absolute/path/to/Qwen3.5-4B-Q4_K_S.gguf
```

For a persistent Linux service, adapt this systemd unit to the checkout,
virtualenv, GGUF path, and existing unprivileged user on your server:

```ini
[Unit]
Description=Local JEV-compatible decision server
After=network.target

[Service]
Type=simple
User=jev
WorkingDirectory=/opt/jev
EnvironmentFile=/etc/jev.env
ExecStart=/opt/jev/.venv/bin/jev
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Example `/etc/jev.env`:

```ini
JEV_BACKEND=llamacpp
JEV_GGUF=/opt/jev/models/Qwen3.5-4B-Q4_K_S.gguf
JEV_HOST=127.0.0.1
JEV_PORT=8077
```

Save the unit as `/etc/systemd/system/jev.service`, ensure the service user can
read the checkout and weights and write its model/tokenizer cache, then run:

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now jev
sudo journalctl -u jev -f
```

The example unit is a template, not an automatic installer. Test the foreground
command under the service user's environment before enabling it.

## Remote clients

The default bind is `127.0.0.1:8077`. For a private remote server, an SSH tunnel
lets clients use the same localhost URL without exposing the HTTP port:

```sh
ssh -N -L 8077:127.0.0.1:8077 user@your-server
```

For a shared endpoint, set `JEV_API_KEY` on the server and put a TLS reverse
proxy with access controls and rate limits in front of the loopback listener.
Clients send `Authorization: Bearer <key>`. The included Python clients read
`JEV_API_KEY` and accept `--url` or `JEV_URL` for the server's base URL.
The built-in server is plain HTTP, with no TLS, rate limiting, or durable job
queue; it is not an internet-facing production gateway. `/ready` is unauthenticated.

## Operational limits

- Requests execute serially against one loaded backend. Concurrent clients wait.
- Defaults: 32 questions, 1 MiB request body, 4,096-token context. Oversized input
  is rejected; it is not silently truncated.
- `GET /ready` succeeds after model loading; `POST /v1/systemone` runs decisions.
- CLI flags override environment variables. `jev --help` lists the flags.
- Run `jev-bench --suite smoke` against each deployment, then use the public
  suite and your own labeled examples to assess quality and latency.

The benchmark records client-observed latency. Run it on the client machine
whose network path you want to measure, and record the server hardware/backend
with `--label`.
