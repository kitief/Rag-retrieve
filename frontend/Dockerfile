# Build stage
FROM node:20-alpine AS builder
WORKDIR /app

# npm registry. Defaults to npmmirror because registry.npmjs.org can stall on
# some networks; override at build time with:
#   docker compose build --build-arg NPM_REGISTRY=https://registry.npmjs.org
ARG NPM_REGISTRY=https://registry.npmmirror.com
RUN npm config set registry ${NPM_REGISTRY} && npm config set fetch-retries 5

# Copy package files first for better layer caching
COPY package.json ./
# Use npm install (works without package-lock.json for first builds)
RUN npm install --legacy-peer-deps

# Copy source code and build
COPY . .
RUN npm run build

# Runtime stage — serve with Nginx
FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
