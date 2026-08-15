# Flight Deck Checklists — static site, nginx on Alpine.
#
#   docker build -t flightdeck .
#   docker run --rm -p 8080:8080 flightdeck
#   → http://localhost:8080  (or http://<your-ip>:8080 from a tablet next to the sim)

# --- stage 1: compile checklists/*.yaml into index.html -----------------------
# No PyYAML here on purpose: build.py falls back to its bundled parser, so the
# build stage stays tiny and that fallback path gets exercised on every build.
FROM alpine:3 AS build
RUN apk add --no-cache python3
WORKDIR /src
COPY build.py index.html app.html ./
COPY checklists ./checklists
RUN python3 build.py && python3 build.py --check

# --- stage 2: serve it -------------------------------------------------------
FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/index.html /usr/share/nginx/html/index.html
COPY --from=build /src/app.html /usr/share/nginx/html/app.html
COPY --from=build /src/robots.txt /src/sitemap.xml /usr/share/nginx/html/

# Worker processes drop to the unprivileged nginx user (see the image's own
# nginx.conf). For a fully rootless container, swap the base image above for
# nginxinc/nginx-unprivileged:alpine — it already listens on 8080.
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=2s \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
CMD ["nginx", "-g", "daemon off;"]
