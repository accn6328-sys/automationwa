# ── Stage 1: Build dependencies ───────────────────────────────────────────
FROM node:20-slim AS builder

WORKDIR /app

# Install Python 3 + pip + ffmpeg + opencv dependencies via apt
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv ffmpeg git \
        libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 && \
    rm -rf /var/lib/apt/lists/*

# Ensure python3 symlink
RUN ln -sf /usr/bin/python3 /usr/local/bin/python3 && \
    ln -sf /usr/bin/python3 /usr/local/bin/python

# Copy package files and install Node deps
COPY package*.json ./
RUN npm install --legacy-peer-deps

# Install Python deps
COPY requirements.txt ./
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt || \
    pip3 install --no-cache-dir -r requirements.txt

# ── Stage 2: Final image ───────────────────────────────────────────────────
FROM node:20-slim

WORKDIR /app

# Install runtime dependencies (Python + ffmpeg + opencv runtime libs)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 python3-pip ffmpeg \
        libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 && \
    rm -rf /var/lib/apt/lists/* && \
    ln -sf /usr/bin/python3 /usr/local/bin/python3 && \
    ln -sf /usr/bin/python3 /usr/local/bin/python

# Copy installed Node modules from builder
COPY --from=builder /app/node_modules ./node_modules

# Install Python packages in final image
COPY --from=builder /app/requirements.txt ./requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt || \
    pip3 install --no-cache-dir -r requirements.txt

# Copy all source files
COPY . .

EXPOSE 8080

CMD ["node", "app.js"]
