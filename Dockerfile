FROM node:20-slim

WORKDIR /app

# Install Python 3, pip, ffmpeg, git, and system C/C++ graphics dependencies for OpenCV
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv ffmpeg git \
        libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 && \
    rm -rf /var/lib/apt/lists/* && \
    ln -sf /usr/bin/python3 /usr/local/bin/python3 && \
    ln -sf /usr/bin/python3 /usr/local/bin/python

# Copy package requirements and install dependencies
COPY package*.json ./
RUN npm install --legacy-peer-deps

COPY requirements.txt ./
RUN python3 -m pip install --no-cache-dir --break-system-packages -r requirements.txt || \
    python3 -m pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

EXPOSE 8080

CMD ["node", "app.js"]
