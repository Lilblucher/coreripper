# Livia bot image (runs on the CODE VPS).
# Includes Chromium (for whatsapp-web.js) and python3 (for the stdlib fallback
# brain — no pip packages needed). Node 22 has global fetch, so no HTTP SDK.
FROM node:22-bookworm-slim

# Chromium + minimal fonts/libs puppeteer needs, plus python3 for the brain.
RUN apt-get update && apt-get install -y --no-install-recommends \
      chromium \
      python3 \
      ca-certificates \
      fonts-liberation \
      libnss3 libatk-bridge2.0-0 libatk1.0-0 libcups2 libdrm2 libxkbcommon0 \
      libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2 \
      libpango-1.0-0 libcairo2 \
    && rm -rf /var/lib/apt/lists/*

# whatsapp-web.js must use the system Chromium, not download its own.
ENV PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true
ENV CHROME_PATH=/usr/bin/chromium
ENV PYTHON_PATH=python3
ENV NODE_ENV=production

WORKDIR /app

# Install deps first for layer caching.
COPY package.json package-lock.json* ./
RUN npm install --omit=dev --no-audit --no-fund

# App source.
COPY . .

# sessions/ (WhatsApp auth) and knowledge/ are mounted as volumes at runtime.
EXPOSE 3001

CMD ["node", "whatsapp_bot.js"]
