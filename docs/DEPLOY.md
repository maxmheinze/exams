# Deployment

This is how `exams.maxheinze.eu` is deployed: a dedicated service user, a Python venv,
a hardened `systemd` unit running `uvicorn` on `127.0.0.1:8003`, and `nginx` serving the
static frontend and reverse-proxying `/api/`. The box is a small (4 GB) shared VPS
running Ubuntu 24.04, so the configuration is deliberately memory-conscious.

## 1. System packages

```
sudo apt update
sudo apt install python3-venv \
  texlive-latex-recommended texlive-latex-extra texlive-fonts-recommended latexmk \
  poppler-utils libdmtx0t64 zint bubblewrap nginx certbot python3-certbot-nginx
```

- `texlive-*` + `latexmk` — exam and report compilation.
- `poppler-utils` (`pdftoppm`) + `libdmtx0t64` — page rasterization and DataMatrix decode.
- `zint` — barcode generation.
- `bubblewrap` — optional sandbox layer (the app falls back gracefully if the kernel
  restricts user namespaces, which it may on 24.04 under systemd).

## 2. Service user and directories

```
sudo useradd --system --create-home --home-dir /home/exams --shell /usr/sbin/nologin exams
sudo -u exams mkdir -p /home/exams/app /home/exams/frontend /home/exams/work
sudo chmod 755 /home/exams            # so nginx can read the frontend
```

- `app/` — backend code (`app.py`, `gen_cli.py`, `examgen/`).
- `frontend/` — static SPA (`index.html`, `style.css`, `app.js`, `vendor/`).
- `work/` — ephemeral job dirs; the only writable path for the service.

## 3. Python environment

```
sudo -u exams python3 -m venv /home/exams/venv
sudo -u exams /home/exams/venv/bin/pip install -r /home/exams/app/requirements.txt
```

Note the `setuptools` entry in `requirements.txt`: Python 3.12 dropped `distutils` from
the standard library, but `pylibdmtx` still imports it, so `setuptools` (which ships a
compatibility shim) must be installed in the venv or the service will fail to import.

`matplotlib` needs a writable config/cache dir. Because the unit sets
`ProtectHome=read-only`, `app.py` points `MPLCONFIGDIR` at `work/.mplcache` (inside the
unit's `ReadWritePaths`) automatically — no manual step required.

## 4. Deploy the code

```
# backend
sudo cp app.py gen_cli.py /home/exams/app/
sudo cp examgen/*.py /home/exams/app/examgen/
# frontend (fetch vendored libs first, then copy the whole tree)
./frontend/fetch-vendor.sh
sudo cp -r frontend/index.html frontend/style.css frontend/app.js frontend/vendor /home/exams/frontend/
sudo chown -R exams:exams /home/exams/app /home/exams/frontend
sudo find /home/exams/frontend -type d -exec chmod 755 {} \;
sudo find /home/exams/frontend -type f -exec chmod 644 {} \;
```

## 5. systemd unit

Install the unit from this repo (`exams.service`) and start it:

```
sudo cp exams.service /etc/systemd/system/exams.service
sudo systemctl daemon-reload
sudo systemctl enable --now exams.service
curl -s http://127.0.0.1:8003/api/health        # -> {"status":"ok",...}
```

The unit caps memory (`MemoryMax=1800M`) as an OOM backstop — the per-compile
`RLIMIT_AS` (1.5 GiB, in `examgen/security.py`) is designed to trip first so a runaway
compile fails as one job rather than killing the service. It also denies all network
egress except loopback, runs read-only except for `work/`, and applies the usual
`Protect*`/`NoNewPrivileges` hardening.

## 6. nginx

Static frontend + reverse proxy. The streaming read endpoint needs buffering disabled
so progress reaches the browser live, and a large body limit for scanned PDFs.

```nginx
server {
    listen 443 ssl http2;
    server_name exams.maxheinze.eu;

    # ssl_certificate / ssl_certificate_key are managed by certbot (see below)

    root /home/exams/frontend;
    index index.html;

    client_max_body_size 300m;

    location / {
        try_files $uri $uri/ =404;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8003;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        limit_req  zone=exams_gen_req burst=5 nodelay;
        limit_conn exams_gen_conn 4;
    }

    # streaming, large upload: read/sort scanned PDFs
    location = /api/grade/read {
        proxy_pass http://127.0.0.1:8003;
        proxy_set_header Host $host;
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_read_timeout 1800s;
        proxy_send_timeout 1800s;
        client_max_body_size 300m;
        limit_req  zone=exams_gen_req burst=5 nodelay;
        limit_conn exams_gen_conn 4;
    }
}

server {
    listen 80;
    server_name exams.maxheinze.eu;
    return 301 https://$host$request_uri;
}
```

Rate-limit zones (e.g. `/etc/nginx/conf.d/exams_ratelimit.conf`):

```nginx
limit_req_zone  $binary_remote_addr zone=exams_gen_req:10m rate=15r/m;
limit_conn_zone $binary_remote_addr zone=exams_gen_conn:10m;
```

TLS via certbot:

```
sudo certbot --nginx -d exams.maxheinze.eu
sudo nginx -t && sudo systemctl reload nginx
```

## 7. Updating

```
# backend change -> copy files, then:
sudo systemctl restart exams.service
# frontend change -> copy files (no restart); hard-refresh the browser to bust cache.
```

Nothing is persisted between requests: each job runs in a `work/job_*` dir that is
removed when the request finishes, with an hourly sweep of any orphans left by a crash.
