# Livia — deployment (two VPS, Docker)

Phase 1 splits the bot across the two existing VPS without disturbing the sites
already running on them:

- **Code VPS** — runs the bot container (`livia/docker-compose.yml`).
- **Data VPS** — runs a dedicated Redis for caching + conversation memory
  (`livia/deploy/data-vps/docker-compose.yml`).

Everything is isolated so it can't collide with your other websites: a
dedicated Docker network, `livia-`-prefixed containers, Redis on **6380** (never
the default 6379 a host Redis might use), and the bot publishes **no 80/443** —
only the `/send` API on `127.0.0.1:3001`.

---

## 1. Data VPS (Redis)

```bash
cd livia/deploy/data-vps
cp .env.example .env
# edit .env:
#   REDIS_PASSWORD=<long random string>
#   REDIS_BIND_IP=<this VPS's PRIVATE ip, e.g. 10.0.0.2>   # NOT a public ip
#   REDIS_PORT=6380
docker compose up -d
docker compose logs -f   # confirm "Ready to accept connections"
```

> **Security:** Redis must only be reachable over the private link between your
> two VPS — Contabo private networking or a WireGuard tunnel. `REDIS_BIND_IP`
> defaults to `127.0.0.1` precisely so it is never exposed publicly by accident;
> set it to the private IP the code VPS will dial. Also make sure your firewall
> (ufw / Contabo firewall) does **not** open 6380 to the internet. The password
> is required; there is no unauthenticated access.

## 2. Code VPS (the bot)

```bash
cd livia
cp .env.example .env
# edit .env:
#   GROQ_API_KEY=...            # primary
#   GEMINI_API_KEY=...          # fallback
#   REDIS_URL=redis://:<REDIS_PASSWORD>@<DATA_VPS_PRIVATE_IP>:6380/0
#   LIVIA_DM_MODE=all           # or 'named'
#   SEND_API_PORT=3001          # change if 3001 is taken on this host
docker compose up -d --build
docker compose logs -f         # a QR code prints on first run
```

**Link the WhatsApp number** (first run only): scan the QR in the logs with the
phone that will be Livia's number (WhatsApp → Settings → Linked devices → Link a
device). The session is saved in the `livia-sessions` volume, so restarts don't
need a re-scan.

## 3. CoreRipper monitors (if the bot moved hosts)

CoreRipper's `WHATSAPP_BOT_URL` must point at this bot's `/send` API. If the bot
now runs on a different VPS than CoreRipper, set that env on the CoreRipper side
to reach `:3001` across your private network (or a tunnel) — don't expose 3001
publicly.

## Updating knowledge

`knowledge/` is bind-mounted into the bot container, so editing
`knowledge/profile.md` (etc.) on the code VPS host updates the bot live — no
rebuild, no restart. Start by filling in `knowledge/profile.md`.

## Health checks

```bash
# bot up + WhatsApp link state (contract: 400=ready, 503=not linked)
curl -s -o /dev/null -w '%{http_code}\n' -X POST \
  http://127.0.0.1:3001/send -H 'Content-Type: application/json' -d '{}'

# redis reachable from the code VPS
docker run --rm redis:7-alpine redis-cli -u "$REDIS_URL" ping   # -> PONG
```
